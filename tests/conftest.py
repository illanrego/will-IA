"""Suite-wide isolation: no test may touch the real chat.

A few client and chat tests build a ``Config`` whose root defaults to ``~/.willia``.  The usage
meter appends a line on every model call, so an unsandboxed root would write test data straight
into the live chat's meter.  Every test therefore runs with ``WILLIA_HOME`` pointed at a temp
directory; a test that wants its own root can still override it with ``monkeypatch.setenv``.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolated_willia_home(tmp_path, monkeypatch):
    monkeypatch.setenv("WILLIA_HOME", str(tmp_path / "willia-home"))
