$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv")) {
  Write-Host "Creating virtual environment..."
  python -m venv .venv
  & .\.venv\Scripts\Activate.ps1
  pip install -r requirements.txt
} else {
  & .\.venv\Scripts\Activate.ps1
}

# Re-assert LAN bind + firewall on every start (IP/profile can change after updates).
. .\scripts\ensure-lan-access.ps1
$lanIp = $script:UbetraLanIp
$hostName = $script:UbetraHostName
if (-not $lanIp) { $lanIp = "YOUR-LAN-IP" }
if (-not $hostName) { $hostName = $env:COMPUTERNAME }
$env:UBETRA_PUBLIC_APP_URL = "http://${lanIp}:8000"

Write-Host ""
Write-Host "Starting UBETRA (LAN-reachable, IPv4+IPv6)"
Write-Host "  This PC:      http://127.0.0.1:8000"
Write-Host "  Wi-Fi IP:     http://${lanIp}:8000   <- use this on phones"
Write-Host "  Hostname:     http://${hostName}:8000"
Write-Host "  Same Wi-Fi as this PC. Hard-refresh the phone if the PWA looks stuck."
Write-Host ""

# 0.0.0.0 = all IPv4 interfaces (127.0.0.1 + Wi-Fi LAN). Avoid "--host ::" on
# Windows: it often binds IPv6-only, so 127.0.0.1 / phones on IPv4 fail while
# orphaned reloader children can keep answering with stale code.
python -m uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
