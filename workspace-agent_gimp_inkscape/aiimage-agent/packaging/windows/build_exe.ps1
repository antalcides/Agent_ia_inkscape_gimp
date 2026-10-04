<#
.SYNOPSIS
    Construye AI-Image-Agent.exe (Windows 10/11) con PyInstaller.
.USAGE
    powershell -ExecutionPolicy Bypass -File packaging\windows\build_exe.ps1
    .\packaging\windows\build_exe.ps1 -OneFile -Clean
    .\packaging\windows\build_exe.ps1 -SignThumbprint "ABC..."   # si tienes certificado
#>
[CmdletBinding()]
param(
    [switch]$OneFile,          # genera un único .exe en vez de carpeta
    [switch]$Clean,            # borra build/ y dist/ antes
    [switch]$NoVenv,           # usa el Python actual (sin entorno virtual)
    [string]$Python = "",      # python.exe concreto a usar
    [string]$SignThumbprint = ""
)

$ErrorActionPreference = "Stop"
$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $Repo
Write-Host "== AI Image Agent · build Windows ==" -ForegroundColor Cyan
Write-Host "repo: $Repo"

function Find-Python() {
    if ($Python -and (Test-Path $Python)) { return $Python }
    foreach ($c in @("py", "python", "python3")) {
        $p = Get-Command $c -ErrorAction SilentlyContinue
        if ($p) {
            $ver = & $p -c "import sys;print('%d.%d' % sys.version_info[:2])" 2>$null
            if ($LASTEXITCODE -eq 0) {
                $maj, $min = $ver.Split(".")
                if ([int]$maj -gt 3 -or ([int]$maj -eq 3 -and [int]$min -ge 9)) { return $p.Source }
            }
        }
    }
    foreach ($g in Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*" -Directory -ErrorAction SilentlyContinue) {
        if (Test-Path "$($g.FullName)\python.exe") { return "$($g.FullName)\python.exe" }
    }
    throw "No se encontró Python 3.9+. Instálalo (winget install Python.Python.3.12) o pasa -Python C:\ruta\python.exe"
}

$Py = Find-Python
Write-Host "python: $Py"
& $Py -V

# --- Inkscape y GIMP NO se empaquetan: la app los usa del sistema. Se avisa si faltan.
foreach ($t in @(@("Inkscape", "$env:ProgramFiles\Inkscape\bin\inkscape.exe"),
                 @("GIMP", "$env:ProgramFiles\GIMP 3\bin\gimp-3.0.exe"),
                 @("GIMP", "$env:ProgramFiles\GIMP 2\bin\gimp-2.10.exe"))) {
    $found = (Get-Command $t[0] -ErrorAction SilentlyContinue) -or (Test-Path $t[1])
    if (-not $found) { Write-Host "aviso: $($t[0]) no parece instalado (la app puede indicarlo en Ajustes)" -ForegroundColor Yellow }
}

if ($Clean) {
    Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue
    Write-Host "limpiado build/ dist/"
}

# --- entorno virtual aislado (reproducible)
if (-not $NoVenv) {
    $venv = Join-Path $Repo ".venv-build"
    if (-not (Test-Path "$venv\Scripts\python.exe")) {
        Write-Host "creando venv en $venv"
        & $Py -m venv $venv
    }
    $Py = "$venv\Scripts\python.exe"
    & $Py -m pip install --upgrade pip --quiet
}

Write-Host "instalando PyInstaller…"
& $Py -m pip install "pyinstaller>=6.0" --quiet
if ($LASTEXITCODE) { throw "pip install pyinstaller falló (¿sin red? usa -NoVenv con pyinstaller ya instalado)" }

if ($OneFile) { $env:AIA_ONEFILE = "1" } else { $env:AIA_ONEFILE = "0" }

Write-Host "ejecutando PyInstaller…"
& $Py -m PyInstaller --noconfirm --distpath dist --workpath build packaging\windows\AIImageAgent.spec
if ($LASTEXITCODE) { throw "PyInstaller falló" }

$target = if ($OneFile) { "dist\AI-Image-Agent.exe" } else { "dist\AI-Image-Agent\AI-Image-Agent.exe" }
if (-not (Test-Path $target)) { throw "no se encontró el ejecutable esperado: $target" }

if ($SignThumbprint) {
    Write-Host "firmando con certificado $SignThumbprint"
    $sig = Get-Command "signtool.exe" -ErrorAction SilentlyContinue
    if (-not $sig) { throw "signtool.exe no está en PATH (Instala el Windows SDK)" }
    & signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /sha1 $SignThumbprint $target
}

$size = [math]::Round(((Get-ChildItem (Split-Path $target) -Recurse | Measure-Object Length -Sum).Sum / 1MB), 1)
Write-Host ""
Write-Host "LISTO → $target   (${size} MB en total)" -ForegroundColor Green
Write-Host "prueba:  & '$target' --tools"
Write-Host "repartir: copia la carpeta dist\AI-Image-Agent\ (o el .exe único) y ejecútala; no requiere Python."
