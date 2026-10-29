"""Decision table for guard_bash. Every hole found in the retail-analyst-agent review
has a row here, so it can't silently come back."""
import pytest

from conftest import run_hook, sh

import devflow_common as dc
import guard_bash as gb

ON_FEATURE = [
    # --- allowed (no decision)
    ("git status", None),
    ("git push origin feat/x", None),
    ("git push -u origin feat/x", None),
    ("git push", None),
    ("git commit -m 'feat: x'", None),
    ("git commit -mnew-feature", None),          # -m value is not -n
    ("git commit -m -n", None),                  # -m value is not -n
    ("git checkout main", None),
    ("git checkout -b feat/y", None),
    ("git switch main", None),
    ("git branch -d feat/old", None),            # safe delete
    ("git restore --staged file.py", None),
    ("git clean -n", None),
    ("git clean -nd", None),
    ("git push --dry-run --force origin main", None),
    ("git merge-base main HEAD", None),
    ("git merge --abort", None),
    ("git rebase --abort", None),
    ("git stash", None),
    ("git stash pop", None),
    ("gh pr create --draft --title x --body y", None),
    ("gh pr view 5", None),
    ("gh api repos/o/r/pulls/5", None),
    ("gh api -X GET repos/o/r/rulesets", None),
    ("npm install", None),                       # installs from the lockfile
    ("npm ci", None),
    ("uv sync --frozen", None),
    ("uv run pytest -q", None),
    ("echo 'git push --force' > notes.txt", None),   # quoted text is not a command
    ("cat .env.example", None),
    ("cdk synth", None),
    ("cdk diff", None),
    ("aws sts get-caller-identity --profile railagent", None),
    ("aws bedrock list-foundation-models --region eu-north-1", None),
    ("aws dynamodb scan --table-name t", None),
    ("aws s3 ls", None),
    # --- force pushes: deny
    ("git push --force origin feat/x", "deny"),
    ("git push -f", "deny"),
    ("git push -fu origin feat/x", "deny"),
    ("git push --force-with-lease", "deny"),
    ("git push --force-with-lease=feat/x:abc origin feat/x", "deny"),
    ("git push origin +feat/x", "deny"),
    ("git push --mirror", "deny"),
    # --- protected branch: deny
    ("git push origin main", "deny"),
    ("git push origin feat/x:main", "deny"),
    ("git push origin HEAD:refs/heads/main", "deny"),
    ("git push origin HEAD:main", "deny"),
    ("git push origin --delete main", "deny"),
    ("git push origin :main", "deny"),
    ("git push --all origin", "deny"),
    # --- hook bypasses: deny
    ("git commit --no-verify -m x", "deny"),
    ("git commit -n -m x", "deny"),
    ("git commit -nm x", "deny"),
    ("git commit -am x -n", "deny"),
    ("git push --no-verify origin feat/x", "deny"),
    ("git -c core.hooksPath=/dev/null commit -m x", "deny"),
    ("git config core.hooksPath /dev/null", "deny"),
    # --- history rewrites: deny
    ("git rebase main", "deny"),
    ("git rebase -i HEAD~3", "deny"),
    ("git pull --rebase origin main", "deny"),
    ("git pull -r", "deny"),
    ("gh pr merge 5 --admin --merge", "deny"),
    # --- destructive local ops: ask
    ("git reset --hard HEAD~3", "ask"),
    ("git reset --hard", "ask"),
    ("git clean -fdx", "ask"),
    ("git clean -f", "ask"),
    ("git checkout -- .", "ask"),
    ("git checkout .", "ask"),
    ("git checkout HEAD~1 -- src/app.py", "ask"),
    ("git checkout -f main", "ask"),
    ("git restore .", "ask"),
    ("git restore src/app.py", "ask"),
    ("git restore --staged --worktree src/app.py", "ask"),
    ("git switch -f main", "ask"),
    ("git switch --discard-changes main", "ask"),
    ("git branch -D feat/x", "ask"),
    ("git branch -d -f feat/x", "ask"),
    ("git branch --delete --force feat/x", "ask"),
    ("git stash drop", "ask"),
    ("git stash clear", "ask"),
    ("git worktree remove --force ../wt", "ask"),
    ("git filter-branch --tree-filter x HEAD", "ask"),
    ("git push origin --delete feat/old", "ask"),
    # --- merges and GitHub writes: ask
    ("git merge feat/y", "ask"),
    ("gh pr merge 5 --merge --delete-branch", "ask"),
    ("gh pr merge 5 --squash", "ask"),
    ("gh api -X PUT repos/o/r/pulls/5/merge", "ask"),
    ("gh api --method=DELETE repos/o/r/git/refs/heads/x", "ask"),
    ("gh api -XPATCH repos/o/r", "ask"),
    ("gh api repos/o/r/issues -f title=x", "ask"),   # a body field implies POST
    ("gh repo delete o/r --yes", "ask"),
    ("gh secret set TOKEN", "ask"),
    # --- dependencies: ask
    ("uv add requests", "ask"),
    ("uv remove requests", "ask"),
    ("uv pip install requests", "ask"),
    ("pip install requests", "ask"),
    ("python3 -m pip install requests", "ask"),
    ("npm install lodash", "ask"),
    ("npm i -D vitest", "ask"),
    ("pnpm add zod", "ask"),
    ("yarn add zod", "ask"),
    ("poetry add httpx", "ask"),
    # --- cloud: ask / deny
    ("cdk deploy --all --profile railagent", "ask"),
    ("cdk destroy", "ask"),
    ("npx cdk deploy", "ask"),
    ("aws dynamodb delete-table --table-name t", "ask"),
    ("aws s3 rm s3://b/k", "ask"),
    ("aws lambda invoke --function-name f out.json", "ask"),
    ("aws dynamodb list-tables --region us-east-1", "deny"),
    ("aws --region=eu-west-1 s3 ls", "deny"),
    ("terraform apply", "ask"),
    # --- secrets on disk: ask
    ("cat .env", "ask"),
    ("source .env.local", "ask"),
    ("grep KEY ./.env", "ask"),
    ("cp .env /tmp/x", "ask"),
    # --- compound and nested commands
    ("git add . && git commit -m x && git push origin feat/x", None),
    ("git status; git push --force", "deny"),
    ("git status\ngit push --force", "deny"),
    ("cd sub && git reset --hard", "ask"),
    ("bash -c 'git push --force'", "deny"),
    ("sh -c \"git reset --hard\"", "ask"),
    ("eval git push origin main", "deny"),
    ("FOO=1 git push --force", "deny"),
    ("sudo git push -f", "deny"),
    ("env GIT_TRACE=1 git push origin main", "deny"),
    ("timeout 30 git push origin main", "deny"),
    ("echo $(git push --force)", "deny"),
    ("/usr/bin/git push origin main", "deny"),
    ("git -C ../other push --force", "deny"),
    ("git push origin feat/x && gh pr create --base main", None),  # --base main is not a push to main
    # --- runners don't hide the command (final review)
    ("uv run git push --force", "deny"),
    ("uv run --with boto3 cdk deploy", "ask"),
    ("poetry run git reset --hard", "ask"),
    ("uv run --quiet pytest -q", None),
    # --- dependency upgrades: ask (final review)
    ("uv lock --upgrade", "ask"),
    ("uv lock -U", "ask"),
    ("uv sync --upgrade-package boto3", "ask"),
    ("uv lock -P boto3", "ask"),
    ("npm update", "ask"),
    ("poetry update", "ask"),
    ("uv lock", None),
    ("uv sync", None),
    # --- read-only GraphQL is not a write (final review)
    ("gh api graphql -f query='{ viewer { login } }'", None),
    ("gh api graphql -f query='mutation { addStar(input:{starrableId:\"x\"}) { clientMutationId } }'", "ask"),
    # --- recursive deletes (final review)
    ("rm -rf ~", "deny"),
    ("rm -rf /", "deny"),
    ("rm -rf $HOME/x", "ask"),
    ("rm -rf ../other-project", "ask"),
    ("rm -rf .git", "ask"),
    ("rm -rf .", "ask"),
    ("rm -rf *", "ask"),
    ("rm -rf build dist", None),
    ("rm -rf src/__pycache__", None),
    ("rm -f notes.txt", None),
    ("rm notes.txt", None),
    # --- unparseable: ask
    ("git push 'unbalanced", "ask"),
]


