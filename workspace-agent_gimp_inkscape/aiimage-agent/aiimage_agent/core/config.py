"""Configuración persistente (JSON) y rutas por sistema operativo.

Windows : %APPDATA%\\AI Image Agent\\config.json
Linux   : ~/.config/ai-image-agent/config.json   (respeta XDG_CONFIG_HOME)
"""

from __future__ import annotations

import dataclasses
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

APP_DIRNAME = "ai-image-agent"
APP_DIRNAME_WIN = "AI Image Agent"

KEY_ENVS: Dict[str, List[str]] = {
    "openai": ["OPENAI_API_KEY"],
    "openrouter": ["OPENROUTER_API_KEY"],
    "anthropic": ["ANTHROPIC_API_KEY"],
    "gemini": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
    "ollama": ["OLLAMA_API_KEY"],
    "lmstudio": ["LMSTUDIO_API_KEY"],
    "omniroute": ["OMNIROUTE_API_KEY"],
}
BASE_URL_ENVS: Dict[str, List[str]] = {
    "ollama": ["OLLAMA_HOST"],
    "lmstudio": ["LMSTUDIO_BASE_URL"],
    "omniroute": ["OMNIROUTE_BASE_URL"],
    "openai": ["OPENAI_BASE_URL"],
    "openrouter": ["OPENROUTER_BASE_URL"],
}

DEFAULT_PROVIDERS: Dict[str, Dict[str, Any]] = {
    "openai": {"base_url": "https://api.openai.com/v1", "model": "gpt-4.1-mini"},
    "anthropic": {"base_url": "https://api.anthropic.com", "model": "claude-sonnet-4.5"},
    "gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta", "model": "gemini-2.5-flash"},
    "ollama": {"base_url": "http://localhost:11434", "model": "qwen2.5-coder:7b"},
    "lmstudio": {"base_url": "http://localhost:1234/v1", "model": "local-model"},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1", "model": "openai/gpt-4.1-mini"},
    "omniroute": {"base_url": "http://localhost:20128/v1", "model": "auto"},
}


def config_dir() -> Path:
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / APP_DIRNAME_WIN
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / APP_DIRNAME


def default_workspace() -> Path:
    return Path.home() / "AIImageAgent"


@dataclasses.dataclass
class Config:
    provider: str = "ollama"
    active_provider: Dict[str, Dict[str, Any]] = dataclasses.field(default_factory=dict)
    temperature: float = 0.2
    max_tokens: int = 6000
    timeout: float = 180.0
    verify_tls: bool = True
    # ON por defecto: el plan contiene código generado por un modelo; ejecutar Inkscape/GIMP
    # se activa en la GUI («Modo seguro» desmarcado) o con --execute en la CLI.
    safe_mode: bool = True
    allow_unsafe: bool = False
    auto_run: bool = True
    export_preview: bool = True
    repair_rounds: int = 1
    window_geometry: str = "1400x900"
    workspace: str = ""
    binaries: Dict[str, str] = dataclasses.field(default_factory=lambda: {"inkscape": "", "gimp": "", "python": ""})
    history: List[Dict[str, str]] = dataclasses.field(default_factory=list)
    last_task: str = ""
    last_mode: str = "crear"
    last_apps: List[str] = dataclasses.field(default_factory=lambda: ["inkscape"])

    # -- acceso -------------------------------------------------------------
    def provider_cfg(self, pid: str) -> Dict[str, Any]:
        cfg = dict(DEFAULT_PROVIDERS.get(pid, {"base_url": "", "model": ""}))
        cfg.update(self.active_provider.get(pid, {}) or {})
        if not cfg.get("api_key"):
            for var in KEY_ENVS.get(pid, []):
                if os.environ.get(var):
                    cfg["api_key"] = os.environ[var]
                    break
        if not cfg.get("base_url"):
            for var in BASE_URL_ENVS.get(pid, []):
                val = os.environ.get(var)
                if val:
                    cfg["base_url"] = val if val.startswith("http") else f"http://{val}"
                    break
        return cfg

    def set_provider(self, pid: str, **kw: Any) -> None:
        cur = self.active_provider.setdefault(pid, {})
        cur.update({k: v for k, v in kw.items() if v is not None})

    def ws(self) -> Path:
        p = Path(os.path.expanduser(self.workspace or default_workspace()))
        p.mkdir(parents=True, exist_ok=True)
        return p

    def path(self) -> Path:
        return config_dir() / "config.json"

    # -- persistencia -------------------------------------------------------
    @classmethod
    def load(cls, path: Optional[Path] = None) -> "Config":
        p = path or cls().path()
        if p.is_file():
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                raw = {}
            fields = {f.name for f in dataclasses.fields(cls)}
            return cls(**{k: v for k, v in raw.items() if k in fields})
        c = cls()
        c.workspace = str(default_workspace())
        return c

    def save(self, path: Optional[Path] = None) -> Path:
        p = path or self.path()
        p.parent.mkdir(parents=True, exist_ok=True)
        data = dataclasses.asdict(self)
        data["history"] = data.get("history", [])[-40:]
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, p)
        try:
            if not sys.platform.startswith("win"):
                os.chmod(p, 0o600)  # puede contener API keys
        except OSError:
            pass
        return p
