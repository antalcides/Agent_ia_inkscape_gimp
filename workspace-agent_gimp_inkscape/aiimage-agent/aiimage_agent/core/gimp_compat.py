"""Compatibilidad Script-Fu entre GIMP 2.10 y GIMP 3.x.

GIMP 3 cambió el PDB de forma ruidosa. Datos verificados ejecutando GIMP 3.0.4 real:

  gimp-image-get-active-drawable        NO existe  → gimp-image-get-selected-drawables
                                                     devuelve (#(id …)) : lista con un VECTOR
  gimp-image-get-active-layer           NO existe  → gimp-image-get-selected-layers (igual)
  gimp-image-width / -height            NO existen → gimp-image-get-width / -get-height
  file-png-save / file-jpeg-save        NO existen → gimp-file-save (run-mode image path)
                                                     ¡sin argumento drawable!
  gimp-curves-spline / -brightness-contrast / -hue-saturation  → versión gimp-drawable-*
  gimp-quit                            sí existe, pero tras un fallo GIMP 3 se queda vivo
                                       (por eso el agente usa --quit y mata el proceso)

En lugar de reescribir el código que escribió el modelo, el agente **antepone un preámbulo**
que define los nombres antiguos como adaptadores cuando faltan. Así el mismo plan funciona en
2.10 y en 3.x, y el script que ve el usuario sigue siendo legible.

El preámbulo además expone helpers (`ai-load`, `ai-save`, `ai-width`, `ai-height`, `ai-draw`,
`ai-flatten`, `ai-g3`) que el prompt pide usar preferentemente.
"""

from __future__ import annotations

import re
from typing import List, Tuple

REMOVED_IN_G3: List[Tuple[str, str]] = [
    ("gimp-image-get-active-drawable", "gimp-image-get-selected-drawables  (→ (vector-ref (car …) 0))"),
    ("gimp-image-get-active-layer", "gimp-image-get-selected-layers"),
    ("gimp-image-width", "gimp-image-get-width"),
    ("gimp-image-height", "gimp-image-get-height"),
    ("file-png-save", "gimp-file-save run-mode image path  (sin drawable)"),
    ("file-jpeg-save", "gimp-file-save run-mode image path"),
    ("gimp-curves-spline", "gimp-drawable-curves-spline (opera sobre la drawable)"),
    ("gimp-brightness-contrast", "gimp-drawable-brightness-contrast"),
    ("gimp-hue-saturation", "gimp-drawable-hue-saturation"),
    ("gimp-levels-stretch", "gimp-drawable-levels-stretch"),
    ("gimp-convert-grayscale", "gimp-image-convert-grayscale"),
    ("gimp-image-get-color-profile", "gimp-image-get-color-managed → usa (ai-width)… o Script-Fu 2.10"),
]

NEW_IN_G3: List[Tuple[str, str]] = [
    ("gimp-image-get-selected-drawables", "gimp-image-get-active-drawable (el preámbulo lo define)"),
    ("gimp-image-get-selected-layers", "gimp-image-get-active-layer"),
    ("gimp-image-get-width", "gimp-image-width"),
    ("gimp-image-get-height", "gimp-image-height"),
    ("gimp-file-save", "file-png-save / file-jpeg-save"),
    ("gimp-drawable-curves-spline", "gimp-curves-spline (sobre la imagen)"),
    ("gimp-drawable-brightness-contrast", "gimp-brightness-contrast"),
    ("gimp-drawable-hue-saturation", "gimp-hue-saturation"),
]

