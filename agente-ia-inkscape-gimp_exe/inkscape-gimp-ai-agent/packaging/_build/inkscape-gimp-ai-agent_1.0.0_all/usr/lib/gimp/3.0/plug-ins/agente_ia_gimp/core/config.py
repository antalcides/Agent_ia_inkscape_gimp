# -*- coding: utf-8 -*-
"""Carga y guardado de la configuracion (claves, endpoints, preferencias)."""

from __future__ import annotations

import json
import os
import sys

APP_NAME = "inkscape-gimp-ai-agent"

DEFAULT_CONFIG = {
    "provider": "ollama",
    "model": "",
    "base_url_override": {},      # por proveedor: {"omniroute": "http://..."}
    "api_keys": {},               # por proveedor: {"openai": "sk-..."}
    "providers": {},              # ajustes finos por proveedor
    "temperature": 0.2,
    "max_tokens": 8192,
    "timeout": 600,
    "image_size": "1024x1024",
    "output_dir": "",             # vacio = carpeta del usuario
    "last_prompt": "",
    "language": "es",
}


def config_dir():
    """Directorio de configuracion del usuario segun el sistema operativo."""
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, "InkscapeGimpAIAgent")
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
        os.path.expanduser("~"), ".config")
    return os.path.join(base, APP_NAME)


def config_path():
    return os.path.join(config_dir(), "config.json")


def load_config(path=None):
    path = path or config_path()
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # copia profunda
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                stored = json.load(fh)
            _deep_merge(cfg, stored)
        except Exception as exc:  # configuracion corrupta: se ignora y sigue
            sys.stderr.write("Aviso: no se pudo leer %s (%s)\n" % (path, exc))
    return cfg


def save_config(cfg, path=None):
    path = path or config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2, ensure_ascii=False)
    try:
        os.chmod(path, 0o600)  # solo el usuario puede leer las claves
    except OSError:
        pass
    return path


def _deep_merge(target, source):
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = value
    return target


def default_output_dir(cfg=None):
    cfg = cfg or {}
    if cfg.get("output_dir"):
        return os.path.expanduser(cfg["output_dir"])
    if os.name == "nt":
        base = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    else:
        base = os.path.expanduser("~")
    out = os.path.join(base, "InkscapeGimpAIAgent", "salidas")
    os.makedirs(out, exist_ok=True)
    return out


def unique_path(directory, stem, extension):
    """Genera una ruta libre del tipo agente_20260918_1.svg"""
    import datetime
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    candidate = os.path.join(directory, "%s_%s.%s" % (stem, stamp, extension))
    counter = 1
    while os.path.exists(candidate):
        candidate = os.path.join(directory, "%s_%s_%d.%s"
                                 % (stem, stamp, counter, extension))
        counter += 1
    return candidate
