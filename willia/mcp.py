"""Small JSON-RPC 2.0 MCP client for stdio child processes."""

from __future__ import annotations

import json
import os
import queue
import signal
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path


_EOF = object()
_PROTOCOL_VERSION = "2025-06-18"


@dataclass(frozen=True)
class ServerSpec:
    name: str
    command: str
    args: tuple[str, ...]
    env: dict[str, str]


def _spec(name: str, raw: object) -> ServerSpec:
    if not isinstance(raw, dict):
        raise ValueError(f"MCP server {name!r} must be an object")
    command = raw.get("command")
    args = raw.get("args", [])
    environment = raw.get("env", {})
    if not isinstance(command, str) or not command:
        raise ValueError(f"MCP server {name!r} command must be a nonempty string")
    if (not isinstance(args, list)
            or any(not isinstance(value, str) for value in args)):
        raise ValueError(f"MCP server {name!r} args must be an array of strings")
    if (not isinstance(environment, dict)
            or any(not isinstance(key, str) or not isinstance(value, str)
                   for key, value in environment.items())):
        raise ValueError(f"MCP server {name!r} env must contain string values")
    extras = set(raw) - {"command", "args", "env"}
    if extras:
        raise ValueError(f"MCP server {name!r} has unknown key: {sorted(extras)[0]}")
    return ServerSpec(name, command, tuple(args), dict(environment))


