#!/usr/bin/env python3
"""Stop: refuse to end a turn while the fast offline tests fail.

- Runs only when the turn changed DEVFLOW_CODE_PATHS: uncommitted changes, or commits made
  since the turn started (HEAD recorded by turn_start.py).
- When only DEVFLOW_TEST_PATHS changed (the tests-first task group), red is expected:
  report it without blocking so the user can review the failing tests first.
- Missing services or a timeout are reported, never silently treated as green.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import devflow_common as dc  # noqa: E402


def turn_start(root):
    git_dir = dc.git(root, "rev-parse", "--absolute-git-dir")
    try:
        return (Path(git_dir) / dc.TURN_START_FILE).read_text().strip() if git_dir else None
    except OSError:
        return None


def changed(root, paths, start=None) -> bool:
    if not paths:
        return False
    if dc.git(root, "status", "--porcelain", "--", *paths):
        return True
    head = dc.git(root, "rev-parse", "HEAD")
    if start and head and head != start:
        return bool(dc.git(root, "diff", "--name-only", start, "HEAD", "--", *paths))
    return False


def service_down(spec: str) -> bool:
    host, _, port = spec.rpartition(":")
    try:
        with socket.create_connection((host or "127.0.0.1", int(port)), timeout=1):
            return False
    except (OSError, ValueError):
        return True


def main() -> int:
    payload = dc.read_payload()
    if payload.get("stop_hook_active"):  # already continuing because of this hook
        return 0
    root = dc.project_dir(payload)
    cfg = dc.load_config(root)
    cmd = cfg.get("FAST_TEST_CMD", "").strip()
    if not cmd or dc.git(root, "rev-parse", "--git-dir") is None:
        return 0
    code_paths = dc.cfg_list(cfg, "CODE_PATHS")
    start = turn_start(root)
    if not changed(root, code_paths, start):
        return 0
    down = [s for s in dc.cfg_list(cfg, "SERVICES") if service_down(s)]
    if down:
        dc.emit_system_message(f"Stop hook: tests were NOT run, services down: {', '.join(down)}.")
        return 0
    timeout = int(cfg.get("STOP_TIMEOUT") or 300)
    try:
        out = subprocess.run(["bash", "-c", cmd], cwd=root, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        dc.emit_system_message(f"Stop hook: tests timed out after {timeout}s and were NOT verified.")
        return 0
    if out.returncode == 0:
        return 0
    tail = "\n".join((out.stdout + out.stderr).strip().splitlines()[-40:])
    test_paths = dc.cfg_list(cfg, "TEST_PATHS")
    non_test = [p for p in code_paths if p not in test_paths]
    if test_paths and changed(root, test_paths, start) and not changed(root, non_test, start):
        short = "\n".join(tail.splitlines()[-5:])
        dc.emit_system_message("Stop hook: tests fail with only test files changed "
                               "(tests-first red state, not blocking):\n" + short)
        return 0
    print("Tests fail; fix them before finishing (never weaken a test to pass):", file=sys.stderr)
    print(tail, file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"devflow stop_tests internal error: {exc}", file=sys.stderr)
        sys.exit(1)
