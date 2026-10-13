Implemented the independent work; **P0b still needs two prompt decisions**:

- May the prompt name the five additional tools? The canon lacks them, so the required seven-tool guard remains unimplemented.
- May `- unii:` become `- will:`?

Both exceed the brief’s “exactly two edits allowed” restriction. The current transcription respects that restriction and passes byte verification.

Restored `copy_context()`: removing it failed the existing inheritance/isolation test. Only the eight allowed files changed; no git commands or documentation edits.

Proof:

```sh
~/.hermes/tools/uv-0.12.3-linux-x64/uv run --no-project --with pytest python -m pytest -q
```

**110 passed, 2 warnings in 1.57s.**