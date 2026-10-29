#!/usr/bin/env python3
"""PreToolUse(Edit|Write|MultiEdit|NotebookEdit): ask before an edit that changes
dependencies, writes a secrets file, or loosens the guardrails themselves."""
from __future__ import annotations

import fnmatch
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import devflow_common as dc  # noqa: E402

ENV_FILE = re.compile(r"^\.env(\.(?!example$|sample$|template$|dist$).+)?$")
# Files that configure these guards: an agent editing them could switch a rule off.
GUARD_FILES = (".claude/settings.json", ".claude/settings.local.json", ".claude/devflow.env")


def decide(path: str, root: Path, cfg: dict):
    if not path:
        return None
    p = Path(path)
    try:
        rel = p.resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError):
        rel = p.as_posix()
    name = p.name
    if any(fnmatch.fnmatch(name, pat) for pat in dc.cfg_list(cfg, "DEP_FILES")):
        return f"Editing {name} can change dependencies: needs user approval."
    if ENV_FILE.match(name):
        return f"{name} holds secrets: needs explicit user confirmation before writing it."
    if rel in GUARD_FILES:
        return f"{rel} configures the workflow guardrails: needs explicit user confirmation."
    return None


def main() -> int:
    payload = dc.read_payload()
    tool_input = payload.get("tool_input") or {}
    path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    root = dc.project_dir(payload)
    reason = decide(path, root, dc.load_config(root))
    if reason:
        dc.log_event(root, "guard_edit", "ask", reason, path)
        dc.emit_pretool("ask", reason)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"devflow guard_edit internal error (allowed through): {exc}", file=sys.stderr)
        sys.exit(1)
