"""Sistema de prompts: hace que el modelo devuelva un PLAN accionable en JSON.

El contrato (``PLAN_SCHEMA``) es lo que el parser y el motor de ejecución esperan.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

INKSCAPE_STYLES = "svg, inkscape-actions, python-svg, inkex-python"
GIMP_STYLES = "script-fu, python-fu"

PLAN_SCHEMA = {
    "summary": "string: qué se hará, en 1-3 frases, en el idioma del usuario",
    "notes": ["string: advertencias, limitaciones, qué hace cada paso"],
    "workspace_files": [{"name": "in.svg", "content": "string opcional: contenido inicial del archivo"}],
    "steps": [
        {
            "app": "inkscape | gimp",
            "kind": f"{{{INKSCAPE_STYLES}|{GIMP_STYLES}}} | shell-export",
            "purpose": "string corto",
            "code": "string con EL CÓDIGO (SVG/XML, lista de acciones, Python o Script-Fu)",
            "input": "nombre de archivo de entrada existente o '' (crea archivo nuevo)",
            "output": "nombre de archivo de salida (p.ej. 'logo.svg' o 'photo.png')",
        }
    ],
    "explanation": "string: explicación para el usuario del resultado y cómo seguir",
}

KINDS = {
    "svg": ("inkscape", "Documento SVG completo (XML válido). Se escribe a disco; ideal para crear/crear de cero."),
    "inkscape-actions": ("inkscape", "Acciones CLI de Inkscape 1.x, una por línea: select-all;object-align;..."),
    "python-svg": ("inkscape", "Python 3 con SOLO librería estándar (xml.etree) que lee input y escribe output."),
    "inkex-python": ("inkscape", "Python con 'import inkex' (necesita la extensão runtime de Inkscape)."),
    "script-fu": ("gimp", "Script-Fu (TinyScheme) usando (gimp-version), (car (gimp-file-load ...)) ... (gimp-image-flatten) y file-png-save/file-jpeg-save."),
    "python-fu": ("gimp", "Python-Fu GIMP: `from gimpfu import *`; `pdb.gimp_image_flush(img)`; guardar con `pdb.gimp_file_save`."),
    "shell-export": ("inkscape", "Comandos de exportación/CLI seguros: `inkscape in.svg --export-type=png --export-filename=out.png`."),
}

SYSTEM_TEMPLATE = """Eres el motor de un agente de IA que controla **Inkscape** (vectores) y **GIMP** (bitmaps).
Tu salida es EXCLUSIVAMENTE un objeto JSON que el agente ejecuta. No escribas prosa fuera del JSON.

CONTRATO JSON (campos exactos):
{schema}

REGLAS DE INKSCAPE (vector)
1. Para CREAR o REDEÑAR usa "kind": "svg" y entrega el SVG completo. Debe empezar por
   `<?xml version="1.0" encoding="UTF-8"?>` y tener `xmlns="http://www.w3.org/2000/svg"`, `width`, `height` y `viewBox`.
2. Usa paths/bezier (`M`,`C`,`Q`), grupos `<g>`, `<defs>` con gradientes, `id` y `label` legibles,
   capas con `<group inkscape:label="...">` (namespace inkscape: `xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"`).
3. Nada de `<foreignObject>`, `<script>`, `<animate>` con JS, ni `xlink:href` a recursos externos.
4. Para CORREGIR un SVG existente: si el archivo está adjunto en el mensaje, usa "kind": "python-svg"
   y edítalo con `xml.etree.ElementTree`, o bien devuelve el SVG corregido completo ("svg").
