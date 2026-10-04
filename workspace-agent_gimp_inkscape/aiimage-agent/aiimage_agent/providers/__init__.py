"""Proveedores OpenAI-compatibles (nube y locales) + Anthropic, Gemini y Ollama."""

from __future__ import annotations

from .base import Provider, ProviderError


class OpenAIProvider(Provider):
    id = "openai"
    label = "OpenAI"
    kind = "openai"
    default_base = "https://api.openai.com/v1"
    key_env = "OPENAI_API_KEY"
    default_model = "gpt-4.1-mini"
    blurb = "API de OpenAI (o cualquier endpoint OpenAI-compatible con URL base propia)."


class OpenRouterProvider(Provider):
    id = "openrouter"
    label = "OpenRouter"
    kind = "openai"
    default_base = "https://openrouter.ai/api/v1"
    key_env = "OPENROUTER_API_KEY"
    default_model = "openai/gpt-4.1-mini"
    supports_json_mode = True
    blurb = "Un solo endpoint para cientos de modelos de nube."

    def extra_headers(self):  # atribución recomendada por OpenRouter
        return {
            "HTTP-Referer": "https://arena.ai/ai-image-agent",
            "X-Title": "AI Image Agent",
            "Accept": "text/event-stream, application/json",
        }


class LMStudioProvider(Provider):
    id = "lmstudio"
    label = "LM Studio"
    kind = "openai"
    default_base = "http://localhost:1234/v1"
    needs_key = False
    default_model = "local-model"
    supports_json_mode = False
    blurb = "Modelos locales de LM Studio (Server → habilitar 'Local Server' en :1234)."

    def headers(self):
        h = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h


class OmniRouteProvider(Provider):
    id = "omniroute"
    label = "OmniRoute"
    kind = "openai"
    default_base = "http://localhost:20128/v1"
    needs_key = False
    default_model = "auto"
    supports_json_mode = False
    blurb = ("Gateway local OpenAI-compatible (290+ proveedores, auto-fallback en 429). "
             "Nombres de modelo tipo 'cc/claude-opus-4-7' o 'auto'.")

    def headers(self):
        h = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h


class OllamaProvider(Provider):
    id = "ollama"
    label = "Ollama"
    kind = "ollama"
    default_base = "http://localhost:11434"
    needs_key = False
    default_model = "qwen2.5-coder:7b"
    supports_json_mode = False
    blurb = "Servidor local Ollama (/api/chat nativo, también sirve modelos .gguf descargados)."

    def build_payload(self, messages, model, *, stream, temperature, max_tokens, json_mode):
        payload = super().build_payload(messages, model, stream=stream, temperature=temperature,
                                       max_tokens=max_tokens, json_mode=False)
        if json_mode:
            # Ollama puede forzar JSON sin response_format: formato + prompt (ya pedido en el system)
            payload["format"] = "json"
        return payload


class AnthropicProvider(Provider):
    id = "anthropic"
    label = "Anthropic"
    kind = "anthropic"
    default_base = "https://api.anthropic.com"
    key_env = "ANTHROPIC_API_KEY"
    default_model = "claude-sonnet-4.5"
    blurb = "Claude Messages API (/v1/messages)."


class GeminiProvider(Provider):
    id = "gemini"
    label = "Google Gemini"
    kind = "gemini"
    default_base = "https://generativelanguage.googleapis.com/v1beta"
    key_env = "GEMINI_API_KEY"
    default_model = "gemini-2.5-flash"
    blurb = "Google AI Studio / Generative Language API (x-goog-api-key)."

    def headers(self):
        h = super().headers()
        if not self.api_key:
            raise ProviderError(
                "Google Gemini necesita su API key (AI Studio). Escríbela en Ajustes "
                "o exporta GEMINI_API_KEY / GOOGLE_API_KEY."
            )
        return h

    def __init__(self, **kw):
        if not kw.get("api_key"):
            import os

            kw["api_key"] = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""
        super().__init__(**kw)


PROVIDERS = {
    p.id: p
    for p in (
        OpenAIProvider,
        AnthropicProvider,
        GeminiProvider,
        OllamaProvider,
        LMStudioProvider,
        OpenRouterProvider,
        OmniRouteProvider,
    )
}

# Orden de aparición de los botones en la GUI
PROVIDER_ORDER = ["ollama", "lmstudio", "omniroute", "openai", "anthropic", "gemini", "openrouter"]


def get_provider(provider_id: str, *, base_url: str = "", api_key: str = "",
                 timeout: float = 120.0, verify: bool = True) -> Provider:
    try:
        cls = PROVIDERS[provider_id]
    except KeyError:
        raise ValueError(f"Proveedor desconocido: {provider_id!r}. "
                         f"Disponibles: {', '.join(PROVIDERS)}") from None
    return cls(base_url=base_url, api_key=api_key, timeout=timeout, verify=verify)
