"""Clase base de proveedores + conversores de los 4 formatos de alambre.

  * ``openai``    -> OpenAI, OpenRouter, LM Studio, OmniRoute (OpenAI-compatibles)
  * ``anthropic`` -> Anthropic Messages API
  * ``gemini``    -> Google Generative Language API (v1beta)
  * ``ollama``    -> Ollama nativo (/api/chat, NDJSON)

La GUI/CLI siempre produce mensajes **neutros**: ``{"role": .., "content": str, "images": [paths]}``.
Cada proveedor los traduce a su formato aquí, incluida la visión (imágenes adjuntas).
"""

from __future__ import annotations

import base64
import dataclasses
import json
import mimetypes
import os
from typing import Any, Callable, Dict, Iterable, List, Optional

from ..core import net

ANTHROPIC_VERSION = "2023-06-01"

FALLBACK_MODELS: Dict[str, List[str]] = {
    "openai": ["gpt-4.1-mini", "gpt-4.1", "gpt-4o", "o4-mini"],
    "openrouter": [
        "openai/gpt-4.1-mini",
        "anthropic/claude-sonnet-4.5",
        "google/gemini-2.5-flash",
        "deepseek/deepseek-chat-v3.1",
    ],
    "lmstudio": ["local-model"],
    "omniroute": ["auto", "cc/claude-opus-4-7", "if/kimi-k2.7-code", "openai/gpt-4.1-mini"],
    "ollama": ["qwen2.5-coder:7b", "llama3.1:8b", "deepseek-coder-v2:16b", "gemma3:12b"],
    "anthropic": ["claude-sonnet-4.5", "claude-opus-4.1", "claude-haiku-4.5"],
    "gemini": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"],
}


@dataclasses.dataclass
class ModelInfo:
    id: str
    label: str = ""

    def __post_init__(self) -> None:
        if not self.label:
            self.label = self.id

    def __str__(self) -> str:  # lo que pinta el ttk.Combobox
        return self.label


class ProviderError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Imágenes -> data URI / inline parts
# ---------------------------------------------------------------------------
def _b64_image(path: str) -> tuple[str, str]:
    with open(path, "rb") as fh:
        raw = fh.read()
    mime = mimetypes.guess_type(path)[0] or "image/png"
    if mime == "image/svg+xml":  # no todos los backends aceptan SVG como imagen
        return "image/png", base64.b64encode(raw).decode("ascii")
    return mime, base64.b64encode(raw).decode("ascii")


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------
def delta_text(kind: str, obj: Dict[str, Any]) -> str:
    """Texto incremental de un evento de streaming."""
    try:
        if kind == "openai":
            choices = obj.get("choices") or []
            if not choices:
                return ""
            ch = choices[0] or {}
            delta = ch.get("delta") or {}
            if isinstance(delta.get("content"), str):
                return delta["content"]
            if isinstance(ch.get("text"), str):
                return ch["text"]
            return ""
        if kind == "anthropic":
            if obj.get("type") == "content_block_delta":
                d = obj.get("delta") or {}
                if d.get("type") in (None, "text_delta") and isinstance(d.get("text"), str):
                    return d["text"]
            return ""
        if kind == "gemini":
            parts = (((obj.get("candidates") or [{}])[0]).get("content") or {}).get("parts") or []
            return "".join(p.get("text", "") for p in parts if isinstance(p, dict) and isinstance(p.get("text"), str))
        if kind == "ollama":
            msg = obj.get("message") or {}
            if isinstance(msg.get("content"), str):
                return msg["content"]
            return obj.get("response") if isinstance(obj.get("response"), str) else ""
    except (AttributeError, IndexError, TypeError):
        return ""
    return ""


