# Instalador para Windows (PowerShell)
# Uso:  powershell -ExecutionPolicy Bypass -File install.ps1
# Instala la interfaz grafica y la extension de Inkscape, y copia el plug-in de GIMP.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

function Write-Info($msg)  { Write-Host "[INFO]  $msg" -ForegroundColor Cyan }
function Write-Ok($msg)    { Write-Host "[ OK ]  $msg" -ForegroundColor Green }
function Write-Warn2($msg) { Write-Host "[AVISO] $msg" -ForegroundColor Yellow }

Write-Info "Agente IA para Inkscape y GIMP - instalacion en Windows"

# --- 1. Comprobar Python --------------------------------------------------
$python = $null
foreach ($candidate in @("python", "python3", "py")) {
    if (Get-Command $candidate -ErrorAction SilentlyContinue) { $python = $candidate; break }
}
if (-not $python) {
    Write-Warn2 "No se encontro Python. Instala Python 3.10+ desde https://www.python.org/downloads/"
    Write-Warn2 "Inkscape y GIMP ya incluyen su propio interprete Python, pero la interfaz grafica necesita Python del sistema."
} else {
    Write-Ok "Python detectado: $python"
    & $python -c "import tkinter" 2>$null
    if ($LASTEXITCODE -ne 0) { Write-Warn2 "El modulo tkinter no esta disponible en este Python." }
}

# --- 2. Extension de Inkscape --------------------------------------------
$inkscapeExt = Join-Path $env:APPDATA "inkscape\extensions"
New-Item -ItemType Directory -Force -Path $inkscapeExt | Out-Null
Copy-Item (Join-Path $root "inkscape_ext\agente_ia_inkscape.inx") $inkscapeExt -Force
Copy-Item (Join-Path $root "inkscape_ext\agente_ia_inkscape.py")  $inkscapeExt -Force
# Copiar el nucleo 'core' junto a la extension (Inkscape usa su propio Python)
$coreTarget = Join-Path $inkscapeExt "core"
if (Test-Path $coreTarget) { Remove-Item $coreTarget -Recurse -Force }
Copy-Item (Join-Path $root "core") $coreTarget -Recurse -Force
Write-Ok "Extension de Inkscape instalada en: $inkscapeExt"

# --- 3. Plug-in de GIMP ---------------------------------------------------
$gimpRoot = Join-Path $env:APPDATA "GIMP"
$installed = $false
if (Test-Path $gimpRoot) {
    Get-ChildItem $gimpRoot -Directory | Where-Object { $_.Name -match "^\d" } | ForEach-Object {
        $plugDir = Join-Path $_.FullName "plug-ins\agente_ia_gimp"
        New-Item -ItemType Directory -Force -Path $plugDir | Out-Null
        New-Item -ItemType Directory -Force -Path (Join-Path $plugDir "core") | Out-Null
        Copy-Item (Join-Path $root "core\*") (Join-Path $plugDir "core") -Recurse -Force
        if ($_.Name -like "3*") {
            Copy-Item (Join-Path $root "gimp_plugin\agente_ia_gimp.py") $plugDir -Force
        } else {
            Copy-Item (Join-Path $root "gimp_plugin\agente_ia_gimp_210.py") $plugDir -Force
        }
        Write-Ok "Plug-in de GIMP instalado en: $plugDir"
        $installed = $true
    }
}
if (-not $installed) {
    Write-Warn2 "No se encontro la carpeta de GIMP en $gimpRoot."
    Write-Warn2 "Copia manualmente 'gimp_plugin\agente_ia_gimp.py' y la carpeta 'core' a:"
    Write-Warn2 "  %APPDATA%\GIMP\3.0\plug-ins\agente_ia_gimp\"
}

# --- 4. Acceso directo para la interfaz ----------------------------------
$launcher = Join-Path $root "iniciar_agente.bat"
@"
@echo off
cd /d "%~dp0"
python agent.py
pause
"@ | Set-Content -Encoding ASCII $launcher
Write-Ok "Lanzador creado: $launcher"

Write-Host ""
Write-Ok "Instalacion terminada. Reinicia Inkscape y GIMP para ver los menus."
Write-Host "Abre Inkscape > Extensiones > Agente IA  |  GIMP > Filtros > IA"
Write-Host "Interfaz grafica: doble clic en iniciar_agente.bat"
