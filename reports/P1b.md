Implemented P1b: client fixes, records, dispatch, turn loop, REPL, launcher, and console entry point.

Only allowlisted files were edited. No Git commands or new dependencies.

Proof:
```text
~/.hermes/tools/uv-0.12.3-linux-x64/uv run --no-project --with pytest python -m pytest -q
```

**208 passed**, including 69 new tests; two existing warnings. All tests ran offline without real Codex or subprocess calls.