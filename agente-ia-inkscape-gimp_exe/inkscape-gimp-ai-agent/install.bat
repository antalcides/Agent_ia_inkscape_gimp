@echo off
REM Instalador para Windows (CMD) - llama al instalador de PowerShell.
setlocal
cd /d "%~dp0"
echo ============================================================
echo  Agente IA para Inkscape y GIMP - instalacion (CMD)
echo ============================================================
powershell -ExecutionPolicy Bypass -File "%~dp0install.ps1"
echo.
echo Si la instalacion fallo, abre PowerShell como administrador y ejecuta:
echo   powershell -ExecutionPolicy Bypass -File install.ps1
pause
endlocal
