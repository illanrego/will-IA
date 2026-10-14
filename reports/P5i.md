Implemented the four inspection commands in [app.py](/home/illan/Documents/coding/willia/willia/tui/app.py:494), with asynchronous usage snapshots wired through [__init__.py](/home/illan/Documents/coding/willia/willia/tui/__init__.py:144).

- `:view`, `:tree`, `:status`, and `:usage` reuse the help overlay.
- All scrolling and close keys work; transcript offset, cursor, and visual selection are restored exactly.
- Engine inspection is non-blocking and reports `compacting`.
- Usage opens with local totals while account windows load asynchronously.
- Completion and unknown-command listings include all four names.
- Inspection performs no writes.
- Added coverage in [test_tui_inspect.py](/home/illan/Documents/coding/willia/tests/test_tui_inspect.py:152) and [test_tui_keys.py](/home/illan/Documents/coding/willia/tests/test_tui_keys.py:186).

Full-suite tail:

```text
........................................................................ [ 90%]
.......................................                                  [100%]
-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
399 passed, 3 warnings in 12.51s
/home/illan/.local/share/uv/python/cpython-3.14.7-linux-x86_64-gnu/lib/python3.14/tempfile.py:484: ResourceWarning: Implicitly cleaning up <HTTPError 401: 'no'>
```

The three warnings were a delegate-test thread race, two intentional refused-record warnings, and the displayed cleanup warning.

Stub panel output:

```text
=== :view ===
WILLIA VIEW · 268 B · records 0-2 · settled

<chat>
line 0: model memory
line 1: model memory
line 2: model memory
line 3: model memory
line 4: model memory
line 5: model memory
line 6: model memory
line 7: model memory
line 8: model memory
line 9: model memory
line 10: model memory
line 11: model memory
</chat>
```

```text
=== :tree ===
WILLIA TREE

l0   ████████████ 3
l1   ████         1
nodes 4

ROOTS
l1:0 · records 0-1 · 10 B
l0:2 · records 2 · 8 B

COVERAGE
records 0-2
points 0-1, 2
settled · 0 unbuilt
```

```text
=== :status ===
WILLIA STATUS

Session: 12345678
Records: 3
  tool: 1
  user: 1
  will: 1
View: 268 B · records 0-2
Tree nodes: 4
Settled: yes
Unbuilt nodes: 0
Compaction: idle · queue 0
Jobs: none
```

```text
=== :usage ===
WILLIA USAGE

Usage log: /home/illan/.hermes/cache/scratch/tmp3s9ssgkk/logs/usage.jsonl
Calls: 2
input_tokens: 140
output_tokens: 14
cache_read_tokens: 110
cache_write_tokens: 3
reasoning_tokens: 3
compaction: calls=1 input=40 output=4 cache_read=30 cache_write=1 reasoning=0
turn: calls=1 input=100 output=10 cache_read=80 cache_write=2 reasoning=3
Latest call: 2026-10-14T00:01:00Z (compaction)
go:
rolling: 12.5% resets 2026-10-14T20:00:00Z (4h9m)
codex: plan=plus
5h: 18% resets 15m
```

Nothing requested was left undone. No git commands were run.