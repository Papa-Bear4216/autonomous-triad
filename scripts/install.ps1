<#
.SYNOPSIS
    Installs and links the Autonomous Multi-Agent Triad into the user's environment.
#>

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path "$PSScriptRoot\..").Path
$userHome = $env:USERPROFILE
$agentsDir = Join-Path $userHome ".agents"
$localBin = Join-Path $userHome ".local\bin"
$triadDir = Join-Path $agentsDir "triad"
$advisorSkillDir = Join-Path $agentsDir "skills\claude-advisor"

Write-Host "Installing Autonomous Multi-Agent Triad from $repoRoot..." -ForegroundColor Cyan

# 1. Ensure target directories exist
if (-not (Test-Path $localBin)) {
    New-Item -ItemType Directory -Path $localBin -Force | Out-Null
}
if (-not (Test-Path $agentsDir)) {
    New-Item -ItemType Directory -Path $agentsDir -Force | Out-Null
}
if (-not (Test-Path (Join-Path $agentsDir "skills"))) {
    New-Item -ItemType Directory -Path (Join-Path $agentsDir "skills") -Force | Out-Null
}

# 2. Copy CLI launchers to ~/.local/bin
Write-Host "Copying CLI launchers to $localBin..." -ForegroundColor Green
Copy-Item "$repoRoot\bin\triad.cmd" $localBin -Force
Copy-Item "$repoRoot\bin\triad.ps1" $localBin -Force

# 3. Synchronize triad engine to ~/.agents/triad
Write-Host "Synchronizing triad engine to $triadDir..." -ForegroundColor Green
if (-not (Test-Path $triadDir)) {
    New-Item -ItemType Directory -Path $triadDir -Force | Out-Null
}
Copy-Item "$repoRoot\triad\*" $triadDir -Recurse -Force

# 4. Synchronize claude-advisor skill to ~/.agents/skills/claude-advisor
Write-Host "Synchronizing claude-advisor skill to $advisorSkillDir..." -ForegroundColor Green
if (-not (Test-Path $advisorSkillDir)) {
    New-Item -ItemType Directory -Path $advisorSkillDir -Force | Out-Null
}
Copy-Item "$repoRoot\skills\claude-advisor\*" $advisorSkillDir -Recurse -Force

Write-Host "Installation successful! Verifying triad health..." -ForegroundColor Cyan
& python "$triadDir\triad_engine.py" doctor
