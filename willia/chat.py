"""Own the durable chat and the request assembled for each turn.

The view is rendered before input is logged and frozen across tool rounds.
Compaction runs without model calls at turn start, then in a bounded synchronous
pass after publication; only this owner mutates the memory engine.
"""

from __future__ import annotations

import json
import queue
import shutil
import time
from datetime import datetime, timezone

from . import prompts, records, toolkit
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
        self._diagnostics = None
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
            self._pump()
            self._diagnostics = (paths.logs_dir / "willia.log").open("a", encoding="utf-8")
            self._diagnostics.write(
                f"{datetime.now(timezone.utc).isoformat()} startup root={self.root} "
                f"session={self.session[:8]} records={self.log.count()}\n")
            self._diagnostics.flush()
            return self
        except BaseException:
            self.log.close()
            if self._diagnostics is not None:
                self._diagnostics.close()
            raise

    def _summarize(self, request):
        return self.client.summarize(request)

    def _log_message(self, message: dict, tool_name: str | None = None) -> list[str]:
        chunks = []
        for kind, text in records.classify(message, self.config.node_bytes, tool_name):
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

    def _on_delta(self, kind: str, text: str) -> None:
        if text:
            self._displayed = True
            print(text, end="", flush=True)

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

    def turn(self, texts: list[str]) -> None:
        self.compactor.settle(max_nodes=64, timeout_s=20.0, model_calls=False)
        view_text = self.view.render()
        request = [{"role": "system", "content": self.system},
                   {"role": "assistant", "content": view_text}]
        try:
            request.extend(self._users(texts))
            empty_replies = 0
            while True:
                self._displayed = False
                try:
                    reply = self.client.turn(request, self.tools, on_delta=self._on_delta)
                finally:
                    if self._displayed:
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
                        print("The model returned no ordinary content after one retry.")
                    break
                empty_replies = 0
                for call in reply.tool_calls:
                    arguments = call.arguments
                    displayed = arguments if isinstance(arguments, str) else json.dumps(
                        arguments, ensure_ascii=False)
                    displayed = displayed.replace("\r", "\\r").replace("\n", "\\n")
                    print(f"→ {call.name} {displayed}", flush=True)
                    result = dispatch(call.name, arguments, log=self.log, tree=self.tree,
                                      view=self.view, root=self.root, node_bytes=self.config.node_bytes)
                    message = {"role": "tool", "tool_call_id": call.id, "content": result}
                    self._log_message(message, call.name)
                    request.append(message)
                    print((result.splitlines() or [""])[0][:200], flush=True)
                request.extend(self._users(self._drain_inbox()))
        except ClientError as exc:
            print(f"Error: {exc}", flush=True)
        finally:
            self.end_turn()

    def save(self) -> None:
        self.tree.save()
        self.view.save()
        shutil.copyfile(self.config.view_file, self.config.view_backup_file)

    def _pump(self) -> None:
        self.compactor.run_pending(
            limit=self.config.compact_concurrency, deadline=time.monotonic() + 20.0,
            model_calls=self.config.compact_enabled)
        # Even a deferred pass can retain a context or advance a merge batch.
        # Publish those selections along with any newly built nodes.
        self.save()

    def end_turn(self) -> None:
        self.save()
        self._pump()
        usage = self.client.last_usage
        cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
        reasoning = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0)
        print(f"prompt_tokens={usage.get('prompt_tokens', 0)} "
              f"cached_tokens={usage.get('cached_tokens', cached)} "
              f"reasoning_tokens={usage.get('reasoning_tokens', reasoning)}", flush=True)

    def status(self) -> list[str]:
        return [f"Root: {self.root}", f"Session: {self.session[:8]}",
                f"Records: {self.log.count()}",
                f"View bytes: {len(self.view.render().encode('utf-8'))}",
                f"Unbuilt nodes: {len(self.compactor._queued)}",
                f"Children: {sum(p.is_dir() for p in self.config.agents_dir.iterdir())}",
                f"Last usage: {json.dumps(self.client.last_usage, ensure_ascii=False)}"]

    def close(self) -> None:
        if self._closed:
            return
        try:
            self.save()
        finally:
            self.log.close()
            if self._diagnostics is not None:
                self._diagnostics.close()
            self._closed = True
