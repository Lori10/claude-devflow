---
name: verify
description: Verify finished work before calling it done. Runs every offline gate (lint, tests, openspec validate, secrets, weakened-test scan), reads the diff against the plan, and reports PASS/FAIL with evidence. Use after an /opsx:apply task group, after any code change, and before /devflow:land-branch.
---

# Verify

"Done" means the gates ran and their results are stated, not that tests look green.

1. Run the project's check script from the repo root: `DEVFLOW_CHECK_CMD` in
   `.claude/devflow.env` (default `scripts/check.sh`). CI runs the same script. If a
   service it needs is down, say so; never report PASS for gates that didn't run.
2. Read the diff: `git diff $(git merge-base origin/<protected> HEAD)` plus `git status`
   for uncommitted work. If the branch has an OpenSpec change
   (`openspec/changes/<name>/tasks.md`), check the files its tasks name first, then list
   every changed file **outside** the plan and say why it changed.
3. If the weakened-test scan prints REVIEW, read each hunk and decide with
   [reference.md](reference.md). A weakened test is a FAIL unless the change's delta spec
   changed that behaviour.
4. Report:
   ```
   VERIFY: PASS|FAIL
   - lint: …  - tests: N passed, M skipped  - openspec validate: …  - secrets: …
   - weakened tests: none|<list + verdict>
   - out-of-plan files: none|<list + reason>
   ```
   Quote the failing output tail for any FAIL.
5. For non-trivial changes, suggest `/code-review` and a cold review by a fresh sub-agent
   that didn't write the code. Never run live or billed checks here; the user runs or
   approves them.
