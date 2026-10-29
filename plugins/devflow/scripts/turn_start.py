#!/usr/bin/env python3
"""UserPromptSubmit: remember HEAD when a turn starts, so the Stop hook also sees code
that was committed during the turn (devflow commits once per task group). Prints nothing:
stdout of this event would be added to Claude's context."""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import devflow_common as dc  # noqa: E402


def main() -> int:
    root = dc.project_dir(dc.read_payload())
    git_dir = dc.git(root, "rev-parse", "--absolute-git-dir")
    head = dc.git(root, "rev-parse", "HEAD")
    if git_dir and head:
        try:
            (Path(git_dir) / dc.TURN_START_FILE).write_text(head + "\n")
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
