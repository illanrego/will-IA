"""Credential-file parsing for the one external route willia calls.

Values are read literally so a small dotenv file never becomes a shell or a
second configuration language.
"""

from __future__ import annotations

import os
from pathlib import Path


class MissingCredential(RuntimeError):
    """A required credential was absent from both the process and its env file."""


def env_file_path(path: str | os.PathLike[str] | None = None) -> Path:
    if path is not None:
        return Path(path).expanduser()
    return Path(os.environ.get("WILLIA_ENV_FILE", "~/.hermes/.env")).expanduser()


def read_env_file(path: str | os.PathLike[str] | None = None) -> dict[str, str]:
    """Read literal KEY=VALUE entries, returning an empty mapping if absent."""
    target = env_file_path(path)
    try:
        lines = target.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return {}
    values: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key] = value
    return values


def require(name: str, *, path: str | os.PathLike[str] | None = None) -> str:
    """Return a credential with the process environment taking precedence."""
    if name in os.environ:
        return os.environ[name]
    target = env_file_path(path)
    values = read_env_file(target)
    if name in values:
        return values[name]
    raise MissingCredential(f"Missing credential {name} in {target}")


def opencode_go_key(*, path: str | os.PathLike[str] | None = None) -> str:
    return require("OPENCODE_GO_API_KEY", path=path)
