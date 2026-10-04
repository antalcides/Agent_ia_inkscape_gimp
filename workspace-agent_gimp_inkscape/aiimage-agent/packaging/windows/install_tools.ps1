<#
.SYNOPSIS  Instala las dependencias del sistema para AI Image Agent en Windows.
.USAGE     powershell -ExecutionPolicy Bypass -File packaging\windows\install_tools.ps1
.NOTES     Usa winget. Inkscape y GIMP NO se empaquetan dentro del .exe: la app los
           detecta por PATH/rutas (Ajustes permite fijarlas a mano).
#>
$ErrorActionPreference = "Continue"
$pkgs = [ordered]@{
    "Python.Python.3.12"     = "Python 3.12 (la app ya empaquetada no lo necesita)"
    "Inkscape.Inkscape"      = "Inkscape 1.x  (vectorial)"
    "GIMP.GIMP.3"            = "GIMP 3  (mapas de bits)"
    "Microsoft.VisualStudioCode" = "opcional: editar los scripts generados"
}
$missing = @()
foreach ($k in $pkgs.Keys) {
    $name = ($k -split "\.")[-1]
    $installed = $false
    foreach ($exe in @("$env:ProgramFiles\$name", "${env:ProgramFiles(x86)}\$name")) {
        if (Test-Path $exe) { $installed = $true }
    }
    if ((Get-Command $name -ErrorAction SilentlyContinue)) { $installed = $true }
    if ($k -like "*Python*") { $installed = [bool](Get-Command python -ErrorAction SilentlyContinue) }
    if (-not $installed) { $missing += $k; Write-Host "falta: $($pkgs[$k])" -ForegroundColor Yellow } else { Write-Host "ok   : $($pkgs[$k])" -ForegroundColor Green }
}
if ($missing.Count -eq 0) { Write-Host "nada que instalar"; exit 0 }
Write-Host "`ninstalando con winget: $($missing -join ', ')"
foreach ($m in $missing) { winget install --id $m -e --accept-source-agreements --accept-package-agreements }
Write-Host @"

Reinicia la terminal y comprueba:
    inkscape --version
    gimp --version
Luego abre AI Image Agent y pulsa «Detectar herramientas» en la pestaña Ajustes
(el botón de la barra superior «Comprobar» hace lo mismo).
Si no están en PATH, escribe la ruta en Ajustes, p.ej.
    C:\Program Files\Inkscape\bin\inkscape.exe
    C:\Program Files\GIMP 3\bin\gimp-console-3.0.exe
"@
