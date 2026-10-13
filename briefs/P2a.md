# P2a — the delegates: real subprocesses, background reports, child chats

**Repo:** `~/Documents/coding/willia`. Read `docs/DELEGATES.md` in full (it is the contract for this
run), `docs/TOOLS.md` §4 (the two schemas are **already frozen in `willia/toolkit.py`** — your
implementation must match them, not invent), `docs/LOOP.md` §6 (backgrounding) and §7 (failure modes),
`docs/WIRE-FORMATS.md` §1 (no list-type content).

**Do not edit** `docs/`, `SCOPE.md`, `PLAN.md`, `briefs/`, `reports/`, or any frozen module. The tool
array and the prompt are the cache anchor: **do not add, remove, rename or reword a tool**.
**NO GIT COMMANDS.** **No new dependencies** (stdlib only).

**Proof to report verbatim:** the pytest command from the P1b brief. 230 passed before this run; it
must be green after with your new tests. Tests may spawn local processes (a tiny `python3 -c …` as the
"delegate"); they must **never** touch the network or a real Codex/Hermes.

---

## 1. `willia/jobs.py` — the job supervisor

```python
class Job:  # label, agent, dir, report_path, log_path, started_at, process, thread, timed_out, exit_code
def spawn(*, chat, name: str, agent: str, brief: str, directory: Path | None = None,
          model: str | None = None, timeout_s: int = 1800, command: list[str] | None = None) -> Job
```
- Creates `~/.willia/jobs/<label>-<UTCstamp>/` holding `brief.md`, `run.log`, `report.md`.
- The exact commands (`docs/DELEGATES.md` §2, §3) — build them in one place, `_command(agent, …)`:
  - `delegate_codex`: `<codex bin> exec -m <model> -c model_reasoning_effort="high" --approve-for-me -C <dir> -o <report.md> "$(cat brief.md)"` — pass the brief's text as the **final argv element** (never through a shell), and `-o` writes the report. The binary is `$(npm prefix -g)/bin/codex`; resolve it once and cache it; **not on PATH**.
  - `delegate_hermes`: `hermes chat --oneshot --query-file <brief.md> --format text --in <dir>` — stdout **is** the report; write it to `report.md`.
  - `command=` overrides both, for tests only.
- Model default `gpt-5.6-sol`; `model` may be `gpt-6-astra` (the schema's enum). The account's catalog is `gpt-5.5`, `gpt-5.6-sol`, `gpt-6-astra`; `gpt-6-sol` does not exist.
- `subprocess.Popen(..., start_new_session=True)` so a timeout can kill the whole process group
  (`os.killpg`), stdout+stderr appended to `run.log`, cwd = the working directory.
- **A supervisor thread per job** (never block the caller): wait with the timeout, kill the group on
  expiry, then finish the job (§3). `spawn` returns **immediately**.
- **Never wait or poll from the turn**: no `subprocess.wait` on the caller's thread, no sleep loops.

## 2. The tool entry points (`willia/dispatch.py`)

- `delegate_codex` and `delegate_hermes` stop returning `not implemented yet` and instead validate
  against the frozen schema, spawn, and return **immediately**:
  `{"status": "started", "name": <label>, "agent": "codex"|"hermes", "report_path": "<abs>"}`.
- Validate: `task` non-empty string; `model` one of the two names; `name` when given a safe single path
  component (reuse the child-directory rule); a missing binary or a bad directory returns
  `{"error": "…"}` and **spawns nothing** (nothing is logged as a `tool` in that case — the caller
  decides, so just return the error).
- `web_search`, `web_extract`, `vision` keep returning `not implemented yet: <name>` (P2b owns them).

## 3. Finishing a job: the report, the child chat, the `work` record

On exit, in the supervisor thread, under `chat._engine()`:
1. Read the report (`report.md` for codex, `run.log`'s stdout capture for hermes). Missing or empty →
   the failure path.
2. **Exactly one** record is appended to the chat's log:
   - success → `("work", f"[{label}] {report}")`, clipped head+tail at 30,000 (`records.clip_tool_output`);
   - failure (nonzero exit, timeout, or no report) → `("work", f"[{label}] failed: {reason}")` with the
     reason naming the exit code, the timeout, or "no report", plus the last ~2,000 characters of
     `run.log`. **Never silent.**
   - Then `compactor.seed(...)`, `view.add_root(...)`, `tree.save()`, `view.save()`, `chat.save()`.
3. **The child chat** (`docs/DELEGATES.md` §5): `<root>/agents/<label>/` gets a real chat of its own —
   the brief as one `user` record (split), the process log as `echo` records (clipped), the report as
   one `will` record — with its own `main/`, `tree/`, `view.json`. Build it with the same classes
   (`Log`, `Tree`, `View`, `Compactor` with a no-op summarizer is fine to start: leave nodes unbuilt,
   it is a read-only record). `zoom("<label>")` must then open it through the existing dispatcher.
4. **Delivery** (`docs/LOOP.md` §6): the report must reach the model — the record is already logged, so
   the turn must **not** log it again. Add `Chat.deliver_work(text)` that puts the text into a
   `Chat._deliveries` queue; the turn drains that queue (a) between tool rounds and (b) at the start of
   the next turn, appending it to the request as a message (`{"role": "user", "content": text}`) and
   logging nothing. `Chat.turn` with nothing queued behaves as today.

## 4. Status and orphans

`Chat.status()` gains one line: the live jobs (`label (agent, running 12s)` for each), and on startup
any job directory with **no** `report.md` is listed as orphaned, so a job killed with the process is
visible rather than swallowed.

## 5. Tests (offline; local processes only, no network)

`tests/test_jobs.py`
1. A `command=` override of `python3 -c "print('the report')"`: `spawn` returns immediately, the job
   finishes, the brief/log/report files exist, and **exactly one** `work` record appears with the
   `[label]` prefix and the report's text.
2. A failing command (`python3 -c "import sys; sys.exit(3)"`) → one `work` record
   `"[label] failed: exit 3"` plus the log tail; nothing else logged.
3. A command that produces no output → `"failed: no report"`.
4. A timeout (`timeout_s=1` with `python3 -c "import time; time.sleep(30)"`) → killed (the process is
   gone), `"failed: timeout after …"`, and the test ends quickly (assert the whole test takes < 10 s).
5. The child chat: after a success, `<root>/agents/<label>/view.json` exists, its log holds the brief,
   the log lines and the report, and `dispatch("zoom", {"id": <label>})` opens it with the label.
6. Delivery: with a fake client and a job that finishes during a turn, the report text appears in the
   request messages of that turn or the next, exactly once, and is **not** logged a second time as a
   `user` record.
7. Two jobs with the same requested `name` get distinct labels (a numeric suffix at creation time).
8. A missing binary (`command=[<path that does not exist>]`) → `dispatch` returns `{"error": …}` and no
   job directory is created.

## 6. Constraints

- Touch only: `willia/jobs.py` (new), `willia/dispatch.py`, `willia/chat.py`, `willia/cli.py` (only if
  the orphan line needs a flag), `willia/__init__.py` (exports), `tests/test_jobs.py` (new). Nothing
  else; if another file seems necessary, stop and say so in the report.
- English everywhere; docstrings in the vendored register.
