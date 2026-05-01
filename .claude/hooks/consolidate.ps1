# Stop hook — vault bookkeeping after a session turn.
#
# This hook does NOT call an LLM and cannot author topic pages on its own.
# Authoring happens during the conversation (Claude writes via the Write/Edit
# tools per existing convention). The hook's job is the bookkeeping the LLM
# can't reliably do at the end of every turn:
#
#   1. Detect newly-added or modified files in `memory/` or `Knowledge/`
#      since the last commit and commit them with `[consolidate]` prefix.
#   2. Detect orphans (files on disk but missing from MEMORY.md) and append
#      a notice to CHANGELOG.md so the next /cc-review surfaces them.
#   3. If a file in `memory/` was modified, append a CHANGELOG entry.
#
# Speed budget: < 5 seconds. Never blocks the session.

$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\_lib.ps1"

try {
  if (-not (Test-VaultReachable)) { exit 0 }

  # Use git to see what's pending in the vault.
  $statusOut = Invoke-VaultGit -GitArgs @('status','--porcelain')
  if (-not $statusOut) { exit 0 }

  # Filter to memory/ + Knowledge/ + MEMORY.md changes only.
  $vaultChanges = @($statusOut | Where-Object { $_ -match '^.{2}\s+(memory/|Knowledge/)' })
  if ($vaultChanges.Count -eq 0) { exit 0 }

  $today = (Get-Date -Format 'yyyy-MM-dd')

  # Detect orphans: files in memory/ not referenced from MEMORY.md.
  $memoryFiles = Get-ChildItem $script:MemoryDir -Filter '*.md' | Where-Object { $_.Name -notin @('MEMORY.md','CHANGELOG.md','HEALTH.md') -and -not $_.Name.StartsWith('_') }
  $memoryIndex = ''
  $indexPath = Join-Path $script:MemoryDir 'MEMORY.md'
  if (Test-Path $indexPath) { $memoryIndex = Get-Content -Raw -LiteralPath $indexPath }
  $orphans = @($memoryFiles | Where-Object { $memoryIndex -notmatch [regex]::Escape($_.Name) })

  # Build a CHANGELOG entry covering this turn's vault changes.
  $changelogLines = @()
  $changelogLines += ""
  $changelogLines += "## $today"
  $changelogLines += ""
  foreach ($ln in $vaultChanges) {
    if ($ln -match '^\s*([?MADRC]+)\s+(.+)$') {
      $code = $matches[1].Trim()
      $path = $matches[2].Trim()
      $verb = switch -Regex ($code) {
        '\?\?' { 'added (untracked)' }
        'A'    { 'added' }
        'M'    { 'modified' }
        'D'    { 'deleted' }
        'R'    { 'renamed' }
        default { $code }
      }
      $changelogLines += "- $today [consolidate] **$path** — $verb during session"
    }
  }
  if ($orphans.Count -gt 0) {
    foreach ($o in $orphans) {
      $changelogLines += "- $today [orphan] **memory/$($o.Name)** — exists on disk, missing from MEMORY.md (will be surfaced in /cc-review)"
    }
  }

  # Append to CHANGELOG.md
  $clText = ($changelogLines -join "`n") + "`n"
  Add-Content -LiteralPath $script:ChangelogPath -Value $clText -Encoding UTF8

  # Stage everything and commit.
  [void](Invoke-VaultGit -GitArgs @('add','-A','memory/','Knowledge/'))
  $msg = "[consolidate] $today vault changes (" + $vaultChanges.Count + " file(s)" + $(if ($orphans.Count -gt 0) { ", $($orphans.Count) orphan(s)" } else { '' }) + ")"
  [void](Invoke-VaultGit -GitArgs @('commit','-m', $msg, '--quiet'))
}
catch {
  # Defensive: never crash the session.
  try { Add-Content -LiteralPath $script:ChangelogPath -Value "- $(Get-Date -Format 'yyyy-MM-dd') [error] consolidate hook failed: $($_.Exception.Message)" -Encoding UTF8 } catch {}
}
exit 0
