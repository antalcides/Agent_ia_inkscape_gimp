# -*- coding: utf-8 -*-
"""Prueba de humo del nucleo sin red: simula respuestas de los proveedores."""
import io
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import providers as P
from core import svg_tools as st
from core.config import load_config

cfg = load_config()
cfg["api_keys"] = {"openai": "test", "openrouter": "test"}
cfg["base_url_override"] = {"ollama": "http://localhost:11434/v1"}

# --- 1. Simulacion de la respuesta de chat (familia OpenAI) ----------------
fake_chat = {"choices": [{"message": {"content":
    "Aqui tienes:\n```svg\n<svg xmlns=\"http://www.w3.org/2000/svg\" "
    "width=\"100\" height=\"100\" viewBox=\"0 0 100 100\">"
    "<circle cx=\"50\" cy=\"50\" r=\"40\" fill=\"#4f8cff\"/></svg>\n```"}}]}

captured = {}


def fake_urlopen(req, timeout=None):
    captured["url"] = req.full_url
    captured["headers"] = dict(req.headers)
    body = json.dumps(fake_chat).encode()
    resp = io.BytesIO(body)
    resp.__enter__ = lambda *a: resp
    resp.__exit__ = lambda *a: False
    resp.read = lambda: body
    return resp


urllib.request.urlopen = fake_urlopen

out = P.chat(cfg, "openai", "gpt-4o", [{"role": "user", "content": "dibuja un circulo"}])
assert "svg" in out.lower(), "chat() no devolvio contenido"
assert captured["url"].endswith("/v1/chat/completions"), captured["url"]
assert "Authorization" in captured["headers"], "falta la cabecera de autorizacion"
print("[OK] chat OpenAI-compatible ->", captured["url"])

# --- 2. Extraccion y validacion del SVG -----------------------------------
svg = st.clean_svg(st.extract_svg(out))
assert st.is_valid_svg(svg), "el SVG extraido no es valido"
assert 'xmlns="http://www.w3.org/2000/svg"' in svg
print("[OK] SVG extraido y validado ->", svg[:60], "...")
print("[OK] ids encontrados ->", st.list_element_ids(svg))

# --- 3. Resumen del documento ---------------------------------------------
print("[OK] describe_svg ->", st.describe_svg(svg).splitlines()[0])

# --- 4. Cabeceras de Anthropic y URLs por proveedor ------------------------
conf = P.provider_conf(cfg, "anthropic")
head = P._auth_headers(conf, "secreta")
assert head["x-api-key"] == "secreta" and head["anthropic-version"] == "2023-06-01"
print("[OK] cabeceras Anthropic ->", head)

for pid, expected in [("openai", "/v1"), ("anthropic", "/v1"),
                      ("gemini", "/v1beta"), ("openrouter", "/api/v1"),
                      ("ollama", "/v1"), ("lmstudio", "/v1")]:
    url = P.provider_conf(cfg, pid)["base_url"]
    assert expected in url, (pid, url)
print("[OK] URLs base de los 8 proveedores coherentes")

# --- 5. Multipart para edicion de imagen ----------------------------------
body, ctype = P._multipart({"model": "gpt-image-1", "prompt": "corrige"},
                           {"image": ("a.png", b"\x89PNG\r\n\x1a\n", "image/png")})
assert b'filename="a.png"' in body and ctype.startswith("multipart/form-data")
print("[OK] multipart de edicion de imagen construido:", ctype[:40], "...")

# --- 6. Deteccion de formato y tamano -------------------------------------
from core import bitmap_tools as bt
print("[OK] extension detectada ->", bt.guess_extension(b"\x89PNG\r\n\x1a\n"))
print("[OK] human_size ->", bt.human_size(2048))

print("\nTODAS LAS PRUEBAS DE HUMO PASARON")
