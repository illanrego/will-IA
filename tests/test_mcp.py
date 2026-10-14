import json
import os
from pathlib import Path
import sys
import time

from willia.chat import Chat
from willia.client import Reply, ToolCall
from willia.config import Config
from willia.mcp import Manager, load_servers, tool


STUB = r'''import json
import os
import subprocess
import sys
import time

log_path = os.environ["STUB_LOG"]
pid_path = os.environ["STUB_PID"]
mode = os.environ.get("STUB_MODE", "ok")
open(pid_path, "w").write(str(os.getpid()))
if mode == "descendant":
    child = subprocess.Popen([
        sys.executable, "-c",
        "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)",
    ])
    open(os.environ["STUB_CHILD_PID"], "w").write(str(child.pid))

def record(method):
    with open(log_path, "a") as stream:
        stream.write(method + "\n")

def answer(payload):
    sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
    sys.stdout.flush()

for line in sys.stdin:
    message = json.loads(line)
    method = message["method"]
    record(method)
    if "id" not in message:
        continue
    ident = message["id"]
    if method == "initialize":
        answer({"jsonrpc": "2.0", "id": ident, "result": {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "serverInfo": {"name": "stub", "version": "1"}}})
    elif method == "tools/list":
        answer({"jsonrpc": "2.0", "id": ident, "result": {"tools": [{
            "name": "echo", "description": "Echo arguments",
            "inputSchema": {"type": "object"}}]}})
    elif method == "tools/call" and mode == "error":
        answer({"jsonrpc": "2.0", "id": ident,
                "error": {"code": -32001, "message": "stub refused"}})
    elif method == "tools/call" and mode == "exit":
        sys.exit(7)
    elif method == "tools/call" and mode == "hang":
        time.sleep(30)
    elif method == "tools/call":
        answer({"jsonrpc": "2.0", "id": ident, "result": {
            "content": [{"type": "text", "text": json.dumps(message["params"]["arguments"])}]}})
'''


def configure(tmp_path, *, mode="ok", root_name="chat"):
    root = tmp_path / root_name
    workspace = tmp_path / "workspace"
    root.mkdir(exist_ok=True)
    workspace.mkdir(exist_ok=True)
    script = tmp_path / "stub.py"
    script.write_text(STUB)
    log = tmp_path / f"{root_name}-{mode}.log"
    pid = tmp_path / f"{root_name}-{mode}.pid"
    child_pid = tmp_path / f"{root_name}-{mode}.child.pid"
    (root / "mcp.json").write_text(json.dumps({"servers": {"stub": {
        "command": sys.executable,
        "args": [str(script)],
        "env": {
            "STUB_LOG": str(log), "STUB_PID": str(pid), "STUB_MODE": mode,
            "STUB_CHILD_PID": str(child_pid),
        },
    }}}))
    return root, workspace, log, pid


def assert_dead(pid_path):
    pid = int(pid_path.read_text())
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        status = Path(f"/proc/{pid}/stat")
        if status.is_file() and status.read_text().split()[2] == "Z":
            return
        time.sleep(0.01)
    raise AssertionError(f"MCP child {pid} is still running")


def test_handshake_order_list_and_call_reuse_one_child(tmp_path):
    root, workspace, log, pid = configure(tmp_path)
    manager = Manager(root, workspace, timeout_s=1)
    try:
        listed = json.loads(tool(manager, "list"))
        assert listed["servers"][0]["tools"][0]["name"] == "echo"
        called = json.loads(tool(
            manager, "call", server="stub", name="echo", arguments={"word": "hi"}))
        assert json.loads(called["result"]["content"][0]["text"]) == {"word": "hi"}
        assert log.read_text().splitlines() == [
            "initialize", "notifications/initialized", "tools/list", "tools/call"]
    finally:
        manager.close()
    assert_dead(pid)


def test_server_error_is_readable_and_child_is_closed(tmp_path):
    root, workspace, _log, pid = configure(tmp_path, mode="error")
    manager = Manager(root, workspace, timeout_s=1)
    result = json.loads(tool(
        manager, "call", server="stub", name="echo", arguments={}))
    assert "MCP error -32001: stub refused" in result["error"]
    manager.close()
    assert_dead(pid)


def test_server_exit_mid_call_returns_and_leaves_no_child(tmp_path):
    root, workspace, _log, pid = configure(tmp_path, mode="exit")
    manager = Manager(root, workspace, timeout_s=1)
    result = json.loads(tool(
        manager, "call", server="stub", name="echo", arguments={}))
    assert "exited with 7" in result["error"]
    manager.close()
    assert_dead(pid)


def test_timeout_kills_server_and_returns_instead_of_hanging(tmp_path):
    root, workspace, _log, pid = configure(tmp_path, mode="hang")
    manager = Manager(root, workspace, timeout_s=0.1)
    started = time.monotonic()
    result = json.loads(tool(
        manager, "call", server="stub", name="echo", arguments={}))
    assert time.monotonic() - started < 2
    assert "timed out after 0.1s" in result["error"]
    manager.close()
    assert_dead(pid)


def test_close_kills_descendants_that_outlive_the_server(tmp_path):
    root, workspace, _log, pid = configure(tmp_path, mode="descendant")
    child_pid = tmp_path / "chat-descendant.child.pid"
    manager = Manager(root, workspace, timeout_s=1)
    listed = json.loads(tool(manager, "list"))
    assert listed["servers"][0]["tools"][0]["name"] == "echo"
    manager.close()
    assert_dead(pid)
    assert_dead(child_pid)


def test_configuration_searches_chat_root_before_workspace(tmp_path):
    root, workspace, _log, _pid = configure(tmp_path)
    (workspace / "mcp.json").write_text(json.dumps({"servers": {"other": {
        "command": sys.executable, "args": [], "env": {}}}}))
    path, servers = load_servers(root, workspace)
    assert path == root / "mcp.json"
    assert list(servers) == ["stub"]


class TurnClient:
    def __init__(self):
        self.last_usage = {}
        self.calls = 0

    def turn(self, messages, tools, *, on_delta=None):
        self.calls += 1
        if self.calls == 1:
            return Reply("", "", [ToolCall("m1", "mcp", {"action": "list"})], {},
                         "tool_calls")
        return Reply("done", "", [], {}, "stop")

    def summarize(self, request):
        return "summary"


def test_chat_turn_always_closes_mcp_children(tmp_path):
    root, workspace, _log, pid = configure(tmp_path)
    chat = Chat.open(Config(root=root, workspace=str(workspace)), client=TurnClient())
    try:
        chat.turn(["list the server"])
        assert_dead(pid)
    finally:
        chat.close()
