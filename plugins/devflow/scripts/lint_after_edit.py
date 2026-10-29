#!/usr/bin/env python3
"""PostToolUse(Edit|Write|MultiEdit): lint the edited file with DEVFLOW_LINT_CMD.
Exit 2 feeds the findings back to Claude; a missing linter is not an error."""
from __future__ import annotations

import fnmatch
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import devflow_common as dc  # noqa: E402


def main() -> int:
    payload = dc.read_payload()
    root = dc.project_dir(payload)
    cfg = dc.load_config(root)
    cmd = cfg.get("LINT_CMD", "").strip()
    path = (payload.get("tool_input") or {}).get("file_path") or ""
    if not cmd or not path or not Path(path).is_file():
        return 0
    if not any(fnmatch.fnmatch(Path(path).name, g) for g in dc.cfg_list(cfg, "LINT_GLOBS")):
        return 0
    try:
        out = subprocess.run(shlex.split(cmd) + [path], cwd=root, capture_output=True,
                             text=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return 0
    output = out.stdout + out.stderr
    # The linter itself isn't installed yet (e.g. before the project's dev deps exist).
    if out.returncode != 0 and re.search(r"Failed to spawn|command not found|not found in PATH|ENOENT", output):
        return 0
    if out.returncode != 0:
        print(f"Lint found problems in {path}; fix them:", file=sys.stderr)
        print(output[-4000:], file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"devflow lint_after_edit internal error: {exc}", file=sys.stderr)
        sys.exit(1)
