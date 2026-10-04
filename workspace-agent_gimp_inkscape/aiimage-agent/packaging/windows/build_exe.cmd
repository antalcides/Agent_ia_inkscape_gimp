@echo off
REM ============================================================
REM  AI Image Agent - build del .exe con PyInstaller (CMD)
REM  Uso:  packaging\windows\build_exe.cmd            (carpeta, arranca rápido)
REM        packaging\windows\build_exe.cmd onefile    (un solo .exe)
REM        packaging\windows\build_exe.cmd clean       (limpia antes)
REM ============================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0..\.."
set "REPO=%CD%"
echo == AI Image Agent - build Windows (CMD) ==
echo repo: %REPO%

REM ---------- localizar Python ----------
set "PY="
for %%P in (py python python3) do (
  if not defined PY (
    where %%P >nul 2>nul && (
      for /f "tokens=2 delims= " %%V in ('%%P -V 2^>^&1') do (
        for /f "tokens=1,2 delims=." %%A in ("%%V") do (
          if %%A GEQ 3 (if %%B GEQ 9 set "PY=%%P")
        )
      )
    )
  )
)
if not defined PY (
  for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do if exist "%%D\python.exe" set "PY=%%D\python.exe"
)
if not defined PY (
  echo [ERROR] Necesito Python 3.9+.   winget install Python.Python.3.12
  echo         o añade la carpeta de Python al PATH y vuelve a intentarlo.
  exit /b 1
)
echo python: %PY%
"%PY%" -V

if /i "%~1"=="clean" (
  rmdir /s /q build dist 2>nul
  echo limpiado build\ dist\
)

REM ---------- venv + pyinstaller ----------
set "VENV=%REPO%\.venv-build"
if not exist "%VENV%\Scripts\python.exe" (
  echo creando entorno virtual...
  "%PY%" -m venv "%VENV%" || (echo [ERROR] no se pudo crear el venv & exit /b 1)
)
set "PYV=%VENV%\Scripts\python.exe"
"%PYV%" -m pip install --upgrade pip --quiet
echo instalando PyInstaller...
"%PYV%" -m pip install "pyinstaller>=6.0" --quiet
if errorlevel 1 (echo [ERROR] pip install pyinstaller fallo - revisa la red & exit /b 1)

REM ---------- icono ----------
if not exist "assets\icon.ico" (
  echo generando assets\icon.ico...
  "%PYV%" -m pip install pillow --quiet
  "%PYV%" scripts\make_icon.py assets || (echo [ERROR] no se pudo generar el icono & exit /b 1)
)

REM ---------- build ----------
if /i "%~1"=="onefile" (set "AIA_ONEFILE=1") else (set "AIA_ONEFILE=0")
echo empaquetando...
"%PYV%" -m PyInstaller --noconfirm --distpath dist --workpath build "packaging\windows\AIImageAgent.spec"
if errorlevel 1 (echo [ERROR] PyInstaller fallo & exit /b 1)

set "TARGET=dist\AI-Image-Agent\AI-Image-Agent.exe"
if /i "%~1"=="onefile" set "TARGET=dist\AI-Image-Agent.exe"
if not exist "%TARGET%" (echo [ERROR] no existe %TARGET% & exit /b 1)

echo.
echo LISTO - %TARGET%
echo prueba rapida:  "%TARGET%" --tools
echo para repartir: copia la carpeta dist\AI-Image-Agent\ completa (o el .exe unico).
endlocal
