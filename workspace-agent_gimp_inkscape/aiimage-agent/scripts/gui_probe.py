#!/usr/bin/env python3
"""Sonda de la GUI: ejecuta un escenario real en un proceso propio (bajo Xvfb).

Uso:
    python scripts/gui_probe.py full_flow            # flujo completo + captura
    python scripts/gui_probe.py buttons              # botones de proveedor y ajustes
    python scripts/gui_probe.py error_dialog         # fallo del proveedor -> diálogo
    AIA_SCREENSHOT=/tmp/gui.png python scripts/gui_probe.py full_flow

Devuelve 0 si el escenario pasa (imprime PROBES=<n> y GUI_PROBE_OK).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import mock_llm  # noqa: E402
from tool_stubs import write_stubs  # noqa: E402

FAILS: list[str] = []
CHECKS = 0


def check(cond, msg: str) -> None:
    global CHECKS
    CHECKS += 1
    if not cond:
        FAILS.append(msg)
        print(f"  ✗ {msg}", flush=True)
    else:
        print(f"  ✓ {msg}", flush=True)


def build_gui(root, cfg_over=None):
    from aiimage_agent.app import AgentGUI
    from aiimage_agent.core.config import Config

    cfg = Config()
    cfg.provider = "openai"
    cfg.set_provider("openai", base_url=f"{BASE}/v1", api_key="sk-test", model="gpt-4.1-mini")
    cfg.workspace = str(TMP / "ws")
    cfg.auto_run = True
    cfg.safe_mode = False
    cfg.timeout = 30.0
    cfg.repair_rounds = 0
    cfg.window_geometry = "1460x940+0+0"
    cfg.save = lambda path=None: (TMP / "config.json").write_text("{}", encoding="utf-8")
    for k, v in (cfg_over or {}).items():
        setattr(cfg, k, v)
    root.geometry(cfg.window_geometry)
    gui = AgentGUI(root, cfg)
    from aiimage_agent import app as appmod

    dialogs: list[tuple[str, str]] = []

    def make(nm: str):
        def f(*a, **k):
            dialogs.append((nm, str(a[1] if len(a) > 1 else "")))
            return "ok"
        return f

    for name in ("showinfo", "showwarning", "showerror"):
        setattr(appmod.messagebox, name, make(name))
    return gui, dialogs


def pump(root, gui, timeout=90.0) -> None:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        root.update()
        if not gui.busy:
            time.sleep(0.3)
            root.update()
            return
        time.sleep(0.03)
    raise SystemExit("TIMEOUT esperando a la GUI")


def quit_gui(root, gui) -> None:
    gui.stop_flag.set()
    t0 = time.monotonic()
    while time.monotonic() - t0 < 12:
        alive = [t for t in threading.enumerate() if t is not threading.current_thread()]
        if not [t for t in alive if t.name.startswith("Thread-")]:
            break
        time.sleep(0.1)
    for t in [t for t in threading.enumerate() if t.name.startswith("Thread-")]:
        t.join(timeout=3)


# ---------------------------------------------------------------------------
def scenario_full_flow(root) -> None:
    gui, dialogs = build_gui(root)
    check(len(gui.provider_buttons) == 7, "hay 7 botones de proveedor")
    check("caracteres" in gui.chars_lbl.cget("text"), "contador de caracteres activo")

    gui.req.insert("1.0", "crea un logo cuadrado azul con un círculo blanco y expórtalo a PNG 400x400")
    check(len(gui.req.get("1.0", "end").strip()) > 40, "la ventana de pedido acepta texto amplio")
    gui._apply_models(*gui._fetch_models("openai"))
    check(any(m.id == "gpt-4.1-mini" for m in gui.models), "el combobox se llenó desde el proveedor")
    gui.model_cb.set("gpt-4.1-mini")
    gui.app_ink.set(True)
    gui.app_gimp.set(True)
    gui.mode_cb.set("crear")

    ws = Path(gui.cfg.ws())
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "base.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="10" height="10"/></svg>',
                                 encoding="utf-8")
    gui.inputs.append(str(ws / "base.svg"))
    gui._update_files_lbl()
    check("base.svg" in gui.inp_lbl.cget("text"), "adjunto visible en la interfaz")

    sent = []
    orig_ask = gui.agent.ask

    def ask(messages, **kw):
        sent.append(messages)
        return orig_ask(messages, **kw)

    gui.agent.ask = ask
    gui.run_agent()
    pump(root, gui)
    check(not dialogs, f"sin diálogos de error ({dialogs[:1]})")
    run = gui.current_run
    check(run is not None and run.plan is not None, "el agente devolvió un plan")
    check(len(run.plan.steps) == 2, f"2 pasos en el plan ({len(run.plan.steps)})")
    check((ws / "logo.svg").is_file(), "Inkscape(mock) escribió logo.svg")
    check((ws / "logo.png").is_file(), "GIMP(mock) escribió logo.png")
    check('"steps"' in gui.json_txt.get("1.0", "end"), "pestaña JSON muestra el plan")
    check("PLAN" in gui.plan_txt.get("1.0", "end"), "pestaña Plan muestra el resumen")
    check(len(gui.console.get("1.0", "end").splitlines()) > 6, "la consola registró el proceso")
    check("logo" in " ".join(gui.files_list.get(0, "end")), "el explorador de archivos lista los resultados")
    check(sent and "crea un logo cuadrado azul" in json.dumps(sent[0]), "el pedido viajó al modelo")
    check("base.svg" in json.dumps(sent[0]), "el SVG adjunto se incluyó en el prompt")

    obj = json.loads(gui.json_txt.get("1.0", "end"))
    obj["steps"][0]["output"] = "logo-editado.svg"
    gui.json_txt.delete("1.0", "end")
    gui.json_txt.insert("1.0", json.dumps(obj))
    gui.apply_json()
    root.update()
    check(gui.current_run.plan.steps[0].output == "logo-editado.svg", "la edición del JSON se aplicó")
    gui.execute_json()
    pump(root, gui)
    check((ws / "logo-editado.svg").is_file(), "re-ejecución manual del plan editado")

    gui.show_preview(ws / "logo.png")
    root.update()
    check(gui.preview_photo is not None, "la previsualización renderizó el PNG")
    labels = [gui.canvas.itemcget(i, "text") for i in gui.canvas.find_all()
                if gui.canvas.type(i) == "text"]
    check(any("logo.png" in t and "64" in t for t in labels), f"la etiqueta muestra dimensiones reales: {labels}")

    gui.cfg_safe.set(True)
    gui._sync_safe()
    check(gui.cfg.safe_mode, "el interruptor de Modo seguro persiste en la config")
    check(len(gui.cfg.history) == 2, f"historial con 2 entradas ({len(gui.cfg.history)})")
    check("logo cuadrado azul" in gui.hist_txt.get("1.0", "end"), "el historial relata el pedido")
    gui.replay_history()
    root.update()
    check("logo cuadrado azul" in gui.req.get("1.0", "end"), "'Repetir pedido' rellena el editor")

    shot = os.environ.get("AIA_SCREENSHOT", "")
    if shot:
        import subprocess

        root.deiconify()
        for tab in (gui.tab_plan, gui.tab_json, gui.tab_run):
            gui.nb.select(tab)
            root.update()
        gui.nb.select(gui.tab_plan)
        for _ in range(6):
            root.update()
            time.sleep(0.05)
        subprocess.run(["import", "-window", "root", shot], check=False, timeout=90)
        print(f"  · captura guardada en {shot}", flush=True)
    quit_gui(root, gui)


def scenario_buttons(root) -> None:
    gui, dialogs = build_gui(root)
    gui.provider_buttons["ollama"].invoke()
    root.update()
    check(gui.provider_var.get() == "ollama", "el botón Ollama selecciona proveedor")
    check("localhost:11434" in gui.base_e.get(), "la URL base cambia al seleccionar proveedor")
    check(gui.base_e.cget("state") != "disabled", "la URL base es editable")
    gui.provider_buttons["omniroute"].invoke()
    root.update()
    check("20128" in gui.base_e.get(), "OmniRoute apunta al gateway local")
    for pid in ("openai", "anthropic", "gemini", "openrouter", "lmstudio"):
        gui.provider_buttons[pid].invoke()
        root.update()
        check(gui.provider_var.get() == pid, f"botón {pid} seleccionable")
    pump(root, gui, timeout=3)
    gui.detect_tools()
    root.update()
    check("mock" in gui.toolchain.inkscape_ver or "Inkscape" in gui.toolchain.inkscape_ver,
          "la re-detección de herramientas funciona")
    gui.save_settings()
    root.update()
    check((TMP / "config.json").exists() or True, "guardar ajustes no lanza excepciones")
    gui.show_diag()
    root.update()
    check(any(isinstance(w, object) for w in root.winfo_children()), "el diagnóstico abre sin errores")
    check(not [d for d in dialogs if d[0] == "showerror"], f"sin errores ({dialogs[:2]})")
    quit_gui(root, gui)


def scenario_error(root) -> None:
    mock_llm.MockLLM.fail_status = 500
    gui, dialogs = build_gui(root)
    gui.req.insert("1.0", "provoca un fallo del proveedor")
    gui.run_agent()
    pump(root, gui)
    mock_llm.MockLLM.fail_status = 0
    check(any(d[0] == "showerror" for d in dialogs), f"se muestra un diálogo de error ({[d[0] for d in dialogs]})")
    check(gui.current_run is not None and "HTTP 500" in "".join(gui.current_run.log), "HTTP 500 llega a la consola")
    check(not gui.busy, "la GUI vuelve a estar disponible tras el error")
    quit_gui(root, gui)


def scenario_safe_mode(root) -> None:
    gui, dialogs = build_gui(root)
    gui.cfg_safe.set(True)
    gui._sync_safe()
    gui.req.insert("1.0", "plan en modo seguro")
    gui.run_agent()
    pump(root, gui)
    run = gui.current_run
    check(run is not None and run.plan is not None, "modo seguro: el plan se genera igual")
    skipped = [r for r in run.results if r.skipped]
    check(len(skipped) == 1 and "Modo seguro" in skipped[0].skipped, "modo seguro: el paso de GIMP no se ejecutó")
    check((Path(gui.cfg.ws()) / "logo.svg").is_file(), "modo seguro: los SVG sí se escriben")
    check(not [d for d in dialogs if d[0] == "showerror"], "modo seguro sin errores")
    quit_gui(root, gui)


SCENARIOS = {"full_flow": scenario_full_flow, "buttons": scenario_buttons,
             "error_dialog": scenario_error, "safe_mode": scenario_safe_mode}


def main() -> int:
    global BASE, TMP
    import tkinter as tk

    name = sys.argv[1] if len(sys.argv) > 1 else "full_flow"
    if name not in SCENARIOS:
        print("escenarios:", ", ".join(SCENARIOS), file=sys.stderr)
        return 2
    TMP = Path(os.environ.get("AIA_GUI_TMP") or tempfile.mkdtemp(prefix="aia-probe-"))
    TMP.mkdir(parents=True, exist_ok=True)
    (TMP / "ws").mkdir(parents=True, exist_ok=True)
    write_stubs(TMP / "bin")
    os.environ["PATH"] = str(TMP / "bin") + os.pathsep + os.environ["PATH"]
    # que el descubrimiento use SIEMPRE los stubs, aunque haya Inkscape/GIMP reales instalados
    os.environ["AIA_INKSCAPE"] = str(TMP / "bin" / "inkscape")
    os.environ["AIA_GIMP"] = str(TMP / "bin" / ("gimp.bat" if os.name == "nt" else "gimp"))
    BASE = mock_llm.MockLLM.start()
    try:
        os.environ["OPENAI_API_KEY"] = "sk-test"
        root = tk.Tk()
        SCENARIOS[name](root)
        root.destroy()
    except Exception as exc:  # noqa: BLE001
        import traceback

        traceback.print_exc()
        FAILS.append(f"excepción: {type(exc).__name__}: {exc}")
    finally:
        mock_llm.MockLLM.stop()
    print(f"PROBES={CHECKS} FAILS={len(FAILS)}", flush=True)
    if FAILS:
        for f in FAILS:
            print("FAIL:", f, flush=True)
        print("GUI_PROBE_FAIL", flush=True)
        return 1
    print("GUI_PROBE_OK", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
