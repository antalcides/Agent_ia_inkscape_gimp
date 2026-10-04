#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agente de IA para GIMP 3.0 (Python-Fu con GObject-Introspection).

Registra dos procedimientos dentro del menu:
  Filtros > IA > Agente IA: crear imagen
  Filtros > IA > Agente IA: corregir imagen

Reutiliza el nucleo compartido 'core/' (mismo que la interfaz y la extension de
Inkscape), por lo que soporta OpenAI, Anthropic, Gemini, OpenRouter, OmniRoute,
Ollama, LM Studio y cualquier endpoint compatible OpenAI.

Instalacion (Linux):
  cp agente_ia_gimp.py  ~/.config/GIMP/3.0/plug-ins/agente_ia_gimp/agente_ia_gimp.py
  chmod +x ~/.config/GIMP/3.0/plug-ins/agente_ia_gimp/agente_ia_gimp.py
Instalacion (Windows):
  copiar a  %APPDATA%\\GIMP\\3.0\\plug-ins\\agente_ia_gimp\\agente_ia_gimp.py
"""

from __future__ import annotations

import os
import sys
import tempfile

import gi

gi.require_version("Gimp", "3.0")
gi.require_version("Gegl", "0.4")
from gi.repository import Gimp, GObject, GLib  # noqa: E402

# --------------------------------------------------------------------------
# Nucleo compartido: se busca en la propia carpeta del plug-in y en la de arriba
# --------------------------------------------------------------------------
_here = os.path.dirname(os.path.abspath(__file__))
for candidate in (_here, os.path.join(_here, ".."), os.path.join(_here, "..", "..")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

try:
    from core import providers as P
    from core import bitmap_tools as bt
    from core.config import load_config, save_config, default_output_dir, unique_path
    _CORE_OK = True
except ImportError as exc:  # el plug-in avisa pero no rompe GIMP
    _CORE_OK = False
    _CORE_ERROR = str(exc)

PROC_CREATE = "plug-in-agente-ia-crear"
PROC_FIX = "plug-in-agente-ia-corregir"

PROVIDER_IDS = ["openai", "anthropic", "gemini", "openrouter", "omniroute",
                "ollama", "lmstudio", "custom"]


def _cfg():
    """Carga la configuracion guardada (compartida con la interfaz)."""
    return load_config()


def _export_image_png(image):
    """Exporta la imagen GIMP actual a un PNG temporal y devuelve (bytes, ruta)."""
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.close()
    path = tmp.name
    Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, image,
                   Gimp.file_new_for_path(path), None)
    with open(path, "rb") as fh:
        return fh.read(), path


def _load_png_as_layer(image, png_bytes):
    """Carga bytes PNG como una nueva capa dentro de la imagen actual."""
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.write(png_bytes)
    tmp.close()
    loaded = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE,
                            Gimp.file_new_for_path(tmp.name))
    layer = loaded.get_layers()[0] if hasattr(loaded, "get_layers") else None
    if layer is not None:
        new_layer = layer.copy()
        image.insert_layer(new_layer, None, -1)
    else:
        # API alternativa: crear capa a partir del archivo
        layer = Gimp.Layer.new_from_file(image, tmp.name, "Capa IA",
                                         Gimp.LayerMode.NORMAL,
                                         100.0, Gimp.LayerType.from_string("RGBA"),
                                         0, 0, 0)
        image.insert_layer(layer, None, -1)
    image.displays_flush() if hasattr(image, "displays_flush") else None
    try:
        os.unlink(tmp.name)
    except OSError:
        pass


def _run_create(procedure, run_mode, image, drawable, provider, model, prompt,
                config):
    """Crea una imagen nueva con IA y la inserta como capa."""
    if not _CORE_OK:
        return procedure.new_return_values(
            Gimp.PDBStatusType.EXECUTION_ERROR,
            GLib.Error("No se encontro el nucleo 'core': %s" % _CORE_ERROR))
    if not prompt.strip():
        return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR,
                                           GLib.Error("El pedido esta vacio."))
    cfg = _cfg()
    try:
        blob = P.generate_image(cfg, provider, model, prompt,
                                size=cfg.get("image_size", "1024x1024"))
        _load_png_as_layer(image, blob)
        out = default_output_dir(cfg)
        path = unique_path(out, "gimp_bitmap", bt.guess_extension(blob))
        bt.save_bytes(blob, path)
        Gimp.message("Imagen generada y anadida como capa.\nCopia: %s" % path)
    except Exception as exc:  # noqa: BLE001
        return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR,
                                           GLib.Error(str(exc)))
    return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, None)


def _run_fix(procedure, run_mode, image, drawable, provider, model, prompt, config):
    """Corrige la imagen actual: edicion por API o script de GIMP equivalente."""
    if not _CORE_OK:
        return procedure.new_return_values(
            Gimp.PDBStatusType.EXECUTION_ERROR,
            GLib.Error("No se encontro el nucleo 'core': %s" % _CORE_ERROR))
    cfg = _cfg()
    try:
        blob, tmp = _export_image_png(image)
        conf = P.provider_conf(cfg, provider)
        if conf.get("supports_image_edit"):
            edited = P.edit_image(cfg, provider, model, blob, prompt,
                                  size=cfg.get("image_size", "1024x1024"),
                                  filename="gimp_entrada.png")
            _load_png_as_layer(image, edited)
            Gimp.message("Imagen corregida y anadida como nueva capa.")
        else:
            # Sin edicion por API: se pide un script de GIMP/Python
            analysis = ""
            try:
                analysis = P.describe_image(
                    cfg, provider, model, blob,
                    "Describe los defectos de esta imagen y los arreglos "
                    "convenientes para: %s" % prompt)
            except Exception as exc:  # noqa: BLE001
                analysis = "(vision no disponible: %s)" % exc
            code = P.chat(cfg, provider, model, [
                {"role": "system", "content":
                 "Eres experto en automatizacion de GIMP con Python-Fu. Devuelve "
                 "solo un bloque ```python``` con un script que corrija la imagen "
                 "(color, ruido, nitidez, recorte) y la guarde en PNG."},
                {"role": "user", "content":
                 "Analisis: %s\n\nPeticion: %s" % (analysis, prompt)}])
            out = default_output_dir(cfg)
            path = unique_path(out, "script_gimp", "py")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(code)
            Gimp.message("El proveedor no edita bitmaps por API.\n"
                         "Se genero un script de GIMP/Python en:\n%s" % path)
        try:
            os.unlink(tmp)
        except OSError:
            pass
    except Exception as exc:  # noqa: BLE001
        return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR,
                                           GLib.Error(str(exc)))
    return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, None)


class AgenteIAGimp(Gimp.PlugIn):
    """Plug-in principal de GIMP 3.0."""

    def do_query_procedures(self):
        return [PROC_CREATE, PROC_FIX]

    def do_set_i18n(self, name):
        return False

    def _add_args(self, procedure, creator):
        procedure.add_string_argument("provider", "Proveedor",
                                      "Proveedor de IA", PROVIDER_IDS[5],
                                      GObject.ParamFlags.READWRITE)
        procedure.add_string_argument("model", "Modelo",
                                      "Nombre del modelo", "",
                                      GObject.ParamFlags.READWRITE)
        procedure.add_string_argument("prompt", "Pedido",
                                      "Descripcion del trabajo a realizar", "",
                                      GObject.ParamFlags.READWRITE)
        procedure.add_enum_argument("run-mode", "Modo de ejecucion",
                                    "Modo de ejecucion",
                                    Gimp.RunMode, Gimp.RunMode.NONINTERACTIVE,
                                    GObject.ParamFlags.READWRITE)

    def do_create_procedure(self, name):
        if name == PROC_CREATE:
            procedure = Gimp.ImageProcedure.new(self, name,
                                                Gimp.PDBProcType.PLUGIN,
                                                _run_create, None)
            procedure.set_menu_label("Agente IA: crear imagen")
            procedure.add_menu_path("<Image>/Filters/IA")
            procedure.set_documentation("Crea una imagen con IA y la anade como capa.",
                                        "Usa cualquier proveedor configurado.",
                                        name)
            procedure.set_attribution("Agente IA", "Agente IA", "2026")
            procedure.add_image_argument("image", "Imagen", "Imagen destino",
                                         GObject.ParamFlags.READWRITE)
            procedure.add_drawable_argument("drawable", "Objeto", "Objeto de trabajo",
                                            GObject.ParamFlags.READWRITE)
            procedure.add_string_argument("provider", "Proveedor", "Proveedor de IA",
                                          "ollama", GObject.ParamFlags.READWRITE)
            procedure.add_string_argument("model", "Modelo", "Modelo", "",
                                          GObject.ParamFlags.READWRITE)
            procedure.add_string_argument("prompt", "Pedido", "Que imagen crear", "",
                                          GObject.ParamFlags.READWRITE)
            procedure.add_enum_argument("run-mode", "Modo", "Modo de ejecucion",
                                        Gimp.RunMode, Gimp.RunMode.NONINTERACTIVE,
                                        GObject.ParamFlags.READWRITE)
            return procedure

        if name == PROC_FIX:
            procedure = Gimp.ImageProcedure.new(self, name,
                                                Gimp.PDBProcType.PLUGIN,
                                                _run_fix, None)
            procedure.set_menu_label("Agente IA: corregir imagen")
            procedure.add_menu_path("<Image>/Filters/IA")
            procedure.set_documentation("Corrige la imagen con IA (capa nueva).",
                                        "Corrige color, ruido, nitidez o recorte.",
                                        name)
            procedure.set_attribution("Agente IA", "Agente IA", "2026")
            procedure.add_image_argument("image", "Imagen", "Imagen a corregir",
                                         GObject.ParamFlags.READWRITE)
            procedure.add_drawable_argument("drawable", "Objeto", "Objeto de trabajo",
                                            GObject.ParamFlags.READWRITE)
            procedure.add_string_argument("provider", "Proveedor", "Proveedor de IA",
                                          "ollama", GObject.ParamFlags.READWRITE)
            procedure.add_string_argument("model", "Modelo", "Modelo", "",
                                          GObject.ParamFlags.READWRITE)
            procedure.add_string_argument("prompt", "Pedido", "Que corregir", "",
                                          GObject.ParamFlags.READWRITE)
            procedure.add_enum_argument("run-mode", "Modo", "Modo de ejecucion",
                                        Gimp.RunMode, Gimp.RunMode.NONINTERACTIVE,
                                        GObject.ParamFlags.READWRITE)
            return procedure

        return None


Gimp.main(AgenteIAGimp.__gtype__, sys.argv)
