param(
  [ValidateSet("local", "k8s")]
  [string]$Mode = "local"
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command choco -ErrorAction SilentlyContinue)) {
  throw "Chocolatey is required on Windows for runtime bootstrap"
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
  choco install docker-desktop -y
}

if ($Mode -eq "k8s") {
  if (-not (Get-Command kubectl -ErrorAction SilentlyContinue)) {
    choco install kubernetes-cli -y
  }
  if (-not (Get-Command helm -ErrorAction SilentlyContinue)) {
    choco install kubernetes-helm -y
  }
  if (-not (Get-Command kind -ErrorAction SilentlyContinue)) {
    choco install kind -y
  }
}

Write-Host "[runtime-bootstrap-ps] completed"
