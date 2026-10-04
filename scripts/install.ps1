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
$item = Get-Item $triadDir -Force -ErrorAction SilentlyContinue
$isLinked = $item -and $item.LinkType -in @('Junction','SymbolicLink')
$norm = { param($p) if ($p) { [IO.Path]::GetFullPath($p).TrimEnd('\') } }
$target = if ($isLinked) { & $norm ($item.Target | Select-Object -First 1) }
$repoTriad = & $norm "$repoRoot\triad"
if ($isLinked -and $target -ieq $repoTriad) {
    Write-Host "Triad engine is already linked via junction ($triadDir -> $repoTriad)." -ForegroundColor Green
} else {
    if ($isLinked) {
        Write-Warning "$triadDir is a link to '$target'; replacing with a real copy."
        $item.Delete()
    }
    if (-not (Test-Path $triadDir)) {
        New-Item -ItemType Directory -Path $triadDir -Force | Out-Null
    }
    Copy-Item "$repoRoot\triad\*" $triadDir -Recurse -Force
}

# 4. Synchronize claude-advisor skill to ~/.agents/skills/claude-advisor
Write-Host "Synchronizing claude-advisor skill to $advisorSkillDir..." -ForegroundColor Green
if (-not (Test-Path $advisorSkillDir)) {
    New-Item -ItemType Directory -Path $advisorSkillDir -Force | Out-Null
}
Copy-Item "$repoRoot\skills\claude-advisor\*" $advisorSkillDir -Recurse -Force

# 5. Ensure ~/.local/bin is on the user PATH so `triad` resolves from any shell
try {
    $regKey = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey("Environment", $true)
    if ($regKey) {
        $rawPath = [string]$regKey.GetValue("Path", "", [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
        $pathKind = try { $regKey.GetValueKind("Path") } catch { [Microsoft.Win32.RegistryValueKind]::String }
        if (-not ($rawPath -split ";" | Where-Object { $_ -eq $localBin })) {
            Write-Host "Adding $localBin to user PATH (preserving $pathKind)..." -ForegroundColor Green
            $newPath = if ($rawPath.Trim()) { "$rawPath;$localBin" } else { $localBin }
            $regKey.SetValue("Path", $newPath, $pathKind)
        }
        $regKey.Close()
    }
} catch {
    Write-Warning "Could not update User Environment Path in registry: $_"
}
if (-not ($env:Path -split ";" | Where-Object { $_ -eq $localBin })) {
    $env:Path = "$env:Path;$localBin"
}

Write-Host "Installation successful! Verifying triad health (quick mode, no live advisor probe)..." -ForegroundColor Cyan
& python "$triadDir\triad_engine.py" doctor --quick
if ($LASTEXITCODE -ne 0) {
    Write-Warning "Triad installed successfully, but no enabled advisor is currently authenticated. Run 'codex login', configure API keys, or enable local Ollama to complete setup."
}
exit 0