PRELUDE = r"""; ==== AI Image Agent · preámbulo de compatibilidad GIMP 2.10 / 3.x ====
(define ai-g3 (if (> (string->number (substring (car (gimp-version)) 0 1)) 2) #t #f))

(define (ai-first-item lst)
  "saca el primer id de estructuras (#(id)) o (id) que devuelve el PDB"
  (cond ((null? lst) #f)
        ((vector? (car lst)) (if (> (vector-length (car lst)) 0) (vector-ref (car lst) 0) #f))
        ((pair? (car lst)) (car (car lst)))
        (else (car lst))))

(define (ai-width image) (car (if ai-g3 (gimp-image-get-width image) (gimp-image-width image))))
(define (ai-height image) (car (if ai-g3 (gimp-image-get-height image) (gimp-image-height image))))
(define (ai-flatten image) (car (gimp-image-flatten image)))
(define (ai-draw image)
  (if ai-g3
      (let ((it (ai-first-item (gimp-image-get-selected-drawables image))))
        (if it it (ai-flatten image)))
      (car (gimp-image-get-active-drawable image))))
(define (ai-load path) (car (gimp-file-load RUN-NONINTERACTIVE path path)))
(define (ai-save image path)
  (gimp-image-flatten image)
  (if ai-g3
      (gimp-file-save RUN-NONINTERACTIVE image path)
      (file-png-save RUN-NONINTERACTIVE image (ai-flatten image) path path 0 9 1 1 1 1 1)))
(define (ai-info tag image)
  (gimp-message (string-append tag " " (number->string (ai-width image)) "x"
                               (number->string (ai-height image)) " gimp3=" (if ai-g3 "si" "no"))))

; --- adaptadores para que el código estilo 2.10 corra en GIMP 3 ---
(if (not (defined? 'gimp-image-width))
    (define (gimp-image-width image) (gimp-image-get-width image)))
(if (not (defined? 'gimp-image-height))
    (define (gimp-image-height image) (gimp-image-get-height image)))
(if (not (defined? 'gimp-image-get-active-drawable))
    (define (gimp-image-get-active-drawable image) (list (ai-draw image))))
(if (not (defined? 'gimp-image-get-active-layer))
    (define (gimp-image-get-active-layer image) (list (ai-draw image))))
(if (not (defined? 'file-png-save))
    (define (file-png-save rm image drawable filename raw . rest) (gimp-file-save rm image filename)))
(if (not (defined? 'file-jpeg-save))
    (define (file-jpeg-save rm image drawable filename raw . rest) (gimp-file-save rm image filename)))
(define ai-agent-ready #t)
; ==== fin del preámbulo (el plan del modelo va debajo) ====
"""

QUIT_RE = re.compile(r"\(\s*gimp-quit\s*(?:0\s*)?\)")


def major_from_version(text: str) -> int:
    m = re.search(r"(\d+)\.(\d+)", text or "")
    return int(m.group(1)) if m else 0


def wrap_script(code: str, gimp_major: int, *, with_prelude: bool = True) -> Tuple[str, List[str]]:
    """Devuelve (script_final, notas). `script_final` se carga con `(load …)` desde GIMP."""
    notes: List[str] = []
    body = (code or "").strip()
    if QUIT_RE.search(body):
        body = QUIT_RE.sub("", body)
        notes.append("se quitó (gimp-quit …) del script: el agente controla la salida de GIMP")
    if not body:
        notes.append("script vacío: no hay nada que ejecutar")
        return (PRELUDE if with_prelude else ""), notes
    for name, repl in compat_hits(body, gimp_major):
        notes.append(f"GIMP {gimp_major}.x no tiene `{name}` → sustituido por el adaptador "
                     f"del preámbulo ({repl}); revisa el resultado")
    if with_prelude:
        if re.match(r"\s*\(define\s+ai-run\b|\(define\s*\(ai-run", body):
            wrapped = body
        else:
            indented = "\n".join(("  " + ln) if ln.strip() else ln for ln in body.splitlines())
            wrapped = "(define (ai-run)\n" + indented + "\n)\n(ai-run)"
        return PRELUDE + "\n" + wrapped, notes
    return body, notes


def compat_hits(code: str, gimp_major: int) -> List[Tuple[str, str]]:
    """Qué nombres ausentes usa el script y contra qué se cambian."""
    table = REMOVED_IN_G3 if gimp_major >= 3 else NEW_IN_G3
    hits: List[Tuple[str, str]] = []
    for name, repl in table:
        if re.search(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])", code or ""):
            hits.append((name, repl))
    return hits


def compat_warnings(code: str, gimp_major: int) -> List[str]:
    warns = [f"{'' if gimp_major >= 3 else 'GIMP 2.10 no tiene'}{'GIMP 3 no tiene' if gimp_major >= 3 else ''}"
             f" `{name}`: en {gimp_major}.x usa `{repl}`."
             for name, repl in compat_hits(code, gimp_major)]
    low = (code or "").lower()
    if any(h in low for h in ("(ai-save", "(ai-load", "(ai-draw", "(ai-width", "(ai-height")):
        warns.append("el script usa los helpers ai-* del agente (válidos en GIMP 2.10 y 3.x).")
    if "gimp-display-new" in low:
        warns.append("gimp-display-new abre ventanas: innecesario en modo batch.")
    if "(gimp-quit" in low:
        warns.append("(gimp-quit 0) lo gestiona el agente; se quita del script.")
    return warns


def scheme_balance(code: str) -> Tuple[bool, str]:
    """Chequeo rápido de paréntesis (evita lanzar GIMP para algo que no va a compilar)."""
    depth = 0
    in_str = False
    esc = False
    for i, c in enumerate(code or ""):
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth < 0:
                return False, f"paréntesis de cierre sobrante en la posición {i}"
    if depth != 0:
        return False, f"{depth} paréntesis(es) sin cerrar"
    if in_str:
        return False, "cadena sin cerrar"
    return True, ""
