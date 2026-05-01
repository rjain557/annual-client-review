# Stop hook — preference-shaped statement detector.
#
# Scans the current transcript for sentences shaped like preferences
# ("I prefer", "always", "don't ever", "never") and writes a one-line
# notice to the retrieval log so the next /cc-review can prompt for
# explicit save. We do NOT auto-write to preferences.md — preferences
# should feel intentional, per the bootstrap spec.
#
# Speed budget: < 2 seconds. Never blocks the session.

$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\_lib.ps1"

try {
  $payload = Read-HookInput
  if (-not $payload) { exit 0 }
  $transcriptPath = $payload.transcript_path
  if (-not $transcriptPath -or -not (Test-Path -LiteralPath $transcriptPath)) { exit 0 }

  # Read the last ~20KB of the transcript — that's where the most recent
  # human turn lives. Don't try to parse the JSONL fully; just text-scan.
  $bytes = (Get-Item -LiteralPath $transcriptPath).Length
  $offset = [math]::Max(0, $bytes - 20000)
  $tail = Get-Content -LiteralPath $transcriptPath -Raw -Encoding UTF8
  if ($offset -gt 0) { $tail = $tail.Substring($offset) }

  # Look for "user" turns whose content contains a preference-shaped phrase.
  # Match patterns are intentionally narrow to avoid false positives.
  $patterns = @(
    'I (?:prefer|like|want|hate|love|always|never)\s+\w',
    "don't (?:ever\s+)?(?:do|use|run|call|write|create|edit|modify|delete|push|commit|merge)\b",
    'always\s+(?:use|prefer|do|run|call|write|create)\b',
    'never\s+(?:use|do|run|call|write|create|edit|modify|delete|push|commit|merge)\b',
    'from now on\b',
    'going forward\b'
  )

  $hits = @()
  foreach ($p in $patterns) {
    $m = [regex]::Matches($tail, $p, [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
    foreach ($x in $m) { $hits += $x.Value }
  }

  if ($hits.Count -eq 0) { exit 0 }

  # Log the detection so /cc-review can surface it later. Do NOT modify preferences.md.
  Write-RetrievalLog -Entry @{
    event = 'preference_signal'
    note = 'preference-shaped statement detected; consider explicit save to memory/preferences.md'
    samples = ($hits | Select-Object -First 3)
  }
}
catch {
  # Defensive: never crash the session.
}
exit 0
