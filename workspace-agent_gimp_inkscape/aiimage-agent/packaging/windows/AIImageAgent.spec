# -*- mode: python ; coding: utf-8 -*-
r"""Especificación de PyInstaller para AI Image Agent (Windows y Linux).

Construir .exe (PowerShell o CMD):
    pyinstaller --noconfirm packaging\windows\AIImageAgent.spec

Variables de entorno del build:
    AIA_ONEFILE=1  → un único .exe autoextraíble (arranque más lento, más antivirus)
    AIA_CONSOLE=1  → consola visible (útil para `--cli`, `--tools` y depurar)
Por defecto: una carpeta autocontenida y sin consola (es una app gráfica).
"""

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ONEDIR = os.environ.get("AIA_ONEFILE", "0") != "1"
CONSOLE = os.environ.get("AIA_CONSOLE", "0") == "1"

# SPECPATH es la carpeta del .spec (packaging/windows) → la raíz del repo está dos niveles arriba
ROOT = Path(SPECPATH).resolve().parents[1]
ENTRY = ROOT / "run_agent.py"
if not ENTRY.is_file():                       # por si alguien copia el .spec a la raíz
    ROOT = Path(SPECPATH).resolve()
datas = []
for name in ("icon.ico", "icon.png", "icon.svg", "icon-512.png", "icon-1024.png"):
    p = ROOT / "assets" / name
    if p.is_file():
        datas.append((str(p), "assets"))

hidden = collect_submodules("aiimage_agent") + [
    "tkinter", "tkinter.filedialog", "tkinter.messagebox", "tkinter.simpledialog",
    "tkinter.ttk", "tkinter.font", "queue", "xml.etree.ElementTree", "mimetypes",
]

# Pillow es OPCIONAL en runtime (previsualización con escalado fino). Si está
# instalado en el entorno de build se incluye; si no, Tk hace el trabajo.
excludes = ["numpy", "scipy", "matplotlib", "PyQt5", "PySide2", "test", "setuptools"]
try:
    import PIL  # noqa: F401

    hidden += ["PIL", "PIL.Image", "PIL.ImageTk"]
except ImportError:
    excludes.append("PIL")

a = Analysis(
    [str(ROOT / "run_agent.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={"collect-submodules": ["aiimage_agent"]},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

if ONEDIR:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="AI-Image-Agent",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=CONSOLE,                   # app gráfica: sin consola negra (AIA_CONSOLE=1 para verla)
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=str(ROOT / "assets" / "icon.ico") if (ROOT / "assets" / "icon.ico").is_file() else None,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name="AI-Image-Agent",
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name="AI-Image-Agent",
        debug=False,
        strip=False,
        upx=False,
        console=CONSOLE,
        icon=str(ROOT / "assets" / "icon.ico") if (ROOT / "assets" / "icon.ico").is_file() else None,
    )
