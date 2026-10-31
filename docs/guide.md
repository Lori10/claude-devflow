# devflow guide: what it does, why, and when to use it

The [README](../README.md) is the reference: install steps, every hook rule, every config
key. This guide explains the reasoning behind them: which problems the kit solves, why it is
built the way it is, where it stops helping, and when to leave it out.

## The problem

A coding agent like Claude Code is fast and usually right. The expensive failures are the
rare ones, and they repeat across projects:

| Failure | What it looks like |
|---|---|
| Building before agreeing | The agent starts coding from a one-line request; the result solves a slightly different problem, and the review happens after the work instead of before it. |
| "Done" without evidence | A task is reported finished while tests were never run, are red, or were edited until they passed. |
| Irreversible git operations | `push --force`, `reset --hard`, `clean -fd`, a commit straight to `main`, a deleted branch. Each one is a single command, and some can't be undone. |
| Dependency creep | Packages added or upgraded on the way to a fix, without anyone deciding to take them on. |
| Cloud mistakes | A deploy nobody approved, a resource in the wrong region, an idle resource that keeps billing. |
| Secrets in public | A `.env` read into the transcript, or a key file pushed to a public repo. |
| Lost context | After `/compact` or a new session, the agent no longer knows which branch, change or task it was on. |
| Tool drift | An unpinned CLI (here: OpenSpec) changes behavior between runs or between local and CI. |

None of these is solved by a better prompt. A rule in `CLAUDE.md` is advice: it is followed
most of the time, and "most of the time" is exactly what fails on the hundredth turn.

## The core idea: enforce rules, don't only state them

devflow puts each rule at the layer that can actually guarantee it:

