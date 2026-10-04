# -*- coding: utf-8 -*-
"""Utilidades para extraer, limpiar y validar SVG devuelto por un LLM."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

SVG_NS = "http://www.w3.org/2000/svg"

# System prompt de sistema para el modo vectorial.
SVG_SYSTEM_PROMPT = (
    "Eres un experto en graficos vectoriales SVG e Inkscape. "
    "Devuelve SIEMPRE SVG valido y autocontenido, sin explicaciones fuera del codigo. "
    "Reglas: usa el espacio de nombres xmlns=\"http://www.w3.org/2000/svg\"; "
    "incluye los atributos width, height y viewBox; agrupa con <g>; "
    "no uses recursos externos ni fuentes de red; "
    "prefiere formas geometricas, trazos <path> y estilos con atributos fill y stroke. "
    "Envuelve la respuesta en un bloque ```svg ... ```. "
    "Si el usuario pide corregir un SVG existente, devuelve el documento completo ya corregido."
)

BITMAP_PROMPT_SYSTEM = (
    "Eres un director de arte experto en generacion de imagenes. "
    "Reescribe la peticion del usuario como un prompt tecnico, detallado y en un solo "
    "parrafo, optimizado para un modelo de difusion (composicion, iluminacion, estilo, "
    "paleta, encuadre). No anadas texto explicativo, solo el prompt final."
)


def extract_svg(text):
    """Extrae el primer bloque SVG de un texto (con o sin cercas markdown)."""
    if not text:
        return ""
    fence = re.search(r"```(?:svg|xml)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fence:
        candidate = fence.group(1).strip()
        if "<svg" in candidate.lower():
            return candidate
    match = re.search(r"<svg\b.*?</svg>", text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(0).strip()
    return ""


def clean_svg(svg_text):
    """Normaliza un SVG: quita basura, garantiza xmlns y viewBox."""
    if not svg_text:
        return ""
    svg_text = svg_text.strip()
    svg_text = re.sub(r"^```[a-zA-Z]*|```$", "", svg_text).strip()
    # Declaracion XML duplicada o incrustada
    svg_text = re.sub(r"<\?xml.*?\?>", "", svg_text, flags=re.DOTALL)
    svg_text = re.sub(r"<!DOCTYPE.*?>", "", svg_text, flags=re.DOTALL)
    if "<svg" not in svg_text.lower():
        return ""
    if "xmlns=" not in svg_text:
        svg_text = svg_text.replace("<svg", '<svg xmlns="%s"' % SVG_NS, 1)
    if "viewBox" not in svg_text and "viewbox" not in svg_text.lower():
        width = _attr(svg_text, "width")
        height = _attr(svg_text, "height")
        if width and height:
            w = _num(width)
            h = _num(height)
            svg_text = re.sub(r"<svg", '<svg viewBox="0 0 %s %s"' % (w, h), 1)
    return svg_text


def _attr(tag, name):
    m = re.search(r'<svg[^>]*\b%s="([^"]+)"' % name, tag, re.IGNORECASE)
    return m.group(1) if m else ""


def _num(value):
    m = re.match(r"[\d.]+", value or "")
    return m.group(0) if m else "100"


def is_valid_svg(svg_text):
    """Comprueba que el SVG se pueda parsear y contiene la raiz svg."""
    if not svg_text or "<svg" not in svg_text.lower():
        return False
    try:
        root = ET.fromstring(svg_text)
    except ET.ParseError:
        return False
    return root.tag.split("}")[-1].lower() == "svg"


def describe_svg(svg_text, max_len=6000):
    """Resumen textual del SVG para pasarlo como contexto al modelo."""
    if not svg_text:
        return "(documento vacio)"
    stats = {}
    try:
        root = ET.fromstring(svg_text)
        for node in root.iter():
            tag = node.tag.split("}")[-1]
            stats[tag] = stats.get(tag, 0) + 1
    except ET.ParseError:
        pass
    lines = ["Resumen de elementos: %s" % (", ".join(
        "%s x%d" % (k, v) for k, v in sorted(stats.items())) or "sin datos")]
    lines.append("--- SVG actual (recortado) ---")
    lines.append(svg_text[:max_len])
    return "\n".join(lines)


def list_element_ids(svg_text):
    return re.findall(r'\bid="([^"]+)"', svg_text or "")


def minimal_svg(width=256, height=256):
    """SVG vacio de referencia."""
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<svg xmlns="%s" width="%d" height="%d" viewBox="0 0 %d %d"></svg>'
            % (SVG_NS, width, height, width, height))
