"""Recursos empaquetados (iconos), válidos en repo, en .exe de PyInstaller y en Flatpak."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _bases() -> list[Path]:
    out: list[Path] = []
    forced = os.environ.get("AIIMAGE_AGENT_ASSETS")   # lo usa el manifiesto de Flatpak
    if forced:
        out.append(Path(forced))
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        out.append(Path(meipass))
    here = Path(__file__).resolve().parent          # .../aiimage_agent/core
    out += [here.parents[1] / "assets", here.parent / "assets"]
    exe = Path(sys.executable).parent
    out += [exe / "assets", exe / "_internal" / "assets"]
    out.append(Path.cwd() / "assets")
    return out


def asset(name: str) -> Path | None:
    for b in _bases():
        p = b / name
        if p.is_file():
            return p
        p2 = b / "assets" / name
        if p2.is_file():
            return p2
    return None


def asset_dir() -> Path | None:
    for b in _bases():
        for cand in (b / "assets", b):
            if (cand / "icon.png").is_file():
                return cand
    return None


def asset_path_str(name: str) -> str:
    """Ruta absoluta con barras invertidas si toca (Windows) o '' si no existe."""
    p = asset(name)
    return str(p) if p else ""
