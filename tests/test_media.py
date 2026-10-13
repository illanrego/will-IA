"""Exercise the media archive directly, without a host or turn loop."""

import base64
import json
import logging

import pytest

from willia import media


PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a"
    "X1sAAAAASUVORK5CYII="
)
IMAGE = {
    "type": "image_url",
    "image_url": {"url": "data:image/png;base64," + base64.b64encode(PNG).decode()},
}


def pending(root):
    return json.loads((root / "assets" / "pending.json").read_text())


def test_inline_image_is_archived_and_indexed(tmp_path):
    media.archive_media(tmp_path, 7, [{"type": "text", "text": "Look at this"}, IMAGE])

    entry = {"path": "assets/7-1.png", "type": "image"}
    assert (tmp_path / entry["path"]).read_bytes() == PNG
    assert media.media_for(tmp_path, 7) == [entry]
    assert json.loads((tmp_path / "assets" / "index.json").read_text()) == {"7": [entry]}


def test_media_only_message_is_archived_and_indexed(tmp_path):
    media.archive_media(tmp_path, 0, [IMAGE])

    assert media.media_for(tmp_path, 0) == [{"path": "assets/0-0.png", "type": "image"}]
    assert (tmp_path / "assets" / "0-0.png").read_bytes() == PNG


def test_two_parts_keep_content_order(tmp_path):
    gif = b"GIF89a"
    media.archive_media(tmp_path, 3, [
        IMAGE,
        {"type": "text", "text": "Between the images"},
        {"type": "input_image", "data": base64.b64encode(gif).decode(),
         "mime_type": "image/gif"},
    ])

    assert media.media_for(tmp_path, 3) == [
        {"path": "assets/3-0.png", "type": "image"},
        {"path": "assets/3-2.gif", "type": "image"},
    ]
    assert (tmp_path / "assets" / "3-0.png").read_bytes() == PNG
    assert (tmp_path / "assets" / "3-2.gif").read_bytes() == gif


def test_undecodable_payload_warns_and_keeps_message_ingestible(tmp_path, caplog):
    reference = "data:image/png;base64,%%%invalid=="
    part = {"type": "image_url", "image_url": {"url": reference}}
    with caplog.at_level(logging.WARNING, logger="willia.media"):
        media.archive_media(tmp_path, 4, [part, {"type": "text", "text": "Still here"}, IMAGE])

    assert "Skipped media part 0 on message 4" in caplog.text
    assert "reference recorded for retry" in caplog.text
    entry, = pending(tmp_path)
    assert entry["message_id"] == 4
    assert entry["part_index"] == 0
    assert entry["type"] == "image"
    assert entry["reference"] == reference
    assert entry["part"] == part
    assert entry["attempts"] == 1
    assert "invalid data URL" in entry["error"]
    assert media.media_for(tmp_path, 4) == [{"path": "assets/4-2.png", "type": "image"}]


@pytest.mark.parametrize("scheme", ["http", "https"])
def test_remote_reference_survives_retry_unchanged(tmp_path, scheme):
    reference = f"{scheme}://example.invalid/image%2Fname.png?sig=A%2Bb&x=1#Original"
    media.archive_media(tmp_path, 5, [{"type": "image_url", "image_url": {"url": reference}}])
    before = pending(tmp_path)

    assert media.retry_pending_media(tmp_path) == {"archived": 0, "pending": 1, "remote": 1}
    assert pending(tmp_path) == before
    assert pending(tmp_path)[0]["reference"].encode() == reference.encode()
    assert media.media_for(tmp_path, 5) == []


def test_index_failure_retries_merge_entries_and_preserve_attempt_count(tmp_path, monkeypatch, caplog):
    media.archive_media(tmp_path, 8, [IMAGE])
    media.archive_media(tmp_path, 9, [IMAGE])
    original = media.media_for(tmp_path, 8)
    unrelated = media.media_for(tmp_path, 9)
    entries = [{"path": "assets/8-1.png", "type": "image"}]
    atomic_json = media.atomic_json

    def fail_index(path, value):
        if path.name == "index.json":
            raise OSError("index unavailable")
        atomic_json(path, value)

    with monkeypatch.context() as patch:
        patch.setattr(media, "atomic_json", fail_index)
        with caplog.at_level(logging.WARNING, logger="willia.media"):
            media.archive_media(tmp_path, 8, [{"type": "text", "text": "Another"}, IMAGE])
        assert "Could not index media for message 8" in caplog.text
        entry, = pending(tmp_path)
        assert entry == {
            "message_id": 8, "part_index": None, "type": "index", "reference": None,
            "error": "index unavailable", "attempts": 1, "entries": entries,
        }
        assert (tmp_path / entries[0]["path"]).read_bytes() == PNG
        assert media.media_for(tmp_path, 8) == original

        assert media.retry_pending_media(tmp_path) == {"archived": 0, "pending": 1, "remote": 0}
        assert pending(tmp_path)[0]["attempts"] == 2
        media.record_pending_media(tmp_path, 8, None, "index", None, "still unavailable",
                                   entries=entries)
        entry, = pending(tmp_path)
        assert entry["attempts"] == 2
        assert entry["error"] == "still unavailable"

    assert media.retry_pending_media(tmp_path) == {"archived": 1, "pending": 0, "remote": 0}
    assert pending(tmp_path) == []
    assert media.media_for(tmp_path, 8) == original + entries
    assert media.media_for(tmp_path, 9) == unrelated
    assert media.retry_pending_media(tmp_path) == {"archived": 0, "pending": 0, "remote": 0}


def test_pending_local_file_can_be_archived_later(tmp_path):
    source = tmp_path / "arrives-later.png"
    part = {"type": "image", "path": str(source), "mime_type": "image/png"}
    media.record_pending_media(tmp_path, 6, 0, "image", str(source), "not available", part=part)

    assert media.retry_pending_media(tmp_path) == {"archived": 0, "pending": 1, "remote": 0}
    assert pending(tmp_path)[0]["attempts"] == 2
    source.write_bytes(PNG)
    assert media.retry_pending_media(tmp_path) == {"archived": 1, "pending": 0, "remote": 0}
    assert pending(tmp_path) == []
    assert media.media_for(tmp_path, 6) == [{"path": "assets/6-0.png", "type": "image"}]
    assert (tmp_path / "assets" / "6-0.png").read_bytes() == PNG


def test_pending_data_url_retries_without_original_part(tmp_path):
    media.record_pending_media(tmp_path, 2, 3, "image", IMAGE["image_url"]["url"], "write failed")

    assert media.retry_pending_media(tmp_path) == {"archived": 1, "pending": 0, "remote": 0}
    assert media.media_for(tmp_path, 2) == [{"path": "assets/2-3.png", "type": "image"}]
    assert (tmp_path / "assets" / "2-3.png").read_bytes() == PNG


@pytest.mark.parametrize(("part", "raw", "extension", "kind"), [
    ({"type": "input_audio", "input_audio": {"data": "UklGRg==", "format": "wav"}},
     b"RIFF", ".wav", "audio"),
    ({"type": "input_file", "file_data": "data:application/pdf;base64,JVBERi0xLjc="},
     b"%PDF-1.7", ".pdf", "file"),
])
def test_audio_and_file_extensions_and_types(tmp_path, part, raw, extension, kind):
    media.archive_media(tmp_path, 1, [part])

    path = f"assets/1-0{extension}"
    assert media.media_for(tmp_path, 1) == [{"path": path, "type": kind}]
    assert (tmp_path / path).read_bytes() == raw
