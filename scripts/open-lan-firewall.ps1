# Run as Administrator when firewall updates fail from a normal shell.
# Idempotent: creates or refreshes the UBETRA LAN rule.
$ErrorActionPreference = "Stop"
$ruleName = "UBETRA Dev (TCP 8000)"

$existing = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
if ($existing) {
  Set-NetFirewallRule -DisplayName $ruleName -Enabled True -Action Allow -Profile Any
  Write-Host "Refreshed firewall rule: $ruleName (TCP 8000 inbound, all profiles)."
} else {
  New-NetFirewallRule `
    -DisplayName $ruleName `
    -Direction Inbound `
    -Action Allow `
    -Protocol TCP `
    -LocalPort 8000 `
    -Profile Any |
    Out-Null
  Write-Host "Created firewall rule: $ruleName (TCP 8000 inbound, all profiles)."
}

Write-Host "On this PC: Settings → Network → Wi-Fi → your network → set to Private if phones still cannot connect."
Write-Host "Then start the app with:  .\run.ps1"
