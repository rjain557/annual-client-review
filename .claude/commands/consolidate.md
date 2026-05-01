---
description: Manually consolidate the current session — write/update topic files in the vault for any durable knowledge that emerged.
allowed-tools: Read, Write, Edit, Glob, Grep, Bash
---

Look back at the current conversation and decide whether anything durable
should be saved to the vault. The Stop hook handles bookkeeping; this command
is for **explicit, on-demand consolidation** when the user says "save this".

Vault path: `C:\Users\rjain.TECHNIJIAN\OneDrive - Technijian, Inc\Documents\obsidian\annual-client-review\`

## Decide what to save

For each candidate piece of knowledge:

- **Compatible with existing memory** → update the matching topic file in `memory/`.
- **New topic** → create a new file under `memory/` using the existing naming convention:
  - `feedback_<slug>.md` for rules / corrections / "always do X" / "never do Y"
  - `project_<slug>.md` for active state, ongoing initiatives, recent decisions
  - `reference_<slug>.md` for stable facts, API quirks, system invariants
  - `user_<slug>.md` for user-specific facts (role, preferences, signature)
  - Distilled long-form notes go in `Knowledge/<slug>.md` (no frontmatter; plain markdown)
- **Contradicting existing memory** → DO NOT overwrite. Append to the existing
  file's body under a `## Open questions` section: `CONTRADICTION detected on
  <today>: existing says X, new session says Y. Resolve.` Lower the file's
  `confidence` field one step (high → medium → low). Note in CHANGELOG with
  `[contradiction]` prefix.
- **Preferences** ("I prefer", "always", "from now on") → append to
  `memory/preferences.md` (create if missing) with a one-line bullet plus the
  reason. Ask the user to confirm before writing.
- **Trivial / procedural / one-off** → don't save.

## Required frontmatter for new memory/ files

```yaml
---
name: <short topic name>
description: <one-line description used by retrieval ranking — be specific>
type: <feedback|project|reference|user>
last_updated: <YYYY-MM-DD>
volatility: <stable|evolving|ephemeral>
access_count: 0
last_accessed: <YYYY-MM-DD>
confidence: <high|medium|low>
aliases: []
sources: [<originSessionId or session date>]
---
```

Volatility default by type: `feedback`/`reference`/`user` → `stable`,
`project` → `evolving`, "current state of X" snapshots → `ephemeral`.

## After writing

1. If a new file was created, add a one-line entry to `memory/MEMORY.md` under
   the appropriate section header.
2. Append to `memory/CHANGELOG.md`: `<today> [consolidate] <file> — <what changed>`.
3. The Stop hook will commit the vault. If you want a commit immediately, run
   `git -C "<vault>" add -A && git -C "<vault>" commit -m "[consolidate] <summary>"`.

End with a one-line summary: what was saved, what was skipped, and why.
