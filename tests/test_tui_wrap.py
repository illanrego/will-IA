"""The wrapper's contract: prose breaks between words, and nothing is ever lost."""

from __future__ import annotations

import sys

sys.path.insert(0, str(__import__("pathlib").Path.home() / "Documents/coding/willia"))

from willia.tui.render import wrap                      # noqa: E402


def test_wrapping_breaks_between_words_not_inside_them():
    """A wrapped answer must read as prose: no word is ever cut in half."""
    text = ("The metering path needs a look, because the writer has not been exercised since "
            "the branch landed.")
    rows = wrap(text, 24, "body")
    assert len(rows) > 2
    assert [word for row in rows for word in row.text.split()] == text.split()


def test_wrapping_never_exceeds_the_width_and_keeps_the_text():
    text = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu"
    rows = wrap(text, 18, "body")
    assert all(sum(1 for _ in row.text) <= 18 for row in rows)
    assert " ".join(row.text.strip() for row in rows).split() == text.split()


def test_a_word_wider_than_the_row_is_cut_not_lost():
    word = "x" * 25
    rows = wrap(word, 10, "body")
    assert "".join(row.text for row in rows) == word
    assert max(len(row.text) for row in rows) <= 10


def test_a_hard_newline_still_breaks_the_row():
    rows = wrap("first\nsecond", 40, "body")
    assert [row.text for row in rows] == ["first", "second"]


def test_wrapping_keeps_the_logical_source_line_for_yanking():
    text = "one two three four five six seven eight"
    for row in wrap(text, 12, "body"):
        assert row.source_text == text
