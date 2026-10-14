"""Read-only discovery of Hermes-style SKILL.md procedure files."""

from __future__ import annotations

import ast
import difflib
import json
import os
from dataclasses import dataclass
from pathlib import Path


MAX_DEPTH = 4
MAX_ENTRIES = 100


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    path: Path
    content: str


def _scalar(value: str) -> str | None:
    value = value.strip()
    if not value:
        return None
    if value[0:1] in {'"', "'"}:
        try:
            parsed = ast.literal_eval(value)
        except (SyntaxError, ValueError):
            return None
        return parsed if isinstance(parsed, str) else None
    if value[0] in "[{&*!":
        return None
    return value


def parse_frontmatter(content: str) -> tuple[str, str] | None:
    """Read the name and description from a small safe YAML scalar subset."""
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    try:
        end = next(index for index in range(1, len(lines)) if lines[index].strip() == "---")
    except StopIteration:
        return None
    values: dict[str, str] = {}
    index = 1
    while index < end:
        line = lines[index]
        if not line.strip() or line.lstrip().startswith("#"):
            index += 1
            continue
        if line[:1].isspace() or ":" not in line:
            return None
        key, raw = line.split(":", 1)
        key = key.strip()
        if key in values:
            return None
        raw = raw.strip()
        if raw in {"|", ">", "|-", ">-", "|+", ">+"}:
            block = []
            index += 1
            while index < end and (not lines[index] or lines[index][:1].isspace()):
                block.append(lines[index].lstrip())
                index += 1
            separator = "\n" if raw.startswith("|") else " "
            values[key] = separator.join(block).strip()
            continue
        scalar = _scalar(raw)
        if scalar is None:
            return None
        values[key] = scalar
        index += 1
    name, description = values.get("name"), values.get("description")
    if not name or not description:
        return None
    return name, description


def roots(workspace: Path) -> list[Path]:
    result = []
    configured = os.environ.get("WILLIA_SKILLS")
    if configured:
        result.append(Path(configured).expanduser())
    result.extend((Path(workspace).expanduser() / "skills", Path.home() / ".hermes" / "skills"))
    return result


def _files(root: Path):
    if not root.is_dir():
        return
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(directory)
        try:
            depth = len(current.relative_to(root).parts)
        except ValueError:
            continue
        dirnames[:] = [] if depth >= MAX_DEPTH else sorted(dirnames)
        if "SKILL.md" in filenames:
            yield current / "SKILL.md"


def discover(workspace: Path) -> list[Skill]:
    """Return unique valid skills, honoring root and file discovery order."""
    found: dict[str, Skill] = {}
    for root in roots(workspace):
        for path in _files(root):
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            metadata = parse_frontmatter(content)
            if metadata is None:
                continue
            name, description = metadata
            found.setdefault(name, Skill(name, description, path.resolve(), content))
    return list(found.values())


def tool(workspace: Path, action: object, *, name: object = None) -> str:
    try:
        found = discover(workspace)
        if action == "list":
            visible = found[:MAX_ENTRIES]
            return json.dumps({
                "skills": [
                    {"name": skill.name, "description": skill.description}
                    for skill in visible
                ],
                "omitted": len(found) - len(visible),
            }, ensure_ascii=False)
        if action == "read":
            if not isinstance(name, str) or not name:
                raise ValueError("name must be a nonempty string")
            selected = next((skill for skill in found if skill.name == name), None)
            if selected is None:
                suggestions = difflib.get_close_matches(
                    name, [skill.name for skill in found], n=5, cutoff=0.3)
                return json.dumps({
                    "error": f"unknown skill: {name}", "suggestions": suggestions,
                }, ensure_ascii=False)
            return json.dumps({
                "name": selected.name,
                "path": str(selected.path),
                "content": selected.content,
            }, ensure_ascii=False)
        raise ValueError("action must be list or read")
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
