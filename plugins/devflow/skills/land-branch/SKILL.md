---
name: land-branch
description: Land the current feature branch on the protected branch. Commits, verifies (skipping an unchanged tree that already passed), checks the OpenSpec change is archived, pushes, opens or readies the PR, watches CI until green, and merges with a merge commit after explicit user confirmation. Use when a piece of work is ready to land.
---

# Land branch

The protected branch (`DEVFLOW_PROTECTED_BRANCH`, default `main`) is guarded by a GitHub
ruleset (PR + green `checks` job, no bypass), so the merge happens on GitHub, never
locally. Commits and feature-branch pushes need no confirmation; the merge does.

1. `git branch --show-current`. On the protected branch: stop.
2. Commit remaining work with a conventional message (`feat: …`, `fix: …`, `chore: …`,
   `docs: …`). Follow CLAUDE.md for attribution trailers.
3. Run the check script with `--if-stale --land` (default `scripts/check.sh --if-stale --land`):
   - `already verified` means this exact tree passed every gate; go on.
   - `--land` fails while the branch's OpenSpec change is still in `openspec/changes/`.
     Archive it first (`/opsx:archive <name>`, then commit), unless the user explicitly
     says to land without archiving.
   - Any other FAIL: run `/devflow:verify`, fix, repeat. Don't continue on FAIL.
4. `git push -u origin <branch>`, then show what went out:
   `git log --oneline --stat origin/<protected>..HEAD`.
5. Open the PR if none exists: `gh pr create --base <protected> --title "<conventional title>" --body …`.
   For an OpenSpec change, the body summarises its `proposal.md` and links the archived
   change folder. If a draft PR exists, update its body if the plan changed and run
   `gh pr ready`.
6. `gh pr checks --watch --fail-fast`.
   - Red: `gh run view --log-failed`, fix the cause on the branch, commit, push, watch again.
     Never weaken a test, skip a check, or use `--admin` / `--no-verify` to get green.
   - Same failure twice after a fix: stop and show the user the log.
7. Green: show the PR URL and the checks, and ask whether to merge. On approval:
   ```
   gh pr merge --merge --delete-branch
   git switch <protected>
   git pull origin <protected>
   ```
   Merge commit only; no rebase or squash unless the user explicitly asks.
8. Confirm CI on the merge commit: `gh run list --branch <protected> --limit 1`.
