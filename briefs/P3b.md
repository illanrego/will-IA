# brief: the Codex account in the meter and the rail

Read first: `docs/WIRE-FORMATS.md` section 9 (the usage surface), `willia/usage.py`,
`willia/cli.py` (`_print_usage`), `willia/tui/__init__.py` (`build_rail_facts` and `run`),
`willia/tui/hints.py`, and `tests/test_usage.py`.

Today the meter and the rail show one account: OpenCode Go, from `GET {base}/usage` with
`OPENCODE_GO_API_KEY`. Illan asked for **both** accounts, with the reset countdowns, on `/usage` and
in the rail. The reset data is already in both payloads, so this adds no new call beyond the second
account's own.

## 1. `usage.codex_windows(...)` — the Codex account's own windows

- Credential: **`~/.codex/auth.json`, read only** — `tokens.access_token` and `tokens.account_id`.
  Never refresh the token, never write that file, and never print or log the token or the account id.
- URL: mirror the Codex CLI's own PathStyle split. Take a base (default
  `https://chatgpt.com/backend-api/codex`), strip a trailing `/codex`, then append `/wham` when
  `/backend-api` appears in the base and `/api/codex` otherwise, then `/usage`. For the default that
  is `https://chatgpt.com/backend-api/wham/usage`.
- Headers: `Authorization: Bearer <access_token>`, `chatgpt-account-id: <account_id>`,
  `Accept: application/json`, and a real `User-Agent` (a bare library agent is refused).
- **This exact payload was measured live on 2026-10-14** (do not invent fields):

```json
{"plan_type": "plus",
 "rate_limit": {"allowed": true, "limit_reached": false,
   "primary_window": {"used_percent": 12, "limit_window_seconds": 18000,
                      "reset_after_seconds": 14900, "reset_at": 1791975321},
   "secondary_window": {"used_percent": 18, "limit_window_seconds": 604800,
                        "reset_after_seconds": 551849, "reset_at": 1792512270}},
 "model_usage": {"gpt-6-astra": {"available": true, "available_at": null,
                                 "credits_would_enable": false}},
 "rate_limit_reset_credits": {"available_count": 3, "applicable_available_count": 0},
 "credits": {"has_credits": false, "unlimited": false, "balance": "0"}}
```

  (The response also carries `user_id`, `account_id` and `email`; **none of those may appear in any
  output, rail row, log line or error message.**)
- Return a normalized mapping, so no caller has to know this shape:

```python
{"plan": "plus",
 "primary": {"label": "5h", "percent": 12, "resets_in_s": 14900},
 "secondary": {"label": "7d", "percent": 18, "resets_in_s": 551849},
 "reset_credits": 3,
 "astra_available": True}
```

  Missing pieces are `None` rather than fatal: a payload without `model_usage` simply has no
  `astra_available`. An absent auth file, an expired token (HTTP 401) and a network failure each
  raise a **named** error whose message says which of the three it was and never quotes the token.

## 2. One countdown helper

The TUI already formats a countdown in `tui/__init__.py::_countdown` (from an ISO string or an epoch
second). The Codex payload gives `reset_after_seconds`, so it needs the same formatting from a
duration. Put **one** implementation in `willia/usage.py` that takes a number of seconds and returns
`"12m"` / `"3h51m"` / `"4d17h"` (days and hours when there are days, hours and minutes when there are
hours, minutes otherwise), have the TUI use it, and delete the duplicate. The tests for it go in
`tests/test_usage.py`.

## 3. `willia --usage` shows both accounts

Keep every existing line. Add the Codex block in the same shape as the Go one, labelled, with the
countdowns and the plan; include the reset credits when the payload has them. **A failure on one
account must not fail the command or hide the other**: print
`codex: unavailable (<reason>)` and still exit 0 with the Go numbers and the local meter intact.

## 4. The rail gains the second account

- Today: `go` (the three percentages) and `resets` (their countdowns).
- Wanted: `go` and `go ↺` for the Go pair, then `codex` and `codex ↺` for the Codex pair — the four
  rows adjacent, in that order, so it is obvious which countdown belongs to which account. Keep the
  label column's width in mind (the rail fits 9 cells; `codex ↺` fits).
- `willia/tui/hints.py` gains entries for the two new labels, in the same register as the rest
  (second person, plain, one or two sentences). The Codex hint should say what the two windows are
  and that the payload also reports whether the expensive model is available.
- `tui/__init__.py::run` already fetches the Go windows on a daemon thread at startup; fetch the
  Codex ones the same way, in the same thread or a second one, so **nothing on the startup path ever
  waits** (that is a hard rule here: a network call on the startup path once left the terminal blank).
  A failed or slow fetch leaves the row showing `unavailable`, never a blank rail and never a stall.
- `build_rail_facts` must stay a pure function of its arguments: pass the Codex windows in the same
  way the Go ones are passed today, and keep returning the layout-neutral `(label, value, style)`
  tuples.

## Constraints (every one, again)

- **No git commands of any kind.** No commit, stash, branch, restore, diff or reset.
- Edit only: `willia/usage.py`, `willia/cli.py`, `willia/tui/__init__.py`, `willia/tui/hints.py`,
  `tests/test_usage.py`, `tests/test_tui_*.py`.
- **No new dependency.** Standard library only.
- Never write to `~/.codex`, never refresh that token, never emit the token, the account id, the email
  or the user id anywhere.
- All tests offline: inject or monkeypatch the transport, and point the auth file at a `tmp_path`.
  The suite must never touch the real `~/.codex` and never make a network call.
- The system prompt, the tool array, the log format and the TUI's idle silence do not change.

## Proof

Run the whole suite (`uv run --no-project --with pytest python -m pytest -q`) and paste the tail.
Then paste `codex_windows`' body, list the files you changed, and state plainly anything you could not
do.
