#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Extension de Inkscape 1.x: Agente IA para crear y corregir SVG.

Usa el nucleo compartido (core/providers.py) para hablar con cualquier
proveedor y aplica el SVG resultante directamente al documento de Inkscape.

Instalacion (Linux):
  cp -r inkscape_ext/* ~/.config/inkscape/extensions/
Instalacion (Windows):
  copiar los archivos a %APPDATA%\\inkscape\\extensions\\
"""

from __future__ import annotations

import os
import sys

import inkex

# ---------------------------------------------------------------------------
# Localizar el nucleo compartido (core/) instalado junto a la extension
# ---------------------------------------------------------------------------
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

try:
    from core import providers as P
    from core import svg_tools as st
    from core.config import load_config, save_config, default_output_dir, unique_path
except ImportError:
    # Estructura plana (todo dentro de la misma carpeta de extensiones)
    sys.path.insert(0, os.path.join(_here, ".."))
    from core import providers as P
    from core import svg_tools as st
    from core.config import load_config, save_config, default_output_dir, unique_path


class AgenteIAVectorial(inkex.EffectExtension):
    """Extension de efecto que consulta a un modelo de IA y aplica el SVG."""

    def add_arguments(self, pars):
        pars.add_argument("--provider", default="ollama")
        pars.add_argument("--model", default="")
        pars.add_argument("--mode", default="crear")
        pars.add_argument("--prompt", default="")
        pars.add_argument("--save_copy", type=inkex.Boolean, default=True)
        pars.add_argument("--api_key", default="")
        pars.add_argument("--base_url", default="")
        pars.add_argument("--temperature", type=float, default=0.2)
        pars.add_argument("--max_tokens", type=int, default=8192)

    # ------------------------------------------------------------------ utils
    def _cfg(self):
        cfg = load_config()
        opts = self.options
        cfg["provider"] = opts.provider
        cfg["model"] = opts.model or cfg.get("model", "")
        cfg["temperature"] = opts.temperature
        cfg["max_tokens"] = opts.max_tokens
        if opts.api_key:
            cfg.setdefault("api_keys", {})[opts.provider] = opts.api_key
        if opts.base_url:
            cfg.setdefault("base_url_override", {})[opts.provider] = opts.base_url
        try:
            save_config(cfg)
        except Exception as exc:  # noqa: BLE001
            inkex.errormsg("Aviso: no se pudo guardar la configuracion: %s" % exc)
        return cfg

    def _document_svg(self):
        """Serializa el documento SVG actual a texto."""
        return self.document.tostring().decode("utf-8")

    def _selected_svg(self):
        """Serializa la seleccion actual (o el documento completo si no hay seleccion)."""
        ids = self.options.ids
        if ids:
            nodes = [self.svg.getElementById(i) for i in ids]
            nodes = [n for n in nodes if n is not None]
            if nodes:
                wrapper = inkex.Group()
                for node in nodes:
                    wrapper.append(node)
                return wrapper.tostring().decode("utf-8")
        return self._document_svg()

    def _parse_result(self, svg_text):
        """Convierte el texto SVG devuelto por el modelo en un arbol inkex."""
        try:
            return inkex.load_svg(svg_text.encode("utf-8")).getroot()
        except Exception as exc:  # noqa: BLE001
            inkex.errormsg("El SVG devuelto no se pudo interpretar: %s" % exc)
            return None

    def _replace_document(self, new_root):
        """Sustituye el contenido del documento actual por el SVG nuevo."""
        # Se conserva la raiz del documento y se reemplazan sus hijos.
        for child in list(self.document.getroot()):
            self.document.getroot().remove(child)
        for child in list(new_root):
            self.document.getroot().append(child)
        for attr in ("width", "height", "viewBox"):
            if attr in new_root.attrib:
                self.document.getroot().set(attr, new_root.attrib[attr])

    def _append_layer(self, new_root):
        """Anade el SVG nuevo como una capa, conservando el documento original."""
        layer = self.svg.add(inkex.Layer.new("Agente IA"))
        for child in list(new_root):
            tag = child.tag.split("}")[-1]
            if tag in ("defs", "namedview"):
                continue
            layer.append(child)

    def _save_copy(self, svg_text, stem="agente_ia"):
        try:
            out_dir = default_output_dir(self._cfg())
            path = unique_path(out_dir, stem, "svg")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(svg_text)
            return path
        except Exception as exc:  # noqa: BLE001
            inkex.errormsg("No se pudo guardar la copia: %s" % exc)
            return ""

    # ------------------------------------------------------------------- run
    def effect(self):
        opts = self.options
        if not (opts.prompt or "").strip():
            inkex.errormsg("Escribe una descripcion en el campo 'Descripcion del trabajo'.")
            return

        cfg = self._cfg()
        mode = opts.mode or "crear"

        if mode == "corregir_seleccion":
            source = self._selected_svg()
        elif mode == "corregir_documento":
            source = self._document_svg()
        else:
            source = ""

        if mode == "crear":
            user = opts.prompt
        else:
            user = ("%s\n\nDocumento SVG actual que debes corregir y devolver completo:\n%s"
                    % (opts.prompt, st.describe_svg(source, max_len=12000)))

        messages = [
            {"role": "system", "content": st.SVG_SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ]

        inkex.utils.debug("Consultando a %s (%s)..."
                          % (opts.provider, opts.model or "(modelo por defecto)"))
        try:
            answer = P.chat(cfg, opts.provider, opts.model, messages,
                            temperature=opts.temperature,
                            max_tokens=opts.max_tokens)
        except Exception as exc:  # noqa: BLE001
            inkex.errormsg("Error al consultar al proveedor:\n%s" % exc)
            return

        svg_text = st.clean_svg(st.extract_svg(answer))
        if not svg_text or not st.is_valid_svg(svg_text):
            inkex.errormsg("El modelo no devolvio un SVG valido. Respuesta:\n%s"
                           % answer[:1200])
            return

        root = self._parse_result(svg_text)
        if root is None:
            return

        if mode == "crear":
            self._append_layer(root)
            if opts.save_copy:
                path = self._save_copy(svg_text, "vector_ia")
                if path:
                    inkex.utils.debug("Copia guardada en: %s" % path)
        else:
            self._replace_document(root)
            if opts.save_copy:
                path = self._save_copy(svg_text, "corregido_ia")
                if path:
                    inkex.utils.debug("Documento corregido guardado en: %s" % path)

        inkex.utils.debug("Listo. Revisa el documento en el lienzo.")


if __name__ == "__main__":
    AgenteIAVectorial().run()
