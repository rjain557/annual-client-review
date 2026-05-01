---
description: Weekly vault review — surface new/updated topics, contradictions, volatility candidates, and prune candidates. Apply approved decisions and stamp the review date.
allowed-tools: Read, Edit, Glob, Grep, Bash
---

Run the weekly vault review. Target time: 5–10 minutes of human attention.

Vault path: `C:\Users\rjain.TECHNIJIAN\OneDrive - Technijian, Inc\Documents\obsidian\annual-client-review\`

## What to do

1. **Read** `memory/HEALTH.md` and the last 7 days of `memory/CHANGELOG.md`.
2. **Compute** these lists by reading the vault directly:
   - **New topics this week** — files in `memory/` whose `last_updated` is within the last 7 days AND whose path appears for the first time in CHANGELOG. Show name + one-line description from frontmatter.
   - **Updated topics this week** — files modified in last 7 days that aren't new. Spot-check 3 for accuracy.
   - **Unresolved contradictions** — `grep -l "CONTRADICTION detected" memory/*.md`. Read each, present the conflict.
   - **Volatility candidates to review:**
     - `stable` topics modified in the last 7 days (might actually be `evolving`)
     - `evolving` topics whose `last_updated` is older than 60 days (might be `stable`)
     - Any `evolving` topic that's a "current state of X" snapshot (might be `ephemeral`)
   - **Ephemerals approaching 60-day archive deadline** — `volatility: ephemeral` AND `last_accessed` > 50 days ago.
   - **Prune candidates** — `access_count: 0` AND age > 30 days. (After 30 days, never-accessed = dead weight.)
   - **Preference signals from the log** — `grep "preference_signal" memory/.retrieval-log.jsonl | tail -10`. Surface for explicit save.
3. **Present everything as a numbered checklist** with topic links. For each item, propose an action: "keep", "promote to stable", "demote to ephemeral", "archive", "merge with X", "resolve contradiction", "add to preferences.md".
4. **Wait for the user to approve specific items** ("apply 1, 3, 5, skip the rest").
5. **Apply the approved actions:**
   - Volatility changes: edit frontmatter `volatility:` field.
   - Archive: move to `memory/_archive/<filename>` and remove from MEMORY.md.
   - Preference saves: append to `memory/preferences.md` (create the file if missing — use a simple frontmatter `name: User Preferences\ntype: preferences\nlast_updated: <today>\nvolatility: stable`, then bullet list).
   - Contradiction resolutions: edit the affected file, remove the `CONTRADICTION detected` block, optionally bump `confidence` back up.
6. **Stamp the review date** — edit `memory/HEALTH.md` so the **Last `/cc-review` run** field shows today's ISO date. Update **Days since last review** to 0 and **Next review due** to today + 7 days.
7. **Append a CHANGELOG entry** — `<today> [reorg] /cc-review applied: <N decisions, brief summary>`.
8. **Commit to vault git** — `git -C "<vault>" add -A && git -C "<vault>" commit -m "[reorg] <today> weekly review"`.
9. **Final report** — what was done, what's left, when next review is due.

## Notes

- Be tight. The whole pass should fit on one screen for the user.
- If the user is in a hurry, accept "approve all" and apply everything.
- Never delete files — archive only.
- If there's nothing to review (fresh install with no week of data), say so plainly and stamp the review anyway so the cadence starts.
