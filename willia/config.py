"""Configuration values and data paths owned by the standalone harness.

The model client and loop share one typed source of defaults without creating
the data directories as a side effect of reading configuration.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_LOG = logging.getLogger(__name__)
DEFAULT_WORKSPACE = "~/Documents/coding"


@dataclass(frozen=True)
class TurnConfig:
    reasoning_effort: str | None = "medium"


@dataclass(frozen=True)
class CompactionConfig:
    thinking_disabled: bool = True
    max_tokens: int = 700


@dataclass(frozen=True)
class ModelConfig:
    provider: str = "opencode-go"
    base_url: str = "https://opencode.ai/zen/go/v1"
    model: str = "deepseek-v4.1-flash"
    referer: str = "https://github.com/illanrego/will-IA"
    turns: TurnConfig = field(default_factory=TurnConfig)
    compactions: CompactionConfig = field(default_factory=CompactionConfig)
    turn_timeout_s: int = 120
    compaction_timeout_s: int = 60
    drain_join_s: int = 5
    watchdog_grace_s: int = 60


@dataclass(frozen=True)
class WebConfig:
    backend: str = "ddgs"
    max_results: int = 5
    extract_char_limit: int = 15_000


@dataclass(frozen=True)
class VisionConfig:
    model: str | None = None
    max_chars: int = 4_000


@dataclass(frozen=True)
class CodexDelegateConfig:
    enabled: bool = True
    bin: str = "$(npm prefix -g)/bin/codex"
    model: str = "gpt-5.6-sol"
    model_precise: str = "gpt-6-astra"
    reasoning_effort: str = "high"
    dir: str = DEFAULT_WORKSPACE
    timeout_minutes: int = 30


@dataclass(frozen=True)
class HermesDelegateConfig:
    enabled: bool = True
    bin: str = "hermes"
    timeout_minutes: int = 30


@dataclass(frozen=True)
class DelegatesConfig:
    codex: CodexDelegateConfig = field(default_factory=CodexDelegateConfig)
    hermes: HermesDelegateConfig = field(default_factory=HermesDelegateConfig)


@dataclass(frozen=True)
class ReplConfig:
    stream: bool = True
    history: bool = True


@dataclass(frozen=True)
class Paths:
    root: Path
    main_dir: Path
    tree_dir: Path
    view_file: Path
    view_backup_file: Path
    session_file: Path
    assets_dir: Path
    agents_dir: Path
    jobs_dir: Path
    logs_dir: Path
    prompt_file: Path

    @classmethod
    def from_root(cls, root: str | os.PathLike[str]) -> Paths:
        base = Path(root).expanduser()
        return cls(
            root=base,
            main_dir=base / "main",
            tree_dir=base / "tree",
            view_file=base / "view.json",
            view_backup_file=base / "backups" / "view.json",
            session_file=base / "session.json",
            assets_dir=base / "assets",
            agents_dir=base / "agents",
            jobs_dir=base / "jobs",
            logs_dir=base / "logs",
            prompt_file=base / "prompt.md",
        )


def data_root() -> Path:
    """Return the configured chat root without creating it."""
    return Path(os.environ.get("WILLIA_HOME", "~/.willia")).expanduser()


def paths(root: str | os.PathLike[str] | None = None) -> Paths:
    """Derive every durable path from one root without touching the filesystem."""
    return Paths.from_root(data_root() if root is None else root)


def _path(name: str, root: str | os.PathLike[str] | None = None) -> Path:
    return getattr(paths(root), name)


def main_dir(root: str | os.PathLike[str] | None = None) -> Path:
    return _path("main_dir", root)


def tree_dir(root: str | os.PathLike[str] | None = None) -> Path:
    return _path("tree_dir", root)


def view_file(root: str | os.PathLike[str] | None = None) -> Path:
    return _path("view_file", root)


def view_backup_file(root: str | os.PathLike[str] | None = None) -> Path:
    return _path("view_backup_file", root)


def session_file(root: str | os.PathLike[str] | None = None) -> Path:
    return _path("session_file", root)


def assets_dir(root: str | os.PathLike[str] | None = None) -> Path:
    return _path("assets_dir", root)


def agents_dir(root: str | os.PathLike[str] | None = None) -> Path:
    return _path("agents_dir", root)


def jobs_dir(root: str | os.PathLike[str] | None = None) -> Path:
    return _path("jobs_dir", root)


def logs_dir(root: str | os.PathLike[str] | None = None) -> Path:
    return _path("logs_dir", root)


def prompt_file(root: str | os.PathLike[str] | None = None) -> Path:
    return _path("prompt_file", root)


def _warn_unknown(data: dict[str, Any], known: set[str], prefix: str = "") -> None:
    for key in data.keys() - known:
        name = f"{prefix}.{key}" if prefix else key
        _LOG.warning("Unknown configuration key: %s", name)


def _expect(data: dict[str, Any], key: str, default: Any, expected: type | tuple[type, ...],
            prefix: str = "") -> Any:
    if key not in data:
        return default
    value = data[key]
    name = f"{prefix}.{key}" if prefix else key
    accepted = expected if isinstance(expected, tuple) else (expected,)
    if int in accepted and bool not in accepted and type(value) is bool:
        raise ValueError(f"Configuration key {name} has the wrong type")
    if not isinstance(value, accepted):
        raise ValueError(f"Configuration key {name} has the wrong type")
    return value


def _object(data: dict[str, Any], key: str, prefix: str = "") -> dict[str, Any]:
    value = _expect(data, key, {}, dict, prefix)
    return value


def _turns(data: dict[str, Any]) -> TurnConfig:
    _warn_unknown(data, {"reasoning_effort"}, "model.turns")
    return TurnConfig(reasoning_effort=_expect(
        data, "reasoning_effort", "medium", (str, type(None)), "model.turns"
    ))


def _compactions(data: dict[str, Any]) -> CompactionConfig:
    _warn_unknown(data, {"thinking_disabled", "max_tokens"}, "model.compactions")
    return CompactionConfig(
        thinking_disabled=_expect(
            data, "thinking_disabled", True, bool, "model.compactions"
        ),
        max_tokens=_expect(data, "max_tokens", 700, int, "model.compactions"),
    )


def _model(data: dict[str, Any]) -> ModelConfig:
    known = {
        "provider", "base_url", "model", "referer", "turns", "compactions",
        "turn_timeout_s", "compaction_timeout_s", "drain_join_s",
        "watchdog_grace_s",
    }
    _warn_unknown(data, known, "model")
    return ModelConfig(
        provider=_expect(data, "provider", "opencode-go", str, "model"),
        base_url=_expect(data, "base_url", "https://opencode.ai/zen/go/v1", str, "model"),
        model=_expect(data, "model", "deepseek-v4.1-flash", str, "model"),
        referer=_expect(data, "referer", ModelConfig().referer, str, "model"),
        turns=_turns(_object(data, "turns", "model")),
        compactions=_compactions(_object(data, "compactions", "model")),
        turn_timeout_s=_expect(data, "turn_timeout_s", 120, int, "model"),
        compaction_timeout_s=_expect(
            data, "compaction_timeout_s", 60, int, "model"
        ),
        drain_join_s=_expect(data, "drain_join_s", 5, int, "model"),
        watchdog_grace_s=_expect(data, "watchdog_grace_s", 60, int, "model"),
    )


def _web(data: dict[str, Any]) -> WebConfig:
    _warn_unknown(data, {"backend", "max_results", "extract_char_limit"}, "web")
    return WebConfig(
        backend=_expect(data, "backend", "ddgs", str, "web"),
        max_results=_expect(data, "max_results", 5, int, "web"),
        extract_char_limit=_expect(data, "extract_char_limit", 15_000, int, "web"),
    )


def _vision(data: dict[str, Any]) -> VisionConfig:
    _warn_unknown(data, {"model", "max_chars"}, "vision")
    return VisionConfig(
        model=_expect(data, "model", None, (str, type(None)), "vision"),
        max_chars=_expect(data, "max_chars", 4_000, int, "vision"),
    )


def _codex(data: dict[str, Any], workspace: str = DEFAULT_WORKSPACE) -> CodexDelegateConfig:
    known = {
        "enabled", "bin", "model", "model_precise", "reasoning_effort", "dir",
        "timeout_minutes",
    }
    _warn_unknown(data, known, "delegates.codex")
    defaults = CodexDelegateConfig()
    return CodexDelegateConfig(
        enabled=_expect(data, "enabled", defaults.enabled, bool, "delegates.codex"),
        bin=_expect(data, "bin", defaults.bin, str, "delegates.codex"),
        model=_expect(data, "model", defaults.model, str, "delegates.codex"),
        model_precise=_expect(
            data, "model_precise", defaults.model_precise, str, "delegates.codex"
        ),
        reasoning_effort=_expect(
            data, "reasoning_effort", defaults.reasoning_effort, str, "delegates.codex"
        ),
        dir=_expect(data, "dir", workspace, str, "delegates.codex"),
        timeout_minutes=_expect(
            data, "timeout_minutes", defaults.timeout_minutes, int, "delegates.codex"
        ),
    )


def _hermes(data: dict[str, Any]) -> HermesDelegateConfig:
    _warn_unknown(data, {"enabled", "bin", "timeout_minutes"}, "delegates.hermes")
    defaults = HermesDelegateConfig()
    return HermesDelegateConfig(
        enabled=_expect(data, "enabled", defaults.enabled, bool, "delegates.hermes"),
        bin=_expect(data, "bin", defaults.bin, str, "delegates.hermes"),
        timeout_minutes=_expect(
            data, "timeout_minutes", defaults.timeout_minutes, int, "delegates.hermes"
        ),
    )


def _delegates(data: dict[str, Any], workspace: str = DEFAULT_WORKSPACE) -> DelegatesConfig:
    _warn_unknown(data, {"codex", "hermes"}, "delegates")
    return DelegatesConfig(
        codex=_codex(_object(data, "codex", "delegates"), workspace),
        hermes=_hermes(_object(data, "hermes", "delegates")),
    )


def _repl(data: dict[str, Any]) -> ReplConfig:
    _warn_unknown(data, {"stream", "history"}, "repl")
    return ReplConfig(
        stream=_expect(data, "stream", True, bool, "repl"),
        history=_expect(data, "history", True, bool, "repl"),
    )


@dataclass(frozen=True)
class Config:
    model: ModelConfig = field(default_factory=ModelConfig)
    view_min_bytes: int = 64_000
    view_max_bytes: int = 128_000
    node_bytes: int = 512
    compact_view_min_bytes: int = 16_000
    compact_view_max_bytes: int = 32_000
    compact_enabled: bool = True
    compact_concurrency: int = 8
    compact_max_retries: int = 5
    tool_clip_chars: int = 30_000
    workspace: str = DEFAULT_WORKSPACE
    web: WebConfig = field(default_factory=WebConfig)
    vision: VisionConfig = field(default_factory=VisionConfig)
    delegates: DelegatesConfig = field(default_factory=DelegatesConfig)
    repl: ReplConfig = field(default_factory=ReplConfig)
    root: Path = field(default_factory=data_root)
    config_file: Path = field(default_factory=lambda: data_root() / "config.json")
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def load(cls, path: str | os.PathLike[str] | None = None) -> Config:
        root = data_root()
        if path is None:
            config_file = Path(
                os.environ.get("WILLIA_CONFIG", str(root / "config.json"))
            ).expanduser()
        else:
            config_file = Path(path).expanduser()
        if config_file.exists():
            with config_file.open(encoding="utf-8") as handle:
                raw = json.load(handle)
            if not isinstance(raw, dict):
                raise ValueError("Configuration root has the wrong type")
        else:
            raw = {}

        known = {
            "model", "view_min_bytes", "view_max_bytes", "node_bytes",
            "compact_view_min_bytes", "compact_view_max_bytes", "compact_enabled",
            "compact_concurrency", "compact_max_retries", "tool_clip_chars", "workspace", "web",
            "vision", "delegates", "repl",
        }
        _warn_unknown(raw, known)
        workspace = _expect(raw, "workspace", DEFAULT_WORKSPACE, str)
        return cls(
            model=_model(_object(raw, "model")),
            view_min_bytes=_expect(raw, "view_min_bytes", 64_000, int),
            view_max_bytes=_expect(raw, "view_max_bytes", 128_000, int),
            node_bytes=_expect(raw, "node_bytes", 512, int),
            compact_view_min_bytes=_expect(raw, "compact_view_min_bytes", 16_000, int),
            compact_view_max_bytes=_expect(raw, "compact_view_max_bytes", 32_000, int),
            compact_enabled=_expect(raw, "compact_enabled", True, bool),
            compact_concurrency=_expect(raw, "compact_concurrency", 8, int),
            compact_max_retries=_expect(raw, "compact_max_retries", 5, int),
            tool_clip_chars=_expect(raw, "tool_clip_chars", 30_000, int),
            workspace=workspace,
            web=_web(_object(raw, "web")),
            vision=_vision(_object(raw, "vision")),
            delegates=_delegates(_object(raw, "delegates"), workspace),
            repl=_repl(_object(raw, "repl")),
            root=root,
            config_file=config_file,
            raw=raw,
        )

    @property
    def paths(self) -> Paths:
        return Paths.from_root(self.root)

    @property
    def main_dir(self) -> Path:
        return self.paths.main_dir

    @property
    def tree_dir(self) -> Path:
        return self.paths.tree_dir

    @property
    def view_file(self) -> Path:
        return self.paths.view_file

    @property
    def view_backup_file(self) -> Path:
        return self.paths.view_backup_file

    @property
    def session_file(self) -> Path:
        return self.paths.session_file

    @property
    def assets_dir(self) -> Path:
        return self.paths.assets_dir

    @property
    def agents_dir(self) -> Path:
        return self.paths.agents_dir

    @property
    def jobs_dir(self) -> Path:
        return self.paths.jobs_dir

    @property
    def logs_dir(self) -> Path:
        return self.paths.logs_dir

    @property
    def prompt_file(self) -> Path:
        return self.paths.prompt_file
