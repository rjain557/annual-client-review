# Shared helpers for the annual-client-review memory hooks.
# Dot-source: . "$PSScriptRoot\_lib.ps1"

$script:VaultRoot = 'C:\Users\rjain.TECHNIJIAN\OneDrive - Technijian, Inc\Documents\obsidian\annual-client-review'
$script:MemoryDir = Join-Path $script:VaultRoot 'memory'
$script:KnowledgeDir = Join-Path $script:VaultRoot 'Knowledge'
$script:ChangelogPath = Join-Path $script:MemoryDir 'CHANGELOG.md'
$script:HealthPath = Join-Path $script:MemoryDir 'HEALTH.md'
$script:RetrievalLogPath = Join-Path $script:MemoryDir '.retrieval-log.jsonl'
$script:PreferencesPath = Join-Path $script:MemoryDir 'preferences.md'

function Get-VaultRoot { $script:VaultRoot }
function Get-MemoryDir { $script:MemoryDir }
function Get-KnowledgeDir { $script:KnowledgeDir }

function Read-HookInput {
  # Claude Code passes hook payload as JSON on stdin. Returns $null if empty.
  $raw = [Console]::In.ReadToEnd()
  if ([string]::IsNullOrWhiteSpace($raw)) { return $null }
  try { $raw | ConvertFrom-Json } catch { return $null }
}

function Test-VaultReachable {
  Test-Path -LiteralPath $script:VaultRoot -PathType Container
}

function Write-RetrievalLog {
  param([hashtable] $Entry)
  if (-not (Test-VaultReachable)) { return }
  $Entry['ts'] = (Get-Date -Format 'yyyy-MM-ddTHH:mm:ssK')
  $line = ($Entry | ConvertTo-Json -Compress -Depth 6)
  try { Add-Content -LiteralPath $script:RetrievalLogPath -Value $line -Encoding UTF8 } catch {}
}

function Get-MemoryFrontmatter {
  param([string] $Path)
  $raw = Get-Content -Raw -LiteralPath $Path -ErrorAction SilentlyContinue
  if (-not $raw -or $raw -notmatch '^---\r?\n') { return $null }
  $parts = $raw -split "(?ms)^---\r?\n", 3
  if ($parts.Count -lt 3) { return $null }
  $fm = $parts[1] -replace '(?ms)\r?\n?---\r?\n.*$', ''
  $obj = [ordered]@{}
  foreach ($ln in ($fm -split "`r?`n")) {
    if ($ln -match '^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$') {
      $obj[$matches[1]] = $matches[2]
    }
  }
  return $obj
}

function Update-MemoryFrontmatter {
  param([string] $Path, [hashtable] $Updates)
  $raw = Get-Content -Raw -LiteralPath $Path -ErrorAction SilentlyContinue
  if (-not $raw -or $raw -notmatch '^---\r?\n') { return $false }
  $parts = $raw -split "(?ms)^---\r?\n", 3
  if ($parts.Count -lt 3) { return $false }
  $fmBlock = $parts[1] -replace '(?ms)\r?\n?---\r?\n.*$', ''
  $body = $parts[2]
  $lines = $fmBlock -split "`r?`n" | Where-Object { $_ -ne '' }
  $newLines = @()
  $touched = @{}
  foreach ($ln in $lines) {
    if ($ln -match '^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$') {
      $k = $matches[1]
      if ($Updates.ContainsKey($k)) {
        $newLines += "${k}: $($Updates[$k])"
        $touched[$k] = $true
      } else {
        $newLines += $ln
      }
    } else {
      $newLines += $ln
    }
  }
  foreach ($k in $Updates.Keys) {
    if (-not $touched.ContainsKey($k)) { $newLines += "${k}: $($Updates[$k])" }
  }
  $rebuilt = "---`n" + ($newLines -join "`n") + "`n---`n" + $body
  try {
    Set-Content -LiteralPath $Path -Value $rebuilt -NoNewline -Encoding UTF8
    return $true
  } catch { return $false }
}

function Invoke-VaultGit {
  # Runs `git <args>` inside the vault root, swallowing errors so a hook never blocks a session.
  param([string[]] $GitArgs)
  if (-not (Test-VaultReachable)) { return $null }
  Push-Location -LiteralPath $script:VaultRoot
  try {
    $out = & git @GitArgs 2>&1
    return $out
  } catch { return $null }
  finally { Pop-Location }
}

function Get-DaysSinceReview {
  if (-not (Test-Path $script:HealthPath)) { return 999 }
  $content = Get-Content -Raw -LiteralPath $script:HealthPath
  if ($content -match 'Last `/cc-review` run:\*\*\s*(\d{4}-\d{2}-\d{2})') {
    try {
      $last = [datetime]::ParseExact($matches[1], 'yyyy-MM-dd', $null)
      return [int]((Get-Date) - $last).TotalDays
    } catch { return 999 }
  }
  return 999
}
