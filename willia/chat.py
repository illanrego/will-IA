"""Own the durable chat and the request assembled for each turn.

The view is rendered before input is logged and frozen across tool rounds.
One harness lock serializes the turn with the background compaction pump.
"""

from __future__ import annotations

import json
import queue
import shutil
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone

from . import jobs, prompts, records, toolkit
from .client import Client, ClientError
from .compactor import Compactor
from .dispatch import dispatch
from .session import session_id
from .store import Log
from .tree import Tree
from .view import View, ViewStateUnavailable


class Chat:
    @classmethod
    def open(cls, config, *, client=None) -> Chat:
        self = cls()
        self.config = config
        self.root = config.root
        self.inbox = None
        self._closed = False
        self._deliveries: queue.SimpleQueue[str] = queue.SimpleQueue()
        self._startup_orphans: list[str] = []
        self._diagnostics = None
        self._engine_lock = threading.RLock()
        self._drain_lock = threading.Lock()
        self._drain: threading.Thread | None = None
        self.last_pass_start: str | None = None
        self.last_pass_finish: str | None = None
        self.last_pass_built: int | None = None
        self.last_pass_error: str | None = None
        self._last_pass_finished_monotonic: float | None = None
        self._zero_build_passes = 0
        self._stuck_reported = False
        paths = config.paths
        # Read-only preflight precedes even lock creation and torn-tail repairs.
        # Losing the view must leave every existing byte available for recovery.
        if not paths.view_file.exists():
            try:
                with Log(self.root, read_only=True) as probe:
                    View(Tree(self.root, config.node_bytes, read_only=True),
                         config.view_min_bytes, config.view_max_bytes, records=probe.count())
            except ViewStateUnavailable as exc:
                raise ViewStateUnavailable(
                    f"{exc} Use willia --restore-view with {paths.view_backup_file}; "
                    "nothing was written."
                ) from exc
        self.log = Log(self.root)
        try:
            self.tree = Tree(self.root, config.node_bytes)
            self.view = View(self.tree, config.view_min_bytes, config.view_max_bytes,
                             records=self.log.count())
            for directory in (paths.main_dir, paths.tree_dir, paths.assets_dir,
                              paths.agents_dir, paths.jobs_dir, paths.logs_dir,
                              paths.view_backup_file.parent):
                directory.mkdir(parents=True, exist_ok=True)
            self._startup_orphans = jobs.orphaned(self)
            if not paths.prompt_file.exists():
                paths.prompt_file.write_text(prompts.default_instructions(), encoding="utf-8")
            self.system = prompts.build_system_prompt(paths.prompt_file.read_text(encoding="utf-8"))
            self.tools = toolkit.schemas()
            self.session = session_id(self.root)
            self.client = client if client is not None else Client(config, self.session)
            self.compactor = Compactor(self.tree, self._summarize,
                                       node_bytes=config.node_bytes,
                                       max_retries=config.compact_max_retries, view=self.view)
            self.compactor.system = self.system
            self.compactor.tools = self.tools
            with self._engine():
                changed = False
                for i in range(self.view._end(), self.log.count()):
                    self.view.add_root(i)
                    changed = True
                for i in range(self.log.count()):
                    if self.tree.get(0, i) is None:
                        record = self.log.get(i)
                        if record is None:
                            raise ValueError(f"Cannot seed refused log record {i}")
                        self.compactor.seed(record.i, record.text, record.kind)
                        changed = True
                if changed:
                    self.view.merge_batch(self.log.count())
            self.save()
            self._diagnostics = (paths.logs_dir / "willia.log").open("a", encoding="utf-8")
            self._diagnostics.write(
                f"{datetime.now(timezone.utc).isoformat()} startup root={self.root} "
                f"session={self.session[:8]} records={self.log.count()}\n")
            self._diagnostics.flush()
            drain = self.start_drain()
            # Give an immediately satisfiable reconciliation pass a scheduling
            # slice; real model work remains in the daemon after this short cap.
            drain.join(min(config.model.drain_join_s, 0.1))
            return self
        except BaseException:
            self.log.close()
            if self._diagnostics is not None:
                self._diagnostics.close()
            raise

    def _summarize(self, request):
        return self.client.summarize(request)

    @contextmanager
    def _engine(self):
        """Serialize every access to the mutable memory engine."""
        with self._engine_lock:
            yield

    def _log_message(self, message: dict, tool_name: str | None = None) -> list[str]:
        chunks = []
        classified = records.classify(message, self.config.node_bytes, tool_name)
        with self._engine():
            for kind, text in classified:
                i = self.log.append(kind, text)
                self.compactor.seed(i, text, kind)
                self.view.add_root(i)
                chunks.append(text)
        return chunks

    def _users(self, texts: list[str]) -> list[dict]:
        return [{"role": "user", "content": chunk}
                for text in texts
                for chunk in self._log_message({"role": "user", "content": text})]

    def _drain_inbox(self) -> list[str]:
        if self.inbox is None:
            return []
        if hasattr(self.inbox, "drain_messages"):
            return self.inbox.drain_messages()
        texts = []
        while True:
            try:
                texts.append(self.inbox.get_nowait())
            except queue.Empty:
                return texts

    def deliver_work(self, text: str) -> None:
        """Queue an already logged work record for one model delivery."""
        if not isinstance(text, str) or not text:
            raise ValueError("Delivered work must be nonempty text")
        self._deliveries.put(text)

    def _drain_deliveries(self) -> list[dict]:
        messages = []
        while True:
            try:
                value = self._deliveries.get_nowait()
            except queue.Empty:
                return messages
            messages.append({"role": "user", "content": value})

    @staticmethod
    def _emit(sink, event: str, **data) -> None:
        """Report a display event without letting a broken display break a turn."""
        if sink is None:
            return
        try:
            sink(event, **data)
        except Exception:
            pass

    def _on_delta(self, kind: str, text: str, *, sink=None) -> None:
        if text:
            self._displayed = True
            if sink is None:
                print(text, end="", flush=True)
            else:
                self._emit(sink, "delta", kind=kind, text=text)

    @staticmethod
    def _assistant(reply) -> dict:
        message = {"role": "assistant", "content": reply.content or ""}
        if reply.tool_calls:
            calls = []
            for call in reply.tool_calls:
                raw = call.raw_arguments
                if raw is None:
                    raw = call.arguments if isinstance(call.arguments, str) else json.dumps(
                        call.arguments, ensure_ascii=False)
                calls.append({"id": call.id, "type": "function", "function": {
                    "name": call.name, "arguments": raw}})
            message["tool_calls"] = calls
        return message

    def turn(self, texts: list[str], *, sink=None) -> None:
        self.check_liveness()
        with self._engine():
            self.compactor.settle(max_nodes=64, timeout_s=20.0, model_calls=False)
        drain = self._drain
        if drain is not None and drain.is_alive() and drain is not threading.current_thread():
            drain.join(self.config.model.drain_join_s)
        with self._engine():
            view_text = self.view.render()
        request = [{"role": "system", "content": self.system},
                   {"role": "assistant", "content": view_text}]
        try:
            request.extend(self._drain_deliveries())
            request.extend(self._users(texts))
            empty_replies = 0
            while True:
                request.extend(self._drain_deliveries())
                self._displayed = False
                try:
                    reply = self.client.turn(
                        request, self.tools,
                        on_delta=lambda kind, text: self._on_delta(kind, text, sink=sink),
                    )
                finally:
                    if self._displayed and sink is None:
                        print(flush=True)
                assistant = self._assistant(reply)
                self._log_message(assistant)
                request.append(assistant)
                if not reply.tool_calls:
                    if not reply.content:
                        empty_replies += 1
                        if empty_replies == 1:
                            request.extend(self._users(self._drain_inbox()))
                            continue
                        notice = "The model returned no ordinary content after one retry."
                        if sink is None:
                            print(notice)
                        else:
                            self._emit(sink, "notice", text=notice)
                    break
                empty_replies = 0
                for call in reply.tool_calls:
                    arguments = call.arguments
                    displayed = arguments if isinstance(arguments, str) else json.dumps(
                        arguments, ensure_ascii=False)
                    displayed = displayed.replace("\r", "\\r").replace("\n", "\\n")
                    if sink is None:
                        print(f"→ {call.name} {displayed}", flush=True)
                    else:
                        self._emit(
                            sink, "tool_call", name=call.name,
                            arguments=arguments, displayed=displayed,
                        )
                    started = time.monotonic()
                    with self._engine():
                        result = dispatch(
                            call.name, arguments, log=self.log, tree=self.tree,
                            view=self.view, root=self.root,
                            node_bytes=self.config.node_bytes, chat=self)
                    elapsed_ms = (time.monotonic() - started) * 1000.0
                    message = {"role": "tool", "tool_call_id": call.id, "content": result}
                    record_tool = None if call.name in {
                        "delegate_codex", "delegate_hermes"
                    } else call.name
                    self._log_message(message, record_tool)
                    request.append(message)
                    if sink is None:
                        print((result.splitlines() or [""])[0][:200], flush=True)
                    else:
                        self._emit(
                            sink, "tool_result", name=call.name, result=result,
                            elapsed_ms=elapsed_ms,
                        )
                request.extend(self._drain_deliveries())
                request.extend(self._users(self._drain_inbox()))
        except ClientError as exc:
            notice = f"Error: {exc}"
            if sink is None:
                print(notice, flush=True)
            else:
                self._emit(sink, "notice", text=notice)
        finally:
            self.end_turn(sink=sink)

    def save(self) -> None:
        with self._engine():
            self._save_locked()

    def _save_locked(self) -> None:
        self.tree.save()
        self.view.save()
        shutil.copyfile(self.config.view_file, self.config.view_backup_file)

    def _work_locked(self) -> bool:
        return bool(self.compactor._pending) or not self.view.settled()

    def _record_pass(self, built: int, error: str | None, work_remains: bool,
                     queued: int) -> None:
        self.last_pass_finish = datetime.now(timezone.utc).isoformat()
        self._last_pass_finished_monotonic = time.monotonic()
        self.last_pass_built = built
        self.last_pass_error = error
        if built or not work_remains:
            self._zero_build_passes = 0
            self._stuck_reported = False
            return
        self._zero_build_passes += 1
        if self._zero_build_passes < 2 or self._stuck_reported:
            return
        line = (
            f"{datetime.now(timezone.utc).isoformat()} WATCHDOG STUCK "
            f"queued={queued} last_error={error or 'none'}\n"
        )
        if self._diagnostics is not None:
            self._diagnostics.write(line)
            self._diagnostics.flush()
        self._stuck_reported = True

    def _run_pass(self, *, deadline: float | None = None) -> int:
        self.last_pass_start = datetime.now(timezone.utc).isoformat()
        built = 0
        error = None
        work_remains = True
        queued = 0
        try:
            with self._engine():
                built = self.compactor.run_pending(
                    limit=self.config.compact_concurrency,
                    deadline=deadline,
                    model_calls=True,
                )
                # A deferred pass can retain a context or advance a merge batch.
                self._save_locked()
                work_remains = self._work_locked()
                queued = len(self.compactor._pending)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            try:
                with self._engine():
                    work_remains = self._work_locked()
                    queued = len(self.compactor._pending)
            except Exception:
                work_remains = True
        self._record_pass(built, error, work_remains, queued)
        return built

    def _pump(self) -> int:
        """Run the retained synchronous, deadline-bounded end-turn pass."""
        return self._run_pass(deadline=time.monotonic() + 20.0)

    def _drain_once(self) -> None:
        try:
            with self._engine():
                work_remains = self._work_locked()
            if work_remains:
                self._run_pass()
        finally:
            if self._closed and self._diagnostics is not None:
                self._diagnostics.close()
                self._diagnostics = None

    def start_drain(self) -> threading.Thread:
        """Start one daemon compaction pass, or return the pass already running."""
        with self._drain_lock:
            if self._drain is not None and self._drain.is_alive():
                return self._drain
            self._drain = threading.Thread(
                target=self._drain_once, name="willia-compaction-drain", daemon=True)
            self._drain.start()
            return self._drain

    def check_liveness(self) -> bool:
        """Drive a stale queue once and make repeated zero-progress passes loud."""
        drain = self._drain
        if drain is not None and drain.is_alive():
            return False
        with self._engine():
            work_remains = self._work_locked()
        if not work_remains:
            return False
        finished = self._last_pass_finished_monotonic
        if (finished is not None
                and time.monotonic() - finished < self.config.model.watchdog_grace_s):
            return False
        self._run_pass(deadline=time.monotonic() + 20.0)
        return True

    def end_turn(self, *, sink=None) -> None:
        self.save()
        watchdog_ran = self.check_liveness()
        drain = self._drain
        if not watchdog_ran and (drain is None or not drain.is_alive()):
            self._pump()
        self.start_drain()
        usage = self.client.last_usage
        cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
        reasoning = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0)
        if sink is None:
            print(f"prompt_tokens={usage.get('prompt_tokens', 0)} "
                  f"cached_tokens={usage.get('cached_tokens', cached)} "
                  f"reasoning_tokens={usage.get('reasoning_tokens', reasoning)}", flush=True)
        else:
            self._emit(sink, "end", usage=dict(usage))

    def status(self) -> list[str]:
        drain = self._drain
        with self._engine():
            work_remains = self._work_locked()
            view_bytes = len(self.view.render().encode("utf-8"))
            unbuilt = len(self.compactor._queued)
        if drain is not None and drain.is_alive():
            pump = "summarizing"
        elif self._stuck_reported and work_remains:
            pump = "stuck"
        elif work_remains:
            pump = "queued"
        else:
            pump = "idle"
        return [f"Root: {self.root}", f"Session: {self.session[:8]}",
                f"Records: {self.log.count()}", f"View bytes: {view_bytes}",
                f"Unbuilt nodes: {unbuilt}", f"Compaction: {pump}",
                f"Last pass: start={self.last_pass_start or 'never'} "
                f"finish={self.last_pass_finish or 'never'} "
                f"built={self.last_pass_built if self.last_pass_built is not None else 'n/a'} "
                f"error={self.last_pass_error or 'none'}",
                f"Children: {sum(p.is_dir() for p in self.config.agents_dir.iterdir())}",
                jobs.status_line(self, self._startup_orphans),
                f"Last usage: {json.dumps(self.client.last_usage, ensure_ascii=False)}"]

    def close(self) -> None:
        if self._closed:
            return
        drain = self._drain
        if drain is not None and drain.is_alive() and drain is not threading.current_thread():
            drain.join(self.config.model.drain_join_s)
        try:
            if drain is None or not drain.is_alive():
                self.save()
        finally:
            self.log.close()
            if self._diagnostics is not None and (drain is None or not drain.is_alive()):
                self._diagnostics.close()
                self._diagnostics = None
            self._closed = True
