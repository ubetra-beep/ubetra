# Ensures phones on the same Wi-Fi can reach UBETRA on TCP 8000.
# Safe to run on every start (idempotent). Prefer Admin for firewall changes.
$ErrorActionPreference = "Continue"
$ruleName = "UBETRA Dev (TCP 8000)"
$port = 8000

function Get-UbetraLanIPv4 {
  $preferred = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object {
      $_.IPAddress -notlike '127.*' -and
      $_.IPAddress -notlike '169.254.*' -and
      $_.PrefixOrigin -ne 'WellKnown' -and
      $_.InterfaceAlias -match 'Wi-?Fi|Ethernet|WLAN|Wireless'
    } |
    Sort-Object -Property InterfaceMetric |
    Select-Object -First 1
  if ($preferred) { return $preferred.IPAddress }

  return (
    Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
      Where-Object {
        $_.IPAddress -notlike '127.*' -and
        $_.IPAddress -notlike '169.254.*' -and
        $_.InterfaceAlias -notmatch 'vEthernet|Hyper-V|WSL|VMware|VirtualBox|Loopback|Docker|Tailscale|ZeroTier' -and
        $_.PrefixOrigin -ne 'WellKnown'
      } |
      Select-Object -First 1 -ExpandProperty IPAddress
  )
}

function Ensure-UbetraFirewall {
  $existing = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
  try {
    if (-not $existing) {
      New-NetFirewallRule `
        -DisplayName $ruleName `
        -Direction Inbound `
        -Action Allow `
        -Protocol TCP `
        -LocalPort $port `
        -Profile Any `
        -ErrorAction Stop | Out-Null
      Write-Host "Firewall: created '$ruleName' (TCP $port, all profiles)."
    } else {
      Set-NetFirewallRule -DisplayName $ruleName -Enabled True -Action Allow -Profile Any -ErrorAction Stop
      $filters = Get-NetFirewallRule -DisplayName $ruleName | Get-NetFirewallPortFilter -ErrorAction SilentlyContinue
      if ($filters -and ($filters.Protocol -ne "TCP" -or "$($filters.LocalPort)" -notmatch "$port")) {
        Remove-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
        New-NetFirewallRule `
          -DisplayName $ruleName `
          -Direction Inbound `
          -Action Allow `
          -Protocol TCP `
          -LocalPort $port `
          -Profile Any `
          -ErrorAction Stop | Out-Null
      }
      Write-Host "Firewall: refreshed '$ruleName' (enabled, TCP $port, all profiles)."
    }
  } catch {
    Write-Host "Firewall: could not update rule (need Admin once)."
    Write-Host "  Run as Admin:  .\scripts\open-lan-firewall.ps1"
  }
}

function Stop-UbetraPortListeners {
  $pids = [System.Collections.Generic.HashSet[int]]::new()

  Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { if ($_.OwningProcess -gt 0) { [void]$pids.Add([int]$_.OwningProcess) } }

  # Also catch uvicorn/reloader workers (Windows can leave orphans after parent exits).
  Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction SilentlyContinue |
    Where-Object {
      $_.CommandLine -and (
        $_.CommandLine -match 'uvicorn|backend\.app\.main' -or
        $_.CommandLine -match 'multiprocessing\.spawn'
      )
    } |
    ForEach-Object { [void]$pids.Add([int]$_.ProcessId) }

  foreach ($procId in ($pids | Sort-Object)) {
    $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if (-not $proc) { continue }
    Write-Host "Stopping listener on :$port (PID $procId $($proc.ProcessName))."
    Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
  }
  Start-Sleep -Milliseconds 800
}

function Show-UbetraHostnameHint {
  param([string]$LanIp, [string]$HostName)
  if (-not $HostName) { return }
  Write-Host ""
  Write-Host "Hostname note: $HostName resolves to several addresses (Wi-Fi, VMware, VPN, IPv6)."
  Write-Host "  Phones/browsers often pick the wrong one - use the Wi-Fi IP when that happens."
  Write-Host "  Preferred:  http://${LanIp}:${port}"
  Write-Host "  Hostname:   http://${HostName}:${port}"
}

$lanIp = Get-UbetraLanIPv4
if (-not $lanIp) { $lanIp = "YOUR-LAN-IP" }
$hostName = $env:COMPUTERNAME

Ensure-UbetraFirewall
Stop-UbetraPortListeners

$wifi = Get-NetConnectionProfile -ErrorAction SilentlyContinue |
  Where-Object { $_.InterfaceAlias -match 'Wi-?Fi|WLAN|Wireless' } |
  Select-Object -First 1
if ($wifi) {
  Write-Host ("Wi-Fi network '{0}' is {1}." -f $wifi.Name, $wifi.NetworkCategory)
  if ($wifi.NetworkCategory -eq "Public") {
    Write-Host ("  Tip: Settings -> Network -> Wi-Fi -> {0} -> Private (more reliable for LAN)." -f $wifi.Name)
  }
}

$script:UbetraLanIp = $lanIp
$script:UbetraHostName = $hostName
$env:UBETRA_PUBLIC_APP_URL = "http://${lanIp}:${port}"
Write-Host ("LAN URL: {0}" -f $env:UBETRA_PUBLIC_APP_URL)
Show-UbetraHostnameHint -LanIp $lanIp -HostName $hostName
