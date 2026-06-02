$ErrorActionPreference = "Stop"

Set-Location -Path $PSScriptRoot
$env:PYTHONPATH = Join-Path $PSScriptRoot "src"

$python = "python"
if (Get-Command py -ErrorAction SilentlyContinue) {
  $python = "py"
  $args = @("-3", "-m", "switchgear_customer_insight", "web", "--host", "127.0.0.1", "--port", "8790")
} else {
  $args = @("-m", "switchgear_customer_insight", "web", "--host", "127.0.0.1", "--port", "8790")
}

Write-Host "正在启动施耐德盘厂企业洞察研究工作台..."
Write-Host "地址: http://127.0.0.1:8790/"
Start-Process "http://127.0.0.1:8790/"
& $python @args
