# -*- coding: utf-8 -*-
"""
Capa de proveedores de IA, agnostica y sin dependencias externas.

Se usa EXCLUSIVAMENTE la biblioteca estandar (urllib) para que el modulo
funcione tambien dentro del interprete Python embebido de Inkscape y de GIMP,
que no incluye 'requests'.

Proveedores soportados:
  - OpenAI            (API compatible OpenAI, nube)
  - Anthropic         (API Messages)
  - Gemini            (Google AI Studio / generateContent)
  - OpenRouter        (API compatible OpenAI, nube)
  - OmniRoute         (API compatible OpenAI, nube o gateway propio)
  - Ollama            (local, /v1 compatible OpenAI)
  - LM Studio         (local, /v1 compatible OpenAI)
  - Custom            (cualquier endpoint compatible OpenAI)
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_TIMEOUT = 600  # segundos

# ---------------------------------------------------------------------------
# Catalogo de proveedores. Todo es editable desde config.json
# ---------------------------------------------------------------------------
PROVIDERS = {
    "openai": {
        "label": "OpenAI (nube)",
        "kind": "openai",
        "base_url": "https://api.openai.com/v1",
        "api_key_env": "OPENAI_API_KEY",
        "needs_key": True,
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini", "o4-mini"],
        "vision_models": ["gpt-4o", "gpt-4.1"],
        "image_model": "gpt-image-1",
        "supports_image": True,
        "supports_image_edit": True,
        "notes": "Texto, vision y generacion/edicion de imagenes con gpt-image-1.",
    },
    "anthropic": {
        "label": "Anthropic (nube)",
        "kind": "anthropic",
        "base_url": "https://api.anthropic.com/v1",
        "api_key_env": "ANTHROPIC_API_KEY",
        "needs_key": True,
        "models": ["claude-sonnet-4-5", "claude-opus-4-1", "claude-3-5-haiku-latest"],
        "vision_models": ["claude-sonnet-4-5", "claude-opus-4-1"],
        "image_model": "",
        "supports_image": False,
        "supports_image_edit": False,
        "notes": "Muy bueno para SVG y codigo. No genera imagenes bitmap propias: "
                 "para bitmaps se devuelve un script de GIMP/Python ejecutable.",
    },
    "gemini": {
        "label": "Google Gemini (nube)",
        "kind": "gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "api_key_env": "GEMINI_API_KEY",
        "needs_key": True,
        "models": ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash"],
        "vision_models": ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash"],
        "image_model": "imagen-3.0-generate-002",
        "supports_image": True,
        "supports_image_edit": False,
        "notes": "Texto, vision y generacion de imagenes con Imagen.",
    },
    "openrouter": {
        "label": "OpenRouter (nube)",
        "kind": "openai",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key_env": "OPENROUTER_API_KEY",
        "needs_key": True,
        "models": [
            "openai/gpt-4o-mini",
            "anthropic/claude-sonnet-4.5",
            "google/gemini-2.5-pro",
            "meta-llama/llama-3.3-70b-instruct",
            "qwen/qwen-2.5-coder-32b-instruct",
        ],
        "vision_models": ["openai/gpt-4o-mini", "anthropic/claude-sonnet-4.5",
                          "google/gemini-2.5-pro"],
        "image_model": "",
        "supports_image": False,
        "supports_image_edit": False,
        "notes": "Cientos de modelos con una sola clave. Pulsa 'Cargar modelos' "
                 "para obtener la lista real.",
    },
    "omniroute": {
        "label": "OmniRoute (nube o gateway propio)",
        "kind": "openai",
        "base_url": "https://api.omniroute.ai/v1",
        "api_key_env": "OMNIROUTE_API_KEY",
        "needs_key": False,
        "models": [],
        "vision_models": [],
        "image_model": "",
        "supports_image": False,
        "supports_image_edit": False,
        "notes": "Router compatible OpenAI. Ajusta la URL base y la clave segun tu "
                 "instalacion (si es local, algo como http://localhost:8080/v1).",
    },
    "ollama": {
        "label": "Ollama (local)",
        "kind": "openai",
        "base_url": "http://localhost:11434/v1",
        "api_key_env": "OLLAMA_API_KEY",
        "needs_key": False,
        "models": ["llama3.2", "qwen2.5-coder", "mistral", "llava"],
        "vision_models": ["llama3.2-vision", "llava", "qwen2.5vl"],
        "image_model": "",
        "supports_image": False,
        "supports_image_edit": False,
        "notes": "Modelos locales. Arranca con 'ollama serve'. Sin clave de API.",
    },
    "lmstudio": {
        "label": "LM Studio (local)",
        "kind": "openai",
        "base_url": "http://localhost:1234/v1",
        "api_key_env": "LMSTUDIO_API_KEY",
        "needs_key": False,
        "models": [],
        "vision_models": [],
        "image_model": "",
        "supports_image": False,
        "supports_image_edit": False,
        "notes": "Activa el servidor local en la pestana Developer de LM Studio "
                 "(puerto 1234 por defecto).",
    },
    "custom": {
        "label": "Personalizado (compatible OpenAI)",
        "kind": "openai",
        "base_url": "http://localhost:8000/v1",
        "api_key_env": "CUSTOM_API_KEY",
        "needs_key": False,
        "models": [],
        "vision_models": [],
        "image_model": "",
        "supports_image": False,
        "supports_image_edit": False,
        "notes": "Cualquier servidor compatible OpenAI (vLLM, llama.cpp, LocalAI, "
                 "text-generation-webui, Together, Groq, DeepSeek...).",
    },
}


class ProviderError(RuntimeError):
    """Error legible para mostrar en la interfaz."""


# ---------------------------------------------------------------------------
# Utilidades HTTP (solo stdlib)
# ---------------------------------------------------------------------------
def _request(url, method="GET", payload=None, headers=None, timeout=DEFAULT_TIMEOUT,
             raw_body=None, content_type="application/json"):
    data = None
    if raw_body is not None:
        data = raw_body
    elif payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", content_type)
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", "Inkscape-Gimp-AI-Agent/1.0")
    for key, value in (headers or {}).items():
        if value:
            req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:1200]
        raise ProviderError("HTTP %s al llamar a %s\n%s" % (exc.code, url, detail))
    except urllib.error.URLError as exc:
        raise ProviderError(
            "No se pudo conectar con %s\n%s\n"
            "(Si es un proveedor local, comprueba que el servidor esta arrancado "
            "y que la URL base es correcta.)" % (url, exc.reason))
    if not body:
        return {}
    try:
        return json.loads(body.decode("utf-8", "replace"))
    except ValueError:
        return {"raw": body.decode("utf-8", "replace")}


def _get_json(url, headers=None, timeout=DEFAULT_TIMEOUT):
    return _request(url, "GET", headers=headers, timeout=timeout)


def _post_json(url, payload, headers=None, timeout=DEFAULT_TIMEOUT):
    return _request(url, "POST", payload=payload, headers=headers, timeout=timeout)


def _multipart(fields, files):
    """Construye un cuerpo multipart/form-data sin dependencias externas.

    fields: dict de campos de texto
    files:  dict {nombre_campo: (nombre_archivo, bytes, mime)}
    """
    boundary = "----InkscapeGimpAIAgentBoundary7d91ab"
    chunks = []
    for name, value in fields.items():
        chunks.append(("--%s\r\n" % boundary).encode())
        chunks.append(('Content-Disposition: form-data; name="%s"\r\n\r\n' % name).encode())
        chunks.append(("%s\r\n" % value).encode())
    for name, (filename, blob, mime) in files.items():
        chunks.append(("--%s\r\n" % boundary).encode())
        chunks.append(('Content-Disposition: form-data; name="%s"; filename="%s"\r\n'
                       % (name, filename)).encode())
        chunks.append(("Content-Type: %s\r\n\r\n" % mime).encode())
        chunks.append(blob)
        chunks.append(b"\r\n")
    chunks.append(("--%s--\r\n" % boundary).encode())
    return b"".join(chunks), "multipart/form-data; boundary=%s" % boundary


# ---------------------------------------------------------------------------
# Configuracion efectiva por proveedor
# ---------------------------------------------------------------------------
def provider_conf(cfg, provider_id):
    """Devuelve el diccionario del proveedor mezclado con lo guardado en config."""
    base = dict(PROVIDERS.get(provider_id, PROVIDERS["custom"]))
    overrides = (cfg.get("providers", {}) or {}).get(provider_id, {}) or {}
    base.update({k: v for k, v in overrides.items() if v not in (None, "")})
    return base


def resolve_api_key(cfg, provider_id):
    conf = provider_conf(cfg, provider_id)
    saved = (cfg.get("api_keys", {}) or {}).get(provider_id, "")
    if saved:
        return saved
    env_name = conf.get("api_key_env")
    if env_name:
        return os.environ.get(env_name, "")
    return ""


def _auth_headers(conf, key):
    if conf.get("kind") == "anthropic":
        headers = {"anthropic-version": "2023-06-01"}
        if key:
            headers["x-api-key"] = key
        return headers
    headers = {}
    if key:
        headers["Authorization"] = "Bearer %s" % key
    elif conf.get("kind") == "openai" and not conf.get("needs_key", True):
        # Muchos servidores locales exigen el encabezado aunque ignoren el valor.
        headers["Authorization"] = "Bearer not-needed"
    if "openrouter" in (conf.get("base_url") or ""):
        headers["HTTP-Referer"] = "https://local.inkscape-gimp-ai-agent"
        headers["X-Title"] = "Inkscape-GIMP AI Agent"
    return headers


def to_data_uri(blob, mime="image/png"):
    return "data:%s;base64,%s" % (mime, base64.b64encode(blob).decode("ascii"))


# ---------------------------------------------------------------------------
# Listado de modelos (para el desplegable de la interfaz)
# ---------------------------------------------------------------------------
def list_models(cfg, provider_id):
    conf = provider_conf(cfg, provider_id)
    key = resolve_api_key(cfg, provider_id)
    base = (cfg.get("base_url_override") or {}).get(provider_id) or conf["base_url"]
    base = base.rstrip("/")

    if conf["kind"] == "gemini":
        url = "%s/models?key=%s" % (base, urllib.parse.quote(key or ""))
        data = _get_json(url)
        names = [m.get("name", "").replace("models/", "")
                 for m in data.get("models", []) if m.get("name")]
        if not names:
            raise ProviderError("El proveedor no devolvio modelos. Respuesta: %s"
                                % str(data)[:400])
        return sorted(n for n in names if n)

    if conf["kind"] == "anthropic":
        data = _get_json(base + "/models?limit=100", headers=_auth_headers(conf, key))
        names = [m.get("id") for m in data.get("data", []) if m.get("id")]
        if not names:
            raise ProviderError("Sin modelos en la respuesta: %s" % str(data)[:400])
        return names

    try:
        data = _get_json(base + "/models", headers=_auth_headers(conf, key))
    except ProviderError:
        # Algunos servidores solo exponen /v1/models -> reintento explicito
        if not base.endswith("/v1"):
            data = _get_json(base + "/v1/models", headers=_auth_headers(conf, key))
        else:
            raise
    raw = data.get("data", data.get("models", []))
    names = []
    for item in raw:
        if isinstance(item, dict):
            names.append(item.get("id") or item.get("name") or "")
        elif isinstance(item, str):
            names.append(item)
    names = sorted({n for n in names if n})
    if not names:
        raise ProviderError("Sin modelos en la respuesta: %s" % str(data)[:400])
    return names


# ---------------------------------------------------------------------------
# Chat / texto
# ---------------------------------------------------------------------------
def chat(cfg, provider_id, model, messages, temperature=0.2, max_tokens=8192,
         timeout=DEFAULT_TIMEOUT):
    """Devuelve el texto de la respuesta del modelo."""
    if not model:
        raise ProviderError("Selecciona un modelo antes de ejecutar el pedido.")
    conf = provider_conf(cfg, provider_id)
    key = resolve_api_key(cfg, provider_id)
    base = ((cfg.get("base_url_override") or {}).get(provider_id)
            or conf["base_url"]).rstrip("/")

    if conf["kind"] == "gemini":
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        contents = []
        for m in messages:
            if m["role"] == "system":
                continue
            role = "user" if m["role"] == "user" else "model"
            contents.append({"role": role, "parts": [{"text": m["content"]}]})
        payload = {"contents": contents}
        gen = {}
        if temperature is not None:
            gen["temperature"] = float(temperature)
        if max_tokens:
            gen["maxOutputTokens"] = int(max_tokens)
        if gen:
            payload["generationConfig"] = gen
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        url = "%s/models/%s:generateContent?key=%s" % (
            base, urllib.parse.quote(model), urllib.parse.quote(key or ""))
        data = _post_json(url, payload, timeout=timeout)
        cands = data.get("candidates") or []
        if not cands:
            raise ProviderError("Respuesta sin candidatos: %s" % str(data)[:600])
        parts = (cands[0].get("content") or {}).get("parts") or []
        return "".join(p.get("text", "") for p in parts)

    if conf["kind"] == "anthropic":
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        msgs = [{"role": ("assistant" if m["role"] == "assistant" else "user"),
                 "content": m["content"]}
                for m in messages if m["role"] in ("user", "assistant")]
        payload = {"model": model, "messages": msgs,
                   "max_tokens": int(max_tokens or 8192)}
        if temperature is not None:
            payload["temperature"] = float(temperature)
        if system:
            payload["system"] = system
        data = _post_json(base + "/messages", payload,
                          headers=_auth_headers(conf, key), timeout=timeout)
        return "".join(b.get("text", "") for b in data.get("content", []))

    # Familia compatible OpenAI (OpenAI, OpenRouter, OmniRoute, Ollama, LM Studio)
    payload = {"model": model, "messages": messages}
    if temperature is not None:
        payload["temperature"] = float(temperature)
    if max_tokens:
        payload["max_tokens"] = int(max_tokens)
    data = _post_json(base + "/chat/completions", payload,
                      headers=_auth_headers(conf, key), timeout=timeout)
    choices = data.get("choices") or []
    if not choices:
        raise ProviderError("Respuesta sin 'choices': %s" % str(data)[:600])
    msg = choices[0].get("message") or {}
    content = msg.get("content")
    if isinstance(content, list):  # algunos routers devuelven bloques
        content = "".join(part.get("text", "") for part in content
                          if isinstance(part, dict))
    return content or msg.get("reasoning_content", "") or ""


# ---------------------------------------------------------------------------
# Imagenes bitmap
# ---------------------------------------------------------------------------
def decode_image_response(data):
    """Extrae los bytes de imagen de una respuesta de generacion/edicion."""
    items = data.get("data") or []
    if items:
        first = items[0]
        if first.get("b64_json"):
            return base64.b64decode(first["b64_json"])
        if first.get("url"):
            with urllib.request.urlopen(first["url"], timeout=DEFAULT_TIMEOUT) as r:
                return r.read()
    preds = data.get("predictions") or []
    if preds:
        for p in preds:
            if p.get("bytesBase64Encoded"):
                return base64.b64decode(p["bytesBase64Encoded"])
    if data.get("image"):
        return base64.b64decode(data["image"])
    raise ProviderError("La respuesta no contiene imagen: %s" % str(data)[:600])


def generate_image(cfg, provider_id, model, prompt, size="1024x1024",
                   timeout=DEFAULT_TIMEOUT):
    """Genera una imagen bitmap. Devuelve bytes PNG/JPEG."""
    conf = provider_conf(cfg, provider_id)
    key = resolve_api_key(cfg, provider_id)
    base = ((cfg.get("base_url_override") or {}).get(provider_id)
            or conf["base_url"]).rstrip("/")
    model = model or conf.get("image_model", "")
    if not model:
        raise ProviderError(
            "El proveedor '%s' no tiene modelo de imagen configurado.\n"
            "Escribe el nombre del modelo de imagen en el campo 'Modelo' o "
            "configura 'image_model' en config.json." % conf["label"])

    if conf["kind"] == "gemini":
        url = "%s/models/%s:predict?key=%s" % (base, urllib.parse.quote(model),
                                               urllib.parse.quote(key or ""))
        payload = {"instances": [{"prompt": prompt}],
                   "parameters": {"sampleCount": 1}}
        return decode_image_response(_post_json(url, payload, timeout=timeout))

    if conf["kind"] == "anthropic" or not conf.get("supports_image"):
        raise ProviderError(
            "El proveedor '%s' no ofrece generacion de imagenes bitmap.\n"
            "Opciones: usa otro proveedor para generar la imagen o pide al agente "
            "un script de GIMP que la cree por procedimiento." % conf["label"])

    payload = {"model": model, "prompt": prompt, "n": 1}
    if size:
        payload["size"] = size
    return decode_image_response(_post_json(
        base + "/images/generations", payload,
        headers=_auth_headers(conf, key), timeout=timeout))


def edit_image(cfg, provider_id, model, image_bytes, prompt, size=None,
               filename="entrada.png", timeout=DEFAULT_TIMEOUT):
    """Edita/corrige una imagen existente (endpoint /images/edits)."""
    conf = provider_conf(cfg, provider_id)
    key = resolve_api_key(cfg, provider_id)
    base = ((cfg.get("base_url_override") or {}).get(provider_id)
            or conf["base_url"]).rstrip("/")
    model = model or conf.get("image_model", "")
    if not conf.get("supports_image_edit"):
        raise ProviderError(
            "El proveedor '%s' no soporta edicion de imagenes por API.\n"
            "Usa el modo 'Correccion por script' para que el agente devuelva "
            "codigo de GIMP/Python aplicable a la imagen." % conf["label"])
    fields = {"model": model, "prompt": prompt, "n": "1"}
    if size:
        fields["size"] = size
    mime = mimetypes.guess_type(filename)[0] or "image/png"
    body, content_type = _multipart(fields, {"image": (filename, image_bytes, mime)})
    data = _request(base + "/images/edits", "POST", headers=_auth_headers(conf, key),
                    raw_body=body, content_type=content_type, timeout=timeout)
    return decode_image_response(data)


def describe_image(cfg, provider_id, model, image_bytes, instruction,
                   timeout=DEFAULT_TIMEOUT):
    """Analiza una imagen con un modelo de vision y devuelve texto."""
    conf = provider_conf(cfg, provider_id)
    if conf["kind"] in ("openai", "anthropic") or conf.get("vision_models"):
        data_uri = to_data_uri(image_bytes)
        if conf["kind"] == "anthropic":
            messages = [{"role": "user", "content": [
                {"type": "text", "text": instruction},
                {"type": "image", "source": {
                    "type": "base64", "media_type": "image/png",
                    "data": data_uri.split(",", 1)[1]}}]}]
            key = resolve_api_key(cfg, provider_id)
            base = ((cfg.get("base_url_override") or {}).get(provider_id)
                    or conf["base_url"]).rstrip("/")
            payload = {"model": model, "max_tokens": 4096, "messages": messages}
            out = _post_json(base + "/messages", payload,
                             headers=_auth_headers(conf, key), timeout=timeout)
            return "".join(b.get("text", "") for b in out.get("content", []))
        messages = [{"role": "user", "content": [
            {"type": "text", "text": instruction},
            {"type": "image_url", "image_url": {"url": data_uri}}]}]
        return chat(cfg, provider_id, model, messages, timeout=timeout)
    raise ProviderError(
        "El proveedor '%s' no tiene un modelo de vision configurado.\n"
        "Anade su nombre en 'vision_models' (config.json) o selecciona un modelo "
        "multimodal." % conf["label"])


def connectivity_summary(cfg):
    """Estado rapido de cada proveedor para mostrarlo en la interfaz."""
    lines = []
    for pid in PROVIDERS:
        conf = provider_conf(cfg, pid)
        key = resolve_api_key(cfg, pid)
        if conf.get("needs_key") and not key:
            state = "sin clave de API"
        else:
            state = "listo" if key or not conf.get("needs_key") else "revisar"
        lines.append("%-12s %-34s %s" % (pid, conf["base_url"], state))
    return "\n".join(lines)
