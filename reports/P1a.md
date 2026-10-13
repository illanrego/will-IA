Implemented and committed P1a as `e3488ed` (`P1a: add model client and configuration`).

- Added typed nested configuration, documented paths, env parsing, durable session IDs, and the stateless OpenCode Go client.
- Added `model.turn_timeout_s = 120` and `model.compaction_timeout_s = 60`; these are the two additions omitted from the documented JSON sample.
- Added 28 fully offline tests. Total: 139 passing.
- No frozen files or documentation were modified.
- Existing untracked `probes/p1a-live-proof.py` remains untouched.

Proof:

```text
~/.hermes/tools/uv-0.12.3-linux-x64/uv run --no-project --with pytest python -m pytest -q
```

```text
139 passed, 2 warnings in 1.42s
```

The two warnings are expected assertions from existing corrupt-record refusal tests.