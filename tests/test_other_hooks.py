from conftest import run_hook, sh, write_config

import devflow_common as dc


# --- config parsing

def test_config_parsing(tmp_path):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "devflow.env").write_text(
        "# comment\nDEVFLOW_PROTECTED_BRANCH=develop\nDEVFLOW_FAST_TEST_CMD=\"uv run pytest -x\"\n"
        "OTHER=ignored\nnot a line\nDEVFLOW_SERVICES='127.0.0.1:5432'\n")
    cfg = dc.load_config(tmp_path)
    assert cfg["PROTECTED_BRANCH"] == "develop"
    assert cfg["FAST_TEST_CMD"] == "uv run pytest -x"
    assert cfg["SERVICES"] == "127.0.0.1:5432"
    assert "OTHER" not in cfg and cfg["STOP_TIMEOUT"] == "300"


def test_config_defaults_without_file(tmp_path):
    assert dc.load_config(tmp_path) == dc.DEFAULTS


# --- guard_edit

def edit(repo, path):
    return run_hook("guard_edit.py", {"tool_name": "Edit", "tool_input": {"file_path": str(path)}}, repo)


def test_edit_dependency_file_asks(repo):
    _, out, _ = edit(repo, repo / "pyproject.toml")
    assert out["hookSpecificOutput"]["permissionDecision"] == "ask"


def test_edit_env_file_asks_but_example_does_not(repo):
    assert edit(repo, repo / ".env")[1]["hookSpecificOutput"]["permissionDecision"] == "ask"
    assert edit(repo, repo / ".env.example")[1] is None


def test_edit_guard_config_asks(repo):
    for rel in (".claude/settings.json", ".claude/devflow.env"):
        _, out, _ = edit(repo, repo / rel)
        assert out["hookSpecificOutput"]["permissionDecision"] == "ask", rel


def test_edit_normal_file_silent(repo):
    assert edit(repo, repo / "src" / "app.py") == (0, None, "")


# --- lint_after_edit

def lint(repo, path):
    return run_hook("lint_after_edit.py", {"tool_name": "Edit", "tool_input": {"file_path": str(path)}}, repo)


def test_lint_failure_feeds_back(repo):
    write_config(repo, LINT_CMD="false", LINT_GLOBS="*.py")
    f = repo / "a.py"
    f.write_text("x = 1\n")
    code, _, err = lint(repo, f)
    assert code == 2 and "a.py" in err


def test_lint_pass_and_glob_filter(repo):
    write_config(repo, LINT_CMD="true", LINT_GLOBS="*.py")
    (repo / "a.py").write_text("x\n")
    assert lint(repo, repo / "a.py")[0] == 0
    write_config(repo, LINT_CMD="false", LINT_GLOBS="*.py")
    (repo / "a.md").write_text("x\n")
    assert lint(repo, repo / "a.md")[0] == 0


def test_lint_runner_cannot_spawn_tool_is_not_an_error(repo):
    write_config(repo, LINT_CMD="sh -c 'echo error: Failed to spawn: ruff >&2; exit 2' x", LINT_GLOBS="*.py")
    (repo / "a.py").write_text("x\n")
    assert lint(repo, repo / "a.py")[0] == 0


def test_lint_missing_tool_is_not_an_error(repo):
    write_config(repo, LINT_CMD="no-such-linter-xyz", LINT_GLOBS="*.py")
    (repo / "a.py").write_text("x\n")
    assert lint(repo, repo / "a.py")[0] == 0


# --- stop_tests

def stop(repo, active=False):
    return run_hook("stop_tests.py", {"stop_hook_active": active}, repo)


def setup_stop(repo, cmd, **extra):
    write_config(repo, FAST_TEST_CMD=cmd, CODE_PATHS="src tests", TEST_PATHS="tests", **extra)
    (repo / "src").mkdir(exist_ok=True)
    (repo / "tests").mkdir(exist_ok=True)


def test_stop_skips_when_no_code_changed(repo):
    setup_stop(repo, "false")
    assert stop(repo) == (0, None, "")


