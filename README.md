# claude-devflow

A spec-driven, test-first workflow for Claude Code that **enforces** its rules instead of
only asking for them. Two pieces, one repo:

| Piece | What it is | How you get it |
|---|---|---|
| **`devflow` plugin** | Guard hooks (git, dependencies, cloud, secrets), tests before a turn ends, lint after edits, re-orientation after `/compact`, and the `/devflow:new-branch`, `/devflow:verify`, `/devflow:land-branch` skills | Plugin marketplace in this repo; projects enable it in `.claude/settings.json` |
| **Project template** | `CLAUDE.md`, `CONTRIBUTING.md`, `openspec/config.yaml` rules, `.claude/settings.json`, `.claude/devflow.env`, `scripts/check.sh` (the gates CI also runs), CI with gitleaks, Dependabot, GitHub ruleset script | `copier copy` once per project, `copier update` to pull template fixes later |

It works with [OpenSpec](https://github.com/Fission-AI/OpenSpec) (Fission AI): the `/opsx:*`
skills come from `openspec init` in each project, pinned to the version in
`.claude/devflow.env`.

## The loop

`/devflow:new-branch` → `/opsx:propose` → **you approve** → `/opsx:apply` (tests first,
one commit per task group, draft PR) → `/devflow:verify` → live checks (**you** run or
approve) → `/opsx:archive` → `/devflow:land-branch` (**you** approve the merge; GitHub
blocks it until CI is green). Details: the generated `CONTRIBUTING.md`.

## Start a new project

```bash
uvx copier copy --trust gh:Lori10/claude-devflow my-project
cd my-project && claude          # trust the folder; Claude Code offers to install devflow
# after the first push:
scripts/setup_github.sh          # merge-commit only, secret scanning, ruleset on main
```

`--trust` lets the template run its post-copy tasks: `git init` (if needed), `chmod` on the
scripts, and `openspec init --tools claude` with the pinned version. Adding it to an
existing repo works the same way (`copier copy` into the repo); `CLAUDE.md` and
`openspec/config.yaml` are never overwritten once they exist.

Install the plugin by hand (e.g. before this repo is on GitHub):

```bash
claude plugin marketplace add ~/claude-devflow     # or: Lori10/claude-devflow
claude plugin install devflow@lori10-devflow
```

## What the hooks enforce

| Hook | Rule |
|---|---|
| `guard_bash` (PreToolUse Bash) | **deny**: force-push (`--force`, `--force-with-lease`, `--mirror`, `+refspec`), pushing to or deleting the protected branch, committing on it, `--no-verify` / `commit -n`, rebase / `pull --rebase`, `-c core.hooksPath`, `gh pr merge --admin`, AWS calls outside the project region, `rm -r` on `/` or your home · **ask**: `rm -r` outside the project, on the project root or on `.git`, `reset --hard`, `clean`, `checkout -- / . / -f`, `restore`, `switch -f`, `branch -D`, `stash drop/clear`, merges, non-GET `gh api` (read-only GraphQL excluded), repo/secret settings, dependency installs and upgrades (`uv lock --upgrade`, `npm update`, …), `cdk deploy/destroy`, AWS write calls, `terraform apply`, anything touching `.env` · **rewrite**: bare or unpinned `openspec` → pinned CLI (lone read-only calls are allowed) |
| `guard_edit` (PreToolUse Edit/Write) | **ask**: dependency files, `.env*`, and the guard config itself (`.claude/settings*.json`, `.claude/devflow.env`) |
| `lint_after_edit` (PostToolUse) | runs `DEVFLOW_LINT_CMD <file>`; findings go back to Claude |
| `turn_start` (UserPromptSubmit) | records `HEAD` so the Stop hook also sees code committed during the turn |
| `stop_tests` (Stop) | runs `DEVFLOW_FAST_TEST_CMD` when the turn changed code (uncommitted, or committed since the turn started); blocks on red, except when only tests changed (the tests-first red state); reports down services and timeouts instead of passing silently |
| `session_context` (SessionStart compact) | re-prints branch, dirty files, open changes with task counts, and the branch's unchecked tasks |
| startup check (SessionStart startup/resume) | warns visibly when `python3` ≥ 3.8 is missing, so the guards can't be off without you knowing |

Every deny/ask is appended to `.claude/gate-events.jsonl` (gitignored) so false alarms can
be found and the rules tuned.

The hooks parse commands with `shlex`, so quoting, `&&`/`;`/newline chains, `bash -c '…'`,
`eval`, `env`/`sudo`/`timeout` wrappers, `uv run`/`poetry run`, `$(…)` and `git -C/-c` global options don't hide a
command. They are still **guardrails against accidents, not a security boundary**: the
GitHub ruleset and CI are the authoritative gates. A hook that hits an internal error lets
the call through (with a visible error) rather than blocking your session. Python 3.8+
(stdlib only, tested on 3.8, 3.10 and 3.12) is the only runtime requirement; no `jq`,
`perl` or GNU grep.

## Configuration: `.claude/devflow.env`

Parsed as `KEY=VALUE`, never executed. With no file, the git guards still work with `main`
as the protected branch, and everything project-specific is off.

| Key | Default | Used by |
|---|---|---|
| `DEVFLOW_PROTECTED_BRANCH` | `main` | git guards, skills, `check.sh` |
| `DEVFLOW_OPENSPEC_VERSION` | (empty: no pinning) | openspec rewrite, `check.sh` (single source of truth) |
| `DEVFLOW_CHECK_CMD` | `scripts/check.sh` | `/devflow:verify`, `/devflow:land-branch` |
| `DEVFLOW_FAST_TEST_CMD` | (empty: Stop hook off) | Stop hook |
| `DEVFLOW_CODE_PATHS` / `DEVFLOW_TEST_PATHS` | `src tests` / `tests` | Stop hook, weakened-test scan |
| `DEVFLOW_LINT_CMD` / `DEVFLOW_LINT_GLOBS` | (empty) / `*.py` | lint after edit |
| `DEVFLOW_SERVICES` | (empty) | Stop hook, `check.sh` (`host:port` list) |
| `DEVFLOW_DEP_FILES` | pyproject, uv.lock, requirements, package*.json, lockfiles | edit guard |
| `DEVFLOW_PUBLIC_REPO` | `true` | secret-looking-file check on push |
| `DEVFLOW_CLOUD` / `DEVFLOW_AWS_REGION` | (empty) | cloud guard (`aws`) |
| `DEVFLOW_STOP_TIMEOUT` | `300` | Stop hook |

## Personal defaults

`user/CLAUDE.md` holds preferences meant for every project (commit style, attribution,
dependency and test rules). Copy it to `~/.claude/CLAUDE.md` to apply it everywhere.

## Notes

- **Versioning**: `copier copy`/`copier update` use the latest **git tag** of this repo, and
  projects get the plugin version from `plugin.json`. Release by bumping
  `plugins/devflow/.claude-plugin/plugin.json`, committing, and tagging `vX.Y.Z`.
- **CI expects a lockfile** (`uv.lock` / `package-lock.json`): add `pyproject.toml` or
  `package.json` in the project's first change, or the `checks` job fails at install.

- **gitleaks-action** is free for personal accounts; repos owned by an organization need a
  `GITLEAKS_LICENSE` secret. `check.sh` also runs a local gitleaks scan when it's installed.
- **Sandbox** (template option `sandbox`, off by default): turns on Claude Code's Bash
  sandbox with `.env` in `filesystem.denyRead` and network limited to package registries,
  GitHub and (for AWS projects) `*.amazonaws.com`. Stronger than the hook, but any other
  host then needs approval, so it's opt-in.
- **Dependency prompts during project setup**: every edit to `pyproject.toml` asks. While
  scaffolding, set `DEVFLOW_DEP_FILES=` (empty) in `.claude/devflow.env`, then restore it.
- **Actions are pinned to SHAs** that were current when the template was written;
  Dependabot opens PRs to bump them.

## Development

```bash
uv run --group dev pytest        # hook decision tables, weakened-test scan, template render
claude plugin validate . && claude plugin validate ./plugins/devflow
```

Ideas borrowed from other projects: a test suite for the hooks
([claude-code-guardrails](https://github.com/honokasoftware-ai/claude-code-guardrails)),
the gate event log ([agent-os-openspec](https://github.com/henemm/agent-os-openspec)), and
guards for `reset --hard`/`clean`/`branch -D`
([git-guardrails skill](https://www.skills.sh/mattpocock/skills/git-guardrails-claude-code)).
