---
name: new-branch
description: Create a feature/fix/chore/docs branch off an up-to-date protected branch, following the devflow git workflow. Use when starting any new piece of work.
---

# New branch

Never start work on the protected branch (`DEVFLOW_PROTECTED_BRANCH` in
`.claude/devflow.env`, default `main`). Branch first: the OpenSpec plan is committed too.

1. `git status`. If there are uncommitted changes, stop and ask the user what to do with
   them. Don't stash, reset or discard on your own.
2. Update the protected branch:
   ```
   git switch <protected>
   git pull origin <protected>
   ```
3. Pick the prefix from the work: `feat/`, `fix/`, `chore/` or `docs/`. For an OpenSpec
   change, name the branch after the change (`feat/add-report-rename`) so the session
   hook and `check.sh --land` can find it. Ask for a name if none was given.
   ```
   git switch -c <prefix>/<name>
   ```
4. Confirm with `git branch --show-current`.
