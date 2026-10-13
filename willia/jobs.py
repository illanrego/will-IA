"""Supervise background delegates and publish their durable reports.

Every subprocess has one supervisor thread.  The caller only performs bounded
validation and process creation; waiting, timeout handling, child-chat writes,
and delivery back to the model all happen in that thread.
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from . import records, text, tools
from .compactor import Compactor
from .store import Log
from .tree import Tree
from .view import View


_LABEL_LOCK = threading.Lock()
_RESERVED_LABELS: dict[Path, set[str]] = {}
_JOBS_LOCK = threading.Lock()
_JOBS: list["Job"] = []
_JOB_NAME = re.compile(r"^(?P<label>.+)-\d{8}T\d{6}(?:\.\d{6})?Z(?:-\d+)?$")


@dataclass
class Job:
    label: str
    agent: str
    dir: Path
    report_path: Path
    log_path: Path
    started_at: datetime
    process: subprocess.Popen
    thread: threading.Thread | None
    timed_out: bool = False
    exit_code: int | None = None


def _normal_agent(agent: str) -> str:
    names = {
        "codex": "codex",
        "delegate_codex": "codex",
        "hermes": "hermes",
        "delegate_hermes": "hermes",
    }
    try:
        return names[agent]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"unknown delegate: {agent}") from exc


@lru_cache(maxsize=1)
def _codex_binary() -> Path:
    """Resolve the global npm Codex binary once, never through the shell."""
    try:
        result = subprocess.run(
            ["npm", "prefix", "-g"], check=True, capture_output=True,
            text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise FileNotFoundError(f"cannot resolve the global Codex binary: {exc}") from exc
    prefix = result.stdout.strip()
    if not prefix:
        raise FileNotFoundError("cannot resolve the global Codex binary: npm returned no prefix")
    binary = Path(prefix) / "bin" / "codex"
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise FileNotFoundError(f"codex not found at {binary}")
    return binary


def _executable(command: list[str]) -> str:
    if not isinstance(command, list) or not command or any(
            not isinstance(part, str) or not part for part in command):
        raise ValueError("command must be a nonempty list of strings")
    candidate = command[0]
    if os.path.isabs(candidate) or os.sep in candidate:
        path = Path(candidate).expanduser()
        if not path.is_file() or not os.access(path, os.X_OK):
            raise FileNotFoundError(f"delegate binary not found at {path}")
        return str(path)
    resolved = shutil.which(candidate)
    if resolved is None:
        raise FileNotFoundError(f"delegate binary not found: {candidate}")
    return resolved


def _command(agent: str, *, brief_path: Path, report_path: Path,
             directory: Path, model: str | None = None) -> list[str]:
    """Build either frozen delegate command in one place."""
    agent = _normal_agent(agent)
    if agent == "codex":
        # The frozen schema retains the former ``gpt-6-sol`` tool spelling, but
        # the account catalog's real model name is ``gpt-5.6-sol``.
        chosen_model = "gpt-5.6-sol" if model in (None, "gpt-6-sol") else model
        return [
            str(_codex_binary()), "exec", "-m", chosen_model,
            "-c", 'model_reasoning_effort="high"', "--approve-for-me",
            "-C", str(directory), "-o", str(report_path),
            brief_path.read_text(encoding="utf-8"),
        ]
    binary = shutil.which("hermes")
    if binary is None:
        raise FileNotFoundError("hermes not found on PATH")
    return [
        binary, "chat", "--oneshot", "--query-file", str(brief_path),
        "--format", "text", "--in", str(directory),
    ]


def _label(root: Path, requested: str) -> str:
    if tools.child_chat_dir(root, requested) is None:
        raise ValueError("name must be a safe single path component")
    root = root.resolve()
    agents = root / "agents"
    jobs_dir = root / "jobs"
    with _LABEL_LOCK:
        reserved = _RESERVED_LABELS.setdefault(root, set())
        if jobs_dir.is_dir():
            for path in jobs_dir.iterdir():
                match = _JOB_NAME.fullmatch(path.name) if path.is_dir() else None
                if match is not None:
                    reserved.add(match.group("label"))
        label = requested
        suffix = 2
        while label in reserved or (agents / label).exists():
            label = f"{requested}-{suffix}"
            suffix += 1
        reserved.add(label)
        return label


def _job_directory(root: Path, label: str) -> Path:
    jobs_dir = root / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    path = jobs_dir / f"{label}-{stamp}"
    counter = 2
    while True:
        try:
            path.mkdir()
            return path
        except FileExistsError:
            path = jobs_dir / f"{label}-{stamp}-{counter}"
            counter += 1


def _append_child_record(log: Log, tree: Tree, view: View, compactor: Compactor,
                         kind: str, value: str) -> None:
    i = log.append(kind, value)
    compactor.seed(i, value, kind)
    view.add_root(i)


def _child_chat(chat, job: Job, brief: str, process_log: str,
                report: str, work_text: str) -> None:
    child_root = Path(chat.root) / "agents" / job.label
    child_root.mkdir(parents=True, exist_ok=False)
    with Log(child_root) as log:
        tree = Tree(child_root, chat.config.node_bytes)
        view = View(
            tree, chat.config.view_min_bytes, chat.config.view_max_bytes,
            records=0,
        )
        compactor = Compactor(
            tree, lambda _request: "", node_bytes=chat.config.node_bytes,
            max_retries=chat.config.compact_max_retries, view=view,
        )
        for chunk in text.split_for_kind(brief, chat.config.node_bytes, "user"):
            _append_child_record(log, tree, view, compactor, "user", chunk)
        clipped_log = records.clip_tool_output(process_log)
        for chunk in text.split_for_kind(clipped_log, chat.config.node_bytes, "echo"):
            _append_child_record(log, tree, view, compactor, "echo", chunk)
        _append_child_record(log, tree, view, compactor, "will", report or work_text)
        tree.save()
        view.save()


def _publish(chat, job: Job, brief: str, process_log: str,
             report: str, work_text: str) -> None:
    with chat._engine():
        i = chat.log.append("work", work_text)
        chat.compactor.seed(i, work_text, "work")
        chat.view.add_root(i)
        chat.tree.save()
        chat.view.save()
        chat.save()
    _child_chat(chat, job, brief, process_log, report, work_text)
    chat.deliver_work(work_text)


def _finish(chat, job: Job, brief: str, *, stdout_is_report: bool,
            timeout_s: int) -> None:
    try:
        try:
            stdout, stderr = job.process.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            job.timed_out = True
            try:
                os.killpg(job.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout, stderr = job.process.communicate()
        job.exit_code = job.process.returncode
        stdout_text = (stdout or b"").decode("utf-8", errors="replace")
        stderr_text = (stderr or b"").decode("utf-8", errors="replace")
        process_log = stdout_text + stderr_text
        with job.log_path.open("a", encoding="utf-8") as stream:
            stream.write(process_log)
        if stdout_is_report:
            job.report_path.write_text(stdout_text, encoding="utf-8")
        try:
            report = job.report_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            report = ""
        report = report.strip()

        if job.timed_out:
            reason = f"timeout after {timeout_s}s"
        elif job.exit_code:
            reason = f"exit {job.exit_code}"
        elif not report:
            reason = "no report"
        else:
            reason = ""
        if reason:
            work_text = f"[{job.label}] failed: {reason}"
            tail = process_log[-2_000:].strip()
            if tail:
                work_text += "\n" + tail
        else:
            work_text = records.clip_tool_output(f"[{job.label}] {report}")
        _publish(chat, job, brief, process_log, report, work_text)
    finally:
        # ``poll`` now reflects a final state even if publication itself failed.
        if job.exit_code is None:
            job.exit_code = job.process.poll()


def spawn(*, chat, name: str, agent: str, brief: str,
          directory: Path | None = None, model: str | None = None,
          timeout_s: int = 1800, command: list[str] | None = None) -> Job:
    """Start one delegate and return without waiting for it."""
    agent = _normal_agent(agent)
    if not isinstance(brief, str) or not brief.strip():
        raise ValueError("task must be a nonempty string")
    if type(timeout_s) is not int or timeout_s <= 0:
        raise ValueError("timeout_s must be a positive integer")
    workdir = Path.cwd() if directory is None else Path(directory).expanduser()
    if not workdir.is_absolute():
        raise ValueError("delegate directory must be absolute")
    if not workdir.is_dir():
        raise ValueError(f"delegate directory does not exist: {workdir}")

    override: list[str] | None = None
    if command is not None:
        override = list(command) if isinstance(command, list) else command
        executable = _executable(override)
        override = [executable, *override[1:]]
    else:
        # Resolve missing binaries before creating any job artifact.
        if agent == "codex":
            _codex_binary()
        elif shutil.which("hermes") is None:
            raise FileNotFoundError("hermes not found on PATH")

    root = Path(chat.root)
    label = _label(root, name)
    job_dir = _job_directory(root, label)
    brief_path = job_dir / "brief.md"
    log_path = job_dir / "run.log"
    report_path = job_dir / "report.md"
    brief_path.write_text(brief, encoding="utf-8")
    log_path.touch()
    argv = override or _command(
        agent, brief_path=brief_path, report_path=report_path,
        directory=workdir, model=model,
    )
    try:
        process = subprocess.Popen(
            argv, cwd=workdir, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError:
        brief_path.unlink(missing_ok=True)
        log_path.unlink(missing_ok=True)
        job_dir.rmdir()
        raise

    job = Job(
        label=label, agent=agent, dir=job_dir, report_path=report_path,
        log_path=log_path, started_at=datetime.now(timezone.utc),
        process=process, thread=None,
    )
    thread = threading.Thread(
        target=_finish,
        kwargs={
            "chat": chat,
            "job": job,
            "brief": brief,
            "stdout_is_report": command is not None or agent == "hermes",
            "timeout_s": timeout_s,
        },
        name=f"willia-delegate-{label}", daemon=True,
    )
    job.thread = thread
    with _JOBS_LOCK:
        _JOBS.append(job)
    thread.start()
    return job


def running(chat) -> list[Job]:
    root = Path(chat.root).resolve()
    with _JOBS_LOCK:
        return [
            job for job in _JOBS
            if job.dir.parent.parent.resolve() == root
            and job.thread is not None and job.thread.is_alive()
        ]


def orphaned(chat) -> list[str]:
    jobs_dir = Path(chat.root) / "jobs"
    if not jobs_dir.is_dir():
        return []
    return sorted(
        path.name for path in jobs_dir.iterdir()
        if path.is_dir() and not (path / "report.md").is_file()
    )


def status_line(chat, startup_orphans: list[str]) -> str:
    now = datetime.now(timezone.utc)
    live = [
        f"{job.label} ({job.agent}, running {max(0, int((now - job.started_at).total_seconds()))}s)"
        for job in running(chat)
    ]
    parts = live or ["none"]
    if startup_orphans:
        parts.append("orphaned: " + ", ".join(startup_orphans))
    return "Jobs: " + "; ".join(parts)
