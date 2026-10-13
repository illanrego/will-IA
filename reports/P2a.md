Implemented P2a within the allowed files:

- Added asynchronous subprocess supervision, timeouts, process-group killing, durable reports, and child chats in [jobs.py](/home/illan/Documents/coding/willia/willia/jobs.py).
- Wired delegate validation and dispatch in [dispatch.py](/home/illan/Documents/coding/willia/willia/dispatch.py).
- Added work delivery queues, live/orphan job status, and single-record handling in [chat.py](/home/illan/Documents/coding/willia/willia/chat.py).
- Added 11 offline tests in [test_jobs.py](/home/illan/Documents/coding/willia/tests/test_jobs.py).
- Preserved the frozen tool schemas. The legacy `gpt-6-sol` schema value is translated to the real `gpt-5.6-sol` subprocess model.
- No Git commands, network calls, new dependencies, or forbidden-file edits.

Required proof command, verbatim:

```text
~/.hermes/tools/uv-0.12.3-linux-x64/uv run --no-project --with pytest python -m pytest -q
```

Result: `241 passed, 2 warnings in 9.34s`. The two warnings are the existing intentional invalid-record warnings from `tests/test_store.py`.