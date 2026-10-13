import json

import pytest

from willia.session import session_id


def test_generates_once_and_reuses_the_same_value(tmp_path):
    first = session_id(tmp_path)
    second = session_id(tmp_path)

    assert first == second
    assert len(first) == 32
    assert json.loads((tmp_path / "session.json").read_text()) == {"session": first}


@pytest.mark.parametrize("body", ["not json", "{}", '{"session":5}'])
def test_malformed_existing_file_raises_without_rotating(tmp_path, body):
    path = tmp_path / "session.json"
    path.write_text(body)

    with pytest.raises((ValueError, json.JSONDecodeError)):
        session_id(tmp_path)

    assert path.read_text() == body


def test_atomic_write_leaves_no_temporary_file(tmp_path):
    session_id(tmp_path)

    assert [path.name for path in tmp_path.iterdir()] == ["session.json"]
