import pytest

from willia.envfile import MissingCredential, openrouter_key, read_env_file, require


def test_parses_comments_blanks_quotes_and_literal_shell_characters(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        "# credentials\n\n"
        "PLAIN=value\n"
        "SINGLE='$HOME'\n"
        'DOUBLE="literal `whoami`"\n'
        "SPACED = around \n"
    )

    assert read_env_file(path) == {
        "PLAIN": "value",
        "SINGLE": "$HOME",
        "DOUBLE": "literal `whoami`",
        "SPACED": "around",
    }


def test_shell_syntax_is_never_expanded(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("TOKEN=$EXPAND_ME-$(uname)-`id`\n")
    monkeypatch.setenv("EXPAND_ME", "secret")

    assert read_env_file(path)["TOKEN"] == "$EXPAND_ME-$(uname)-`id`"


def test_missing_key_names_key_and_file(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("OTHER=value\n")
    monkeypatch.delenv("NEEDED_KEY", raising=False)

    with pytest.raises(MissingCredential) as caught:
        require("NEEDED_KEY", path=path)

    assert "NEEDED_KEY" in str(caught.value)
    assert str(path) in str(caught.value)


def test_real_environment_overrides_file(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("OPENROUTER_API_KEY=file-value\n")
    monkeypatch.setenv("OPENROUTER_API_KEY", "environment-value")

    assert openrouter_key(path=path) == "environment-value"


def test_default_file_can_be_overridden(tmp_path, monkeypatch):
    path = tmp_path / "credentials.env"
    path.write_text("CUSTOM=value\n")
    monkeypatch.setenv("WILLIA_ENV_FILE", str(path))
    monkeypatch.delenv("CUSTOM", raising=False)

    assert require("CUSTOM") == "value"