def full_text(kind: str, obj: Dict[str, Any]) -> str:
    """Texto completo de una respuesta no-stream."""
    try:
        if kind == "openai":
            choices = obj.get("choices") or []
            if not choices:
                raise ProviderError(f"Sin 'choices' en la respuesta: {_short(obj)}")
            content = (choices[0] or {}).get("message", {}).get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                return "".join(p.get("text", "") for p in content if isinstance(p, dict))
            raise ProviderError(f"'content' inesperado: {_short(obj)}")
        if kind == "anthropic":
            blocks = obj.get("content") or []
            if isinstance(blocks, str):
                return blocks
            out = [b.get("text", "") for b in blocks
                   if isinstance(b, dict) and b.get("type") in (None, "text")]
            if not "".join(out).strip():
                raise ProviderError(f"Anthropic no devolvió texto: {_short(obj)}")
            return "".join(out)
        if kind == "gemini":
            cands = obj.get("candidates") or []
            if not cands:
                raise ProviderError(f"Gemini sin 'candidates': {_short(obj)}")
            parts = (cands[0].get("content") or {}).get("parts") or []
            return "".join(p.get("text", "") for p in parts if isinstance(p, dict) and isinstance(p.get("text"), str))
        if kind == "ollama":
            content = full_text("openai", obj) if obj.get("choices") else ""
            if content:
                return content
            msg = obj.get("message") or {}
            if isinstance(msg.get("content"), str):
                return msg["content"]
            if isinstance(obj.get("response"), str):
                return obj["response"]
    except (AttributeError, IndexError, TypeError) as exc:
        raise ProviderError(f"Respuesta ilegible: {exc}") from None
    raise ProviderError(f"Respuesta ilegible: {_short(obj)}")


def parse_models(kind: str, obj: Dict[str, Any]) -> List[ModelInfo]:
    if kind == "ollama":
        out = []
        for m in obj.get("models") or []:
            if isinstance(m, dict) and m.get("name"):
                size = m.get("size")
                label = str(m["name"])
                if isinstance(size, int) and size > 1_000_000:
                    label += f"  ({size / 1e9:.1f} GB)"
                out.append(ModelInfo(str(m["name"]), label))
        return out
    if kind == "gemini":
        out = []
        for m in obj.get("models") or []:
            name = str(m.get("name", "")).replace("models/", "")
            if name:
                out.append(ModelInfo(name, str(m.get("displayName") or name)))
        return out
    raw = obj.get("data") or obj.get("models") or []
    out: List[ModelInfo] = []
    for m in raw:
        if isinstance(m, str):
            out.append(ModelInfo(m))
        elif isinstance(m, dict) and m.get("id"):
            out.append(ModelInfo(str(m["id"]), str(m.get("name") or m.get("id") or m["id"])))
    return out


def _short(obj: Any, n: int = 400) -> str:
    try:
        s = json.dumps(obj, ensure_ascii=False)
    except (TypeError, ValueError):
        s = str(obj)
    return s[:n]


