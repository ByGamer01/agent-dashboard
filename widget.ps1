$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$port = 7788

$listener = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if (-not $listener) {
  Write-Host "Iniciando servidor..."
  Start-Process -FilePath "python" -ArgumentList "server.py" -WorkingDirectory $projectDir -WindowStyle Minimized
  Start-Sleep -Seconds 2
}

$url = "http://127.0.0.1:$port"
$chrome = "${env:ProgramFiles}\Google\Chrome\Application\chrome.exe"
$chromeX86 = "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe"

if (Test-Path $chrome) {
  Start-Process $chrome "--app=$url --window-size=1200,750 --window-position=80,80 --disable-extensions --no-first-run"
} elseif (Test-Path $chromeX86) {
  Start-Process $chromeX86 "--app=$url --window-size=1200,750 --window-position=80,80 --disable-extensions --no-first-run"
} else {
  Start-Process $url
}
