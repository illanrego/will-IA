"""Read-only report on one chat's durable state.

Nothing here writes: the log and the tree are opened read-only, the view is only read, and no
directory is created.  Point it at a root with ``--root`` or ``WILLIA_HOME``; it defaults to
``~/.willia``.

    uv run --no-project python scripts/session-report.py [--root PATH]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from willia import usage                      # noqa: E402
from willia.config import Config              # noqa: E402
from willia.store import Log                  # noqa: E402
from willia.tree import Tree                  # noqa: E402
from willia.view import View                  # noqa: E402


def _session(root: Path) -> str:
    """The stored session id, or a note that there is none.  Never creates one."""
    try:
        data = json.loads((root / "session.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "none"
    value = data.get("session") if isinstance(data, dict) else None
    return value if isinstance(value, str) and value else "malformed"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="session-report",
                                     description="Read-only report on one willia chat.")
    parser.add_argument("--root", default=None, help="chat root (default: ~/.willia)")
    options = parser.parse_args(argv)
    if options.root:
        os.environ["WILLIA_HOME"] = str(Path(options.root).expanduser())
    try:
        config = Config.load()
    except (OSError, ValueError) as exc:
        print(f"session-report: {exc}", file=sys.stderr)
        return 1
    root = config.root

    print(f"Root: {root}")
    print(f"Session: {_session(root)}")
    prompt_file = root / "prompt.md"
    print(f"Prompt file: {prompt_file}"
          + (f" ({prompt_file.stat().st_size} bytes)" if prompt_file.is_file() else " (absent)"))

    main_dir = root / "main"
    if not main_dir.is_dir():
        print("Records: no log directory - nothing has been logged yet")
        return 0

    with Log(root, read_only=True) as log:
        count = log.count()
        kinds: Counter = Counter()
        refused = 0
        first = latest = None
        for i in range(count):
            record = log.get(i)
            if record is None:
                refused += 1
                continue
            kinds[record.kind] += 1
            first = first or record.date
            latest = record.date

    print(f"Records: {count} (refused positions: {refused})")
    for kind in sorted(kinds):
        print(f"  {kind}: {kinds[kind]}")
    print(f"First date: {first}")
    print(f"Latest date: {latest}")

    tree = Tree(root, config.node_bytes, read_only=True)
    nodes = tree.nodes()
    print(f"Tree nodes: {len(nodes)}")
    for level in sorted({level for level, _index in nodes}):
        print(f"  level {level}: {sum(1 for other, _i in nodes if other == level)}")

    try:
        # View has no read-only flag of its own; it only ever writes on save(), which is
        # never called here - so the read is a read.
        view = View(Tree(root, config.node_bytes, read_only=True),
                    config.view_min_bytes, config.view_max_bytes)
        text = view.render()
        print(f"View: bytes={len(text.encode('utf-8'))} lines={len(view.lines())} "
              f"settled={view.settled()} covers={view._end()} of {count}")
    except Exception as exc:  # noqa: BLE001 - a report must not die on an unavailable view
        print(f"View: unavailable ({type(exc).__name__}: {exc})")

    jobs_dir = root / "jobs"
    job_dirs = sorted(path.name for path in jobs_dir.iterdir() if path.is_dir()) \
        if jobs_dir.is_dir() else []
    orphans = [name for name in job_dirs if not (jobs_dir / name / "report.md").is_file()]
    print(f"Jobs: {len(job_dirs)} (without a report: {orphans})")

    agents_dir = root / "agents"
    agents = sorted(path.name for path in agents_dir.iterdir() if path.is_dir()) \
        if agents_dir.is_dir() else []
    print(f"Children: {len(agents)} {agents}")

    print(f"Archived media index: {'yes' if (root / 'assets' / 'index.json').is_file() else 'no'}")

    entries = usage.read(usage.usage_file(root))
    summary = usage.totals(entries)
    buckets = " ".join(f"{name}={summary[name]}" for name in usage.BUCKETS)
    print(f"Usage: calls={summary['calls']} {buckets}")
    for kind in sorted(summary["by_kind"]):
        print(f"  {kind}: calls={summary['by_kind'][kind]['calls']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
