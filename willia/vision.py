"""Text-returning vision tool over the chat's OpenCode Go client."""

from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path

from . import media
from .config import VisionConfig


def _bounded(answer: str, max_chars: int) -> str:
    note = "\n\n[truncated to the configured vision answer limit]"
    if len(answer) <= max_chars:
        return answer
    if max_chars <= len(note):
        return note[:max_chars]
    return answer[:max_chars - len(note)] + note


def vision(image_url: object, question: object, *, client, config: VisionConfig,
           root: Path, log) -> str:
    """Resolve an image reference, ask the owner client, and return JSON text."""
    try:
        if not isinstance(image_url, str) or not image_url:
            raise ValueError("image_url must be a nonempty string")
        if not isinstance(question, str) or not question.strip():
            raise ValueError("question must be a nonempty string")
        resolved = image_url
        if not image_url.startswith(("http://", "https://")):
            path = Path(image_url).expanduser()
            raw = path.read_bytes()
            mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            resolved = f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"
            message_id = log.count() - 1
            if message_id >= 0:
                media.archive_media(
                    Path(root), message_id,
                    [{"type": "image_url", "image_url": {"url": resolved}}],
                )
        answer = client.vision(resolved, question)
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("vision returned no answer")
        return json.dumps({
            "answer": _bounded(answer.strip(), config.max_chars),
            "source": image_url,
        }, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
