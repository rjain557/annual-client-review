# SessionEnd hook — recompute vault HEALTH metrics, write HEALTH.md,
# and surface a warning if the weekly review is overdue.
#
# Speed budget: < 5 seconds. Never blocks the session.

$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\_lib.ps1"

try {
  if (-not (Test-VaultReachable)) { exit 0 }

  $files = Get-ChildItem $script:MemoryDir -Filter '*.md' | Where-Object { $_.Name -notin @('MEMORY.md','CHANGELOG.md','HEALTH.md') -and -not $_.Name.StartsWith('_') }
  $knowledgeFiles = if (Test-Path $script:KnowledgeDir) { Get-ChildItem $script:KnowledgeDir -Filter '*.md' } else { @() }

  $now = Get-Date
  $stale60 = 0; $stale180 = 0
  $volStable = 0; $volEvolving = 0; $volEphemeral = 0
  $totalAccess = 0; $neverAccessed = 0; $hot = 0
  $maxLines = 0; $maxFile = ''; $totalLines = 0

  foreach ($f in $files) {
    $fm = Get-MemoryFrontmatter -Path $f.FullName
    $lines = (Get-Content -LiteralPath $f.FullName).Count
    $totalLines += $lines
    if ($lines -gt $maxLines) { $maxLines = $lines; $maxFile = $f.Name }

    $age = ($now - $f.LastWriteTime).TotalDays
    if ($age -gt 60)  { $stale60++ }
    if ($age -gt 180) { $stale180++ }

    if ($fm) {
      switch ($fm['volatility']) {
        'stable'    { $volStable++ }
        'evolving'  { $volEvolving++ }
        'ephemeral' { $volEphemeral++ }
        default     { $volEvolving++ }
      }
      $ac = 0
      try { $ac = [int]$fm['access_count'] } catch {}
      $totalAccess += $ac
      if ($ac -eq 0) { $neverAccessed++ }
      if ($ac -ge 10) { $hot++ }
    } else {
      $volEvolving++
      $neverAccessed++
    }
  }

  # Reconcile MEMORY.md vs files on disk.
  $indexPath = Join-Path $script:MemoryDir 'MEMORY.md'
  $orphans = 0; $phantoms = 0
  if (Test-Path $indexPath) {
    $idxText = Get-Content -Raw -LiteralPath $indexPath
    foreach ($f in $files) {
      if ($idxText -notmatch [regex]::Escape($f.Name)) { $orphans++ }
    }
    $referenced = [regex]::Matches($idxText, '\(([a-z_0-9.]+\.md)\)') | ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique
    $onDisk = $files | ForEach-Object { $_.Name }
    foreach ($r in $referenced) { if ($onDisk -notcontains $r) { $phantoms++ } }
  }

  # Retrieval log — last 30 days.
  $attempts = 0; $hits = 0
  if (Test-Path $script:RetrievalLogPath) {
    $cutoff = (Get-Date).AddDays(-30)
    $logLines = Get-Content -LiteralPath $script:RetrievalLogPath
    foreach ($ln in $logLines) {
      try {
        $e = $ln | ConvertFrom-Json
        if ($e.event -ne 'retrieval') { continue }
        if ($e.ts) {
          try { $ts = [datetime]$e.ts } catch { $ts = $now }
          if ($ts -lt $cutoff) { continue }
        }
        $attempts++
        if ($e.matched_count -gt 0) { $hits++ }
      } catch {}
    }
  }
  $hitRate = if ($attempts -gt 0) { [math]::Round(($hits / $attempts) * 100, 1) } else { 'reconstructing' }
  $missRate = if ($attempts -gt 0) { [math]::Round((($attempts - $hits) / $attempts) * 100, 1) } else { 'reconstructing' }

  # Days since last /cc-review (read existing HEALTH.md).
  $daysSince = Get-DaysSinceReview
  $reviewLine = if ($daysSince -ge 999) { 'never' } else { "$daysSince days ago" }
  $nextDue = (Get-Date).AddDays([math]::Max(7 - $daysSince, 1)).ToString('yyyy-MM-dd')

  # Classification.
  $classification = 'GREEN'
  $reasons = @()
  if ($files.Count -gt 400) { $classification = 'RED'; $reasons += "topic count > 400 ($($files.Count))" }
  elseif ($files.Count -ge 150) { if ($classification -eq 'GREEN') { $classification = 'YELLOW' }; $reasons += "topic count 150-400 ($($files.Count))" }
  if ($attempts -ge 30) {
    $hr = [double]$hitRate
    if ($hr -lt 50) { $classification = 'RED'; $reasons += "hit rate < 50% ($hr%)" }
    elseif ($hr -lt 70) { if ($classification -eq 'GREEN') { $classification = 'YELLOW' }; $reasons += "hit rate 50-70% ($hr%)" }
  }
  if ($files.Count -gt 0) {
    $stalePct = [math]::Round(($stale180 / $files.Count) * 100, 1)
    if ($stalePct -gt 25) { $classification = 'RED'; $reasons += "stale-180 > 25% ($stalePct%)" }
    elseif ($stalePct -ge 10) { if ($classification -eq 'GREEN') { $classification = 'YELLOW' }; $reasons += "stale-180 10-25% ($stalePct%)" }
  }
  if ($daysSince -gt 30) { $classification = 'RED'; $reasons += "review overdue ($daysSince days)" }
  elseif ($daysSince -gt 14) { if ($classification -eq 'GREEN') { $classification = 'YELLOW' }; $reasons += "review overdue ($daysSince days)" }
  elseif ($daysSince -gt 7) { $reasons += "review due ($daysSince days since last run)" }

  $today = (Get-Date -Format 'yyyy-MM-dd')

  # Build HEALTH.md.
  $health = @"
# Vault Health

> Auto-updated by ``health-check.ps1`` on SessionEnd. Last run: $today.

---

## Weekly Review Status

- **Last ``/cc-review`` run:** $reviewLine
- **Days since last review:** $daysSince
- **Unresolved contradictions:** (run ``/contradictions`` to enumerate)
- **Topics edited this week:** (see ``CHANGELOG.md``)
- **Next review due:** $nextDue

If days-since-review > 14, this hook prints a warning. If > 30, ``/graduate`` will refuse to give a recommendation until you run ``/cc-review``.

---

## Status: $classification

$(if ($reasons.Count -gt 0) { "Reasons: " + ($reasons -join '; ') } else { 'All thresholds within green band.' })

---

## Size

| Metric | Value |
|---|---|
| Topic files in ``memory/`` | $($files.Count) |
| Long-form notes in ``Knowledge/`` | $($knowledgeFiles.Count) |
| Total lines (memory) | $totalLines |
| Largest topic | $maxLines lines (``$maxFile``) |
| Files exceeding 2000 lines | $(@($files | Where-Object { (Get-Content -LiteralPath $_.FullName).Count -gt 2000 }).Count) |

## Retrieval quality (last 30 days)

| Metric | Value |
|---|---|
| Retrieval attempts | $attempts |
| Hit rate | $hitRate$(if ($hitRate -ne 'reconstructing') { '%' }) |
| Miss rate | $missRate$(if ($missRate -ne 'reconstructing') { '%' }) |
| Never-accessed topics | $neverAccessed of $($files.Count) |
| Hot topics (>=10 accesses) | $hot |

## Freshness

| Metric | Value |
|---|---|
| Stale > 60 days | $stale60 |
| Stale > 180 days | $stale180 |
| Orphans (file without index entry) | $orphans |
| Phantoms (index entry without file) | $phantoms |

## Volatility distribution

| Level | Count |
|---|---:|
| ``stable`` | $volStable |
| ``evolving`` | $volEvolving |
| ``ephemeral`` | $volEphemeral |

---

## Classification thresholds

GREEN — all of: topic count < 150 · hit rate > 70% · miss rate < 15% · stale-180 < 10%
YELLOW — any of: topic count 150-400 · hit rate 50-70% · miss rate 15-30% · stale-180 10-25% · dead-weight > 30%
RED — any of: topic count > 400 · hit rate < 50% · miss rate > 30% · stale-180 > 25%
"@

  Set-Content -LiteralPath $script:HealthPath -Value $health -NoNewline -Encoding UTF8

  # Commit health update (will be a no-op if no metric changed).
  [void](Invoke-VaultGit -GitArgs @('add', 'memory/HEALTH.md'))
  [void](Invoke-VaultGit -GitArgs @('commit','-m', "[health] $today auto-update", '--quiet'))

  # Print review-overdue banner to user.
  if ($daysSince -ge 30) {
    Write-Output ""
    Write-Output "================================================================="
    Write-Output "  VAULT REVIEW IS OVERDUE ($daysSince days). HEALTH metrics may be"
    Write-Output "  unreliable. /graduate will refuse until you run /cc-review."
    Write-Output "================================================================="
  } elseif ($daysSince -ge 21) {
    Write-Output ""
    Write-Output "WARNING: vault review overdue ($daysSince days). Run /cc-review."
  } elseif ($daysSince -ge 14) {
    Write-Output ""
    Write-Output "Vault review is overdue ($daysSince days). Please run /cc-review soon."
  } elseif ($daysSince -ge 7) {
    Write-Output ""
    Write-Output "Reminder: weekly /cc-review is due (last run: $reviewLine)."
  }
}
catch {
  # Defensive: never crash the session.
}
exit 0
