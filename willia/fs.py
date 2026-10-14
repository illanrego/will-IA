"""Native shell and filesystem tools."""

from __future__ import annotations

import difflib
import fnmatch
import json
import os
import re
import signal
import subprocess
from pathlib import Path

from .config import Config


_MAX_READ_BYTES = 5 * 1024 * 1024
_MAX_SEARCH_FILE_BYTES = 5 * 1024 * 1024


def _error(message: object) -> str:
    return json.dumps({"error": str(message)}, ensure_ascii=False)


def _json(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _workspace(config: Config | None) -> Path:
    return Path((config or Config()).workspace).expanduser().resolve()


def _path(value: object, config: Config | None) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError("path must be a nonempty string")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = _workspace(config) / path
    return path.resolve()


def _positive_integer(value: object, default: int, name: str) -> int:
    result = default if value is None else value
    if type(result) is not int or result < 1:
        raise ValueError(f"{name} must be a positive integer")
    return result


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    head = (limit + 1) // 2
    tail = limit // 2
    return text[:head] + (text[-tail:] if tail else "")


def _replacement_bytes(raw: bytes) -> int:
    replaced = 0
    offset = 0
    while offset < len(raw):
        try:
            raw[offset:].decode("utf-8")
            break
        except UnicodeDecodeError as exc:
            replaced += exc.end - exc.start
            offset += exc.end
    return replaced


def terminal(command: object, workdir: object = None, timeout_s: object = None,
             config: Config | None = None) -> str:
    """Run one shell command in a workspace and return its bounded output."""
    try:
        if not isinstance(command, str) or not command:
            return _error("command must be a nonempty string")
        timeout = _positive_integer(timeout_s, 120, "timeout_s")
        if timeout > 600:
            return _error("timeout_s must be at most 600")
        if workdir is None:
            directory = _workspace(config)
        else:
            if not isinstance(workdir, str) or not workdir:
                return _error("workdir must be an absolute directory path")
            raw_directory = Path(workdir).expanduser()
            if not raw_directory.is_absolute():
                return _error("workdir must be an absolute directory path")
            directory = raw_directory.resolve()
        if not directory.exists():
            return _error(f"workdir does not exist: {directory}")
        if not directory.is_dir():
            return _error(f"workdir is not a directory: {directory}")
        process = subprocess.Popen(
            command, shell=True, cwd=directory,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True,
        )
        timed_out = False
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout, stderr = process.communicate()
        settings = config or Config()
        budget = settings.tool_clip_chars
        if type(budget) is not int or budget < 1:
            return _error("tool_clip_chars must be a positive integer")
        return _json({
            "exit_code": process.returncode,
            "stdout": _clip(stdout.decode("utf-8", errors="replace"), budget),
            "stderr": _clip(stderr.decode("utf-8", errors="replace"), budget),
            "workdir": str(directory),
            "timed_out": timed_out,
        })
    except Exception as exc:
        return _error(exc)


def read_file(path: object, offset: object = None, limit: object = None,
              config: Config | None = None) -> str:
    """Read and line-number a bounded head of a text file."""
    try:
        source = _path(path, config)
        first = _positive_integer(offset, 1, "offset")
        count = _positive_integer(limit, 2000, "limit")
        if not source.exists():
            return _error(f"path does not exist: {source}")
        if not source.is_file():
            return _error(f"path is not a file: {source}")
        with source.open("rb") as handle:
            raw = handle.read(_MAX_READ_BYTES)
        if b"\x00" in raw:
            return _error(f"binary file contains a NUL byte: {source}")
        replaced = _replacement_bytes(raw)
        lines = raw.decode("utf-8", errors="replace").splitlines()
        selected = lines[first - 1:first - 1 + count]
        content = "\n".join(
            f"{line_number}: {text}"
            for line_number, text in enumerate(selected, start=first)
        )
        return _json({
            "path": str(source),
            "content": content,
            "total_lines": len(lines),
            "offset": first,
            "replaced_bytes": replaced,
        })
    except Exception as exc:
        return _error(exc)


def write_file(path: object, content: object,
               config: Config | None = None) -> str:
    """Replace a UTF-8 text file, or create it when it does not exist."""
    try:
        destination = _path(path, config)
        if not isinstance(content, str):
            return _error("content must be a string")
        if destination.exists() and destination.is_dir():
            return _error(f"path is not a file: {destination}")
        encoded = content.encode("utf-8")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(encoded)
        return _json({"path": str(destination), "bytes_written": len(encoded)})
    except Exception as exc:
        return _error(exc)


def patch(path: object, old_string: object, new_string: object,
          replace_all: object = False, config: Config | None = None) -> str:
    """Replace exact text and return the resulting unified diff."""
    try:
        source = _path(path, config)
        if not source.exists():
            return _error(f"path does not exist: {source}")
        if not source.is_file():
            return _error(f"path is not a file: {source}")
        if not isinstance(old_string, str) or not old_string:
            return _error("old_string must be a nonempty string")
        if not isinstance(new_string, str):
            return _error("new_string must be a string")
        if type(replace_all) is not bool:
            return _error("replace_all must be a boolean")
        before = source.read_bytes().decode("utf-8")
        occurrences = before.count(old_string)
        if occurrences == 0:
            return _error("old_string was not found")
        if not replace_all and occurrences != 1:
            return _error("old_string appears more than once")
        replacements = occurrences if replace_all else 1
        after = before.replace(old_string, new_string, -1 if replace_all else 1)
        diff = "".join(difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=str(source),
            tofile=str(source),
        ))
        source.write_bytes(after.encode("utf-8"))
        return _json({
            "path": str(source), "diff": diff, "replacements": replacements,
        })
    except Exception as exc:
        return _error(exc)


