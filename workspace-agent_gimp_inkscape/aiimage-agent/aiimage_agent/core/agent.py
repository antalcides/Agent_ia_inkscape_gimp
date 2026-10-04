"""Orquestador: pedido -> prompt -> proveedor -> PLAN -> ejecución -> (reparo)."""

from __future__ import annotations

import dataclasses
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..providers import get_provider
from . import prompts
from .config import Config
from .plan import Plan, parse_plan, plan_to_json
from .runner import StepResult, Toolchain, discover, results_to_text, run_plan

LOG = Callable[[str], None]
DELTA = Callable[[str], None]


@dataclasses.dataclass
class AgentRun:
    raw_text: str = ""
    plan: Optional[Plan] = None
    results: List[StepResult] = dataclasses.field(default_factory=list)
    log: List[str] = dataclasses.field(default_factory=list)
    error: str = ""
    rounds: int = 0
    elapsed: float = 0.0

    @property
    def ok(self) -> bool:
        return bool(self.plan) and not self.error and all(
            r.ok or r.skipped for r in self.results)

    def files(self) -> List[str]:
        out: List[str] = []
        for r in self.results:
            out += [f for f in r.files if f not in out]
        return out


class Agent:
    def __init__(self, cfg: Config, toolchain: Optional[Toolchain] = None) -> None:
        self.cfg = cfg
        self._tc = toolchain
        self.log_lines: List[str] = []

    # -- herramienta --------------------------------------------------------
    def toolchain(self, refresh: bool = False) -> Toolchain:
        if self._tc is None or refresh:
            b = self.cfg.binaries or {}
            self._tc = discover(b.get("inkscape", ""), b.get("gimp", ""))
            if b.get("python"):
                self._tc.python = [b["python"]]
        return self._tc

    def provider(self, pid: Optional[str] = None):
        pid = pid or self.cfg.provider
        pc = self.cfg.provider_cfg(pid)
        return get_provider(pid, base_url=pc.get("base_url", ""), api_key=pc.get("api_key", ""),
                            timeout=self.cfg.timeout, verify=self.cfg.verify_tls)

    # -- un paso de LLM -----------------------------------------------------
    def ask(self, messages: List[Dict[str, Any]], *, model: str, pid: Optional[str] = None,
            on_delta: Optional[DELTA] = None, json_mode: bool = True) -> str:
        return self.provider(pid).complete(messages, model=model or self.cfg.provider_cfg(pid or self.cfg.provider).get("model", ""),
                                           temperature=self.cfg.temperature, max_tokens=self.cfg.max_tokens,
                                           json_mode=json_mode, on_delta=on_delta)

    # -- flujo completo -----------------------------------------------------
    def run(self, task: str, *, mode: str = "crear", apps: Optional[List[str]] = None,
            inputs: Optional[List[str]] = None, images: Optional[List[str]] = None,
            model: str = "", provider: str = "", on_delta: Optional[DELTA] = None,
            log: Optional[LOG] = None, should_stop: Optional[Callable[[], bool]] = None,
            execute: Optional[bool] = None, workspace: Optional[Path] = None) -> AgentRun:
        run = AgentRun()
        say = self._logger(log, run)
        t0 = time.monotonic()
        apps = apps or ["inkscape"]
        ws = Path(workspace) if workspace else self.cfg.ws()
        ws.mkdir(parents=True, exist_ok=True)
        pid = provider or self.cfg.provider
        model = model or self.cfg.provider_cfg(pid).get("model", "")
        pcfg = self.cfg.provider_cfg(pid)
        say(f"◆ Proveedor {pid} @ {pcfg.get('base_url')} · modelo {model or '(sin modelo)'}")
        say(f"◆ Objetivo: {', '.join(apps)} · modo {mode} · espacio de trabajo {ws}")

        messages = prompts.build_messages(task, mode=mode, apps=apps, workspace=str(ws),
                                         inputs=inputs, image_paths=images)
        try:
            text = self.ask(messages, model=model, pid=pid, on_delta=on_delta)
        except Exception as exc:  # noqa: BLE001 - se muestra en la GUI
            run.error = f"{type(exc).__name__}: {exc}"
            say(f"✗ {run.error}")
            run.elapsed = time.monotonic() - t0
            return run
        run.raw_text = text
        try:
            plan = parse_plan(text, default_app=apps[0])
        except ValueError as exc:
            run.error = str(exc)
            say(f"✗ {exc}")
            run.elapsed = time.monotonic() - t0
            return run
        run.plan = plan
        say(f"✓ Plan recibido: {len(plan.steps)} paso(s). {plan.summary}")
        for w in plan.warnings:
            say(f"  ! {w}")

        do_exec = self.cfg.auto_run if execute is None else execute
        if not do_exec:
            say("◇ auto_run desactivado: no se ejecuta nada. Edita el plan y pulsa 'Ejecutar plan'.")
            run.elapsed = time.monotonic() - t0
            return run
        self._execute(run, ws, say, should_stop, rounds=self.cfg.repair_rounds, model=model, pid=pid)
        run.elapsed = time.monotonic() - t0
        return run

    def execute(self, plan: Plan, *, log: Optional[LOG] = None,
                should_stop: Optional[Callable[[], bool]] = None,
                workspace: Optional[Path] = None, allow_unsafe: Optional[bool] = None) -> AgentRun:
        run = AgentRun(plan=plan)
        say = self._logger(log, run)
        ws = Path(workspace) if workspace else self.cfg.ws()
        do_unsafe = self.cfg.allow_unsafe if allow_unsafe is None else allow_unsafe
        t0 = time.monotonic()
        self._execute(run, ws, say, should_stop, rounds=0, model="", pid="",
                      allow_unsafe=do_unsafe)
        run.elapsed = time.monotonic() - t0
        return run

    # -- interno ------------------------------------------------------------
    def _execute(self, run: AgentRun, ws: Path, say: LOG, should_stop, *, rounds: int,
                 model: str, pid: str, allow_unsafe: Optional[bool] = None) -> None:
        tc = self.toolchain()
        say("◆ Herramientas:\n" + "\n".join("    " + l for l in tc.summary().splitlines()))
        unsafe = self.cfg.allow_unsafe if allow_unsafe is None else allow_unsafe
        for attempt in range(rounds + 1):
            run.results = run_plan(run.plan or Plan(), ws, tc, safe_mode=self.cfg.safe_mode,
                                   allow_unsafe=unsafe, export_preview=self.cfg.export_preview,
                                   should_stop=should_stop, timeout=min(600.0, self.cfg.timeout), log=say)
            run.rounds = attempt + 1
            failed = [r for r in run.results if not r.ok and not r.skipped]
            if not failed:
                say("✓ Ejecución completa sin errores.")
                return
            if should_stop and should_stop():
                say("◇ Cancelado por el usuario.")
                return
            if attempt >= rounds or not model:
                say(f"✗ {len(failed)} paso(s) con error. Revísalo en Consola y pulsa 'Reparar con IA'.")
                return
            say(f"◇ Paso {attempt + 1}: reintentando con la IA ({len(failed)} fallo(s))…")
            if not self._repair(run, ws, say, model=model, pid=pid):
                say("◇ No se pudo obtener un plan corregido; se deja el resultado actual.")
                return

    def _repair(self, run: AgentRun, ws: Path, say: LOG, *, model: str, pid: str) -> bool:
        plan = run.plan or Plan()
        log = results_to_text(run.results)[-6000:]
        msgs = [
            {"role": "system", "content": prompts.build_system_prompt()},
            {"role": "user", "content":
                "TU PLAN ANTERIOR FALLÓ AL EJECUTARSE. Corrígelo y devuelve el JSON COMPLETO del contrato "
                "(summary, notes, steps, explanation). Cambia solo lo necesario para que funcione; "
                "no borres lo que sí funcionaba.\n\n"
                f"=== PLAN ENVIADO ===\n{plan_to_json(plan)}\n\n=== SALIDA/ERRORES REALES ===\n{log}\n\n"
                f"Espacio de trabajo: {ws}\nArchivos presentes: "
                f"{', '.join(sorted(p.name for p in ws.glob('*') if p.is_file())[:40])}"},
        ]
        try:
            text = self.ask(msgs, model=model, pid=pid, on_delta=None)
        except Exception as exc:  # noqa: BLE001
            say(f"✗ El intento de reparación falló: {exc}")
            return False
        try:
            new_plan = parse_plan(text, default_app=(plan.steps[0].app if plan.steps else "inkscape"))
        except ValueError as exc:
            say(f"✗ La reparación no devolvió un plan válido: {exc}")
            return False
        run.raw_text = text
        run.plan = new_plan
        say(f"✓ Plan corregido recibido ({len(new_plan.steps)} pasos): {new_plan.summary}")
        return True

    def _logger(self, log: Optional[LOG], run: AgentRun) -> LOG:
        def say(msg: str) -> None:
            stamp = time.strftime("%H:%M:%S")
            line = f"[{stamp}] {msg}"
            run.log.append(line)
            self.log_lines.append(line)
            if log:
                log(msg)

        return say