5. Ajustes globales rápidos → "inkscape-actions": una acción por línea, SIN `--actions=`.
   Vocabulario VERIFICADO en Inkscape 1.4 (el agente lo comprueba contra `inkscape --action-list`
   de tu instalación y DESCARTA con un aviso lo que no exista; NO inventes nombres):
     select-all, select-clear, select-invert, select-by-id, select-by-selector, select-by-element,
     delete-selection, duplicate, selection-group, selection-make-bitmap-copy,
     object-align, object-align-on-canvas, object-distribute, object-flip-horizontal,
     object-flip-vertical, object-rotate-90-ccw, object-rotate-90-cw, object-remove-overlaps,
     object-release-clip, object-stroke-to-path, object-set-attribute,
     path-union, path-difference, path-intersection, path-simplify, path-break-apart,
     text-put-on-path, text-convert-to-glyphs, fit-canvas-to-selection, clone-unlink,
     file-open, file-new,
     export-area-page, export-area-drawing, export-area-snap, export-dpi, export-background,
     export-background-opacity, export-width, export-height, export-margin, export-text-to-path
   Con argumento se escriben `accion:valor` (p.ej. `export-dpi:300`, `export-background:#ffffff`).
   NO escribas `export-type`, `export-filename` ni `export-overwrite`: el agente los añade con el
   archivo de salida del paso. NO existen edit-delete, item-remove, select-none ni trace-bitmap
   (Inkscape no vectoriza por lotes: si te piden vectorizar un PNG, dilo en "notes" y propón
   potrace/autotrace como `shell-export` solo si el usuario lo confirma).
   El agente añade `--batch-process` automáticamente (sin eso, Inkscape 1.x IGNORA las acciones).
   Sin GUI no hay selección real: `select-all` + `delete-selection` puede no aplicar cambios; si
   necesitas certeza, edita el SVG con "svg" o "python-svg" en lugar de acciones.

REGLAS DE GIMP (bitmap)
6. Prefiere "script-fu" (funciona igual en GIMP 2.10 y 3.x). El agente antepone un preámbulo de
   compatibilidad con estos helpers, ÚSALOS para lo que cambia entre versiones:
     (ai-load "ruta")            → carga y devuelve la imagen
     (ai-save image "ruta")      → aplana y guarda (file-png-save en 2.10, gimp-file-save en 3.x)
     (ai-width image) / (ai-height image)     → dimensiones en px
     (ai-draw image) / (ai-flatten image)     → drawable activa / aplanada
     ai-g3                                      → #t si es GIMP 3+
   Estructura obligatoria: `(define (ai-run) … )` seguido de `(ai-run)`.
7. Rutas: escribe `{{INPUT}}` y `{{OUTPUT}}` como marcadores; el agente los reemplaza por rutas absolutas.
   Ejemplo mínimo válido en cualquier GIMP:
   (define (ai-run) (let* ((image (ai-load "{{INPUT}}"))) (gimp-image-scale image 1200 800)
     (ai-save image "{{OUTPUT}}") (gimp-image-delete image))) (ai-run)
7b. En GIMP 3 NO existen gimp-image-width, gimp-image-get-active-drawable, file-png-save,
   gimp-brightness-contrast ni gimp-curves-spline: usa los helpers ai-* o las variantes
   gimp-drawable-* / gimp-image-get-selected-drawables, y recuerda que en 3.x los accesores
   también devuelven listas ((car …)).
8. Imprime trazabilidad con `(gimp-message "...")` cuando hagas un cambio no obvio.
9. Nunca borres ni sobrescribas el archivo de entrada: la salida va a un archivo nuevo.
10. Para editar vectores NO uses GIMP; para editar píxeles NO uses Inkscape.

CALIDAD
11. Modela números realistas (dpi, tamaño en px, colores hex). Si falta un dato, decide algo razonable y dilo en "notes".
12. Máximo 4 pasos. Pasos cortos y comprobables. Si la petición es imposible, responde JSON con
    "steps": [] y explica en "summary"/"explanation" qué hace falta (eso es válido y no es un error).
13. El código debe ejecutarse sin intervención humana: ni `gimp-display-new`, ni `gimp-quit`, ni `sys.exit`,
    ni `input()`, ni red, ni subprocesos.

