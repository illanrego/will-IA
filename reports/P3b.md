Implemented both-account usage reporting for CLI and TUI, with read-only Codex credentials, isolated failures, shared countdown formatting, and daemon-thread fetching.

### Test tail

```text
-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
358 passed, 3 warnings in 11.08s
```

The warnings were one background-job thread race in `tests/test_jobs.py` and two intentional invalid-record warnings in `tests/test_store.py`.

### `codex_windows`

```python
def codex_windows(*, base: str = "https://chatgpt.com/backend-api/codex",
                  auth_file: str | Path | None = None, timeout: float = 20.0) -> dict:
    """Read and normalize the Codex account's plan windows without changing its auth.

    The credential is read once from ``~/.codex/auth.json``.  This function never refreshes it,
    writes it, or includes credential or account data in an exception.
    """
    auth_path = Path(auth_file) if auth_file is not None else Path.home() / ".codex" / "auth.json"
    try:
        auth = json.loads(auth_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CodexAuthMissingError("Codex auth file is absent") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CodexAuthMissingError("Codex auth file is unavailable") from exc

    tokens = auth.get("tokens") if isinstance(auth, dict) else None
    access_token = tokens.get("access_token") if isinstance(tokens, dict) else None
    account_id = tokens.get("account_id") if isinstance(tokens, dict) else None
    if not isinstance(access_token, str) or not access_token:
        raise CodexAuthMissingError("Codex auth file has no access token")
    if not isinstance(account_id, str) or not account_id:
        raise CodexAuthMissingError("Codex auth file has no account id")

    root = base.rstrip("/")
    if root.endswith("/codex"):
        root = root[:-len("/codex")]
    path = "/wham" if "/backend-api" in root else "/api/codex"
    request = urllib.request.Request(
        root + path + "/usage",
        headers={
            "Authorization": f"Bearer {access_token}",
            "chatgpt-account-id": account_id,
            "Accept": "application/json",
            "User-Agent": f"willia/{_package_version()}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise CodexTokenExpiredError("Codex token expired (HTTP 401)") from exc
        raise CodexNetworkError(f"Codex usage network failure (HTTP {exc.code})") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise CodexNetworkError("Codex usage network failure") from exc
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CodexResponseError("Codex usage response was invalid") from exc

    data = data if isinstance(data, dict) else {}
    rate_limit = data.get("rate_limit")
    rate_limit = rate_limit if isinstance(rate_limit, dict) else {}
    model_usage = data.get("model_usage")
    model_usage = model_usage if isinstance(model_usage, dict) else {}
    astra = model_usage.get("gpt-6-astra")
    astra = astra if isinstance(astra, dict) else {}
    reset_credits = data.get("rate_limit_reset_credits")
    reset_credits = reset_credits if isinstance(reset_credits, dict) else {}
    plan = data.get("plan_type")
    credits = reset_credits.get("available_count")
    available = astra.get("available")
    return {
        "plan": plan if isinstance(plan, str) else None,
        "primary": _codex_window(rate_limit.get("primary_window"), "5h"),
        "secondary": _codex_window(rate_limit.get("secondary_window"), "7d"),
        "reset_credits": credits if type(credits) is int else None,
        "astra_available": available if type(available) is bool else None,
    }
```

### Changed files

- [willia/usage.py](/home/illan/Documents/coding/willia/willia/usage.py:227)
- [willia/cli.py](/home/illan/Documents/coding/willia/willia/cli.py:122)
- [willia/tui/__init__.py](/home/illan/Documents/coding/willia/willia/tui/__init__.py:43)
- [willia/tui/hints.py](/home/illan/Documents/coding/willia/willia/tui/hints.py:42)
- [tests/test_usage.py](/home/illan/Documents/coding/willia/tests/test_usage.py:184)
- [tests/test_tui_render.py](/home/illan/Documents/coding/willia/tests/test_tui_render.py:117)
- [tests/test_tui_keys.py](/home/illan/Documents/coding/willia/tests/test_tui_keys.py:317)

Nothing from the brief remains undone. I made no Git calls, no live network request, and did not read or write the real `~/.codex`; all validation was offline as required.