def ctx_for(root):
    return gb.Ctx(cwd=root, root=root, cfg=dc.load_config(root))


@pytest.mark.parametrize("command,expected", ON_FEATURE)
def test_decision_on_feature_branch(repo, command, expected):
    assert gb.evaluate(command, ctx_for(repo)).decision == expected


@pytest.mark.parametrize("command,expected", [
    ("git commit -m x", "deny"),
    ("git -c user.name=x commit -m x", "deny"),     # -c no longer hides the subcommand
    ("git push", "deny"),
    ("git push origin HEAD", "deny"),
    ("git status", None),
    ("git pull origin main", None),
])
def test_decision_on_protected_branch(repo, command, expected):
    sh(repo, "git", "switch", "-q", "main")
    assert gb.evaluate(command, ctx_for(repo)).decision == expected


def test_protected_branch_is_configurable(repo):
    sh(repo, "git", "switch", "-q", "-c", "develop")
    cfg = dc.load_config(repo)
    cfg["PROTECTED_BRANCH"] = "develop"
    ctx = gb.Ctx(cwd=repo, root=repo, cfg=cfg)
    assert gb.evaluate("git commit -m x", ctx).decision == "deny"
    assert gb.evaluate("git push origin main", ctx).decision is None


# --- openspec pinning