# ---------------------------------------------------------------------------
# Provider base
# ---------------------------------------------------------------------------
class Provider:
    id: str = ""
    label: str = ""
    kind: str = "openai"
    default_base: str = ""
    key_env: str = ""
    needs_key: bool = True
    default_model: str = ""
    supports_json_mode: bool = True
    blurb: str = ""

    def __init__(self, *, base_url: str = "", api_key: str = "",
                 timeout: float = net.DEFAULT_TIMEOUT, verify: bool = True) -> None:
        self.base_url = self.normalize_base((base_url or self.default_base).strip())
        self.api_key = (api_key or (os.environ.get(self.key_env, "") if self.key_env else "")).strip()
        self.timeout = float(timeout)
        self.verify = bool(verify)

    # -- configuración ------------------------------------------------------
    @classmethod
    def normalize_base(cls, base: str) -> str:
        return openai_style_base(base) if cls.kind == "openai" else (base or cls.default_base).rstrip("/")

    def headers(self) -> Dict[str, str]:
        h = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            if self.kind == "anthropic":
                h["x-api-key"] = self.api_key
                h["anthropic-version"] = ANTHROPIC_VERSION
            elif self.kind == "gemini":
                h["x-goog-api-key"] = self.api_key
            else:
                h["Authorization"] = f"Bearer {self.api_key}"
        elif self.needs_key:
            raise ProviderError(
                f"{self.label} necesita una API key: escríbela en la pestaña Ajustes "
                f"o exporta la variable {self.key_env or 'API_KEY'}."
            )
        return h

    def extra_headers(self) -> Dict[str, str]:
        return {}

    def models_path(self) -> str:
        return {"openai": "/models", "ollama": "/api/tags",
                "anthropic": "/v1/models", "gemini": "/models"}[self.kind]

    def chat_path(self, stream: bool) -> str:
        if self.kind == "ollama":
            return "/api/chat"
        if self.kind == "anthropic":
            return "/v1/messages"
        if self.kind == "gemini":
            return f":{'streamGenerateContent?alt=sse' if stream else 'generateContent'}"
        return "/chat/completions"

    # -- mensajes neutros -> wire format ------------------------------------
    def convert_messages(self, messages: List[Dict[str, Any]]) -> tuple[Any, str]:
        """Devuelve (mensajes_wire, system_text) según el formato del proveedor."""
        sys_txt = "\n\n".join(m["content"] for m in messages if m["role"] == "system" and m.get("content"))
        body = [m for m in messages if m["role"] != "system"]

        if self.kind in ("openai", "ollama"):
            out: List[Dict[str, Any]] = []
            if sys_txt:
                out.append({"role": "system", "content": sys_txt})
            for m in body:
                imgs = [i for i in m.get("images") or [] if os.path.isfile(i)]
                if self.kind == "ollama":
                    item: Dict[str, Any] = {"role": m["role"], "content": m["content"]}
                    if imgs:
                        item["images"] = [_b64_image(p)[1] for p in imgs]
                    out.append(item)
                    continue
                if imgs:
                    parts: List[Dict[str, Any]] = [{"type": "text", "text": m["content"]}]
                    for p in imgs:
                        mime, b64 = _b64_image(p)
                        parts.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
                    out.append({"role": m["role"], "content": parts})
                else:
                    out.append({"role": m["role"], "content": m["content"]})
            return out, ""

        if self.kind == "anthropic":
            out_a: List[Dict[str, Any]] = []
            for m in body:
                imgs = [i for i in m.get("images") or [] if os.path.isfile(i)]
                if not imgs:
                    out_a.append({"role": "user" if m["role"] == "user" else "assistant", "content": m["content"]})
                    continue
                parts_a: List[Dict[str, Any]] = []
                for p in imgs:
                    mime, b64 = _b64_image(p)
                    parts_a.append({"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}})
                parts_a.append({"type": "text", "text": m["content"]})
                out_a.append({"role": "user" if m["role"] == "user" else "assistant", "content": parts_a})
            return out_a, sys_txt

        if self.kind == "gemini":
            contents: List[Dict[str, Any]] = []
            for m in body:
                parts_g: List[Dict[str, Any]] = [{"text": m["content"]}]
                for p in [i for i in m.get("images") or [] if os.path.isfile(i)]:
                    mime, b64 = _b64_image(p)
                    parts_g.append({"inline_data": {"mime_type": mime, "data": b64}})
                contents.append({"role": "model" if m["role"] == "assistant" else "user", "parts": parts_g})
            return contents, sys_txt

        raise ProviderError(f"kind '{self.kind}' no soportado")  # pragma: no cover

    def build_payload(self, messages: List[Dict[str, Any]], model: str, *, stream: bool,
                      temperature: float, max_tokens: int, json_mode: bool) -> Dict[str, Any]:
        wire, sys_txt = self.convert_messages(messages)
        if self.kind == "ollama":
            payload: Dict[str, Any] = {
                "model": model, "messages": wire, "stream": stream,
                "options": {"temperature": temperature, "num_predict": max_tokens},
            }
            return payload
        if self.kind == "anthropic":
            payload = {"model": model, "messages": wire, "max_tokens": max_tokens,
                       "temperature": temperature, "stream": stream}
            if sys_txt:
                payload["system"] = sys_txt
            return payload
        if self.kind == "gemini":
            payload = {"contents": wire, "generationConfig": {
                "temperature": temperature, "maxOutputTokens": max_tokens}}
            if sys_txt:
                payload["systemInstruction"] = {"parts": [{"text": sys_txt}]}
            if json_mode:
                payload["generationConfig"]["responseMimeType"] = "application/json"
            return payload
        payload = {"model": model, "messages": wire, "temperature": temperature,
                   "max_tokens": max_tokens, "stream": stream}
        if json_mode and self.supports_json_mode:
            payload["response_format"] = {"type": "json_object"}
        return payload

    # -- API pública --------------------------------------------------------
    def chat_url(self, stream: bool, model: str = "") -> str:
        path = self.chat_path(stream)
        if self.kind == "gemini":
            return net.url_join(self.base_url, f"/models/{model}{path}")
        return net.url_join(self.base_url, path)

    def list_models(self) -> List[ModelInfo]:
        url = net.url_join(self.base_url, self.models_path())
        obj = net.request(url, headers={**self.headers(), **self.extra_headers()},
                          timeout=min(25.0, self.timeout))
        return parse_models(self.kind, obj)

    def fallback_models(self) -> List[ModelInfo]:
        ids = FALLBACK_MODELS.get(self.id) or ([self.default_model] if self.default_model else [])
        return [ModelInfo(i) for i in ids]

    def list_models_or_fallback(self) -> tuple[List[ModelInfo], str]:
        try:
            models = self.list_models()
            if models:
                return models, f"Modelos de {self.label} ({self.base_url}): {len(models)}."
        except (net.NetError, ProviderError, ValueError) as exc:
            note = (f"No se pudo consultar {self.base_url}{self.models_path()} ({exc}). "
                    f"Usando lista sugerida.")
            return self.fallback_models(), note
        return self.fallback_models(), f"El proveedor no devolvió modelos. Usando lista sugerida para {self.label}."

    def complete(self, messages: List[Dict[str, Any]], *, model: str, temperature: float = 0.2,
                 max_tokens: int = 6000, json_mode: bool = True,
                 on_delta: Optional[Callable[[str], None]] = None) -> str:
        headers = {**self.headers(), **self.extra_headers()}
        payload = self.build_payload(messages, model, stream=True, temperature=temperature,
                                     max_tokens=max_tokens, json_mode=json_mode)
        text = ""
        stream_error: Optional[Exception] = None
        try:
            for chunk in self._stream(payload, headers, model):
                text += chunk
                if on_delta:
                    on_delta(chunk)
        except (net.NetError, ProviderError) as exc:
            stream_error = exc
        if not text.strip():
            try:
                text = self._nonstream(messages, model, temperature=temperature,
                                       max_tokens=max_tokens, headers=headers, json_mode=json_mode)
            except (net.NetError, ProviderError) as exc:
                if stream_error is not None:
                    raise ProviderError(
                        f"Fallo de streaming: {stream_error}\nFallo no-stream: {exc}"
                    ) from exc
                raise
            if text and on_delta:
                on_delta(text)
        if not text.strip():
            raise ProviderError(f"{self.label} devolvió una respuesta vacía (modelo '{model}').")
        return text

    def _stream(self, payload: Dict[str, Any], headers: Dict[str, str], model: str = "") -> Iterable[str]:
        url = self.chat_url(True, model)
        if self.kind == "ollama":
            return net.stream_ndjson(url, headers=headers, payload=payload,
                                     timeout=self.timeout, verify=self.verify,
                                     on_obj=lambda o: delta_text("ollama", o) or None)
        return net.stream_sse(url, headers=headers, payload=payload, timeout=self.timeout,
                              verify=self.verify, on_event=lambda o: delta_text(self.kind, o) or None)

    def _nonstream(self, messages: List[Dict[str, Any]], model: str, *, temperature: float,
                   max_tokens: int, headers: Dict[str, str], json_mode: bool) -> str:
        payload = self.build_payload(messages, model, stream=False, temperature=temperature,
                                     max_tokens=max_tokens, json_mode=json_mode)
        obj = net.request(self.chat_url(False, model), method="POST", headers=headers, payload=payload,
                          timeout=self.timeout, verify=self.verify)
        return full_text(self.kind, obj)

    def ping(self) -> str:
        models, note = self.list_models_or_fallback()
        first = models[0].id if models else "—"
        return f"{self.label} @ {self.base_url} -> OK ({len(models)} modelos, ej. {first}). {note if 'Usando' in note or 'sugerida' in note else ''}".strip()


def openai_style_base(base: str) -> str:
    """Acepta `https://api.openai.com` o `.../v1` y devuelve siempre base + /v1."""
    base = (base or "").rstrip("/")
    low = base.lower()
    if not low:
        return base
    if any(low.endswith(s) for s in ("/v1", "/v1beta", "/v4", "/api/v1", "/v1/chat/completions")):
        return base
    if "/v1/" in low:
        return base[: base.lower().index("/v1/") + 3]
    if low.endswith("/api"):
        return base + "/v1"
    return base + "/v1"