def _search_roots(root: Path):
    if root.is_file():
        yield root
        return
    for directory, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(name for name in dirnames if name != ".git")
        for name in sorted(filenames):
            yield Path(directory) / name


def search_files(pattern: object, target: object = None, path: object = None,
                 file_glob: object = None, limit: object = None,
                 config: Config | None = None) -> str:
    """Find filenames by glob or matching text lines by regular expression."""
    try:
        if not isinstance(pattern, str) or not pattern:
            return _error("pattern must be a nonempty string")
        mode = "content" if target is None else target
        if mode not in {"content", "files"}:
            return _error("target must be content or files")
        if file_glob is not None and not isinstance(file_glob, str):
            return _error("file_glob must be a string")
        maximum = _positive_integer(limit, 50, "limit")
        root = _workspace(config) if path is None else _path(path, config)
        if not root.exists():
            return _error(f"path does not exist: {root}")
        if not root.is_dir() and not root.is_file():
            return _error(f"path is not a file or directory: {root}")
        regex = re.compile(pattern) if mode == "content" else None
        results: list[dict[str, object]] = []
        truncated = False
        for candidate in _search_roots(root):
            relative = candidate.name if root.is_file() else str(candidate.relative_to(root))
            if mode == "files":
                if not (fnmatch.fnmatch(candidate.name, pattern)
                        or fnmatch.fnmatch(relative, pattern)):
                    continue
                result: dict[str, object] = {"path": str(candidate.resolve())}
                if len(results) == maximum:
                    truncated = True
                    break
                results.append(result)
                continue
            if file_glob is not None and not (
                fnmatch.fnmatch(candidate.name, file_glob)
                or fnmatch.fnmatch(relative, file_glob)
            ):
                continue
            try:
                if candidate.stat().st_size > _MAX_SEARCH_FILE_BYTES:
                    continue
                raw = candidate.read_bytes()
            except OSError:
                continue
            if b"\x00" in raw:
                continue
            for line_number, text in enumerate(
                raw.decode("utf-8", errors="replace").splitlines(), start=1
            ):
                if regex is None or regex.search(text) is None:
                    continue
                result = {
                    "path": str(candidate.resolve()),
                    "line": line_number,
                    "text": text,
                }
                if len(results) == maximum:
                    truncated = True
                    break
                results.append(result)
            if truncated:
                break
        return _json({"results": results, "truncated": truncated})
    except Exception as exc:
        return _error(exc)
