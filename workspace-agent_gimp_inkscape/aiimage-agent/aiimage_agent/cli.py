"""Modo consola (headless) del agente. Útil para pruebas, servidores y automatización.

  python -m aiimage_agent --cli --provider ollama --app gimp -p "reduce a 1200px y aplica niveiles" \\
         -i foto.jpg --execute
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from . import APP_NAME, __version__
from .core.agent import Agent
from .core.config import Config
from .core.plan import parse_plan, plan_to_json, render_plan
from .core.runner import results_to_text
from .providers import PROVIDER_ORDER, PROVIDERS


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="aiimage-agent", description=f"{APP_NAME} · agente de IA para Inkscape y GIMP")
    ap.add_argument("--cli", action="store_true", help="modo consola (sin GUI)")
    ap.add_argument("--provider", "-P", choices=list(PROVIDERS), help="proveedor de IA")
    ap.add_argument("--model", "-m", help="modelo a usar")
    ap.add_argument("--base-url", dest="base_url", help="URL base del proveedor")
    ap.add_argument("--api-key", dest="api_key", help="API key (si aplica)")
    ap.add_argument("--app", "-a", action="append", choices=["inkscape", "gimp"], help="app destino (repetible)")
    ap.add_argument("--mode", "-M", default="crear", choices=["crear", "corregir", "optimizar", "vectorizar", "analizar", "exportar"])
    ap.add_argument("--prompt", "-p", help="pedido para el agente")
    ap.add_argument("--input", "-i", action="append", default=[], help="archivo de entrada (repetible)")
    ap.add_argument("--workspace", "-w", help="carpeta de trabajo")
    ap.add_argument("--execute", "-x", action="store_true", help="ejecutar el plan en Inkscape/GIMP")
    ap.add_argument("--dry-run", action="store_true", help="modo seguro: no ejecutar código")
    ap.add_argument("--allow-unsafe", action="store_true", help="permitir tokens peligrosos en los scripts")
    ap.add_argument("--plan-out", help="guardar el plan en un .json")
    ap.add_argument("--from-plan", help="ejecutar un plan .json existente (sin llamar a la IA)")
    ap.add_argument("--list-models", action="store_true", help="listar modelos del proveedor y salir")
    ap.add_argument("--tools", action="store_true", help="mostrar detección de Inkscape/GIMP y salir")
    ap.add_argument("--providers", action="store_true", help="listar proveedores disponibles y salir")
    ap.add_argument("--timeout", type=float, help="segundos por llamada/paso")
    ap.add_argument("--json", action="store_true", help="salida en JSON (para scripts)")
    ap.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    return ap


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    if args.providers:
        for pid in PROVIDER_ORDER:
            p = PROVIDERS[pid]
            print(f"{p.id:<11} {p.label:<14} base={p.default_base:<45} key={'opcional' if not p.needs_key else 'obligatoria':<12} default={p.default_model}")
            print(f"            {p.blurb}")
        return 0

    cfg = Config.load()
    if args.provider:
        cfg.provider = args.provider
    if args.base_url or args.api_key or args.model:
        cfg.set_provider(cfg.provider, base_url=args.base_url, api_key=args.api_key, model=args.model)
    if args.workspace:
        cfg.workspace = str(Path(args.workspace).expanduser())
    if args.timeout:
        cfg.timeout = args.timeout
    if args.dry_run:
        cfg.safe_mode = True
    elif args.execute:
        cfg.safe_mode = False
    if args.allow_unsafe:
        cfg.allow_unsafe = True
    cfg.auto_run = bool(args.execute)

    agent = Agent(cfg)

    if args.tools:
        print(agent.toolchain(refresh=True).summary())
        return 0

    if args.list_models:
        models, note = agent.provider(args.provider).list_models_or_fallback()
        print(note)
        for m in models:
            print(f"  {m.id}")
        return 0

    if not args.cli:
        # sin --cli intentamos abrir la GUI y caemos a la ayuda si no hay pantalla
        try:
            from .app import main as gui_main

            gui_main()
            return 0
        except Exception as exc:  # noqa: BLE001
            print(f"No se pudo abrir la GUI ({type(exc).__name__}: {exc}).", file=sys.stderr)
            print("Usa --cli para el modo consola.", file=sys.stderr)
            return 2

    if not args.prompt and not args.from_plan:
        print("Falta --prompt (o usa --from-plan).", file=sys.stderr)
        return 2

    if args.from_plan:
        plan = parse_plan(Path(args.from_plan).read_text(encoding="utf-8"))
        run = agent.execute(plan, log=lambda s: print(s, flush=True))
        print(results_to_text(run.results))
        print(f"\nArchivos: {', '.join(run.files()) or '(ninguno)'}")
        return 0 if run.ok else 1

    apps = args.app or ["inkscape"]
    inputs = [str(Path(p).expanduser()) for p in args.input]
    images = [p for p in inputs if Path(p).suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff")]
    vectors = [p for p in inputs if p not in images]

    run = agent.run(
        args.prompt,
        mode=args.mode,
        apps=apps,
        inputs=vectors,
        images=images,
        model=args.model or cfg.provider_cfg(cfg.provider).get("model", ""),
        provider=args.provider,
        on_delta=None if args.json else (lambda s: sys.stdout.write(s)),
        log=lambda s: None if args.json else print("\n" + s, flush=True),
        execute=bool(args.execute),
    )
    if not args.json and run.raw_text and not sys.stdout.isatty():
        pass  # los deltas ya se imprimieron arriba
    if args.json:
        out = {
            "ok": run.ok,
            "error": run.error,
            "plan": plan_to_json(run.plan) if run.plan else None,
            "files": run.files(),
            "log": run.log,
            "elapsed": round(run.elapsed, 2),
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        if run.plan:
            print("\n" + render_plan(run.plan))
        if run.plan and args.execute:
            print("\n=== EJECUCIÓN ===")
            print(results_to_text(run.results))
    if args.plan_out and run.plan:
        Path(args.plan_out).write_text(plan_to_json(run.plan), encoding="utf-8")
        print(f"\nPlan guardado en {args.plan_out}")
    if run.error:
        print(f"\nERROR: {run.error}", file=sys.stderr)
        return 1
    return 0 if (not args.execute or run.ok) else 1
