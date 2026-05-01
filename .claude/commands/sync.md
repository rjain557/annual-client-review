---
description: Manually trigger a full vault sync — commit any uncommitted vault changes and regenerate HEALTH.md.
allowed-tools: Bash, Read, Edit
---

Force a vault sync: commit any dirty vault files and refresh the health dashboard.

Vault path: `C:\Users\rjain.TECHNIJIAN\OneDrive - Technijian, Inc\Documents\obsidian\annual-client-review\`

## Steps

1. Run `git -C "<vault>" status --porcelain` to list uncommitted changes.
   - If clean: report "Vault is already clean — nothing to sync." and stop.

2. Show the user a summary of what will be committed (files changed, added, deleted).

3. Run the health-check hook to regenerate `memory/HEALTH.md` before committing:
   ```
   pwsh -NonInteractive -File "D:\vscode\annual-client-review\annual-client-review\.claude\hooks\health-check.ps1"
   ```
   (This also updates `memory/CHANGELOG.md` with a `[health]` entry.)

4. Stage and commit all vault changes:
   ```
   git -C "<vault>" add -A
   git -C "<vault>" commit -m "[sync] <today> manual vault sync"
   ```

5. Report the commit hash and a one-line summary of what was synced.

## When to use

- After editing memory files directly in Obsidian and wanting Claude to pick up the changes
- After a long session where the Stop hook may have been skipped
- Before a `/graduate` check to ensure HEALTH.md is fresh
- Any time `git status` in the vault shows unexpected drift

## Notes

- OneDrive syncs the vault files automatically; this command handles **git versioning**, not file sync.
- If you want to sync after every session automatically, the Stop hook (`consolidate.ps1`) does this for memory/ and Knowledge/ changes. This command is for manual, full-vault syncs.
