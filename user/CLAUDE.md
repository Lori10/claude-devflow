# Personal defaults (all projects)

Copy to `~/.claude/CLAUDE.md`. A project's own CLAUDE.md wins where they differ.

## Working style
- Spec before code for anything non-trivial: if the project uses OpenSpec, propose first and wait for my approval of the artifacts.
- Tests first: write the failing test from the requirement, then implement. Never weaken, skip or delete an existing test to get green unless the spec changed; say so explicitly if you think a test is wrong.
- "Done" means the checks ran and you state their results. Don't report success for checks that didn't run.
- Ask before adding, removing or upgrading a dependency.
- Live, billed or cloud-changing actions (deploys, paid API runs, evals) need my explicit go-ahead each time.

## Git
- Never work on the protected branch; branch as `feat/…`, `fix/…`, `chore/…`, `docs/…`.
- Conventional commit messages (`feat: …`, `fix: …`, `chore: …`, `docs: …`, `test: …`).
- No `Co-Authored-By: Claude` trailer on commits and no "Generated with Claude Code" line in PRs.
- Merge commits via PR only; no rebase, squash or force-push unless I ask.
