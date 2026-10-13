Implemented P3a in:

- [willia/cli.py](/home/illan/Documents/coding/willia/willia/cli.py)
- [tests/test_notes_cli.py](/home/illan/Documents/coding/willia/tests/test_notes_cli.py)

Added preview/import modes, recursive sorted discovery, exact cost projections, locking, bounded completion, persistence, summaries, resumable pending work, and explicit no-dedup behavior. No frozen modules, documentation, or dependencies were changed.

Required proof:

```bash
~/.hermes/tools/uv-0.12.3-linux-x64/uv run --no-project --with pytest python -m pytest -q
```

Result: **230 passed, 2 pre-existing store warnings in 6.41s.**