Implemented P1c within the allowed files only.

Key changes:

- Added the single `Chat` engine `RLock`.
- Added daemon drain passes, bounded turn joins, and duplicate-drain prevention.
- Added watchdog pass tracking, stuck detection, diagnostics, and status output.
- Added `model.drain_join_s` defaulting to `5`.
- Added `model.watchdog_grace_s` defaulting to `60`.
- Added validation-first `willia --restore-view`.
- Added offline pump, restore, CLI, and configuration tests.
- No dependencies added and no Git commands run.

Required proof:

```text
~/.hermes/tools/uv-0.12.3-linux-x64/uv run --no-project --with pytest python -m pytest -q
```

Result:

```text
223 passed, 2 warnings in 6.39s
```

The two warnings are the existing intentional refused-record warnings from `tests/test_store.py`.