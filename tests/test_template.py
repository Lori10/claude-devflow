"""Render the copier template and run the generated check.sh against a real repo."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import sh

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "template" / "scripts"))
import weakened_tests as wt  # noqa: E402

copier = pytest.importorskip("copier")


def render(dest: Path, **answers):
    data = {"project_name": "Demo Agent", "project_description": "A demo.", **answers}
    copier.run_copy(str(ROOT), str(dest), data=data, defaults=True, unsafe=False,
                    skip_tasks=True, quiet=True)


@pytest.fixture
def py_project(tmp_path):
    dest = tmp_path / "demo"
    render(dest, cloud="aws", aws_region="eu-north-1", aws_profile="demo", claude_action=True)
    return dest


def test_render_produces_expected_files(py_project):
    for rel in ("CLAUDE.md", "CONTRIBUTING.md", ".claude/settings.json", ".claude/devflow.env",
                "openspec/config.yaml", "scripts/check.sh", "scripts/weakened_tests.py",
                "scripts/setup_github.sh", ".github/workflows/ci.yml", ".github/workflows/claude.yml",
                ".github/dependabot.yml", ".gitignore", ".worktreeinclude", ".copier-answers.yml"):
        assert (py_project / rel).is_file(), rel


def test_settings_json_is_valid_and_enables_plugin(py_project):
    s = json.loads((py_project / ".claude/settings.json").read_text())
    assert s["enabledPlugins"] == {"devflow@lori10-devflow": True}
    assert s["extraKnownMarketplaces"]["lori10-devflow"]["source"] == {
        "source": "github", "repo": "Lori10/claude-devflow"}
    allow = s["permissions"]["allow"]
    assert "Bash(uv run pytest -q:*)" in allow
    assert not any(r in ("Bash(uv run:*)", "Bash(:*)") for r in allow)
    assert "Read(./.env)" in s["permissions"]["deny"]


def test_devflow_env_is_single_source(py_project):
    env = (py_project / ".claude/devflow.env").read_text()
    assert "DEVFLOW_OPENSPEC_VERSION=1.15.0" in env
    assert "DEVFLOW_CLOUD=aws" in env and "DEVFLOW_AWS_REGION=eu-north-1" in env
    assert "1.15.0" not in (py_project / ".claude/settings.json").read_text()
    assert "1.15.0" not in (py_project / "scripts/check.sh").read_text()


def test_workflows_keep_github_expressions(py_project):
    ci = (py_project / ".github/workflows/ci.yml").read_text()
    assert "${{ github.ref }}" in ci and "${{ secrets.GITHUB_TOKEN }}" in ci
    assert "uv sync --frozen" in ci
    claude = (py_project / ".github/workflows/claude.yml").read_text()
    assert "author_association" in claude


def test_optional_files_off(tmp_path):
    dest = tmp_path / "plain"
    render(dest, language="node", claude_action=False)
    assert not (dest / ".github/workflows/claude.yml").exists()
    assert "DEVFLOW_CLOUD=\n" in (dest / ".claude/devflow.env").read_text()
    assert "npm ci" in (dest / ".github/workflows/ci.yml").read_text()


def test_generated_scripts_parse(py_project):
    for script in ("scripts/check.sh", "scripts/setup_github.sh"):
        subprocess.run(["bash", "-n", str(py_project / script)], check=True)


def init_project_repo(project: Path, origin: Path):
    """Make the rendered project a repo with origin/main; use trivial gate commands."""
    env = project / ".claude/devflow.env"
    env.write_text(env.read_text().replace("DEVFLOW_OPENSPEC_VERSION=1.15.0", "DEVFLOW_OPENSPEC_VERSION="))
    check = project / "scripts/check.sh"
    check.write_text(check.read_text().replace("uv run ruff check .", "true").replace("uv run pytest -q", "true"))
    check.chmod(0o755)
    (project / "scripts/weakened_tests.py").chmod(0o755)
    sh(origin.parent, "git", "init", "-q", "--bare", "-b", "main", str(origin))
    sh(project, "git", "init", "-q", "-b", "main")
    for k, v in (("user.email", "t@example.com"), ("user.name", "t"), ("commit.gpgsign", "false")):
        sh(project, "git", "config", k, v)
    (project / "tests").mkdir()
    (project / "tests/test_a.py").write_text("def test_a():\n    assert 1 == 1\n")
    sh(project, "git", "add", ".")
    sh(project, "git", "commit", "-q", "-m", "init")
    sh(project, "git", "remote", "add", "origin", str(origin))
    sh(project, "git", "push", "-q", "origin", "main")
    sh(project, "git", "switch", "-q", "-c", "feat/add-thing")


def run_check(project, *args):
    return subprocess.run(["scripts/check.sh", *args], cwd=project, capture_output=True, text=True,
                          env={k: v for k, v in os.environ.items() if k != "GITHUB_ACTIONS"})


def test_check_sh_passes_stamps_and_skips_when_stale(py_project, tmp_path):
    init_project_repo(py_project, tmp_path / "origin.git")
    first = run_check(py_project)
    assert first.returncode == 0, first.stdout
    assert "--> none" in first.stdout
    second = run_check(py_project, "--if-stale")
    assert "already verified" in second.stdout


def test_check_sh_flags_weakened_test_and_does_not_stamp(py_project, tmp_path):
    init_project_repo(py_project, tmp_path / "origin.git")
    (py_project / "tests/test_a.py").write_text("def test_a():\n    pass\n")
    sh(py_project, "git", "commit", "-qam", "weaken")
    out = run_check(py_project)
    assert out.returncode == 0 and "REVIEW" in out.stdout
    assert "already verified" not in run_check(py_project, "--if-stale").stdout


def test_check_sh_land_requires_archived_change(py_project, tmp_path):
    init_project_repo(py_project, tmp_path / "origin.git")
    (py_project / "openspec/changes/add-thing").mkdir(parents=True)
    out = run_check(py_project, "--land")
    assert out.returncode == 1 and "not archived" in out.stdout


# --- weakened-test scan unit tests

DIFF_HEADER = "diff --git a/tests/t.py b/tests/t.py\n--- a/tests/t.py\n+++ b/tests/t.py\n"


@pytest.mark.parametrize("body,flagged", [
    ("-    assert x == 1\n", True),
    ("-def test_old():\n", True),
    ("+@pytest.mark.skip(reason='flaky')\n", True),
    ("+    pytest.skip('later')\n", True),
    ("+it.skip('works', () => {})\n", True),
    ("+test.only('x', () => {})\n", True),
    ("+xit('x', () => {})\n", True),
    ("-  expect(a).toBe(1)\n", True),
    ("-    self.assertEqual(a, 1)\n", True),
    ("+    assert x == 1\n", False),                             # adding is fine
    ("-    assert x == 1\n+    assert x == 1\n", False),         # moved, not removed
    ("-    x = compute()\n+    x = compute(2)\n", False),
])
def test_weakened_scan(body, flagged):
    assert bool(wt.scan(DIFF_HEADER + body)) is flagged


def test_sandbox_option(tmp_path):
    on = tmp_path / "on"
    render(on, sandbox=True, cloud="aws", aws_region="eu-north-1")
    s = json.loads((on / ".claude/settings.json").read_text())
    assert s["sandbox"]["enabled"] is True
    assert ".env" in s["sandbox"]["filesystem"]["denyRead"]
    assert "*.amazonaws.com" in s["sandbox"]["network"]["allowedDomains"]
    off = tmp_path / "off"
    render(off)
    assert "sandbox" not in json.loads((off / ".claude/settings.json").read_text())


def test_check_sh_land_does_not_match_similar_change_names(py_project, tmp_path):
    init_project_repo(py_project, tmp_path / "origin.git")
    sh(py_project, "git", "switch", "-q", "-c", "feat/thing")
    other = py_project / "openspec/changes/archive/2026-10-29-add-thing"
    other.mkdir(parents=True)
    (other / "tasks.md").write_text("- [ ] unfinished task of another change\n")
    sh(py_project, "git", "add", ".")
    sh(py_project, "git", "commit", "-q", "-m", "x")
    assert run_check(py_project, "--land").returncode == 0


def test_check_sh_land_requires_finished_tasks(py_project, tmp_path):
    init_project_repo(py_project, tmp_path / "origin.git")
    archived = py_project / "openspec/changes/archive/2026-10-29-add-thing"
    archived.mkdir(parents=True)
    (archived / "tasks.md").write_text("## 1\n- [x] 1.1 tests\n## 9 Live\n- [ ] 9.1 live eval\n")
    out = run_check(py_project, "--land")
    assert out.returncode == 1 and "unchecked tasks" in out.stdout and "9.1 live eval" in out.stdout
    (archived / "tasks.md").write_text("## 1\n- [x] 1.1 tests\n## 9 Live\n- [x] 9.1 live eval\n")
    sh(py_project, "git", "add", ".")
    sh(py_project, "git", "commit", "-q", "-m", "archive")
    out = run_check(py_project, "--land")
    assert out.returncode == 0, out.stdout
