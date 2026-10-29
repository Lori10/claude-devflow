"""Shared helpers for the devflow hooks: project config, hook I/O, git, event log.

Stdlib only, Python 3.8+. Every hook must fail open on its own bugs (exit 0) and
never print anything but the single JSON object Claude Code expects on stdout.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Defaults apply when .claude/devflow.env doesn't set a key. Git guards work with
# no config at all; everything project-specific is off until configured.
DEFAULTS: Dict[str, str] = {
    "PROTECTED_BRANCH": "main",
    "OPENSPEC_VERSION": "",  # empty: don't pin/rewrite openspec calls
    "CHECK_CMD": "scripts/check.sh",
    "FAST_TEST_CMD": "",  # empty: Stop hook does nothing
    "CODE_PATHS": "src tests",  # a turn touching these runs the Stop hook
    "TEST_PATHS": "tests",  # only these changed -> tests-first red state is allowed
    "LINT_CMD": "",  # per-file lint after Edit/Write; the file path is appended
    "LINT_GLOBS": "*.py",
    "SERVICES": "",  # host:port list the fast tests need, e.g. 127.0.0.1:5432
    "DEP_FILES": "pyproject.toml uv.lock requirements.txt requirements-dev.txt "
    "package.json package-lock.json pnpm-lock.yaml yarn.lock",
    "PUBLIC_REPO": "true",
    "CLOUD": "",  # "aws" enables the cloud guard
    "AWS_REGION": "",
    "STOP_TIMEOUT": "300",
}

CONFIG_FILE = Path(".claude") / "devflow.env"
TURN_START_FILE = "devflow-turn-start"  # in the git dir; written by turn_start.py


def read_payload() -> Dict[str, Any]:
    try:
        data = json.load(sys.stdin)
        return data if isinstance(data, dict) else {}
    except (ValueError, OSError):
        return {}


def project_dir(payload: Optional[Dict[str, Any]] = None) -> Path:
    d = os.environ.get("CLAUDE_PROJECT_DIR") or (payload or {}).get("cwd") or os.getcwd()
    return Path(d)


def load_config(root: Path) -> Dict[str, str]:
    """KEY=VALUE lines prefixed DEVFLOW_; parsed, never sourced or executed."""
    cfg = dict(DEFAULTS)
    path = root / CONFIG_FILE
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return cfg
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        if key.startswith("DEVFLOW_"):
            cfg[key[len("DEVFLOW_"):]] = value
    return cfg


def cfg_list(cfg: Dict[str, str], key: str) -> List[str]:
    return cfg.get(key, "").split()


def cfg_bool(cfg: Dict[str, str], key: str) -> bool:
    return cfg.get(key, "").strip().lower() in ("1", "true", "yes", "on")


def git(cwd: Path, *args: str) -> Optional[str]:
    try:
        out = subprocess.run(
            ["git", "-C", str(cwd), *args],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def current_branch(cwd: Path) -> Optional[str]:
    return git(cwd, "branch", "--show-current") or None


def log_event(root: Path, hook: str, decision: str, reason: str, detail: str = "") -> None:
    """Append every deny/ask to .claude/gate-events.jsonl to spot false alarms later."""
    claude_dir = root / ".claude"
    if not claude_dir.is_dir():
        return
    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "hook": hook,
        "decision": decision,
        "reason": reason,
        "detail": detail[:500],
    }
    try:
        with open(claude_dir / "gate-events.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def emit_pretool(decision: str, reason: str, updated_input: Optional[Dict[str, Any]] = None) -> None:
    out: Dict[str, Any] = {
        "hookEventName": "PreToolUse",
        "permissionDecision": decision,
        "permissionDecisionReason": reason,
    }
    if updated_input is not None:
        out["updatedInput"] = updated_input
    print(json.dumps({"hookSpecificOutput": out}))


def emit_system_message(message: str) -> None:
    print(json.dumps({"systemMessage": message}))