IDIOMA: escribe "summary", "notes" y "explanation" en el idioma del usuario (responde en español si el pedido está en español).
"""

TASK_TEMPLATE = """Objetivo: {task}

Modo: {mode}
Aplicación destino: {apps}
Espacio de trabajo: {workspace}
{inputs}
Devuelve SOLO el JSON del contrato."""

INPUT_BLOCK = """Archivos del proyecto (en el espacio de trabajo):
{listing}
{inline}
"""


def describe(path: str) -> str:
    from .images import describe as _d

    return _d(path)


def build_system_prompt() -> str:
    return SYSTEM_TEMPLATE.replace("{schema}", json.dumps(PLAN_SCHEMA, ensure_ascii=False, indent=1))


def describe_inputs(paths: List[str], include_svg_text: bool = True) -> str:
    """Bloque de contexto sobre archivos adjuntos (SVG inspeccionado, bitmaps listados)."""
    if not paths:
        return ""
    lines, inline = [], []
    for p in paths:
        if not os.path.isfile(p):
            lines.append(f"- {os.path.basename(p)} (NO EXISTE)")
            continue
        size = os.path.getsize(p)
        ext = os.path.splitext(p)[1].lower()
        info = describe(p) if ext in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff") else ""
        lines.append(f"- {os.path.basename(p)} [{ext or '?'}, {size} bytes]" + (f" → {info}" if info else ""))
        if ext == ".svg" and include_svg_text and size <= 60_000:
            try:
                with open(p, encoding="utf-8", errors="replace") as fh:
                    txt = fh.read()
            except OSError:
                continue
            inline.append(f"--- SVG {os.path.basename(p)} ---\n{txt}\n--- fin SVG ---")
        if ext in (".xmp", ".json"):
            try:
                with open(p, encoding="utf-8", errors="replace") as fh:
                    inline.append(f"--- {os.path.basename(p)} ---\n{fh.read()[:4000]}")
            except OSError:
                pass
    body = "\n".join(inline)
    return INPUT_BLOCK.format(listing="\n".join(lines), inline=body or "(sin contenido en línea; se adjuntan como imagen)")


def build_task_prompt(task: str, *, mode: str, apps: List[str], workspace: str,
                      inputs: Optional[List[str]] = None, extra: Optional[str] = None) -> str:
    return TASK_TEMPLATE.format(
        task=task.strip(),
        mode=mode,
        apps=", ".join(apps) if apps else "inkscape, gimp",
        workspace=workspace,
        inputs=(describe_inputs(inputs or []) + (f"\nNota del usuario: {extra}" if extra else "")),
    )


def build_messages(task: str, *, mode: str, apps: List[str], workspace: str,
                   inputs: Optional[List[str]] = None, extra: Optional[str] = None,
                   history: Optional[List[Dict[str, Any]]] = None,
                   image_paths: Optional[List[str]] = None,
                   include_svg_text: bool = True) -> List[Dict[str, Any]]:
    """Mensajes neutros (system + historial + turno actual con imágenes adjuntas)."""
    msgs: List[Dict[str, Any]] = [{"role": "system", "content": build_system_prompt()}]
    for turn in (history or [])[-6:]:
        if turn.get("role") in ("user", "assistant") and turn.get("content"):
            msgs.append({"role": turn["role"], "content": turn["content"], "images": []})
    listing = list(inputs or []) + list(image_paths or [])
    ctx = describe_inputs(listing, include_svg_text=include_svg_text) if listing else ""
    prompt = build_task_prompt(task, mode=mode, apps=apps, workspace=workspace,
                               inputs=inputs, extra=extra)
    if ctx:
        prompt += "\n" + ctx
    msgs.append({"role": "user", "content": prompt,
                 "images": [p for p in (image_paths or []) if _is_bitmap(p)]})
    return msgs


def _is_bitmap(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff")
