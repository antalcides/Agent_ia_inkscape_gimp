# -*- mode: python ; coding: utf-8 -*-
"""
Especificacion de PyInstaller para generar el ejecutable de Windows
(AgenteIA-Inkscape-GIMP.exe) en un solo archivo, sin consola.

Construccion en Windows:
    build_windows.bat
o manualmente:
    py -m pip install --upgrade pyinstaller
    py -m PyInstaller --clean --noconfirm agent.spec
El resultado queda en dist\\AgenteIA-Inkscape-GIMP.exe
"""

block_cipher = None

a = Analysis(
    ["agent.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("config.example.json", "."),
        ("README.md", "."),
        ("core", "core"),
        ("ui", "ui"),
        ("inkscape_ext", "inkscape_ext"),
        ("gimp_plugin", "gimp_plugin"),
    ],
    hiddenimports=[
        "tkinter",
        "tkinter.ttk",
        "tkinter.filedialog",
        "tkinter.messagebox",
        "tkinter.scrolledtext",
        "core.providers",
        "core.config",
        "core.svg_tools",
        "core.bitmap_tools",
        "ui.app",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["numpy", "PIL", "matplotlib", "scipy", "pandas"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="AgenteIA-Inkscape-GIMP",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # sin ventana de consola
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon="packaging/windows/agente_ia.ico",   # coloca tu icono si quieres uno
)
