import json
from pathlib import Path

from willia import skills


def write_skill(root, directory, name, description="A useful procedure.", body="Steps."):
    path = root / directory / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n{body}\n")
    return path


def result(workspace, action, name=None):
    return json.loads(skills.tool(workspace, action, name=name))


def test_frontmatter_parsing_and_whole_file_read(tmp_path, monkeypatch):
    custom = tmp_path / "custom"
    workspace = tmp_path / "work"
    source = write_skill(custom, "alpha", "alpha", '"Quoted description"', "One\nTwo")
    monkeypatch.setenv("WILLIA_SKILLS", str(custom))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")

    listing = result(workspace, "list")
    assert listing == {"skills": [{
        "name": "alpha", "description": "Quoted description"}], "omitted": 0}
    read = result(workspace, "read", "alpha")
    assert read["content"] == source.read_text()
    assert read["path"] == str(source.resolve())


def test_search_order_prefers_env_then_workspace_then_hermes(tmp_path, monkeypatch):
    custom = tmp_path / "custom"
    workspace = tmp_path / "work"
    home = tmp_path / "home"
    write_skill(custom, "one", "same", "from env")
    write_skill(workspace / "skills", "two", "same", "from workspace")
    write_skill(workspace / "skills", "work", "workspace")
    write_skill(home / ".hermes" / "skills", "home", "hermes")
    monkeypatch.setenv("WILLIA_SKILLS", str(custom))
    monkeypatch.setattr(Path, "home", lambda: home)

    listing = result(workspace, "list")
    assert [entry["name"] for entry in listing["skills"]] == [
        "same", "workspace", "hermes"]
    assert listing["skills"][0]["description"] == "from env"


def test_depth_bound_and_symlink_loop_cannot_hang(tmp_path, monkeypatch):
    root = tmp_path / "skills"
    workspace = tmp_path / "work"
    write_skill(root, "a/b/c/d", "at-bound")
    write_skill(root, "a/b/c/d/e", "too-deep")
    (root / "a" / "loop").symlink_to(root, target_is_directory=True)
    monkeypatch.setenv("WILLIA_SKILLS", str(root))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")

    names = [entry["name"] for entry in result(workspace, "list")["skills"]]
    assert names == ["at-bound"]


def test_invalid_frontmatter_is_skipped(tmp_path, monkeypatch):
    root = tmp_path / "skills"
    workspace = tmp_path / "work"
    invalid = root / "bad" / "SKILL.md"
    invalid.parent.mkdir(parents=True)
    invalid.write_text("name: no-delimiters\ndescription: bad\n")
    write_skill(root, "missing", "", "description")
    write_skill(root, "good", "good")
    monkeypatch.setenv("WILLIA_SKILLS", str(root))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")

    assert result(workspace, "list")["skills"] == [{
        "name": "good", "description": "A useful procedure."}]


def test_missing_name_returns_nearest_matches(tmp_path, monkeypatch):
    root = tmp_path / "skills"
    workspace = tmp_path / "work"
    write_skill(root, "deploy", "deploy-service")
    write_skill(root, "design", "design-review")
    monkeypatch.setenv("WILLIA_SKILLS", str(root))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")

    missing = result(workspace, "read", "deploy-servce")
    assert missing["error"] == "unknown skill: deploy-servce"
    assert missing["suggestions"][0] == "deploy-service"


def test_list_cap_reports_exact_omitted_count(tmp_path, monkeypatch):
    root = tmp_path / "skills"
    workspace = tmp_path / "work"
    monkeypatch.setattr(skills, "MAX_ENTRIES", 2)
    for index in range(5):
        write_skill(root, f"s{index}", f"skill-{index}")
    monkeypatch.setenv("WILLIA_SKILLS", str(root))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")

    listing = result(workspace, "list")
    assert len(listing["skills"]) == 2
    assert listing["omitted"] == 3


def test_calls_never_write_inside_skill_directories(tmp_path, monkeypatch):
    root = tmp_path / "skills"
    workspace = tmp_path / "work"
    write_skill(root, "safe", "safe")
    monkeypatch.setenv("WILLIA_SKILLS", str(root))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    before = {path.relative_to(root): path.read_bytes()
              for path in root.rglob("*") if path.is_file()}

    result(workspace, "list")
    result(workspace, "read", "safe")

    after = {path.relative_to(root): path.read_bytes()
             for path in root.rglob("*") if path.is_file()}
    assert after == before