def load_servers(root: Path, workspace: Path) -> tuple[Path | None, dict[str, ServerSpec]]:
    """Load the first configuration found: chat root, then workspace."""
    candidates = (Path(root) / "mcp.json", Path(workspace) / "mcp.json")
    path = next((candidate for candidate in candidates if candidate.is_file()), None)
    if path is None:
        return None, {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(f"cannot read MCP configuration {path}: {exc}") from exc
    if not isinstance(raw, dict) or set(raw) != {"servers"}:
        raise ValueError("MCP configuration must be an object containing only 'servers'")
    servers = raw["servers"]
    if not isinstance(servers, dict):
        raise ValueError("MCP configuration 'servers' must be an object")
    result = {}
    for name, value in servers.items():
        if not isinstance(name, str) or not name:
            raise ValueError("MCP server names must be nonempty strings")
        result[name] = _spec(name, value)
    return path, result


class Server:
    def __init__(self, spec: ServerSpec, *, workspace: Path, timeout_s: float):
        self.spec = spec
        self.timeout_s = timeout_s
        self._next_id = 1
        self._messages: queue.Queue[object] = queue.Queue()
        self._stderr: deque[str] = deque(maxlen=40)
        self._closed = False
        self._tools: list[dict[str, object]] | None = None
        environment = os.environ.copy()
        environment.update(spec.env)
        self.process = subprocess.Popen(
            [spec.command, *spec.args], cwd=workspace, env=environment,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True,
        )
        self._stdout_thread = threading.Thread(
            target=self._read_stdout, name=f"willia-mcp-{spec.name}-stdout", daemon=True)
        self._stderr_thread = threading.Thread(
            target=self._read_stderr, name=f"willia-mcp-{spec.name}-stderr", daemon=True)
        self._stdout_thread.start()
        self._stderr_thread.start()

    def _read_stdout(self) -> None:
        assert self.process.stdout is not None
        try:
            while True:
                line = self.process.stdout.readline()
                if not line:
                    break
                try:
                    value = json.loads(line.decode("utf-8"))
                    if not isinstance(value, dict):
                        raise ValueError("message is not an object")
                    self._messages.put(value)
                except (UnicodeError, ValueError) as exc:
                    self._messages.put(RuntimeError(f"invalid JSON-RPC response: {exc}"))
        finally:
            self._messages.put(_EOF)

    def _read_stderr(self) -> None:
        assert self.process.stderr is not None
        for line in iter(self.process.stderr.readline, b""):
            self._stderr.append(line.decode("utf-8", errors="replace").rstrip())

    def _detail(self) -> str:
        detail = "\n".join(self._stderr).strip()
        return f": {detail}" if detail else ""

    def _send(self, message: dict[str, object]) -> None:
        if self.process.poll() is not None:
            raise RuntimeError(
                f"MCP server {self.spec.name!r} exited with {self.process.returncode}"
                f"{self._detail()}")
        assert self.process.stdin is not None
        try:
            self.process.stdin.write(
                (json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n").encode())
            self.process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise RuntimeError(
                f"MCP server {self.spec.name!r} closed its input{self._detail()}") from exc

    def notify(self, method: str, params: dict[str, object] | None = None) -> None:
        message: dict[str, object] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self._send(message)

    def request(self, method: str, params: dict[str, object] | None = None) -> object:
        request_id = self._next_id
        self._next_id += 1
        message: dict[str, object] = {
            "jsonrpc": "2.0", "id": request_id, "method": method,
        }
        if params is not None:
            message["params"] = params
        self._send(message)
        deadline = time.monotonic() + self.timeout_s
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.close(kill=True)
                raise TimeoutError(
                    f"MCP server {self.spec.name!r} timed out after {self.timeout_s:g}s")
            try:
                response = self._messages.get(timeout=remaining)
            except queue.Empty:
                self.close(kill=True)
                raise TimeoutError(
                    f"MCP server {self.spec.name!r} timed out after {self.timeout_s:g}s") from None
            if response is _EOF:
                self.process.wait(timeout=1)
                raise RuntimeError(
                    f"MCP server {self.spec.name!r} exited with {self.process.returncode}"
                    f"{self._detail()}")
            if isinstance(response, Exception):
                raise response
            if response.get("id") != request_id:
                # Server notifications have no id and may arrive between a request
                # and its reply. There are no concurrent requests in one turn.
                if "id" not in response:
                    continue
                raise RuntimeError(
                    f"MCP server {self.spec.name!r} returned response id "
                    f"{response.get('id')!r}, expected {request_id}")
            if "error" in response:
                error = response["error"]
                if isinstance(error, dict):
                    code = error.get("code")
                    message_text = error.get("message", "unknown error")
                    raise RuntimeError(f"MCP error {code}: {message_text}")
                raise RuntimeError(f"MCP error: {error}")
            if "result" not in response:
                raise RuntimeError(
                    f"MCP server {self.spec.name!r} returned no result")
            return response["result"]

    def handshake(self) -> list[dict[str, object]]:
        if self._tools is not None:
            return self._tools
        self.request("initialize", {
            "protocolVersion": _PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "willia", "version": "0.0.1"},
        })
        self.notify("notifications/initialized")
        result = self.request("tools/list", {})
        if not isinstance(result, dict) or not isinstance(result.get("tools"), list):
            raise RuntimeError(
                f"MCP server {self.spec.name!r} returned an invalid tools/list result")
        if any(not isinstance(tool, dict) for tool in result["tools"]):
            raise RuntimeError(
                f"MCP server {self.spec.name!r} returned an invalid tool schema")
        self._tools = result["tools"]
        return self._tools

    def call(self, name: str, arguments: dict[str, object]) -> object:
        self.handshake()
        return self.request("tools/call", {"name": name, "arguments": arguments})

    def close(self, *, kill: bool = False) -> None:
        if self._closed:
            return
        self._closed = True
        if self.process.stdin is not None:
            try:
                self.process.stdin.close()
            except OSError:
                pass
        if self.process.poll() is None:
            try:
                os.killpg(self.process.pid, signal.SIGKILL if kill else signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                self.process.wait(timeout=1)
        # The server may have exited before descendants in its process group,
        # or a descendant may have ignored SIGTERM after the server stopped.
        # Always finish the whole group so no MCP process survives the turn.
        try:
            os.killpg(self.process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        for stream in (self.process.stdout, self.process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass
        self._stdout_thread.join(timeout=1)
        self._stderr_thread.join(timeout=1)


class Manager:
    """Own on-demand MCP children for exactly one model turn."""
    def __init__(self, root: Path, workspace: Path, *, timeout_s: float = 10.0):
        self.root = Path(root)
        self.workspace = Path(workspace).expanduser().resolve()
        self.timeout_s = timeout_s
        self._servers: dict[str, Server] = {}

    def _configured(self) -> tuple[Path | None, dict[str, ServerSpec]]:
        return load_servers(self.root, self.workspace)

    def _server(self, name: str) -> Server:
        _path, configured = self._configured()
        if name not in configured:
            raise ValueError(f"unknown MCP server: {name}")
        existing = self._servers.get(name)
        if existing is not None and existing.process.poll() is None:
            return existing
        if not self.workspace.is_dir():
            raise ValueError(f"workspace does not exist: {self.workspace}")
        server = Server(configured[name], workspace=self.workspace, timeout_s=self.timeout_s)
        self._servers[name] = server
        return server

    def list(self) -> dict[str, object]:
        path, configured = self._configured()
        servers = []
        for name in configured:
            try:
                schemas = self._server(name).handshake()
                servers.append({"name": name, "tools": schemas})
            except Exception as exc:
                servers.append({"name": name, "error": str(exc)})
                failed = self._servers.pop(name, None)
                if failed is not None:
                    failed.close(kill=True)
        return {"config": str(path) if path is not None else None, "servers": servers}

    def call(self, server: object, tool: object, arguments: object) -> dict[str, object]:
        if not isinstance(server, str) or not server:
            raise ValueError("server must be a nonempty string")
        if not isinstance(tool, str) or not tool:
            raise ValueError("tool must be a nonempty string")
        if not isinstance(arguments, dict):
            raise ValueError("arguments must be a JSON object")
        try:
            result = self._server(server).call(tool, arguments)
            return {"server": server, "tool": tool, "result": result}
        except Exception:
            failed = self._servers.pop(server, None)
            if failed is not None:
                failed.close(kill=True)
            raise

    def close(self) -> None:
        servers, self._servers = self._servers, {}
        for server in servers.values():
            server.close()


def tool(manager: Manager, action: object, *, server: object = None,
         name: object = None, arguments: object = None) -> str:
    try:
        if action == "list":
            return json.dumps(manager.list(), ensure_ascii=False)
        if action == "call":
            return json.dumps(
                manager.call(server, name, {} if arguments is None else arguments),
                ensure_ascii=False,
            )
        raise ValueError("action must be list or call")
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
