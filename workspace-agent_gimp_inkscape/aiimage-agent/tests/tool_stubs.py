"""Stubs de `inkscape` y `gimp` para pruebas sin instalar nada.

Comportamiento intencionadamente "realista":
  * responden a --version con el texto que parsea el runner;
  * escriben el archivo de salida que se les pide (--export-filename / (load "…"));
  * el stub de gimp se queda vivo 30 s tras escribir la salida, para probar que el
    agente detecta el archivo, termina el proceso y no se cuelga.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path
from typing import Dict

INKSCAPE_VERSION = "Inkscape 1.4.2 (mock build)"
GIMP_VERSION = "GNU Image Manipulation Program version 2.10.38 (mock)"

INKSCAPE_STUB = r'''import os, re, sys

def _png(path, w=64, h=64):
    """PNG RGBA real escrito con zlib (Tk no acepta PNG de 1x1)."""
    import struct, zlib
    rows = b"".join(b"\x00" + b"".join(struct.pack("4B", *[(200 if (x // 8 + y // 8) % 2 else 120),
                                                            210 if (x // 8 + y // 8) % 2 else 90,
                                                            220, 255]) for x in range(w)) for y in range(h))
    def ck(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    open(path, "wb").write(b"\x89PNG\r\n\x1a\n" + ck(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
                           + ck(b"IDAT", zlib.compress(rows, 6)) + ck(b"IEND", b""))

import os, re, sys, time
args = sys.argv[1:]
if "--version" in args:
    print("__VER__"); raise SystemExit(0)
def val(flag):
    for i, a in enumerate(args):
        if a == flag and i + 1 < len(args):
            return args[i + 1]
        if a.startswith(flag + "="):
            return a.split("=", 1)[1]
    return None
log = {"argv": args, "cwd": os.getcwd()}
open(os.path.join(os.getcwd(), "_inkscape_calls.log"), "a", encoding="utf-8").write(
    repr(log) + "\n")
out = val("--export-filename") or val("-o")
if out:
    src = next((a for a in args if a.lower().endswith(".svg")), "")
    body = "MOCK-EXPORT from " + os.path.basename(src)
    acts = val("--actions")
    if acts:
        body += "\nACTIONS: " + acts
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    if out.lower().endswith(".png"):
        _png(out, 64, 64)
    else:
        open(out, "w", encoding="utf-8").write(
            '<?xml version="1.0" encoding="UTF-8"?>\n<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
            + "<!-- " + body.replace("--", "- -") + " --></svg>\n")
    print("exported " + out)
if "--actions" in args and not out:
    print("acciones aplicadas (mock)", file=sys.stderr)
raise SystemExit(0)
'''

GIMP_STUB = r'''import os, re, sys

def _png(path, w=64, h=64):
    """PNG RGBA real escrito con zlib (Tk no acepta PNG de 1x1)."""
    import struct, zlib
    rows = b"".join(b"\x00" + b"".join(struct.pack("4B", *[(200 if (x // 8 + y // 8) % 2 else 120),
                                                            210 if (x // 8 + y // 8) % 2 else 90,
                                                            220, 255]) for x in range(w)) for y in range(h))
    def ck(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    open(path, "wb").write(b"\x89PNG\r\n\x1a\n" + ck(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
                           + ck(b"IDAT", zlib.compress(rows, 6)) + ck(b"IEND", b""))

import os, re, sys, time
args = sys.argv[1:]
if "--version" in args:
    print("__VER__"); raise SystemExit(0)
open(os.path.join(os.getcwd(), "_gimp_calls.log"), "a", encoding="utf-8").write(repr(args) + "\n")
code = " ".join(args)
m = re.search(r'\(load "([^"]+)"\)', code) or re.search(r"exec\(open\(r'([^']+)'\)", code)
if not m:
    print("GIMP MOCK: no batch script found in " + code[:200], file=sys.stderr)
    raise SystemExit(2)
script = m.group(1)
try:
    body = open(script, encoding="utf-8").read()
except OSError as exc:
    print("GIMP MOCK: no se pudo leer " + script + ": " + str(exc), file=sys.stderr)
    raise SystemExit(3)
print("(gimp-message) " + os.path.basename(script) + " cargado")
print("SCRIPT_HEAD: " + body[:80].replace(chr(10), " "))
if "SIMULA_ERROR" in body:
    print("procedure Error: mock falla a propósito", file=sys.stderr)
    raise SystemExit(1)
out = None
m2 = re.search(r"OUT:([^\s\"')]+)", body)
if m2:
    out = m2.group(1)
else:
    # la SALIDA es la primera ruta entre comillas DESPUÉS de una llamada de guardado.
    # Ojo: el preámbulo de compatibilidad también contiene "…-save", así que solo
    # cuentan las rutas con extensión de imagen (nunca se pisa un .svg de entrada).
    IMG_EXT = (".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp", ".xcf")
    saves = []
    for m in re.finditer(r"\((?:ai-save|gimp-file-save|gimp-xcf-save|file-[a-z]{3,4}-save)\b", body):
        q = re.search(r"\"((?:/|C:/)[^\"]+)\"", body[m.end():m.end() + 400])
        if q and q.group(1).lower().endswith(IMG_EXT) and q.group(1) not in saves:
            saves.append(q.group(1))
    if not saves:
        cands = [c for c, _ in re.findall(r"(/[^\s\"']+|C:/[^\s\"']+)\.(png|jpg|jpeg)", body)]
        cands = [c for c in cands if "in" not in os.path.basename(c).lower()]
        saves = cands[-1:] or []
    out = saves[0] if saves else None
if not out:
    print("GIMP MOCK: no encontré ruta de salida en el script", file=sys.stderr)
    raise SystemExit(4)
for extra in saves:                 # un script puede guardar más de un archivo
    os.makedirs(os.path.dirname(extra) or ".", exist_ok=True)
    _png(extra, 64, 64)
    print("saved " + extra)
time.sleep(30)   # GIMP real a veces no sale: el agente debe matarlo al ver la salida
'''


def write_stubs(bin_dir: Path) -> Dict[str, str]:
    """Crea ejecutables `inkscape`, `gimp`, `gimp-console-2.10` en bin_dir. Devuelve PATH a añadir."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    scripts = {
        "inkscape_stub.py": INKSCAPE_STUB.replace("__VER__", INKSCAPE_VERSION),
        "gimp_stub.py": GIMP_STUB.replace("__VER__", GIMP_VERSION),
    }
    for name, src in scripts.items():
        (bin_dir / name).write_text(src, encoding="utf-8")
    py = Path(sys.executable)
    names = ["inkscape", "gimp", "gimp-console-2.10", "gimp-console"]
    made: Dict[str, str] = {}
    for i, n in enumerate(names):
        target = "gimp_stub.py" if i else "inkscape_stub.py"
        if os.name == "nt":
            bat = bin_dir / f"{n}.bat"
            bat.write_text(f'@echo off\r\n"{py}" "%~dp0{target}" %*\r\n', encoding="utf-8")
            made[n] = str(bat)
        else:
            sh = bin_dir / n
            sh.write_text(f'#!/bin/sh\nexec "{py}" "$(dirname "$0")/{target}" "$@"\n', encoding="utf-8")
            sh.chmod(sh.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
            made[n] = str(sh)
    return made
