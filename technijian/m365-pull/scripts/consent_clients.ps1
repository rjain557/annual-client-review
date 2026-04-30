# consent_clients.ps1
# Opens the admin-consent URL for each pending GDAP / Reseller client tenant.
#
# HOW TO RUN:
#   1. Sign into your browser with the Technijian admin account that has
#      GDAP Global Admin access for these clients (Partner Center session
#      or any browser where you're already authenticated as that admin).
#   2. Run this script in PowerShell:
#        cd c:\vscode\annual-client-review\annual-client-review
#        .\technijian\m365-pull\scripts\consent_clients.ps1
#   3. For each tenant a browser tab opens showing the permission request.
#      Click "Accept". Then come back to PowerShell and press Enter for next.
#   4. If you get "Need admin approval", you are NOT signed in as a GA for
#      that tenant. Type SKIP to move on.
#
# Prereq: app must have https://login.microsoftonline.com/common/oauth2/nativeclient
# registered as a redirect URI under "Mobile and desktop applications".
#
# After completing all, run check_access.py to verify, then the M365 pulls.

$APP_ID       = "5cbc8ba3-2795-4129-9258-b41102cac82e"
$REDIRECT_URI = "https://login.microsoftonline.com/common/oauth2/nativeclient"

# Only the 7 active clients that still need app admin consent.
# The other 11 active clients (TECHNIJIAN/BIS/CBI/NOR/VAF/SAS/AAOC/ACU/BWH/HHOC/ORX)
# are already consented — confirmed by check_access.py 2026-04-30.
$clients = @(
    @{ code = "CBL";  name = "Christopher L. Blank Attorney at Law"; tenantId = "7f514a44-48f6-4400-a30e-c68d563bee28"; type = "GDAP" },
    @{ code = "CCC";  name = "Culp Construction";                    tenantId = "c9367da3-01f5-4b8d-9461-82eb18a57409"; type = "GDAP" },
    @{ code = "JRM";  name = "JR Medical Inc";                       tenantId = "449cd620-98d9-4f32-9dde-e263485e8dcd"; type = "GDAP" },
    @{ code = "MRM";  name = "MiraculousMinds";                      tenantId = "5631631f-6b02-408b-af52-6b1bac470f59"; type = "GDAP" },
    @{ code = "KES";  name = "KES Homes";                            tenantId = "325e6986-c171-4e39-83a3-c6fcbf9dc0f9"; type = "GDAP" },
    @{ code = "JDH";  name = "JDH Pacific";                          tenantId = "e5cb8b12-8729-4105-b4f0-1520d78a3260"; type = "Reseller" },
    @{ code = "RMG";  name = "Roddel Marketing Group";               tenantId = "6df1ff80-b028-45d0-82b3-4da67fbc0fc0"; type = "Reseller" }
)

Write-Host ""
Write-Host "=== Technijian-Partner-Graph-Read Admin Consent ===" -ForegroundColor Cyan
Write-Host "App ID: $APP_ID"
$gdapCount     = ($clients | Where-Object { $_.type -eq "GDAP" }).Count
$resellerCount = ($clients | Where-Object { $_.type -eq "Reseller" }).Count
Write-Host "$gdapCount GDAP + $resellerCount Cloud Reseller = $($clients.Count) tenants pending consent."
Write-Host ""

$done    = 0
$skipped = 0

foreach ($c in $clients) {
    $url = "https://login.microsoftonline.com/$($c.tenantId)/adminconsent?client_id=$APP_ID&redirect_uri=$REDIRECT_URI"
    $typeLabel = if ($c.type -eq "GDAP") { "[GDAP]    " } else { "[Reseller]" }
    Write-Host "[$($done+$skipped+1)/$($clients.Count)] $typeLabel $($c.code) - $($c.name)" -ForegroundColor Green
    Write-Host "    Tenant: $($c.tenantId)"
    Write-Host "    Opening consent URL..."
    Start-Process $url
    $response = Read-Host "    Press Enter after accepting (or type SKIP to skip)"
    if ($response -match "(?i)^skip") {
        $skipped++
        Write-Host "    Skipped." -ForegroundColor Yellow
    } else {
        $done++
    }
    Write-Host ""
}

Write-Host "=== Done: $done accepted, $skipped skipped ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Verify access:"
Write-Host "  python technijian\m365-pull\scripts\check_access.py"
Write-Host ""
Write-Host "Then run pulls:"
Write-Host "  python technijian\m365-pull\scripts\pull_m365_compliance.py"
Write-Host "  python technijian\m365-pull\scripts\pull_m365_storage.py --period D7"
Write-Host "  python technijian\m365-pull\scripts\pull_m365_security.py --hours 24"
