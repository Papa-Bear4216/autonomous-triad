<#
.SYNOPSIS
    Runs automated verification of the Triad installation.
#>

$ErrorActionPreference = "Stop"

Write-Host "Running Triad verification..." -ForegroundColor Cyan
triad doctor
if ($LASTEXITCODE -eq 0) {
    Write-Host "`nAll Triad subsystems verified successfully!" -ForegroundColor Green
} else {
    Write-Host "`nTriad verification reported an issue." -ForegroundColor Red
}
