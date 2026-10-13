Implemented P0c. The suite increased from 110 to 111 tests and remains green.

Exact pytest command:

```text
~/.hermes/tools/uv-0.12.3-linux-x64/uv run --no-project --with pytest python -m pytest -q
```

Raw output:

```text
........................................................................ [ 64%]
.......................................                                  [100%]
=============================== warnings summary ===============================
tests/test_store.py::test_parseable_invalid_records_are_loud_and_never_reused
  /home/illan/Documents/coding/willia/willia/store.py:79: RuntimeWarning: willia chat log line at /home/illan/.hermes/cache/scratch/pytest-of-illan/pytest-233/test_parseable_invalid_records0/main/2026-10-13.jsonl:177 is refused: unknown record kind 'thought'
    self._refuse(path, offset, data, reason, refused)

tests/test_store.py::test_parseable_invalid_records_are_loud_and_never_reused
  /home/illan/Documents/coding/willia/willia/store.py:79: RuntimeWarning: willia chat log line at /home/illan/.hermes/cache/scratch/pytest-of-illan/pytest-233/test_parseable_invalid_records0/main/2026-10-13.jsonl:279 is refused: record size does not match its text
    self._refuse(path, offset, data, reason, refused)

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
111 passed, 2 warnings in 1.58s
```

The requested `python -c` command could not run because this environment has no `python` executable:

```text
/bin/bash: line 1: python: command not found
```

Equivalent command using the available `python3` produced:

```text
3640 4615
```

Changed files:

- [willia/prompts.py](/home/illan/Documents/coding/willia/willia/prompts.py)
- [willia/prompt-default.md](/home/illan/Documents/coding/willia/willia/prompt-default.md)
- [tests/test_toolkit.py](/home/illan/Documents/coding/willia/tests/test_toolkit.py)
- [pyproject.toml](/home/illan/Documents/coding/willia/pyproject.toml)

No prohibited files were edited, and no git commands were used.