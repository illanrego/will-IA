import logging
from pathlib import Path

import pytest

from willia.config import Config


def test_absent_file_uses_documented_defaults(tmp_path):
    config = Config.load(tmp_path / "missing.json")

    assert config.model.provider == "opencode-go"
    assert config.model.base_url == "https://opencode.ai/zen/go/v1"
    assert config.model.model == "deepseek-v4.1-flash"
    assert config.model.turns.reasoning_effort == "medium"
    assert config.model.compactions.thinking_disabled is True
    assert config.model.compactions.max_tokens == 700
    assert config.model.turn_timeout_s == 120
    assert config.model.compaction_timeout_s == 60
    assert config.view_min_bytes == 64_000
    assert config.compact_concurrency == 8
    assert config.web.max_results == 5
    assert config.vision.model is None
    assert config.delegates.codex.enabled is True
    assert config.delegates.hermes.bin == "hermes"
    assert config.repl.stream is True
    assert config.raw == {}


def test_partial_nested_object_keeps_other_defaults(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"model":{"turns":{"reasoning_effort":"high"}},'
                    '"web":{"max_results":9}}')

    config = Config.load(path)

    assert config.model.turns.reasoning_effort == "high"
    assert config.model.base_url == "https://opencode.ai/zen/go/v1"
    assert config.model.compactions.max_tokens == 700
    assert config.web.max_results == 9
    assert config.web.backend == "ddgs"


def test_unknown_key_warns_without_raising(tmp_path, caplog):
    path = tmp_path / "config.json"
    path.write_text('{"model":{"future_knob":true},"future_section":{}}')

    with caplog.at_level(logging.WARNING):
        config = Config.load(path)

    assert config.model.model == "deepseek-v4.1-flash"
    assert "model.future_knob" in caplog.text
    assert "future_section" in caplog.text


@pytest.mark.parametrize(
    ("body", "key"),
    [
        ('{"view_min_bytes":"large"}', "view_min_bytes"),
        ('{"model":{"turns":[]}}', "model.turns"),
        ('{"vision":{"model":5}}', "vision.model"),
    ],
)
def test_wrong_known_type_raises_with_key(tmp_path, body, key):
    path = tmp_path / "config.json"
    path.write_text(body)

    with pytest.raises(ValueError, match=key):
        Config.load(path)


def test_home_and_config_environment_are_honoured(tmp_path, monkeypatch):
    root = tmp_path / "chat"
    path = tmp_path / "elsewhere.json"
    path.write_text('{"node_bytes":256}')
    monkeypatch.setenv("WILLIA_HOME", str(root))
    monkeypatch.setenv("WILLIA_CONFIG", str(path))

    config = Config.load()

    assert config.root == root
    assert config.config_file == path
    assert config.node_bytes == 256


def test_path_helpers_match_the_documented_layout(tmp_path, monkeypatch):
    monkeypatch.setenv("WILLIA_HOME", str(tmp_path))
    monkeypatch.delenv("WILLIA_CONFIG", raising=False)
    config = Config.load()

    assert config.main_dir == tmp_path / "main"
    assert config.tree_dir == tmp_path / "tree"
    assert config.view_file == tmp_path / "view.json"
    assert config.view_backup_file == tmp_path / "backups" / "view.json"
    assert config.session_file == tmp_path / "session.json"
    assert config.assets_dir == tmp_path / "assets"
    assert config.agents_dir == tmp_path / "agents"
    assert config.jobs_dir == tmp_path / "jobs"
    assert config.logs_dir == tmp_path / "logs"
    assert config.prompt_file == tmp_path / "prompt.md"
    assert config.config_file == tmp_path / "config.json"
    assert all(isinstance(value, Path) for value in (
        config.main_dir, config.tree_dir, config.view_file, config.view_backup_file,
        config.session_file, config.assets_dir, config.agents_dir, config.jobs_dir,
        config.logs_dir, config.prompt_file,
    ))
