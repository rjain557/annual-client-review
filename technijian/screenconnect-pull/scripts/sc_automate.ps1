
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Windows.Forms

$AE = [System.Windows.Automation.AutomationElement]
$TS = [System.Windows.Automation.TreeScope]
$PC = [System.Windows.Automation.PropertyCondition]
$CT = [System.Windows.Automation.ControlType]

function Wait-Element {
    param($Parent, $Scope, $Condition, [int]$TimeoutMs = 8000)
    $end = [DateTime]::Now.AddMilliseconds($TimeoutMs)
    while ([DateTime]::Now -lt $end) {
        $el = $Parent.FindFirst($Scope, $Condition)
        if ($el) { return $el }
        Start-Sleep -Milliseconds 200
    }
    return $null
}

Write-Host "Looking for ScreenConnect Session Capture Processor window..."
$winCond = New-Object $PC($AE::NameProperty, "ScreenConnect Session Capture Processor")
$win = Wait-Element -Parent $AE::RootElement -Scope $TS::Children -Condition $winCond
if (-not $win) { Write-Error "SC Processor window not found. Make sure it is open."; exit 1 }

$win.SetFocus()
Start-Sleep -Milliseconds 400

# --- Check 'Transcode after download' checkbox ---
$chkCond = New-Object $PC($AE::NameProperty, "Transcode after download")
$chk = $win.FindFirst($TS::Descendants, $chkCond)
if ($chk) {
    $tog = $chk.GetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern)
    if ($tog.Current.ToggleState -ne [System.Windows.Automation.ToggleState]::On) {
        Write-Host "Checking 'Transcode after download'..."
        $tog.Toggle()
        Start-Sleep -Milliseconds 300
    } else {
        Write-Host "'Transcode after download' already checked."
    }
} else {
    Write-Warning "Could not find 'Transcode after download' checkbox - continuing anyway."
}

# --- Click 'Choose Capture Files to Transcode' ---
Write-Host "Clicking 'Choose Capture Files to Transcode'..."
$btnCond = New-Object $PC($AE::NameProperty, "Choose Capture Files to Transcode")
$btn = $win.FindFirst($TS::Descendants, $btnCond)
if (-not $btn) { Write-Error "Button not found."; exit 1 }
$btn.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()

# --- Wait for the Open file dialog ---
Write-Host "Waiting for file dialog..."
Start-Sleep -Milliseconds 2000

# Find any new top-level window that is not the SC Processor
$allWinCond = New-Object $PC($AE::ControlTypeProperty, $CT::Window)
$dlg = $null
$end = [DateTime]::Now.AddSeconds(10)
while ([DateTime]::Now -lt $end) {
    $candidates = $AE::RootElement.FindAll($TS::Children, $allWinCond)
    foreach ($c in $candidates) {
        $name = $c.Current.Name
        if ($name -ne "ScreenConnect Session Capture Processor" -and $name -ne "") {
            $dlg = $c
            Write-Host "  Found dialog: $name"
            break
        }
    }
    if ($dlg) { break }
    Start-Sleep -Milliseconds 300
}

if (-not $dlg) { Write-Error "File dialog did not appear."; exit 1 }

$dlg.SetFocus()
Start-Sleep -Milliseconds 400

# --- Navigate to R:\ by typing in the filename box ---
Write-Host "Navigating to R:\..."
[System.Windows.Forms.SendKeys]::SendWait("R:\")
Start-Sleep -Milliseconds 300
[System.Windows.Forms.SendKeys]::SendWait("{ENTER}")
Start-Sleep -Milliseconds 2500   # wait for directory listing to load

# --- Select all files: focus the list view then Ctrl+A ---
Write-Host "Selecting all files (Ctrl+A)..."
$listCond = New-Object $PC($AE::ControlTypeProperty, $CT::List)
$list = $dlg.FindFirst($TS::Descendants, $listCond)
if ($list) {
    $list.SetFocus()
    Start-Sleep -Milliseconds 300
} else {
    Write-Warning "Could not find list view - attempting Ctrl+A anyway"
    # Tab past the filename field to reach the list
    [System.Windows.Forms.SendKeys]::SendWait("{TAB}{TAB}{TAB}")
    Start-Sleep -Milliseconds 200
}

[System.Windows.Forms.SendKeys]::SendWait("^a")
Start-Sleep -Milliseconds 800

# --- Click Open ---
Write-Host "Clicking Open..."
$openBtnCond = New-Object $PC($AE::NameProperty, "Open")
$openBtn = $dlg.FindFirst($TS::Descendants, $openBtnCond)
if ($openBtn) {
    $openBtn.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
    Write-Host "Done - files queued for transcoding."
} else {
    # Fallback: press Enter
    Write-Warning "Open button not found by name - pressing Enter"
    [System.Windows.Forms.SendKeys]::SendWait("{ENTER}")
}

Write-Host ""
Write-Host "Transcoding started. The GUI will process all files to C:\tmp\sc_avis\"
Write-Host "This will take a while - leave the window open."
