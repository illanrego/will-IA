# P1c — the pump: a drain thread, the lock, the watchdog and `--restore-view`

**Repo:** `~/Documents/coding/willia`. Read `docs/LOOP.md` §2, §3 (the liveness rules), §5 (the backup
and its validation) and `docs/ENV.md` §6 (the launcher). `docs/PHASES.md` P1 and the P1b brief say
what already exists; build on it, do not redesign it.

**Do not edit** anything under `docs/`, `SCOPE.md`, `PLAN.md`, `briefs/`, `reports/`, or the frozen
memory modules (`store.py`, `tree.py`, `view.py`, `compactor.py`, `media.py`, `notes.py`, `text.py`,
`tools.py`, `persistence.py`, `toolkit.py`, `prompts.py`, `records.py`, `dispatch.py`).

**NO GIT COMMANDS** — no `git add`, `commit`, `stash`, `checkout`, `reset`, `restore`. The session
commits after verifying; a delegate that commits makes the verification meaningless.
**No new dependencies** (stdlib only).

**Proof to report verbatim:** the pytest command from the P1b brief. It must be green with your new
tests, and **every test must run offline**.

---

## 1. The concurrency rule (`docs/LOOP.md` §3)

`Chat` gains **one** `threading.RLock` guarding every access to `Tree`, `View` and `Compactor` from
both sides — the turn and the drain. Concretely:

- a small private context manager (`Chat._engine()`) that takes the lock;
- every turn-side mutation and read of the engine (`seed`, `add_root`, `put`, `save`, `merge_batch`,
  `render`, `settle`, `run_pending`, `_request`, and the view render that appends the turn's roots)
  happens inside it;
- the drain's **whole `run_pending` wave** runs inside a single acquisition, and so does the
  `tree.save()` / `view.save()` that follows it. A turn's mutation may therefore wait for a wave —
  that is the accepted cost (`docs/LOOP.md` §3), and the join in §2 below bounds the wait.

## 2. The drain thread and the turn's join

- `Chat.start_drain()` spawns **one** daemon thread that runs exactly one pass and exits
  (`run_pending(limit=config.compact_concurrency, model_calls=True)`, then `tree.save()`,
  `view.save()`, then the backup copy). It is started at the end of `end_turn` and after startup
  reconciliation. **Never two drains at once**: keep a single reference and do not start one while
  `is_alive()`.
- The turn's wait (`docs/LOOP.md` §2): before rendering, take the lock and
  `compactor.settle(max_nodes=64, timeout_s=20.0, model_calls=False)`; then, if a drain is running,
  join it for at most `config.model.drain_join_s` (new key, **default 5**, integer seconds). On
  timeout the turn proceeds — the view may carry `(not summarized yet: zoom it)` and that is the
  documented, accepted outcome, not an error. Add the key to `willia/config.py` under `model` and
  report the addition (the doc's JSON sample does not list it).
- `end_turn` keeps its synchronous bounded `run_pending` only when no drain is running.

## 3. The watchdog (`docs/LOOP.md` §3, rule 3)

No extra thread. A single method `Chat.check_liveness()` called at turn start and in `end_turn`:

- if no drain is running **and** (`compactor._pending` is non-empty **or** `not view.settled()`)
  **and** at least `config.model.watchdog_grace_s` (new key, **default 60**, integer seconds) has
  passed since the last pass finished, then drive one pass (synchronously, under the lock) and record
  it;
- if two consecutive passes build **zero** nodes while work is still queued, write one **loud** line
  to `~/.willia/logs/willia.log` naming the queued count and the last error, and keep serving (never
  raise into the turn);
- record on the Chat: the last pass start/finish times, the last pass's built count, and the last
  error — `Chat.status()` prints them (`docs/ENV.md` §6: "summarizing" and "stuck" must be
  distinguishable by looking).

## 4. `willia --restore-view` (`docs/LOOP.md` §5, `docs/ENV.md` §6)

`cli.py` gains the flag. It **validates before adopting**, and refuses loudly with nothing written:

- the backup must parse as the same shape as `view.json` (`version: 2`);
- its covered end (`sum(1 << l for l, _ in pairs)`) must be **≤** `log.count()` — a backup claiming
  more messages than the log holds is refused;
- every pair in it must have a **built** node in the tree;
- on success: copy the backup over `<root>/view.json`, then add the missing roots forward from the
  backup's end to `log.count() - 1`, `merge_batch`, save, run one bounded pass, and print what it
  adopted (the covered end, the record count, the roots added). **Never rebuild a view state** — this
  adopts a real publication and advances it; it never synthesises one.
- with no backup file present, a corrupt backup, or a refused one: exit nonzero naming the reason.

## 5. Tests (offline)

`tests/test_pump.py`
1. **No interleaving:** a fake compactor whose `run_pending` sleeps briefly and records entry/exit
   into a shared list; a turn thread and a drain thread run together; assert the recorded spans never
   overlap (the lock holds).
2. **The join cap:** a drain that takes longer than `drain_join_s` (patched to 1 s) — the turn
   proceeds and the view may be unsettled; assert the turn finished and the drain completed after it.
3. **The join works:** a drain shorter than the cap — the turn starts with a settled view.
4. **The watchdog drives a pass:** queue work with no drain running and the grace period elapsed
   (patched to 0) → the pass runs; two zero-build passes → exactly one loud line in the log
   (assert via the log file's contents or a captured handler).
5. **Never two drains:** calling `start_drain()` twice in a row leaves one live thread.
6. **Liveness end to end:** three scripted turns with a fake client → at the end
   `view.settled()` is true and no queued work remains.

`tests/test_restore_view.py` — the four validation cases (adopt-and-advance; end beyond the log;
an unbuilt pair; a corrupt/absent file), asserting that a refused restore writes **nothing** (compare
`view.json`'s bytes before and after) and that the adopted one leaves the view covering
`log.count()`.

Extend `tests/test_cli.py` for the new flag; extend `tests/test_config.py` for the two new keys
(`drain_join_s`, `watchdog_grace_s`) and their defaults.

## 6. Constraints

- Touch only: `willia/chat.py`, `willia/cli.py`, `willia/config.py`, `willia/__init__.py` (if an
  export is needed), `tests/test_pump.py` (new), `tests/test_restore_view.py` (new), and the two
  existing test files named above. **Nothing else.**
- The pump must never block the REPL's reader thread, and the reader must never touch the engine.
- Nothing per-turn may enter the system prompt or the tool array (`docs/LOOP.md` §9.10).
- English everywhere; keep the docstring register of the modules you are editing.
