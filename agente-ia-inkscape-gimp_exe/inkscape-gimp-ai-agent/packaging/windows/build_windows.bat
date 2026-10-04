@echo off
REM ============================================================
REM  Construye AgenteIA-Inkscape-GIMP.exe  (Windows, un solo archivo)
REM  Requisitos: Python 3.10+ con tkinter (viene con el instalador oficial)
REM ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0\..\.."

echo [INFO] Comprobando Python...
where py >nul 2>&1 && set "PY=py" || set "PY=python"
%PY% --version
if errorlevel 1 (
    echo [ERROR] Python no encontrado. Instalalo desde https://www.python.org/downloads/
    pause
    exit /b 1
)

%PY% -c "import tkinter" >nul 2>&1
if errorlevel 1 (
    echo [AVISO] Este Python no tiene tkinter. Instala Python desde python.org
    echo         marcando la opcion "tcl/tk and IDLE".
)

echo [INFO] Instalando PyInstaller...
%PY% -m pip install --upgrade --quiet pyinstaller
if errorlevel 1 (
    echo [ERROR] No se pudo instalar PyInstaller.
    pause
    exit /b 1
)

echo [INFO] Empaquetando el ejecutable...
%PY% -m PyInstaller --clean --noconfirm agent.spec
if errorlevel 1 (
    echo [ERROR] La construccion fallo.
    pause
    exit /b 1
)

echo.
echo [ OK ] Ejecutable creado en:  dist\AgenteIA-Inkscape-GIMP.exe
echo        Copialo donde quieras y ejecutalo con doble clic.
dir /b dist\*.exe
pause
endlocal
