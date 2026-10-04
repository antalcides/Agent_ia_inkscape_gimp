#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agente de IA para GIMP 2.10 (Python-Fu clasico con 'gimpfu').

Se incluye como alternativa para instalaciones que todavia usan GIMP 2.10.
Para GIMP 3.0 usa agente_ia_gimp.py (GObject-Introspection).

Instalacion (Linux):
  ~/.config/GIMP/2.10/plug-ins/agente_ia_gimp_210.py   (con permiso de ejecucion)
"""

from __future__ import annotations

import os
import sys

from gimpfu import (pdb, register, pf_image, pf_drawable, pf_string, pf_int,  # noqa: F401
                    PF_IMAGE, PF_DRAWABLE, PF_STRING, PF_INT)

_here = os.path.dirname(os.path.abspath(__file__))
for candidate in (_here, os.path.join(_here, ".."), os.path.join(_here, "..", "..")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from core import providers as P  # noqa: E402
from core import bitmap_tools as bt  # noqa: E402
from core.config import load_config, default_output_dir, unique_path  # noqa: E402


def agente_ia_gimp(image, drawable, provider, model, prompt):
    """Crea o corrige la imagen con IA y anade el resultado como capa."""
    cfg = load_config()
    if not prompt:
        pdb.gimp_message("El pedido esta vacio.")
        return
    try:
        blob = P.generate_image(cfg, provider, model, prompt,
                                size=cfg.get("image_size", "1024x1024"))
    except Exception as exc:  # noqa: BLE001
        pdb.gimp_message("No se pudo generar/editar con IA: %s" % exc)
        return

    ext = bt.guess_extension(blob)
    out = default_output_dir(cfg)
    path = unique_path(out, "gimp_bitmap", ext)
    bt.save_bytes(blob, path)

    layer = pdb.gimp_file_load_layer(image, path)
    pdb.gimp_image_insert_layer(image, layer, None, 0)
    pdb.gimp_displays_flush()
    pdb.gimp_message("Capa de IA anadida. Copia guardada en: %s" % path)


register(
    "python-fu-agente-ia-gimp",
    "Agente IA: crear o corregir imagen",
    "Genera o corrige una imagen con cualquier proveedor de IA y la anade como capa.",
    "Agente IA", "Agente IA", "2026",
    "Agente IA: crear o corregir imagen",
    "*",
    [
        (PF_IMAGE, "image", "Imagen", None),
        (PF_DRAWABLE, "drawable", "Objeto", None),
        (PF_STRING, "provider", "Proveedor", "ollama"),
        (PF_STRING, "model", "Modelo", ""),
        (PF_STRING, "prompt", "Pedido (que crear o corregir)", ""),
    ],
    [],
    agente_ia_gimp,
    menu="<Image>/Filters/IA",
)
