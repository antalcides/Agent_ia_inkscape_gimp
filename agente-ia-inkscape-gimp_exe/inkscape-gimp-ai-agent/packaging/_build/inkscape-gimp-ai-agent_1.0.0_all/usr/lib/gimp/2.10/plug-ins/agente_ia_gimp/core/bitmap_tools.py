# -*- coding: utf-8 -*-
"""Utilidades para bitmaps: guardar, medir y convertir SVG a PNG."""

from __future__ import annotations

import os
import shutil
import struct
import subprocess


def save_bytes(blob, path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(blob)
    return path


def guess_extension(blob):
    """Detecta el formato por la cabecera del archivo."""
    if blob[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if blob[:3] == b"\xff\xd8\xff":
        return "jpg"
    if blob[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if blob[:4] == b"RIFF" and blob[8:12] == b"WEBP":
        return "webp"
    return "png"


def image_size(path):
    """Devuelve (ancho, alto) leyendo solo la cabecera, sin dependencias."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(32)
            if head[:8] == b"\x89PNG\r\n\x1a\n":
                w, h = struct.unpack(">II", head[16:24])
                return int(w), int(h)
    except OSError:
        pass
    return None


def find_inkscape():
    """Localiza el ejecutable de Inkscape segun el sistema operativo."""
    for name in ("inkscape", "inkscape.com", "inkscape.exe"):
        found = shutil.which(name)
        if found:
            return found
    candidates = [
        r"C:\Program Files\Inkscape\bin\inkscape.com",
        r"C:\Program Files\Inkscape\bin\inkscape.exe",
        "/usr/bin/inkscape",
        "/usr/local/bin/inkscape",
        "/Applications/Inkscape.app/Contents/MacOS/inkscape",
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def svg_to_png(svg_path, png_path, width=1024, height=1024, background=None):
    """Convierte SVG a PNG usando la linea de comandos de Inkscape."""
    exe = find_inkscape()
    if not exe:
        return None, "No se encontro el ejecutable de Inkscape en el sistema."
    cmd = [exe, svg_path, "--export-type=png", "--export-filename=%s" % png_path,
           "--export-width=%d" % int(width), "--export-height=%d" % int(height)]
    if background:
        cmd += ["--export-background=%s" % background,
                "--export-background-opacity=255"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except Exception as exc:  # noqa: BLE001
        return None, "Fallo al ejecutar Inkscape: %s" % exc
    if proc.returncode != 0 or not os.path.isfile(png_path):
        return None, (proc.stderr or proc.stdout or "Inkscape no genero el PNG.").strip()
    return png_path, ""


def open_in_default_app(path):
    """Abre un archivo con la aplicacion predeterminada del sistema."""
    try:
        if os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]
        elif shutil.which("xdg-open"):
            subprocess.Popen(["xdg-open", path])
        elif shutil.which("open"):
            subprocess.Popen(["open", path])
        return True
    except Exception:  # noqa: BLE001
        return False


def human_size(num_bytes):
    for unit in ("B", "KB", "MB"):
        if num_bytes < 1024:
            return "%.1f %s" % (num_bytes, unit)
        num_bytes /= 1024.0
    return "%.1f GB" % num_bytes
