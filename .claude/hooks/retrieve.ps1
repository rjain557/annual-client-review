# UserPromptSubmit hook — vault retrieval.
# Reads the user's prompt, scores memory + Knowledge files by keyword match,
# emits relevant file paths as system context, increments access counters,
# logs to .retrieval-log.jsonl, and ALWAYS surfaces preferences.md.
#
# Speed budget: < 2 seconds. Falls back silently if anything goes wrong.

$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\_lib.ps1"

try {
  $payload = Read-HookInput
  $prompt = if ($payload -and $payload.prompt) { $payload.prompt } else { '' }
  if ([string]::IsNullOrWhiteSpace($prompt)) { exit 0 }
  if (-not (Test-VaultReachable)) { exit 0 }

  # Tokenize the prompt: lowercase alphanumeric, drop short/stop words.
  $stop = @{}
  foreach ($w in 'the','a','an','and','or','but','if','then','for','of','to','in','on','at','by','with','from','is','are','was','were','be','been','being','do','does','did','have','has','had','will','would','should','can','could','may','might','i','you','we','they','it','this','that','these','those','my','your','our','their','what','when','where','why','how','please','also','still','need','want') { $stop[$w] = $true }
  $tokens = ([regex]::Matches($prompt.ToLower(), '[a-z0-9_]{3,}')) | ForEach-Object { $_.Value } | Where-Object { -not $stop.ContainsKey($_) } | Select-Object -Unique

  if ($tokens.Count -eq 0) { exit 0 }

  # Score memory files (typed) and Knowledge files (long-form notes).
  $candidates = @()
  $candidates += Get-ChildItem $script:MemoryDir -Filter '*.md' | Where-Object { $_.Name -notin @('MEMORY.md','CHANGELOG.md','HEALTH.md') -and -not $_.Name.StartsWith('_') }
  if (Test-Path $script:KnowledgeDir) { $candidates += Get-ChildItem $script:KnowledgeDir -Filter '*.md' }

  $scored = @()
  foreach ($f in $candidates) {
    $fm = Get-MemoryFrontmatter -Path $f.FullName
    $haystack = $f.BaseName
    if ($fm) {
      if ($fm.Contains('name')) { $haystack += " " + $fm['name'] }
      if ($fm.Contains('description')) { $haystack += " " + $fm['description'] }
      if ($fm.Contains('aliases')) { $haystack += " " + $fm['aliases'] }
    }
    $haystack = $haystack.ToLower()
    $score = 0
    foreach ($t in $tokens) { if ($haystack.Contains($t)) { $score++ } }
    if ($score -gt 0) { $scored += [pscustomobject]@{ Path = $f.FullName; Name = $f.Name; Folder = $f.Directory.Name; Score = $score; Frontmatter = $fm } }
  }

  $top = $scored | Sort-Object -Property Score -Descending | Select-Object -First 6

  # Always include preferences.md if present.
  $hasPrefs = Test-Path $script:PreferencesPath

  # Emit system context to stdout for Claude to use.
  if ($top.Count -gt 0 -or $hasPrefs) {
    $vaultRel = $script:VaultRoot
    Write-Output ""
    Write-Output "<system-reminder>"
    Write-Output "Vault retrieval matched the prompt. Read these files (via the Read tool) if relevant to the work:"
    Write-Output ""
    foreach ($r in $top) {
      $rel = $r.Path.Substring($vaultRel.Length).TrimStart('\','/')
      $title = if ($r.Frontmatter -and $r.Frontmatter.Contains('name')) { $r.Frontmatter['name'] } else { $r.Name }
      Write-Output ("- ``${rel}`` — ${title} (match score: $($r.Score))")
    }
    if ($hasPrefs) {
      Write-Output ""
      Write-Output ("- ``memory/preferences.md`` — auto-loaded every retrieval")
    }
    Write-Output ""
    Write-Output "Vault root: ``$vaultRel``"
    Write-Output "</system-reminder>"
  }

  # Update access counters on matched files.
  $today = (Get-Date -Format 'yyyy-MM-dd')
  foreach ($r in $top) {
    if (-not $r.Frontmatter) { continue }
    $newCount = 1
    if ($r.Frontmatter.Contains('access_count')) {
      try { $newCount = ([int]$r.Frontmatter['access_count']) + 1 } catch { $newCount = 1 }
    }
    [void](Update-MemoryFrontmatter -Path $r.Path -Updates @{ access_count = $newCount; last_accessed = $today })
  }

  # Log retrieval.
  Write-RetrievalLog -Entry @{
    event = 'retrieval'
    prompt_len = $prompt.Length
    tokens = ($tokens -join ',')
    matched = ($top | ForEach-Object { $_.Name })
    matched_count = $top.Count
  }
}
catch {
  # Defensive: never block the session on a hook failure.
  Write-RetrievalLog -Entry @{ event = 'error'; phase = 'retrieve'; message = $_.Exception.Message }
}
exit 0
