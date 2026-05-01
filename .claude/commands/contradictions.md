---
description: List unresolved contradictions across the vault and (optionally) help resolve them.
allowed-tools: Read, Edit, Grep
---

Find every memory file that has a `CONTRADICTION detected` block (added by the
consolidate flow when new info conflicts with existing). For each one, present
the conflict in plain language and offer a resolution path.

Vault path: `C:\Users\rjain.TECHNIJIAN\OneDrive - Technijian, Inc\Documents\obsidian\annual-client-review\`

## Steps

1. Grep `memory/*.md` for `CONTRADICTION detected`. For each match:
   - File name + topic name from frontmatter
   - The existing fact (from `## Key facts` or `## Summary`)
   - The new contradicting claim (from `## Open questions`)
   - Date the contradiction was recorded
   - Current `confidence` field
2. Present them as a numbered list. For each, propose:
   - **Keep existing** — the new claim was wrong; remove the contradiction block, restore confidence.
   - **Replace with new** — the existing fact was wrong; overwrite, log as `[replaced]` in CHANGELOG.
   - **Both true (refine)** — they're talking about different cases; rewrite the file to make the distinction clear.
   - **Defer** — leave it; we don't have enough info yet.
3. Apply user's decisions. For each applied resolution:
   - Edit the file body (remove the contradiction block; rewrite content as needed).
   - Adjust `confidence` field appropriately.
   - Append to CHANGELOG with the right prefix (`[reorg]`, `[replaced]`, `[manual]`).
4. Commit to vault git: `git -C "<vault>" add -A && git -C "<vault>" commit -m "[reorg] resolved N contradiction(s)"`.

If no contradictions exist, say "No unresolved contradictions" and stop.
