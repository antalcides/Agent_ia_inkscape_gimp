@echo off
REM Ejecutar la app desde el repositorio (sin empaquetar).
REM   packaging\windows\run_dev.cmd
REM   packaging\windows\run_dev.cmd --cli -p "haz un logo"
cd /d "%~dp0..\.."
set "PY=python"
where python >nul 2>nul || set "PY=py"
if "%~1"=="" ( %PY% run_agent.py ) else ( %PY% run_agent.py %* )
