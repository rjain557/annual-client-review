---
description: Show the current vault HEALTH.md dashboard plus recent CHANGELOG entries.
allowed-tools: Read, Bash
---

Read the vault HEALTH.md and CHANGELOG.md and present a compact dashboard.

Vault path: `C:\Users\rjain.TECHNIJIAN\OneDrive - Technijian, Inc\Documents\obsidian\annual-client-review\`

1. Read `memory/HEALTH.md` — show the **Status**, **Weekly Review Status**, **Size**, **Retrieval quality**, **Freshness**, and **Volatility distribution** sections (skip the threshold reference at the bottom).
2. Read the last ~30 lines of `memory/CHANGELOG.md` — list the most recent vault mutations.
3. Run `git -C "<vault>" log -5 --oneline` and show the last 5 commits.
4. End with a one-line recommendation:
   - GREEN + days-since-review < 7 → "Vault healthy. No action needed."
   - GREEN but review > 7 days → "Vault healthy. Run /cc-review."
   - YELLOW → "Vault drift detected. Run /cc-review and address flagged items."
   - RED → "Vault needs attention. Run /cc-review immediately, then /graduate."

Do not modify any files. Read-only command.