| Layer | Who runs it | Can the agent skip it? | Used for |
|---|---|---|---|
| `CLAUDE.md`, `openspec/config.yaml` | The model reads it | Yes | Intent, conventions, what artifacts must contain |
| Hooks (the plugin) | The Claude Code harness, outside the model | No, apart from the gaps under Limitations | Blocking or confirming risky commands, tests before a turn ends, lint after edits |
| `scripts/check.sh` | The agent or you, on request | Yes (it's an instruction) | Every offline gate in one command |
| CI + GitHub ruleset | GitHub | No | The final authority: nothing reaches `main` without a PR and a green `checks` job |

The layers overlap on purpose. The hooks catch most mistakes early, while they are cheap to
fix. CI and the ruleset catch everything else, including mistakes no hook anticipated. Each
layer assumes the one before it can fail.

## How the pieces map to the failures

| Failure | What devflow does | Why this way |
|---|---|---|
| Building before agreeing | The loop: `/devflow:new-branch` → `/opsx:propose` → **you approve** → `/opsx:apply`. OpenSpec writes proposal, spec deltas, design and tasks before any code. | The cheapest review is of a plan, not a diff. Spec scenarios then become the tests, so the plan stays connected to the code. |
| "Done" without evidence | The Stop hook runs the fast tests whenever a turn changed code and refuses to end the turn on red. `/devflow:verify` runs `check.sh` and reports PASS/FAIL with output. A weakened-test scan flags removed asserts, deleted tests and added skips. | The harness runs the Stop hook, so "I ran the tests" can't be skipped or hallucinated. The weakened-test scan targets the specific way agents reach green dishonestly. |
| Irreversible git operations | `guard_bash` **denies** force-push, pushing to or committing on `main`, `--no-verify`, rebase, and hook-path overrides. It **asks** before `reset --hard`, `clean`, `branch -D`, `stash drop` and similar. | Deny for what is never needed in this workflow; ask for what is sometimes legitimate but must be a deliberate human choice. |
| Dependency creep | Installs, removals and upgrades ask (`uv add`, `pip install`, `npm update`, `uv lock --upgrade`, …). Edits to `pyproject.toml` and lockfiles ask. Proposals must list new dependencies. | A dependency is a long-term decision; it gets made once, explicitly, in the plan. |
| Cloud mistakes | With `DEVFLOW_CLOUD=aws`: AWS calls outside the project region are denied; `cdk deploy/destroy`, `terraform apply` and AWS write calls ask; read-only calls pass. Live and billed checks are a separate final task group that you run or approve. | Reading the cloud is safe and useful; changing it costs money and is shared state. |
| Secrets in public | `.env` reads are denied in settings; commands and edits touching `.env*` ask; a push of secret-looking files to a public repo asks; gitleaks runs locally and in CI; secret scanning with push protection on GitHub. | Several cheap layers, because a leaked key can't be taken back. |
| Lost context | After `/compact`, a hook re-prints branch, uncommitted files, open changes with task counts, and the branch's unchecked tasks. | The state lives in git and `tasks.md`, not in the conversation, so it can always be rebuilt. |
| Tool drift | The OpenSpec version lives in one place (`.claude/devflow.env`). A bare `openspec` command is rewritten to the pinned `npx` call; `check.sh` and CI read the same value. | One source of truth; nothing for local and CI to disagree about. |

## Design decisions

- **Plugin plus template, not one or the other.** Behavior (hooks, skills) changes over
  time and should update everywhere at once: that's the plugin. Files a project owns and
  edits (`CLAUDE.md`, CI, `check.sh`) can't come from a plugin, which also can't ship
  permissions or a `CLAUDE.md`: that's the copier template, and `copier update` brings
  template fixes into existing projects.
- **Deny, ask, allow.** When one command contains several parts, the strictest decision
  wins (deny > ask > allow). "Ask" hands the decision to you instead of guessing, which
  keeps false positives cheap.
- **Commands are parsed, not grepped.** The guards tokenize with `shlex` and unwrap
  `bash -c`, `eval`, `env`/`sudo`/`timeout`, `uv run`/`poetry run`, `$(…)` and
  `git -C/-c`. A regex on the raw string misses `git -c core.hooksPath=/dev/null commit`
  or `git push origin +main`; both bypassed an earlier hand-written setup.
- **Fail open, visibly.** If a guard itself crashes, the command goes through with a
  visible error instead of locking the session. The guards protect against accidents;
  the GitHub ruleset is the hard boundary, so failing open never removes the last line.
- **The tests-first red state is allowed.** The first task group writes failing tests on
  purpose. The Stop hook blocks on red, except when only test files changed; then it
  reports instead of blocking.
- **The Stop hook sees committed work.** devflow commits after every task group, which
  leaves a clean tree. A hook that only checked uncommitted files would skip the tests
  exactly when they matter, so `turn_start` records `HEAD` at the start of each turn and
  the Stop hook also checks what was committed since.
- **One script for local and CI.** `check.sh` is the full gate list, and CI runs the same
  file. A clean tree that passed gets stamped, so landing doesn't rerun identical checks;
  CI never uses the stamp.
- **Merge commits only.** Each task group is a commit; squashing would erase that record of
  how the change was built. Rebase and force-push are denied because they rewrite shared
  history.
- **Config is data.** `.claude/devflow.env` is parsed as `KEY=VALUE` and never executed, so
  a config file can't run code inside a hook.
- **No runtime dependencies.** Python 3.8+ standard library only, no `jq` or GNU tools, so
  the hooks work wherever Claude Code does. A startup check warns if `python3` is missing,
  so the guards are never off silently.
- **The rules are tested.** 229 tests (about 180 command-decision rows plus protocol,
  template and `check.sh` tests) run in CI on Python 3.10 and 3.12. Every bypass found in
  review became a test, so it can't quietly come back.
- **Observable.** Every deny and ask is appended to `.claude/gate-events.jsonl`, so rules
  that fire falsely can be found and tuned instead of guessed at.

## When to use it

Use it for:

- Projects you will work on for more than a few sessions, where a broken `main`, a lost
  branch or an unplanned dependency would cost real time.
- Public repositories, where a pushed secret or a messy history is visible.
- Projects with cloud resources or paid APIs, where an unapproved deploy costs money.
- Solo work where you want team-grade discipline (planning, review gates, protected
  `main`) without a team to provide it.
- Portfolio projects, where the commit history, the specs and the PRs are part of what
  gets read.

Small fixes don't need the full loop: branch, fix, PR. `check.sh --land` only requires an
archived change when the branch has one.

## When not to use it

- Throwaway scripts, spikes and experiments: the plan-first loop and the confirmations
  slow down work whose point is to be fast and disposable.
- Repos that already have their own enforced process (a team's CI, review rules, release
  flow): add only the pieces that fill a gap, or adapt the guards to that process.
- Machines without `python3`: the startup check warns, but the guards won't run.
- When you need a hard security boundary against a hostile agent: devflow isn't one (see
  below). Use the sandbox, containers and restricted credentials for that.

## Limitations

- **Guardrails, not a sandbox.** The guards see the command line, not what a program does
  afterwards. A script that calls `git push --force` from inside Python is not caught. The
  GitHub ruleset still rejects the push, which is why it, not the hook, is the authority.
  The opt-in Bash sandbox narrows this further.
- **Tests-first is encouraged, not enforced per edit.** The Stop hook, the task rules and
  the weakened-test scan make skipping tests visible; tools like
  [tdd-guard](https://github.com/nizos/tdd-guard) block each implementation edit that has
  no failing test, at the cost of more friction.
- **Single-developer defaults.** The ruleset requires a PR and green CI but zero approving
  reviews. A team would raise that and add CODEOWNERS.
- **Pattern-based rules need tuning.** New tools and command shapes appear; the event log
  and the test suite are how the rules keep up.

## Cost of using it

- A few confirmations per change (dependency installs, merges, deploys). That is the
  point, but during initial scaffolding it's tedious: the README explains how to switch
  off the dependency-file prompts temporarily.
- The Stop hook adds the fast test run to the end of every turn that changed code, so the
  fast suite has to stay fast.
- OpenSpec artifacts take a few minutes per change to review. In return, the reviews
  happen before the code.
