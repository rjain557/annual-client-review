---
description: Set the volatility level on a topic file (stable | evolving | ephemeral). Usage — /volatility <topic-or-filename> <level>
allowed-tools: Read, Edit, Glob
argument-hint: <topic-or-filename> <stable|evolving|ephemeral>
---

Update the `volatility` field on the specified topic file.

Vault: `C:\Users\rjain.TECHNIJIAN\OneDrive - Technijian, Inc\Documents\obsidian\annual-client-review\memory\`

Arguments: $ARGUMENTS

## Steps

1. Parse the two arguments: topic identifier (filename or topic slug or fuzzy name match), then level (`stable` | `evolving` | `ephemeral`). If less than two args, list valid levels with semantics and ask.
2. Resolve the topic file:
   - If it ends in `.md`, look in `memory/`.
   - Otherwise, glob `memory/*<arg>*.md` and `memory/*$(arg replaced - with _)*.md`. If multiple match, list them and ask which.
   - If none match, search by `name:` field in frontmatter for a fuzzy substring match.
3. Read the file's current frontmatter, edit the `volatility:` line in place. Bump `last_updated` to today.
4. Append CHANGELOG: `<today> [manual] <file> — volatility changed from <old> to <new>`.
5. Commit: `git -C "<vault>" add -A && git -C "<vault>" commit -m "[manual] <today> volatility: <file> -> <new>"`.

## Volatility semantics (remind the user briefly when applying)

- **stable** — yearly review. Architectural decisions, domain invariants, immutable facts. Consolidation is conservative.
- **evolving** — quarterly review (default). Active development state, ongoing concerns. Normal consolidation.
- **ephemeral** — aggressive. Auto-archive after 60 days with no access. Use for "current state of X" snapshots, library workarounds, flaky-test notes.
