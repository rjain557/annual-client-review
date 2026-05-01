---
description: Assess vault health and recommend whether to stay, clean up, or upgrade the memory stack. Refuses if review is overdue (>30 days).
allowed-tools: Read, Bash
---

Check the vault's current health classification and give a go/no-go recommendation.

Vault path: `C:\Users\rjain.TECHNIJIAN\OneDrive - Technijian, Inc\Documents\obsidian\annual-client-review\`

## Steps

1. Read `memory/HEALTH.md`. Extract:
   - **Status** line (GREEN / YELLOW / RED)
   - **Days since last review** (from Weekly Review Status section)
   - **Stale topics** count (stale-60, stale-180)
   - **Unresolved contradictions** count
   - **Prune candidates** count

2. Guard: if days-since-review > 30, stop and say:
   > Review is **N days overdue**. Run `/cc-review` first, then re-run `/graduate`.

3. Map status to recommendation:

   **GREEN** (days-since-review ≤ 7, stale ≤ 5, contradictions = 0):
   > Vault is healthy. No action needed. Come back after your next `/cc-review`.

   **YELLOW** (any of: days-since-review 8–14, stale 6–15, contradictions 1–3, prune candidates > 5):
   > Vault has drift. Recommended actions before next milestone:
   > - Run `/cc-review` to address flagged items
   > - Resolve open contradictions with `/contradictions`
   > - Prune dead-weight topics (access_count=0, age>30d)
   > Then re-run `/graduate` to confirm GREEN.

   **RED** (any of: days-since-review > 14, stale > 15, contradictions > 3):
   > Vault needs attention before trusting its outputs.
   > 1. Run `/cc-review` immediately
   > 2. Run `/contradictions` and resolve all flagged items
   > 3. Archive prune candidates
   > 4. Re-run `/graduate` — must reach GREEN before relying on retrieval for decisions.

4. Always end with a one-line status stamp:
   `Graduate check: <STATUS> as of <today>. Next /cc-review due: <last_review + 7 days>.`

Do not modify any files. Read-only command.
