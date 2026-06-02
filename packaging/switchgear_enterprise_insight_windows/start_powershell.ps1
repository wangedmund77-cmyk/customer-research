[CmdletBinding()]
param(
  [string]$HostAddress = "127.0.0.1",
  [int]$Port = 8790,
  [switch]$Lan
)

$ErrorActionPreference = "Stop"

function Resolve-PythonCommand {
  $candidates = @(
    @{ Exe = "py"; Args = @("-3.11") },
    @{ Exe = "py"; Args = @("-3") },
    @{ Exe = "python"; Args = @() },
    @{ Exe = "python3"; Args = @() }
  )

  foreach ($candidate in $candidates) {
    if (-not (Get-Command $candidate.Exe -ErrorAction SilentlyContinue)) {
      continue
    }

    try {
      & $candidate.Exe @($candidate.Args + @("-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)")) | Out-Null
      if ($LASTEXITCODE -eq 0) {
        return [pscustomobject]@{
          Exe = $candidate.Exe
          Args = $candidate.Args
        }
      }
    } catch {
      continue
    }
  }

  return $null
}

try {
  Set-Location -Path $PSScriptRoot

  $python = Resolve-PythonCommand
  if ($null -eq $python) {
    throw "Python 3.9 or later was not found. Install it from https://www.python.org/downloads/windows/ and enable 'Add python.exe to PATH'."
  }

  $listenHost = $HostAddress
  if ($Lan) {
    $listenHost = "0.0.0.0"
  }

  $env:PYTHONPATH = Join-Path $PSScriptRoot "src"
  $env:PYTHONUTF8 = "1"
  $env:PYTHONIOENCODING = "utf-8"

  $localUrl = "http://127.0.0.1:$Port/"
  Write-Host "Starting Switchgear Enterprise Insight Workbench..." -ForegroundColor Cyan
  Write-Host "Local URL: $localUrl"

  if ($Lan) {
    Write-Host "LAN mode is enabled. Other computers can open: http://YOUR-LAN-IP:$Port/"
    Write-Host "Allow Python through Windows Firewall if prompted."
  }

  Start-Process $localUrl
  & $python.Exe @($python.Args + @("-m", "switchgear_customer_insight", "web", "--host", $listenHost, "--port", "$Port"))
} catch {
  Write-Host ""
  Write-Host "Startup failed:" -ForegroundColor Red
  Write-Host $_.Exception.Message
  Write-Host ""
  Read-Host "Press Enter to close"
  exit 1
}