def test_stop_blocks_on_red_with_source_change(repo):
    setup_stop(repo, "echo boom; false")
    (repo / "src" / "app.py").write_text("x\n")
    code, _, err = stop(repo)
    assert code == 2 and "boom" in err


def test_stop_tests_first_red_state_does_not_block(repo):
    setup_stop(repo, "false")
    (repo / "tests" / "test_new.py").write_text("x\n")
    code, out, _ = stop(repo)
    assert code == 0 and "tests-first red state" in out["systemMessage"]


def test_stop_green_passes(repo):
    setup_stop(repo, "true")
    (repo / "src" / "app.py").write_text("x\n")
    assert stop(repo) == (0, None, "")


def test_stop_sees_code_committed_during_the_turn(repo):
    setup_stop(repo, "echo red; false")
    run_hook("turn_start.py", {}, repo)              # UserPromptSubmit: HEAD recorded
    (repo / "src" / "app.py").write_text("x\n")
    sh(repo, "git", "add", ".")
    sh(repo, "git", "commit", "-q", "-m", "feat: group 2")   # tree is clean again
    code, _, err = stop(repo)
    assert code == 2 and "red" in err


def test_stop_committed_tests_only_is_red_state(repo):
    setup_stop(repo, "false")
    run_hook("turn_start.py", {}, repo)
    (repo / "tests" / "test_new.py").write_text("x\n")
    sh(repo, "git", "add", ".")
    sh(repo, "git", "commit", "-q", "-m", "test: failing tests")
    code, out, _ = stop(repo)
    assert code == 0 and "tests-first red state" in out["systemMessage"]


def test_stop_ignores_commits_from_before_the_turn(repo):
    setup_stop(repo, "false")
    (repo / "src" / "app.py").write_text("x\n")
    sh(repo, "git", "add", ".")
    sh(repo, "git", "commit", "-q", "-m", "earlier work")
    run_hook("turn_start.py", {}, repo)              # turn starts after that commit
    assert stop(repo) == (0, None, "")


def test_turn_start_prints_nothing(repo):
    assert run_hook("turn_start.py", {}, repo) == (0, None, "")


def test_stop_does_not_loop(repo):
    setup_stop(repo, "false")
    (repo / "src" / "app.py").write_text("x\n")
    assert stop(repo, active=True) == (0, None, "")


def test_stop_reports_service_down(repo):
    setup_stop(repo, "false", SERVICES="127.0.0.1:1")
    (repo / "src" / "app.py").write_text("x\n")
    code, out, _ = stop(repo)
    assert code == 0 and "NOT run" in out["systemMessage"]


def test_stop_reports_timeout(repo):
    setup_stop(repo, "sleep 5", STOP_TIMEOUT="1")
    (repo / "src" / "app.py").write_text("x\n")
    code, out, _ = stop(repo)
    assert code == 0 and "timed out" in out["systemMessage"]


# --- session_context

def test_session_context_lists_branch_changes_and_tasks(repo):
    sh(repo, "git", "switch", "-q", "-c", "feat/add-thing")
    ch = repo / "openspec" / "changes" / "add-thing"
    ch.mkdir(parents=True)
    (ch / "tasks.md").write_text("## 1\n- [x] 1.1 done\n- [ ] 1.2 todo\n")
    (repo / "openspec" / "changes" / "archive").mkdir()
    proc = run_hook_raw(repo)
    assert "Branch: feat/add-thing" in proc
    assert "add-thing (1/2 tasks)" in proc
    assert "- [ ] 1.2 todo" in proc
    assert "archive" not in proc.split("Open OpenSpec changes:")[1].split("Unchecked")[0]


def run_hook_raw(repo):
    import json, os, subprocess, sys
    from conftest import SCRIPTS
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(repo))
    return subprocess.run([sys.executable, str(SCRIPTS / "session_context.py")], input=json.dumps({}),
                          capture_output=True, text=True, env=env).stdout