@pytest.mark.parametrize("command,expected_cmd,decision", [
    ("openspec list", "npx --yes @fission-ai/openspec@1.15.0 list", "allow"),
    ("openspec validate --all --strict", "npx --yes @fission-ai/openspec@1.15.0 validate --all --strict", "allow"),
    ("npx openspec show x", "npx --yes @fission-ai/openspec@1.15.0 show x", "allow"),
    ("npx -y @fission-ai/openspec@1.14.1 list", "npx --yes @fission-ai/openspec@1.15.0 list", "allow"),
    ("openspec archive add-x -y", "npx --yes @fission-ai/openspec@1.15.0 archive add-x -y", "ask"),
    ("cd x && openspec list", "cd x && npx --yes @fission-ai/openspec@1.15.0 list", "ask"),
    ("npx --yes @fission-ai/openspec@1.15.0 list", None, "allow"),      # already pinned
    ("ls openspec/specs", None, None),                                  # a path, not the CLI
])
def test_openspec_pin(repo, command, expected_cmd, decision):
    res = gb.evaluate(command, ctx_for(repo))
    assert res.new_command == expected_cmd
    assert res.decision == decision


def test_no_pin_without_configured_version(repo):
    cfg = dc.load_config(repo)
    cfg["OPENSPEC_VERSION"] = ""
    res = gb.evaluate("openspec list", gb.Ctx(cwd=repo, root=repo, cfg=cfg))
    assert res.new_command is None and res.decision is None


def test_cloud_guard_off_without_config(repo):
    cfg = dc.load_config(repo)
    cfg["CLOUD"] = ""
    ctx = gb.Ctx(cwd=repo, root=repo, cfg=cfg)
    assert gb.evaluate("cdk deploy", ctx).decision is None
    assert gb.evaluate("aws dynamodb delete-table --table-name t", ctx).decision is None


# --- secret-looking files on push (public repos)

def test_push_adding_secret_file_asks(repo):
    (repo / "service-account.json").write_text("{}")
    sh(repo, "git", "add", ".")
    sh(repo, "git", "commit", "-q", "-m", "oops")
    res = gb.evaluate("git push origin feat/x", ctx_for(repo))
    assert res.decision == "ask" and "service-account.json" in " ".join(res.reasons)


def test_secret_file_check_off_for_private_repo(repo):
    (repo / "credentials.txt").write_text("x")
    sh(repo, "git", "add", ".")
    sh(repo, "git", "commit", "-q", "-m", "x")
    cfg = dc.load_config(repo)
    cfg["PUBLIC_REPO"] = "false"
    assert gb.evaluate("git push", gb.Ctx(cwd=repo, root=repo, cfg=cfg)).decision is None


# --- end to end through the hook protocol

def test_hook_protocol_deny_and_event_log(repo):
    code, out, _ = run_hook("guard_bash.py", {"tool_name": "Bash", "cwd": str(repo),
                                              "tool_input": {"command": "git push --force"}}, repo)
    assert code == 0
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    log = (repo / ".claude" / "gate-events.jsonl").read_text()
    assert '"deny"' in log and "git push --force" in log


def test_hook_protocol_rewrite_keeps_other_fields(repo):
    payload = {"tool_name": "Bash", "cwd": str(repo),
               "tool_input": {"command": "openspec list", "description": "list", "timeout": 5000}}
    code, out, _ = run_hook("guard_bash.py", payload, repo)
    hso = out["hookSpecificOutput"]
    assert hso["permissionDecision"] == "allow"
    assert hso["updatedInput"] == {"command": "npx --yes @fission-ai/openspec@1.15.0 list",
                                   "description": "list", "timeout": 5000}


def test_hook_protocol_silent_when_nothing_to_say(repo):
    code, out, err = run_hook("guard_bash.py", {"tool_name": "Bash", "cwd": str(repo),
                                                "tool_input": {"command": "ls -la"}}, repo)
    assert (code, out, err) == (0, None, "")


def test_hook_ignores_other_tools(repo):
    code, out, _ = run_hook("guard_bash.py", {"tool_name": "Read", "tool_input": {}}, repo)
    assert (code, out) == (0, None)


def test_works_outside_a_git_repo(tmp_path):
    ctx = gb.Ctx(cwd=tmp_path, root=tmp_path, cfg=dict(dc.DEFAULTS))
    assert gb.evaluate("git push --force", ctx).decision == "deny"
    assert gb.evaluate("ls", ctx).decision is None
