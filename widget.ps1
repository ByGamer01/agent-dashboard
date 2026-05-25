$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$port = if ($env:DASHBOARD_PORT) { [int]$env:DASHBOARD_PORT } else { 7788 }
$profileDir = Join-Path $env:TEMP "agent-dashboard-widget-profile"

$listener = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if (-not $listener) {
  Write-Host "Iniciando servidor..."
  Start-Process -FilePath "python" -ArgumentList "server.py" -WorkingDirectory $projectDir -WindowStyle Minimized
  Start-Sleep -Seconds 2
}

$url = "http://127.0.0.1:$port"
$chrome = "${env:ProgramFiles}\Google\Chrome\Application\chrome.exe"
$chromeX86 = "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe"
$edge = "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe"
$edge64 = "${env:ProgramFiles}\Microsoft\Edge\Application\msedge.exe"
$appArgs = "--app=$url --window-size=1200,750 --window-position=80,80 --disable-extensions --no-first-run --user-data-dir=`"$profileDir`""

if (Test-Path $chrome) {
  Start-Process $chrome $appArgs
} elseif (Test-Path $chromeX86) {
  Start-Process $chromeX86 $appArgs
} elseif (Test-Path $edge64) {
  Start-Process $edge64 $appArgs
} elseif (Test-Path $edge) {
  Start-Process $edge $appArgs
} else {
  Start-Process $url
}
