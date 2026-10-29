#!/usr/bin/env python3
"""SessionStart(compact): re-orient after compaction. Plain stdout becomes context:
branch, uncommitted files, open OpenSpec changes and the branch's unchecked tasks."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import devflow_common as dc  # noqa: E402


def task_counts(tasks: Path):
    text = tasks.read_text(encoding="utf-8", errors="replace")
    done = len(re.findall(r"^\s*- \[x\]", text, re.M | re.I))
    total = len(re.findall(r"^\s*- \[[ xX]\]", text, re.M))
    return done, total, text


def main() -> int:
    payload = dc.read_payload()
    root = dc.project_dir(payload)
    if dc.git(root, "rev-parse", "--git-dir") is None:
        return 0
    cfg = dc.load_config(root)
    branch = dc.current_branch(root) or "detached"
    lines = ["## Re-orientation after compaction", f"Branch: {branch}"]
    if branch == cfg.get("PROTECTED_BRANCH"):
        lines.append(f"(on the protected branch: start work with /devflow:new-branch)")
    status = (dc.git(root, "status", "--short") or "").splitlines()
    lines.append("Uncommitted: " + ("none" if not status else ""))
    lines += ["  " + s for s in status[:30]]
    changes = root / "openspec" / "changes"
    if changes.is_dir():
        lines.append("Open OpenSpec changes:")
        for d in sorted(p for p in changes.iterdir() if p.is_dir() and p.name != "archive"):
            tasks = d / "tasks.md"
            if tasks.is_file():
                done, total, _ = task_counts(tasks)
                lines.append(f"  - {d.name} ({done}/{total} tasks)")
            else:
                lines.append(f"  - {d.name}")
        # Feature branches are named after their change (feat/add-thing -> add-thing).
        tasks = changes / branch.split("/", 1)[-1] / "tasks.md"
        if tasks.is_file():
            _, _, text = task_counts(tasks)
            open_tasks = [l.strip() for l in text.splitlines() if re.match(r"^\s*- \[ \]", l)]
            lines.append(f"Unchecked tasks in {tasks.relative_to(root)}:")
            lines += ["  " + t for t in open_tasks[:20]]
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"devflow session_context internal error: {exc}", file=sys.stderr)
        sys.exit(1)
