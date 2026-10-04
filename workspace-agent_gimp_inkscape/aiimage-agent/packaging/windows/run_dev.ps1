<#  Ejecutar la app directamente desde el repositorio (sin empaquetar).
    .\packaging\windows\run_dev.ps1  -Args "--tools"
#>
param([string]$Args = "")
$ErrorActionPreference = "Stop"
$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $Repo
$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $py) { $py = "py" }
if ($Args) { & $py run_agent.py $Args.Split(" ") } else { & $py run_agent.py }
