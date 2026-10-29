import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "plugins" / "devflow" / "scripts"
sys.path.insert(0, str(SCRIPTS))


def sh(cwd, *cmd):
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def write_config(root: Path, **values):
    (root / ".claude").mkdir(exist_ok=True)
    lines = [f"DEVFLOW_{k}={v}" for k, v in values.items()]
    (root / ".claude" / "devflow.env").write_text("\n".join(lines) + "\n")


@pytest.fixture
def repo(tmp_path):
    """A repo on feature branch feat/x, with a bare origin that has main."""
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    sh(tmp_path, "git", "init", "-q", "--bare", "-b", "main", str(origin))
    sh(tmp_path, "git", "init", "-q", "-b", "main", str(work))
    for k, v in (("user.email", "t@example.com"), ("user.name", "t"), ("commit.gpgsign", "false")):
        sh(work, "git", "config", k, v)
    (work / "README.md").write_text("x\n")
    sh(work, "git", "add", ".")
    sh(work, "git", "commit", "-q", "-m", "init")
    sh(work, "git", "remote", "add", "origin", str(origin))
    sh(work, "git", "push", "-q", "origin", "main")
    sh(work, "git", "switch", "-q", "-c", "feat/x")
    write_config(work, PROTECTED_BRANCH="main", OPENSPEC_VERSION="1.15.0",
                 CLOUD="aws", AWS_REGION="eu-north-1", PUBLIC_REPO="true")
    return work


def run_hook(script: str, payload: dict, root: Path, extra_env=None):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root), **(extra_env or {}))
    proc = subprocess.run([sys.executable, str(SCRIPTS / script)], input=json.dumps(payload),
                          capture_output=True, text=True, env=env, cwd=root, timeout=120)
    out = json.loads(proc.stdout) if proc.stdout.strip() else None
    return proc.returncode, out, proc.stderr
