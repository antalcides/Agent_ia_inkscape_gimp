#!/usr/bin/env python3
"""Prueba de humo de un AI Image Agent **ya empaquetado** (PyInstaller o el binario de Linux).

Lanza el binario en modo CLI contra un LLM simulado y el Inkscape/GIMP *reales* del equipo,
ejecuta un plan de 3 pasos (SVG → export PNG → reescalado en GIMP) y comprueba los tamaños.

    python3 scripts/frozen_smoke.py                                  # usa dist/AI-Image-Agent/…
    python3 scripts/frozen_smoke.py "C:\\repo\\dist\\AI-Image-Agent\\AI-Image-Agent.exe"
    python3 scripts/frozen_smoke.py --stubs                           # sin herramientas reales

Sale con 0 si todo cuadra. Requiere `tests/mock_llm.py` (viene con el repo).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

PLAN = {
    "summary": "SVG → PNG (Inkscape) → reescalado (GIMP).",
    "notes": [],
    "explanation": "ok",
    "steps": [
        {"app": "inkscape", "kind": "svg", "purpose": "crear el logo", "output": "logo.svg",
         "code": '<?xml version="1.0" encoding="UTF-8"?>\n'
                 '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200" viewBox="0 0 200 200">'
                 '<rect width="200" height="200" fill="#0a58ca"/><circle cx="100" cy="100" r="64" fill="#fff"/></svg>'},
        {"app": "inkscape", "kind": "inkscape-actions", "purpose": "exportar a PNG a 150 dpi",
         "input": "logo.svg", "output": "logo.png",
         "code": "export-area-page;\nexport-dpi:150;\nexport-background:#ffffff;"},
        {"app": "gimp", "kind": "script-fu", "purpose": "reescalar a 96x96",
         "input": "logo.png", "output": "mini.png",
         "code": '(define (ai-run) (let* ((image (ai-load "{INPUT}"))) (gimp-image-scale image 96 96) '
                 '(ai-save image "{OUTPUT}") (gimp-image-delete image))) (ai-run)'},
    ],
}


def find_binary(explicit: str) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    for cand in (ROOT / "dist/AI-Image-Agent/AI-Image-Agent.exe",
                 ROOT / "dist/AI-Image-Agent/AI-Image-Agent",
                 ROOT / "dist/AI-Image-Agent.exe"):
        if cand.exists():
            return cand
    raise SystemExit("no encuentro el binario; constrúyelo primero o pásalo como argumento")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("binary", nargs="?", default="", help="ruta al ejecutable empaquetado")
    ap.add_argument("--stubs", action="store_true", help="usar los stubs de tests (sin Inkscape/GIMP reales)")
    args = ap.parse_args()

    binary = find_binary(args.binary)
    if not binary.exists():
        raise SystemExit(f"no existe {binary}")

    import mock_llm

    from aiimage_agent.core.images import image_size

    mock_llm.MockLLM.plan = PLAN
    base = mock_llm.MockLLM.start()
    env = dict(os.environ)
    env["OPENAI_API_KEY"] = "sk-test"
    env.pop("AIA_INKSCAPE", None)
    env.pop("AIA_GIMP", None)
    tmp = Path(tempfile.mkdtemp(prefix="aia-frozen-"))
    ws = tmp / "ws"
    ws.mkdir()
    if args.stubs:
        from tests.tool_stubs import write_stubs

        write_stubs(tmp / "bin")
        env["PATH"] = str(tmp / "bin") + os.pathsep + env["PATH"]
        env["AIA_INKSCAPE"] = str(tmp / "bin" / "inkscape")
        env["AIA_GIMP"] = str(tmp / "bin" / ("gimp.bat" if os.name == "nt" else "gimp"))

    fails: list[str] = []
    try:
        cmd = [str(binary), "--cli", "--json", "--provider", "openai",
               "--base-url", f"{base}/v1", "--model", "gpt-4.1-mini",
               "--app", "inkscape", "--app", "gimp", "--timeout", "240",
               "--prompt", "prueba de humo", "--execute", "-w", str(ws)]
        print("$", " ".join(cmd[:6]), "… --execute")
        p = subprocess.run(cmd, env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=600)
        print("   exit code:", p.returncode)
        if p.returncode != 0:
            fails.append(f"exit {p.returncode}: {(p.stdout + p.stderr)[-800:]}")
        try:
            out = json.loads(p.stdout)
        except json.JSONDecodeError:
            fails.append("stdout no es JSON: " + p.stdout[-500:])
            out = {}
        if out and not out.get("ok"):
            fails.append("ok=false: " + json.dumps(out.get("log", ""))[-800:])
        files = [Path(f) for f in (out.get("files") or [])]
        print(f"   pasos del plan empaquetado: {len(PLAN['steps'])} · archivos: {[f.name for f in files]}")
        for line in (out.get("log") or [])[-6:]:
            print("   |", line)
        for name, expect in (("logo.svg", None), ("logo.png", None), ("mini.png", (96, 96))):
            f = ws / name
            if not f.exists():
                fails.append(f"falta {name}")
                continue
            if expect and not args.stubs:
                got = image_size(f)
                if got != expect:
                    fails.append(f"{name}: {got} != {expect}")
                else:
                    print(f"   ✓ {name} = {got[0]}×{got[1]} px")
            elif expect:
                print(f"   ✓ {name} (los stubs no reproducen el tamaño)")
            else:
                print(f"   ✓ {name} ({f.stat().st_size} bytes)")
        # el binario debe traer los assets dentro (icono de la ventana y del .ico)
        internal = binary.parent / "_internal" / "assets"
        side = binary.parent / "assets"
        if not ((internal / "icon.ico").exists() or (side / "icon.ico").exists()
                or (ROOT / "assets" / "icon.ico").exists()):
            fails.append("el bundle no lleva assets/icon.ico")
        else:
            print("   ✓ assets/icon.ico accesible desde el bundle")
    finally:
        mock_llm.MockLLM.stop()
        shutil.rmtree(tmp, ignore_errors=True)

    for f in fails:
        print("✗", f)
    print("FROZEN_SMOKE_OK" if not fails else f"FALLOS={len(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
