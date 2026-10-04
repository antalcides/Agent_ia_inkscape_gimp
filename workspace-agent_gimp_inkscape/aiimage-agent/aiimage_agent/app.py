"""Interfaz gráfica (Tkinter) del AI Image Agent.

Diseño: barra superior de **botones de proveedor**, selector de **modelo**,
**ventana amplia** para desarrollar el pedido a la izquierda, y pestañas
(Plan editable / Consola / Archivos / Historial / Ajustes) a la derecha.

Sólo librería estándar: se empaqueta sin problemas en .exe y Flatpak.
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Dict, List, Optional

from . import APP_NAME, __version__
from .core import prompts
from .core.agent import Agent, AgentRun
from .core.config import Config
from .core.plan import edit_steps_from_text, parse_plan, plan_to_json, render_plan
from .providers import PROVIDER_ORDER, PROVIDERS

MODES = ["crear", "corregir", "optimizar", "vectorizar", "analizar", "exportar"]
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff")
VEC_EXT = (".svg",)
ALL_EXT = IMG_EXT + VEC_EXT + (".pdf", ".eps", ".xcf")

ACCENT = "#2f6f4f"
ACCENT_DARK = "#1f4c37"
MUTED = "#6b7280"


def _int(raw, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(float(str(raw).strip())))
    except (TypeError, ValueError):
        return int(default)


def _num(raw, default: float) -> float:
    try:
        return max(1.0, float(str(raw).strip()))
    except (TypeError, ValueError):
        return float(default)


class AgentGUI:
    def __init__(self, root: tk.Tk, cfg: Optional[Config] = None) -> None:
        self.root = root
        self.cfg = cfg or Config.load()
        self.agent = Agent(self.cfg)
        self.q: "queue.Queue[tuple[str, Any]]" = queue.Queue()
        self.stop_flag = threading.Event()
        self.busy = False
        self.models: List[Any] = []
        self.current_run: Optional[AgentRun] = None
        self.inputs: List[str] = []
        self.images: List[str] = []
        self.preview_photo = None
        self.toolchain = self.agent.toolchain()
        self.cfg_safe = tk.BooleanVar(value=self.cfg.safe_mode)

        root.title(f"{APP_NAME} · Inkscape + GIMP · v{__version__}")
        root.geometry(self.cfg.window_geometry or "1420x900")
        root.minsize(1100, 700)
        self._set_icon()
        self._style()
        self._build_menu()
        self._build_top()
        self._build_body()
        self._build_status()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.bind_all("<Control-Return>", lambda e: self.run_agent())
        root.bind_all("<Control-c>", lambda e: self.stop())
        root.bind_all("<Escape>", lambda e: self.stop())
        root.bind_all("<F5>", lambda e: self.refresh_models())
        root.after(60, self._poll)
        self._startup()

    # ------------------------------------------------------------------ UI --
    def _set_icon(self) -> None:
        from .core.resources import asset

        ico, png = asset("icon.ico"), asset("icon.png")
        try:
            if ico and (sys.platform.startswith("win") or not png):
                self.root.iconbitmap(str(ico))
            if png:
                self.root.iconphoto(True, tk.PhotoImage(file=str(png)))
            elif ico and not sys.platform.startswith("win"):
                self.root.iconphoto(True, tk.PhotoImage(file=str(ico)))
        except (tk.TclError, OSError):
            pass

    def _style(self) -> None:
        st = ttk.Style(self.root)
        for theme in ("clam", "alt", "default"):
            if theme in st.theme_names():
                st.theme_use(theme)
                break
        st.configure(".", font=("Segoe UI", 10) if sys.platform.startswith("win") else ("Sans", 10))
        st.configure("TNotebook.Tab", padding=(14, 7))
        st.configure("Tool.TButton", padding=(9, 5))
        st.configure("Run.TButton", padding=(14, 8), font=("Segoe UI", 11, "bold")
                     if sys.platform.startswith("win") else ("Sans", 11, "bold"))
        self.root.option_add("*TCombobox*Listbox.font", ("Consolas", 10) if sys.platform.startswith("win") else ("Monospace", 10))

    def _build_menu(self) -> None:
        m = tk.Menu(self.root)
        f = tk.Menu(m, tearoff=0)
        f.add_command(label="Nuevo pedido (limpia todo)", accelerator="Ctrl+L", command=self.clear_all)
        f.add_command(label="Abrir proyecto…", command=self.open_project)
        f.add_command(label="Guardar plan en .json…", command=self.save_plan)
        f.add_command(label="Guardar script suelto…", command=self.save_script)
        f.add_separator()
        f.add_command(label="Abrir espacio de trabajo", command=lambda: self.open_path(self.cfg.ws()))
        f.add_command(label="Salir", command=self.on_close)
        m.add_cascade(label="Archivo", menu=f)
        v = tk.Menu(m, tearoff=0)
        v.add_command(label="Refrescar modelos", accelerator="F5", command=self.refresh_models)
        v.add_command(label="Re-detectar Inkscape/GIMP", command=self.detect_tools)
        v.add_checkbutton(label="Modo seguro (no ejecutar código)", variable=self.cfg_safe)
        m.add_cascade(label="Ver", menu=v)
        h = tk.Menu(m, tearoff=0)
        h.add_command(label="Cómo se usa", command=self.show_help)
        h.add_command(label="Diagnóstico de entorno", command=self.show_diag)
        h.add_command(label="Acerca de", command=self.show_about)
        m.add_cascade(label="Ayuda", menu=h)
        self.root.config(menu=m)
        self.root.bind_all("<Control-l>", lambda e: self.clear_all())

    def _build_top(self) -> None:
        top = ttk.Frame(self.root, padding=(10, 8, 10, 4))
        top.pack(fill="x")

        ttk.Label(top, text="PROVEEDOR DE IA", foreground=MUTED).grid(row=0, column=0, sticky="w")
        btns = ttk.Frame(top)
        btns.grid(row=1, column=0, columnspan=3, sticky="w", pady=(2, 6))
        self.provider_var = tk.StringVar(value=self.cfg.provider)
        self.provider_buttons: Dict[str, tk.Radiobutton] = {}
        for pid in PROVIDER_ORDER:
            prov = PROVIDERS[pid]
            b = tk.Radiobutton(
                btns, text=prov.label, value=pid, variable=self.provider_var,
                indicatoron=False, width=12, pady=4, command=self._on_provider_change,
                relief="raised", bd=2, highlightthickness=0, selectcolor=ACCENT,
                fg="#1f2937", bg="#ececf1", activebackground="#dcdce4", activeforeground="#111827",
                font=("Segoe UI", 10, "bold") if sys.platform.startswith("win") else ("Sans", 10, "bold"),
            )
            b.pack(side="left", padx=(0, 6))
            self.provider_buttons[pid] = b
        self._paint_provider_buttons()

        self.conn_lbl = ttk.Label(top, text="", foreground=MUTED)
        self.conn_lbl.grid(row=1, column=4, sticky="e", padx=(10, 0))

        row2 = ttk.Frame(top)
        row2.grid(row=2, column=0, columnspan=3, sticky="we", pady=(0, 4))
        ttk.Label(row2, text="Modelo:").pack(side="left")
        self.model_cb = ttk.Combobox(row2, width=42, values=[])
        self.model_cb.pack(side="left", padx=(6, 6))
        self.model_cb.bind("<Return>", lambda e: self._save_form())
        ttk.Button(row2, text="Refrescar (F5)", style="Tool.TButton", command=self.refresh_models).pack(side="left", padx=(0, 6))
        ttk.Button(row2, text="Probar conexión", style="Tool.TButton", command=self.test_connection).pack(side="left", padx=(0, 10))
        ttk.Label(row2, text="URL base:").pack(side="left")
        self.base_e = ttk.Entry(row2, width=40)
        self.base_e.pack(side="left", padx=(4, 6))
        ttk.Label(row2, text="API key:").pack(side="left")
        self.key_e = ttk.Entry(row2, width=28, show="•")
        self.key_e.pack(side="left", padx=(4, 6))
        ttk.Button(row2, text="Ajustes", style="Tool.TButton", command=lambda: self.nb.select(self.tab_cfg)).pack(side="left")

        row3 = ttk.Frame(top)
        row3.grid(row=3, column=0, columnspan=3, sticky="we", pady=(0, 2))
        ttk.Label(row3, text="Aplicación destino:").pack(side="left")
        self.app_ink = tk.BooleanVar(value="inkscape" in (self.cfg.last_apps or []))
        self.app_gimp = tk.BooleanVar(value="gimp" in (self.cfg.last_apps or []))
        if not (self.app_ink.get() or self.app_gimp.get()):
            self.app_ink.set(True)
        ttk.Checkbutton(row3, text="Inkscape (vector)", variable=self.app_ink, command=self._update_apps_lbl).pack(side="left", padx=(6, 10))
        ttk.Checkbutton(row3, text="GIMP (bitmap)", variable=self.app_gimp, command=self._update_apps_lbl).pack(side="left", padx=(0, 16))
        ttk.Label(row3, text="Modo:").pack(side="left")
        self.mode_cb = ttk.Combobox(row3, width=12, values=MODES, state="readonly")
        self.mode_cb.set(self.cfg.last_mode if self.cfg.last_mode in MODES else "crear")
        self.mode_cb.pack(side="left", padx=(4, 16))
        ttk.Label(row3, text="Temp:").pack(side="left")
        self.temp_s = ttk.Scale(row3, from_=0.0, to=1.0, orient="horizontal", length=120)
        self.temp_s.set(self.cfg.temperature)
        self.temp_s.pack(side="left", padx=(4, 4))
        ttk.Checkbutton(row3, text="Modo seguro (no ejecutar)", variable=self.cfg_safe,
                        command=self._sync_safe).pack(side="left", padx=(12, 0))
        self.tools_lbl = ttk.Label(row3, foreground=MUTED, text="")
        self.tools_lbl.pack(side="right", padx=(10, 0))
        self._update_apps_lbl()
        self._sync_safe()

    def _build_body(self) -> None:
        paned = ttk.Panedwindow(self.root, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=10, pady=(0, 4))

        left = ttk.Frame(paned)
        right = ttk.Frame(paned)
        paned.add(left, weight=45)
        paned.add(right, weight=55)

        # ---- izquierda: pedido amplio + acciones + previsualización
        head = ttk.Frame(left)
        head.pack(fill="x")
        ttk.Label(head, text="PEDIDO PARA EL AGENTE  (Ctrl+Enter = ejecutar)",
                  foreground=MUTED).pack(anchor="w")
        ttk.Button(head, text="Vaciar", style="Tool.TButton", command=self.clear_all).pack(side="right")
        self.req = tk.Text(left, height=16, wrap="word", undo=True, relief="solid", bd=1,
                           padx=12, pady=10, font=("Segoe UI", 11) if sys.platform.startswith("win") else ("Sans", 11),
                           background="#fffdf7", insertbackground="#111827")
        self.req.pack(fill="both", expand=True, pady=(4, 4))
        self.req.insert("1.0", self.cfg.last_task or "")
        self.req.bind("<KeyRelease>", lambda e: self._count_chars())
        self.req.bind("<<Modified>>", lambda e: self._count_chars())

        self.inp_lbl = ttk.Label(left, text="sin archivos adjuntos", foreground=MUTED)
        self.inp_lbl.pack(anchor="w")

        bar = ttk.Frame(left)
        bar.pack(fill="x", pady=(2, 4))
        self.run_btn = ttk.Button(bar, text="▶  Ejecutar agente", style="Run.TButton", command=self.run_agent)
        self.run_btn.pack(side="left")
        ttk.Button(bar, text="Detener", style="Tool.TButton", command=self.stop).pack(side="left", padx=6)
        ttk.Button(bar, text="Añadir SVG/PNG…", style="Tool.TButton", command=self.attach_files).pack(side="left", padx=6)
        ttk.Button(bar, text="Quitar adjuntos", style="Tool.TButton", command=self.clear_files).pack(side="left")

        prev_bar = ttk.Frame(left)
        prev_bar.pack(fill="x", pady=(6, 2))
        ttk.Label(prev_bar, text="PREVISUALIZACIÓN", foreground=MUTED).pack(side="left")
        ttk.Button(prev_bar, text="Refrescar", style="Tool.TButton", command=self.show_preview).pack(side="right", padx=(6, 0))
        ttk.Button(prev_bar, text="Abrir en Inkscape", style="Tool.TButton",
                   command=lambda: self.open_in("inkscape")).pack(side="right", padx=(6, 0))
        ttk.Button(prev_bar, text="Abrir en GIMP", style="Tool.TButton",
                   command=lambda: self.open_in("gimp")).pack(side="right")
        self.canvas = tk.Canvas(left, height=230, background="#e9e9ec", highlightthickness=1,
                                relief="solid", bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.show_preview())

        # ---- derecha: pestañas
        self.nb = ttk.Notebook(right)
        self.nb.pack(fill="both", expand=True)

        self.tab_plan = ttk.Frame(self.nb)
        self.nb.add(self.tab_plan, text="  Plan / pasos  ")
        pf = ttk.Frame(self.tab_plan)
        pf.pack(fill="both", expand=True, padx=6, pady=6)
        ttk.Label(pf, text="Los marcadores {INPUT} / {OUTPUT} / {WORKSPACE} se sustituyen por rutas reales al ejecutar.",
                  foreground=MUTED).pack(anchor="w", pady=(0, 4))
        self.plan_txt = tk.Text(pf, wrap="word", font=("Consolas", 10) if sys.platform.startswith("win") else ("Monospace", 10),
                                relief="solid", bd=1, padx=8, pady=6, background="#f7f7f9")
        self.plan_txt.pack(fill="both", expand=True)

        self.tab_json = ttk.Frame(self.nb)
        self.nb.add(self.tab_json, text="  JSON editable  ")
        jf = ttk.Frame(self.tab_json)
        jf.pack(fill="both", expand=True, padx=6, pady=(6, 0))
        jbar = ttk.Frame(self.tab_json)
        jbar.pack(fill="x", padx=6, pady=4)
        ttk.Button(jbar, text="Aplicar edición", style="Tool.TButton", command=self.apply_json).pack(side="left")
        ttk.Button(jbar, text="Ejecutar solo este plan", style="Tool.TButton", command=self.execute_json).pack(side="left", padx=6)
        ttk.Button(jbar, text="Formato", style="Tool.TButton", command=self.format_json).pack(side="left")
        ttk.Label(jbar, text="Puedes corregir el código del modelo antes de ejecutarlo.",
                  foreground=MUTED).pack(side="left", padx=10)
        self.json_txt = tk.Text(jf, wrap="none", font=("Consolas", 10) if sys.platform.startswith("win") else ("Monospace", 10),
                                relief="solid", bd=1, padx=8, pady=6, undo=True)
        self.json_txt.pack(fill="both", expand=True)

        self.tab_run = ttk.Frame(self.nb)
        self.nb.add(self.tab_run, text="  Consola  ")
        cf = ttk.Frame(self.tab_run)
        cf.pack(fill="both", expand=True, padx=6, pady=6)
        self.console = tk.Text(cf, wrap="word", state="disabled", font=("Consolas", 10) if sys.platform.startswith("win") else ("Monospace", 10),
                               relief="solid", bd=1, padx=8, pady=6, background="#11151c", foreground="#d8dee9")
        self.console.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(cf, command=self.console.yview)
        sb.pack(side="right", fill="y")
        self.console.config(yscrollcommand=sb.set)
        cbar = ttk.Frame(self.tab_run)
        cbar.pack(fill="x", padx=6, pady=(0, 6))
        ttk.Button(cbar, text="Ejecutar en Inkscape", style="Tool.TButton",
                   command=lambda: self.run_app_steps("inkscape")).pack(side="left")
        ttk.Button(cbar, text="Ejecutar en GIMP", style="Tool.TButton",
                   command=lambda: self.run_app_steps("gimp")).pack(side="left", padx=6)
        ttk.Button(cbar, text="Reparar con IA (usa la consola como error)", style="Tool.TButton",
                   command=self.repair_with_ai).pack(side="left")
        ttk.Button(cbar, text="Limpiar", style="Tool.TButton", command=self.clear_console).pack(side="right")

        self.tab_files = ttk.Frame(self.nb)
        self.nb.add(self.tab_files, text="  Archivos  ")
        ff = ttk.Frame(self.tab_files)
        ff.pack(fill="both", expand=True, padx=6, pady=6)
        self.files_list = tk.Listbox(ff, font=("Consolas", 10) if sys.platform.startswith("win") else ("Monospace", 10),
                                     activestyle="dotbox")
        self.files_list.pack(side="left", fill="both", expand=True)
        fbtns = ttk.Frame(ff)
        fbtns.pack(side="right", fill="y", padx=(6, 0))
        for label, cmd in (("Abrir", lambda: self.open_selected()), ("Inkscape", lambda: self.open_selected("inkscape")),
                           ("GIMP", lambda: self.open_selected("gimp")), ("Exportar PNG", self.export_png),
                           ("Carpeta", lambda: self.open_path(self.cfg.ws())), ("Refrescar", self.refresh_files)):
            ttk.Button(fbtns, text=label, style="Tool.TButton", command=cmd).pack(fill="x", pady=2)
        self.files_list.bind("<Double-Button-1>", lambda e: self.open_selected())

        self.tab_hist = ttk.Frame(self.nb)
        self.nb.add(self.tab_hist, text="  Historial  ")
        hf = ttk.Frame(self.tab_hist)
        hf.pack(fill="both", expand=True, padx=6, pady=6)
        self.hist_txt = tk.Text(hf, wrap="word", state="disabled", font=("Consolas", 10) if sys.platform.startswith("win") else ("Monospace", 10),
                                relief="solid", bd=1, padx=8, pady=6)
        self.hist_txt.pack(fill="both", expand=True)
        ttk.Button(self.tab_hist, text="Repetir el pedido anterior", style="Tool.TButton",
                   command=self.replay_history).pack(anchor="w", padx=6, pady=(0, 6))
        self._render_history()

        self.tab_cfg = ttk.Frame(self.nb)
        self.nb.add(self.tab_cfg, text="  Ajustes  ")
        self._build_settings_tab()

    def _build_settings_tab(self) -> None:
        f = ttk.Frame(self.tab_cfg, padding=10)
        f.pack(fill="both", expand=True)
        row = 0
        self._cfg_rows: Dict[str, Any] = {}
        for pid in PROVIDER_ORDER:
            prov = PROVIDERS[pid]
            ttk.Label(f, text=f"{prov.label}", font=("", 10, "bold")).grid(row=row, column=0, sticky="w", pady=(8, 0))
            ttk.Label(f, text=prov.blurb, foreground=MUTED, wraplength=640,
                      justify="left").grid(row=row, column=1, columnspan=3, sticky="w", pady=(8, 0))
            row += 1
            pc = self.cfg.provider_cfg(pid)
            ttk.Label(f, text="URL base").grid(row=row, column=0, sticky="w")
            base = ttk.Entry(f, width=52)
            base.insert(0, pc.get("base_url", ""))
            base.grid(row=row, column=1, sticky="we", padx=6)
            ttk.Label(f, text="API key").grid(row=row, column=2, sticky="e")
            key = ttk.Entry(f, width=34, show="•")
            key.insert(0, pc.get("api_key", ""))
            key.grid(row=row, column=3, sticky="we", padx=6)
            self._cfg_rows[pid] = (base, key)
            row += 1

        sep = ttk.Separator(f, orient="horizontal")
        sep.grid(row=row, column=0, columnspan=4, sticky="we", pady=12)
        row += 1
        binrows = [("Ruta de Inkscape (opcional)", "inkscape"), ("Ruta de GIMP (opcional)", "gimp"),
                   ("Ruta de Python (opcional)", "python")]
        for label, k in binrows:
            ttk.Label(f, text=label).grid(row=row, column=0, sticky="w", pady=2)
            e = ttk.Entry(f, width=52)
            e.insert(0, self.cfg.binaries.get(k, ""))
            e.grid(row=row, column=1, columnspan=2, sticky="we", padx=6)
            ttk.Button(f, text="Buscar", style="Tool.TButton",
                       command=lambda k=k: self.browse_bin(k)).grid(row=row, column=3, sticky="e")
            self._cfg_rows[f"bin:{k}"] = (e,)
            row += 1
        ttk.Label(f, text="Espacio de trabajo").grid(row=row, column=0, sticky="w", pady=2)
        self.ws_e = ttk.Entry(f, width=52)
        self.ws_e.insert(0, str(self.cfg.ws()))
        self.ws_e.grid(row=row, column=1, columnspan=2, sticky="we", padx=6)
        ttk.Button(f, text="Elegir", style="Tool.TButton", command=self.browse_ws).grid(row=row, column=3, sticky="e")
        row += 1
        for label, var, spin_key in (
            ("Máx. tokens de salida", tk.IntVar(value=self.cfg.max_tokens), "cfg:max_tokens"),
            ("Timeout por paso (s)", tk.IntVar(value=int(self.cfg.timeout)), "cfg:timeout"),
            ("Rondas de auto-reparación", tk.IntVar(value=self.cfg.repair_rounds), "cfg:repair"),
        ):
            ttk.Label(f, text=label).grid(row=row, column=0, sticky="w", pady=2)
            sp = ttk.Spinbox(f, from_=1, to=64000, textvariable=var, width=10)
            sp.grid(row=row, column=1, sticky="w", padx=6)
            self._cfg_rows[spin_key] = (var,)
            row += 1
        self.auto_run_v = tk.BooleanVar(value=self.cfg.auto_run)
        self.preview_v = tk.BooleanVar(value=self.cfg.export_preview)
        self.allow_unsafe_v = tk.BooleanVar(value=self.cfg.allow_unsafe)
        ttk.Checkbutton(f, text="Ejecutar el plan automáticamente tras generarlo", variable=self.auto_run_v)\
            .grid(row=row, column=0, columnspan=3, sticky="w", pady=(6, 0))
        row += 1
        ttk.Checkbutton(f, text="Exportar previsualización PNG de los SVG (via inkscape CLI)", variable=self.preview_v)\
            .grid(row=row, column=0, columnspan=3, sticky="w")
        row += 1
        cb = ttk.Checkbutton(f, text="PERMITIR código con riesgo (subprocess/os.system en scripts generados)",
                             variable=self.allow_unsafe_v)
        cb.grid(row=row, column=0, columnspan=3, sticky="w")
        row += 1
        ttk.Button(f, text="Guardar ajustes", style="Tool.TButton", command=self.save_settings).grid(row=row, column=0, sticky="w", pady=(10, 0))
        ttk.Button(f, text="Detectar herramientas", style="Tool.TButton", command=self.detect_tools).grid(row=row, column=1, sticky="w", pady=(10, 0))
        f.columnconfigure(1, weight=1)
        f.columnconfigure(3, weight=1)

    def _build_status(self) -> None:
        bar = ttk.Frame(self.root, padding=(10, 2))
        bar.pack(fill="x")
        self.status = ttk.Label(bar, text="listo", foreground=MUTED)
        self.status.pack(side="left")
        self.pbar = ttk.Progressbar(bar, mode="indeterminate", length=180)
        self.pbar.pack(side="right", padx=(8, 0))
        self.chars_lbl = ttk.Label(bar, text="", foreground=MUTED)
        self.chars_lbl.pack(side="right", padx=8)
        self._count_chars()

    # ------------------------------------------------------------- arranque --
    def _startup(self) -> None:
        pid = self.cfg.provider
        pc = self.cfg.provider_cfg(pid)
        self.base_e.insert(0, pc.get("base_url", ""))
        self.key_e.insert(0, pc.get("api_key", ""))
        self.model_cb.set(pc.get("model", ""))
        self._log(f"{APP_NAME} v{__version__} · Python {sys.version.split()[0]} · Tk {self.root.tk.call('info', 'patchlevel')}")
        self._log(self.toolchain.summary())
        self.tools_lbl.config(text=f"Inkscape: {'OK' if self.toolchain.inkscape_ok else 'falta'} · "
                                   f"GIMP: {'OK' if self.toolchain.gimp_ok else 'falta'}")
        self.refresh_models(async_ok=True)
        self.refresh_files()

    # ------------------------------------------------------------ providers --
    def _paint_provider_buttons(self) -> None:
        for pid, b in self.provider_buttons.items():
            sel = pid == self.provider_var.get()
            if sel:
                b.configure(bg=ACCENT, fg="#ffffff", activebackground=ACCENT_DARK,
                            activeforeground="#ffffff", relief="sunken")
            else:
                b.configure(bg="#ececf1", fg="#1f2937", activebackground="#dcdce4",
                            activeforeground="#111827", relief="raised")

    def _on_provider_change(self) -> None:
        pid = self.provider_var.get()
        self.cfg.provider = pid
        pc = self.cfg.provider_cfg(pid)
        self.base_e.delete(0, "end")
        self.base_e.insert(0, pc.get("base_url", ""))
        self.key_e.delete(0, "end")
        self.key_e.insert(0, pc.get("api_key", ""))
        self.model_cb.set(pc.get("model", ""))
        self._paint_provider_buttons()
        self._log(f"Cambiado a {PROVIDERS[pid].label} · {pc.get('base_url')}")
        prov = PROVIDERS[pid]
        self.conn_lbl.config(text=("local · sin API key" if not prov.needs_key else "requiere API key"),
                             foreground=MUTED)
        self.refresh_models(async_ok=True)

    def _save_form(self) -> None:
        pid = self.provider_var.get()
        self.cfg.provider = pid
        self.cfg.set_provider(pid, base_url=self.base_e.get().strip(),
                              api_key=self.key_e.get().strip(), model=self.model_cb.get().strip())
        self.cfg.temperature = float(self.temp_s.get())
        self.cfg.max_tokens = _int(self._cfg_rows["cfg:max_tokens"][0].get(), self.cfg.max_tokens)
        self.cfg.timeout = _num(self._cfg_rows["cfg:timeout"][0].get(), self.cfg.timeout)
        self.cfg.repair_rounds = _int(self._cfg_rows["cfg:repair"][0].get(), self.cfg.repair_rounds, minimum=0)
        self.cfg.auto_run = bool(self.auto_run_v.get())
        self.cfg.export_preview = bool(self.preview_v.get())
        self.cfg.allow_unsafe = bool(self.allow_unsafe_v.get())
        self.cfg.safe_mode = bool(self.cfg_safe.get())
        self.cfg.binaries = {
            "inkscape": self._cfg_rows["bin:inkscape"][0].get().strip(),
            "gimp": self._cfg_rows["bin:gimp"][0].get().strip(),
            "python": self._cfg_rows["bin:python"][0].get().strip(),
        }
        self.cfg.workspace = self.ws_e.get().strip()
        self.cfg.last_mode = self.mode_cb.get()
        self.cfg.last_apps = self._apps()

    def _apps(self) -> List[str]:
        out = []
        if self.app_ink.get():
            out.append("inkscape")
        if self.app_gimp.get():
            out.append("gimp")
        return out or ["inkscape"]

    def _update_apps_lbl(self) -> None:
        self.conn_lbl.config(text="· destino: " + ", ".join(self._apps()))

    def _sync_safe(self) -> None:
        self.cfg.safe_mode = bool(self.cfg_safe.get())

    # -------------------------------------------------------------- acciones --
    def refresh_models(self, async_ok: bool = False) -> None:
        self._save_form()
        pid = self.provider_var.get()
        self.conn_lbl.config(text="consultando modelos…", foreground=MUTED)
        if not async_ok:
            self._apply_models(*self._fetch_models(pid))
            return
        threading.Thread(target=self._worker_models, args=(pid,), daemon=True).start()

    def _worker_models(self, pid: str) -> None:
        try:
            self.q.put(("models", self._fetch_models(pid)))
        except Exception as exc:  # noqa: BLE001
            self.q.put(("log", f"no se pudieron listar modelos: {exc}"))
            self.q.put(("models", ([], f"Error al listar modelos de {pid}: {exc}")))

    def _fetch_models(self, pid: str):
        prov = self.agent.provider(pid)
        models, note = prov.list_models_or_fallback()
        return models, note

    def _apply_models(self, models: List[Any], note: str) -> None:
        self.models = models or []
        labels = [m.label for m in self.models]
        self.model_cb.config(values=labels)
        cur = self.model_cb.get().strip()
        if cur in [m.id for m in self.models]:
            idx = [m.id for m in self.models].index(cur)
            self.model_cb.set(labels[idx])
        elif not cur and labels:
            self.model_cb.set(labels[0])
        self.conn_lbl.config(text=note[:110], foreground=MUTED)
        self._log(f"Modelos de {self.provider_var.get()}: {len(self.models)} → {', '.join(labels[:6])}")

    def detect_tools(self) -> None:
        """Vuelve a buscar Inkscape/GIMP/Python (por si los acabas de instalar)."""
        self._save_form()
        self.status.config(text="buscando Inkscape / GIMP…")
        self.root.update_idletasks()
        self.toolchain = self.agent.toolchain(refresh=True)
        self._log("◆ Re-detección de herramientas:\n" +
                  "\n".join("    " + l for l in self.toolchain.summary().splitlines()))
        self.tools_lbl.config(text=f"Inkscape: {'OK' if self.toolchain.inkscape_ok else 'falta'} · "
                                   f"GIMP: {'OK' if self.toolchain.gimp_ok else 'falta'}")
        messagebox.showinfo(
            APP_NAME,
            self.toolchain.summary() + "\n\nEspacio de trabajo: " + str(self.cfg.ws()) +
            "\nSi falta algo, escribe la ruta exacta en la pestaña Ajustes.",
        )
        self.refresh_files()

    def test_connection(self) -> None:
        self._save_form()
        pid = self.provider_var.get()
        self.conn_lbl.config(text="probando…", foreground=MUTED)
        self.root.update_idletasks()
        try:
            msg = self.agent.provider(pid).ping()
            self.conn_lbl.config(text="conexión OK", foreground=ACCENT)
            self._log("✓ " + msg)
        except Exception as exc:  # noqa: BLE001
            self.conn_lbl.config(text="error de conexión", foreground="#b3261e")
            self._log(f"✗ {exc}")
            messagebox.showerror("Conexión fallida", str(exc)[:1200])

    def run_agent(self) -> None:
        if self.busy:
            messagebox.showinfo(APP_NAME, "Ya hay una tarea en curso. Pulsa Detener si quieres cortarla.")
            return
        task = self.req.get("1.0", "end").strip()
        if not task:
            messagebox.showwarning(APP_NAME, "Escribe primero qué quieres crear o corregir.")
            return
        self._save_form()
        self._persist()
        apps = self._apps()
        inputs = list(self.inputs) + list(self.images)
        if not self._confirm_execution(apps):
            return
        # TODO lo que necesite el hilo se lee aquí: Tk no permite tocar widgets desde otro hilo
        mode = self.mode_cb.get()
        model = self._model_id()
        pid = self.provider_var.get()
        self._set_busy(True, "generando plan…")
        self.stop_flag.clear()
        self.clear_console()
        self._log(f"\n=== NUEVO PEDIDO ({', '.join(apps)} / {mode}) ===")
        t = threading.Thread(target=self._worker_run,
                             args=(task, mode, apps, inputs, model, pid), daemon=True)
        t.start()

    def _worker_run(self, task: str, mode: str, apps: List[str], inputs: List[str],
                    model: str, pid: str) -> None:
        try:
            run = self.agent.run(task, mode=mode, apps=apps,
                                 inputs=[p for p in inputs if p.lower().endswith(VEC_EXT + (".json", ".txt", ".xmp"))],
                                 images=[p for p in inputs if p.lower().endswith(IMG_EXT)],
                                 model=model, provider=pid,
                                 on_delta=lambda s: self.q.put(("delta", s)),
                                 log=lambda s: self.q.put(("log", s)),
                                 should_stop=self.stop_flag.is_set)
            self.q.put(("done", run))
        except Exception as exc:  # noqa: BLE001
            self.q.put(("fatal", f"{exc}\n{traceback.format_exc()[:1500]}"))

    def _model_id(self) -> str:
        raw = self.model_cb.get().strip()
        for m in self.models:
            if raw in (m.label, m.id):
                return m.id
        return raw

    def _confirm_execution(self, apps: List[str]) -> bool:
        """Aviso de seguridad antes de correr código generado en Inkscape/GIMP."""
        if self.cfg_safe.get():
            self._log("Modo seguro activo: se escribirán archivos, no se ejecutará código.")
            return True
        tc = self.agent.toolchain()
        missing = [a for a in apps if not (tc.inkscape_ok if a == "inkscape" else tc.gimp_ok)]
        if missing:
            messagebox.showwarning(APP_NAME,
                                   "No encuentro: " + ", ".join(missing) +
                                   "\n\nEl plan se generará igualmente, pero los pasos de esas apps no correrán. "
                                   "Configura la ruta en Ajustes.")
        return True

    def _set_busy(self, busy: bool, msg: str = "") -> None:
        self.busy = busy
        try:
            self.run_btn.state(["disabled"] if busy else ["!disabled"])
        except tk.TclError:  # pragma: no cover - themes antiguos
            self.run_btn.configure(state="disabled" if busy else "normal")
        if busy:
            self.pbar.start(12)
        else:
            self.pbar.stop()
        if msg:
            self.status.config(text=msg)

    # ------------------------------------------------------------- resultados --
    def _on_done(self, run: AgentRun) -> None:
        self._set_busy(False, f"terminado en {run.elapsed:.1f}s")
        self.current_run = run
        if run.plan:
            self.json_txt.delete("1.0", "end")
            self.json_txt.insert("1.0", plan_to_json(run.plan))
            self.plan_txt.config(state="normal")
            self.plan_txt.delete("1.0", "end")
            self.plan_txt.insert("1.0", render_plan(run.plan))
            self.plan_txt.config(state="disabled")
            self.cfg.last_task = self.req.get("1.0", "end").strip()
            self.cfg.history.insert(0, {"ts": time.strftime("%Y-%m-%d %H:%M"),
                                        "task": self.cfg.last_task[:400],
                                        "provider": self.provider_var.get(),
                                        "model": self._model_id(),
                                        "summary": run.plan.summary[:400],
                                        "steps": str(len(run.plan.steps)),
                                        "ok": "sí" if run.ok else "no"})
            self.cfg.history = self.cfg.history[:40]
            self._render_history()
            self._persist()
        if run.error:
            self.status.config(text="error")
            messagebox.showerror(APP_NAME, run.error[:1500])
        elif run.plan and not run.results:
            self.nb.select(self.tab_json)
            self.status.config(text="plan listo (sin ejecutar) — edítalo en 'JSON editable'")
        else:
            self.status.config(text=f"{len(run.files())} archivo(s) generados en {self.cfg.ws()}")
        self.refresh_files()
        self.show_preview()

    def apply_json(self) -> None:
        if not self.current_run or not self.current_run.plan:
            return
        try:
            new = edit_steps_from_text(self.current_run.plan, self.json_txt.get("1.0", "end").strip())
        except ValueError as exc:
            messagebox.showerror("JSON inválido", str(exc)[:1200])
            return
        self.current_run.plan = new
        self.plan_txt.config(state="normal")
        self.plan_txt.delete("1.0", "end")
        self.plan_txt.insert("1.0", render_plan(new))
        self.plan_txt.config(state="disabled")
        self._log("✓ JSON aplicado al plan (editable).")
        messagebox.showinfo(APP_NAME, f"Plan actualizado: {len(new.steps)} paso(s).\n"
                                      "Usa 'Ejecutar solo este plan' para correrlo.")

    def format_json(self) -> None:
        try:
            obj = json.loads(self.json_txt.get("1.0", "end"))
            self.json_txt.delete("1.0", "end")
            self.json_txt.insert("1.0", json.dumps(obj, ensure_ascii=False, indent=2))
        except json.JSONDecodeError as exc:
            messagebox.showerror("JSON inválido", str(exc))

    def execute_json(self) -> None:
        if not self.current_run or not self.current_run.plan:
            messagebox.showinfo(APP_NAME, "Primero genera un plan con el agente.")
            return
        self._save_form()
        if not self._confirm_execution(self.current_run.plan.apps or ["inkscape"]):
            return
        self._set_busy(True, "ejecutando plan…")
        threading.Thread(target=self._worker_exec, args=(self.current_run.plan,), daemon=True).start()

    def _worker_exec(self, plan: Any) -> None:
        try:
            run = self.agent.execute(plan, log=lambda s: self.q.put(("log", s)),
                                     should_stop=self.stop_flag.is_set)
            self.q.put(("done", run))
        except Exception as exc:  # noqa: BLE001
            self.q.put(("fatal", f"{exc}\n{traceback.format_exc()[:1200]}"))

    def run_app_steps(self, app: str) -> None:
        if not self.current_run or not self.current_run.plan:
            messagebox.showinfo(APP_NAME, "Primero genera un plan.")
            return
        steps = [s for s in self.current_run.plan.steps if s.app == app]
        if not steps:
            messagebox.showinfo(APP_NAME, f"El plan no tiene pasos para {app}.")
            return
        self._save_form()
        from .core.plan import Plan

        plan = Plan(summary=f"Ejecución manual de pasos de {app}", steps=steps)
        self._set_busy(True, f"ejecutando pasos de {app}…")
        threading.Thread(target=self._worker_exec, args=(plan,), daemon=True).start()

    def repair_with_ai(self) -> None:
        if not self.current_run or not self.current_run.plan:
            messagebox.showinfo(APP_NAME, "Nada que reparar todavía.")
            return
        self._save_form()
        model, pid = self._model_id(), self.provider_var.get()
        self._set_busy(True, "pidiendo corrección al modelo…")
        self.stop_flag.clear()
        threading.Thread(target=self._worker_repair, args=(model, pid), daemon=True).start()

    def _worker_repair(self, model: str, pid: str) -> None:
        run = self.current_run
        assert run and run.plan
        try:
            log = "\n".join(run.log)[-6000:]
            msgs = [
                {"role": "system", "content": prompts.build_system_prompt()},
                {"role": "user", "content":
                    "El plan se ejecutó y FALLÓ. Corrígelo y devuelve el JSON COMPLETO del contrato.\n\n"
                    f"=== PLAN ACTUAL ===\n{plan_to_json(run.plan)}\n\n=== CONSOLA ===\n{log}"},
            ]
            text = self.agent.ask(msgs, model=model, pid=pid,
                                  on_delta=lambda s: self.q.put(("delta", s)))
            new = parse_plan(text)

            run.plan = new
            run.raw_text = text
            self.q.put(("log", f"✓ plan corregido: {new.summary}"))
            self.q.put(("done", run))
        except Exception as exc:  # noqa: BLE001
            self.q.put(("fatal", f"reparación fallida: {exc}"))

    # ------------------------------------------------------------- archivos --
    def attach_files(self) -> None:
        paths = filedialog.askopenfilenames(title="Adjuntar SVG / PNG / JPG",
                                            filetypes=[("Soportado", " ".join("*" + e for e in ALL_EXT)),
                                                       ("Todos", "*.*")])
        for p in paths:
            if p.lower().endswith(IMG_EXT):
                if p not in self.images:
                    self.images.append(p)
            elif p not in self.inputs:
                self.inputs.append(p)
            if p.lower().endswith(VEC_EXT):
                dst = self.cfg.ws() / os.path.basename(p)
                try:
                    if not dst.exists():
                        shutil.copyfile(p, dst)
                except OSError:
                    pass
        self._update_files_lbl()

    def clear_files(self) -> None:
        self.inputs, self.images = [], []
        self._update_files_lbl()

    def _update_files_lbl(self) -> None:
        n = len(self.inputs) + len(self.images)
        names = ", ".join(os.path.basename(p) for p in (self.inputs + self.images)[:6])
        self.inp_lbl.config(text=f"{n} adjunto(s): {names}" if n else "sin archivos adjuntos")

    def refresh_files(self) -> None:
        ws = self.cfg.ws()
        items = []
        if ws.is_dir():
            for p in sorted(ws.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
                if p.is_file() and not p.name.startswith("_ai"):
                    try:
                        sz = f"{p.stat().st_size / 1024:.0f} KB"
                    except OSError:
                        sz = "?"
                    items.append(f"{p.name}   ·   {sz}")
        self.files_list.delete(0, "end")
        for it in items[:200]:
            self.files_list.insert("end", it)

    def _selected_file(self) -> Optional[Path]:
        sel = self.files_list.curselection()
        if not sel:
            return None
        name = self.files_list.get(sel[0]).split("   ·   ")[0]
        return self.cfg.ws() / name

    def open_selected(self, app: Optional[str] = None) -> None:
        f = self._selected_file()
        if not f:
            return self.open_path(self.cfg.ws())
        if app:
            return self._launch(app, f)
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(f))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":  # pragma: no cover
                subprocess.Popen(["open", str(f)])
            else:
                subprocess.Popen(["xdg-open", str(f)])
        except (OSError, tk.TclError) as exc:
            messagebox.showerror(APP_NAME, f"No se pudo abrir {f.name}: {exc}")

    def open_in(self, app: str) -> None:
        f = self._selected_file() or self._latest(app)
        if not f:
            messagebox.showinfo(APP_NAME, "No hay archivos que abrir todavía.")
            return
        self._launch(app, f)

    def _latest(self, app: str) -> Optional[Path]:
        ws = self.cfg.ws()
        exts = VEC_EXT if app == "inkscape" else IMG_EXT
        cand = [p for p in sorted(ws.glob("*"), key=lambda x: x.stat().st_mtime, reverse=True)
                if p.is_file() and p.suffix.lower() in exts]
        return cand[0] if cand else None

    def _launch(self, app: str, f: Path) -> None:
        tc = self.agent.toolchain()
        cmd = (tc.inkscape if app == "inkscape" else tc.gimp)
        if not cmd:
            messagebox.showerror(APP_NAME, f"{app} no está disponible; configura la ruta en Ajustes.")
            return
        try:
            subprocess.Popen([*cmd, str(f)], cwd=str(ws_dir(f)))
            self._log(f"Abriendo {f.name} en {app}…")
        except OSError as exc:
            messagebox.showerror(APP_NAME, str(exc))

    def export_png(self) -> None:
        f = self._selected_file()
        if not f or f.suffix.lower() not in VEC_EXT:
            messagebox.showinfo(APP_NAME, "Selecciona un .svg en la lista.")
            return
        self._set_busy(True, "exportando PNG…")
        threading.Thread(target=self._worker_export, args=(f,), daemon=True).start()

    def _worker_export(self, f: Path) -> None:
        from .core.runner import _export_preview

        tc = self.agent.toolchain()
        png = _export_preview(f.parent, f.name, tc, timeout=90) if tc.inkscape_ok else None
        self.q.put(("log", f"✓ exportado: {png}" if png else "✗ fallo la exportación (¿Inkscape disponible?)"))
        self.q.put(("exported", png))

    def open_path(self, p: Path) -> None:
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(p))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":  # pragma: no cover
                subprocess.Popen(["open", str(p)])
            else:
                subprocess.Popen(["xdg-open", str(p)])
        except (OSError, tk.TclError) as exc:
            messagebox.showerror(APP_NAME, str(exc))

    def browse_bin(self, key: str) -> None:
        p = filedialog.askopenfilename(title=f"Ruta del ejecutable de {key}",
                                       filetypes=[("Ejecutables", "*.exe *.bat *.cmd *"), ("Todos", "*.*")])
        if p:
            self._cfg_rows[f"bin:{key}"][0].delete(0, "end")
            self._cfg_rows[f"bin:{key}"][0].insert(0, p)
            self.save_settings(quiet=True)

    def browse_ws(self) -> None:
        p = filedialog.askdirectory(title="Espacio de trabajo")
        if p:
            self.ws_e.delete(0, "end")
            self.ws_e.insert(0, p)

    def save_settings(self, quiet: bool = False) -> None:
        pid = self.provider_var.get()
        self._save_form()
        for pid in PROVIDERS:
            row = self._cfg_rows.get(pid)
            if row and len(row) == 2:
                base, key = row
                self.cfg.set_provider(pid, base_url=base.get().strip(), api_key=key.get().strip())
        self._persist()
        self.toolchain = self.agent.toolchain(refresh=True)
        self.tools_lbl.config(text=f"Inkscape: {'OK' if self.toolchain.inkscape_ok else 'falta'} · "
                                   f"GIMP: {'OK' if self.toolchain.gimp_ok else 'falta'}")
        self._log("Ajustes guardados en " + str(self.cfg.path()))
        if not quiet:
            messagebox.showinfo(APP_NAME, "Ajustes guardados.")

    def _persist(self) -> None:
        try:
            self.cfg.window_geometry = self.root.geometry()
            self.cfg.save()
        except OSError as exc:
            self._log(f"! no se pudo guardar la config: {exc}")

    # ----------------------------------------------------------- consola/UI --
    def _log(self, msg: str) -> None:
        self.console.config(state="normal")
        self.console.insert("end", msg.rstrip("\n") + "\n")
        self.console.see("end")
        self.console.config(state="disabled")

    def clear_console(self) -> None:
        self.console.config(state="normal")
        self.console.delete("1.0", "end")
        self.console.config(state="disabled")

    def clear_all(self) -> None:
        self.req.delete("1.0", "end")
        self.json_txt.delete("1.0", "end")
        self.plan_txt.config(state="normal")
        self.plan_txt.delete("1.0", "end")
        self.plan_txt.config(state="disabled")
        self.clear_files()
        self.current_run = None
        self.status.config(text="listo")

    def _count_chars(self) -> None:
        try:
            n = len(self.req.get("1.0", "end-1c"))
            self.chars_lbl.config(text=f"{n} caracteres")
            self.req.edit_modified(False)
        except tk.TclError:
            pass

    def show_preview(self, path: Optional[Path] = None) -> None:
        c = self.canvas
        c.delete("all")
        f = path or self._selected_file() or self._latest_preview()
        if not f or not Path(f).is_file():
            c.create_text(12, 12, anchor="nw", fill=MUTED,
                          text="sin previsualización aún — genera un plan y ejecútalo")
            return
        f = Path(f)
        try:
            if f.suffix.lower() in VEC_EXT:
                cand = f.parent / (f.stem + ".preview.png")
                if cand.is_file():
                    self._show_image(cand, f)
                else:
                    self._show_svg_text(f)
                return
            self._show_image(f, f)
        except Exception as exc:  # noqa: BLE001
            c.create_text(12, 12, anchor="nw", fill="#b3261e", text=f"no se pudo previsualizar: {exc}")

    def _latest_preview(self) -> Optional[Path]:
        ws = self.cfg.ws()
        imgs = [p for p in sorted(ws.glob("*"), key=lambda x: x.stat().st_mtime, reverse=True)
                if p.suffix.lower() in (".png", ".gif") and not p.name.startswith("_ai")]
        return imgs[0] if imgs else None

    def _show_image(self, png: Path, orig: Path) -> None:
        """Muestra `png` encajado en el lienzo. Usa Pillow si existe; si no, PhotoImage de Tk."""
        from .core.images import image_size

        dims = image_size(orig)
        label = orig.name + (f"  ·  {dims[0]}×{dims[1]} px" if dims else "")
        cw = max(self.canvas.winfo_width(), 220)
        ch = max(self.canvas.winfo_height(), 150)
        img, note = None, ""
        try:
            from PIL import Image, ImageTk

            with Image.open(str(png)) as raw:
                im = raw.convert("RGBA") if raw.mode not in ("RGB", "RGBA", "P") else raw
                resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS", 1)
                im.thumbnail((cw, ch), resample)
                img = ImageTk.PhotoImage(im)
                note = f"encajado a {im.width}×{im.height} px"
        except Exception:  # noqa: BLE001 - sin Pillow: PhotoImage nativo de Tk (PNG/GIF)
            try:
                base = tk.PhotoImage(file=str(png))
                step = max(1, -(-max(base.width(), base.height()) // max(min(cw, ch), 120)))
                img = base.subsample(step, step) if step > 1 else base
                note = f"escala 1/{step}" if step > 1 else "tamaño real"
            except tk.TclError as exc:
                self.canvas.create_text(10, 10, anchor="nw", fill="#b3261e", justify="left",
                                        width=max(cw - 20, 200),
                                        text=f"{label}\nno se pudo previsualizar: "
                                             f"{exc or 'PNG no soportado por esta build de Tk'}.\n"
                                             "Abre el archivo con GIMP/Inkscape para revisarlo.")
                return
        if img is None:  # pragma: no cover
            return
        self.preview_photo = img
        self.canvas.create_image(self.canvas.winfo_width() // 2, self.canvas.winfo_height() // 2, image=img)
        self.canvas.create_rectangle(4, 4, 12 + 8 * len(f"{label}   ({note})"), 26,
                                     fill="#f2f2f5", outline="", state="hidden")
        self.canvas.create_text(8, 8, anchor="nw", fill="#374151", text=f"{label}   ({note})")

    def _show_svg_text(self, svg: Path, extra: str = "") -> None:
        try:
            txt = svg.read_text(encoding="utf-8", errors="replace")[:900]
        except OSError as exc:
            txt = str(exc)
        self.canvas.create_text(10, 10, anchor="nw", width=max(self.canvas.winfo_width() - 20, 200),
                                fill="#111827", justify="left",
                                text=f"{svg.name}{extra}\n\n{txt}")

    def _render_history(self) -> None:
        self.hist_txt.config(state="normal")
        self.hist_txt.delete("1.0", "end")
        if not self.cfg.history:
            self.hist_txt.insert("end", "(aún no hay pedidos registrados)\n")
        for h in self.cfg.history:
            self.hist_txt.insert("end", f"• {h.get('ts')}  [{h.get('provider')}/{h.get('model')}]\n"
                                        f"  pedido: {h.get('task')}\n"
                                        f"  resultado ({h.get('steps')} pasos, ok={h.get('ok')}): {h.get('summary')}\n\n")
        self.hist_txt.config(state="disabled")

    def replay_history(self) -> None:
        if not self.cfg.history:
            return
        self.req.delete("1.0", "end")
        self.req.insert("1.0", self.cfg.history[0].get("task", ""))
        self._log("pedido anterior recuperado en el área de texto")

    def open_project(self) -> None:
        p = filedialog.askdirectory(title="Elige la carpeta del proyecto")
        if p:
            self.ws_e.delete(0, "end")
            self.ws_e.insert(0, p)
            self.save_settings(quiet=True)
            self.refresh_files()

    def save_plan(self) -> None:
        txt = self.json_txt.get("1.0", "end").strip()
        if not txt:
            messagebox.showinfo(APP_NAME, "El JSON está vacío.")
            return
        p = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")],
                                         initialfile="plan.json")
        if p:
            Path(p).write_text(txt, encoding="utf-8")
            self._log(f"plan guardado en {p}")

    def save_script(self) -> None:
        if not self.current_run or not self.current_run.plan:
            return
        ext = {"script-fu": ".scm", "python-fu": ".py", "python-svg": ".py", "inkex-python": ".py",
               "svg": ".svg", "inkscape-actions": ".txt", "shell-export": ".sh", "file": ".txt"}
        step = self.current_run.plan.steps[0]
        p = filedialog.asksaveasfilename(defaultextension=ext.get(step.kind, ".txt"),
                                         initialfile=f"ai_step{ext.get(step.kind, '.txt')}")
        if p:
            Path(p).write_text(step.code, encoding="utf-8")
            self._log(f"script guardado en {p}")

    def show_help(self) -> None:
        tips = (
            "CÓMO SE USA\n\n"
            "1. Elige PROVEEDOR con los botones de arriba (Ollama / LM Studio / OmniRoute = locales, sin API key).\n"
            "2. Pulsa 'Refrescar modelos' (F5) y escoge uno. Con modelos locales pequeños, usa 'svg' o 'inkscape-actions'.\n"
            "3. Escribe el pedido en la ventana grande. Sé específico: tamaño, colores, formato, archivo destino.\n"
            "4. Marca la app destino (Inkscape/GIMP), y si quieres corregir un archivo, adjúntalo con 'Añadir SVG/PNG…'.\n"
            "5. Ejecuta (Ctrl+Enter). El agente pide al modelo un PLAN en JSON, lo escribe en la pestaña 'Plan / pasos'\n"
            "   y ejecuta los pasos. Puedes editar el JSON y pulsar 'Ejecutar solo este plan'.\n"
            "6. Si un paso falla, usa 'Reparar con IA': la consola de errores se le pasa al modelo para que corrija.\n\n"
            "KINDS DE PASO\n"
            "  svg              → el agente escribe el SVG que devolvió el modelo (lo más fiable para crear).\n"
            "  inkscape-actions → acciones CLI de Inkscape 1.x (align, distribute, export, simplify…).\n"
            "  python-svg       → Python con solo librería estándar que edita el SVG (ElementTree).\n"
            "  inkex-python     → código de extensión Inkscape (necesita un Python con 'inkex').\n"
            "  script-fu        → TinyScheme para GIMP (el método más robusto en GIMP 2.10 y 3).\n"
            "  python-fu        → Python-Fu de GIMP 3.\n"
            "  shell-export     → líneas 'inkscape …' / 'gimp …' reescritas con la ruta detectada.\n\n"
            "SEGURIDAD: el código generado se ejecuta en tu máquina. Por eso hay 'Modo seguro', escaneo de tokens\n"
            "peligrosos y ninguna forma de acceso a red desde los pasos. Desactiva el modo seguro solo con planes que hayas leído."
        )
        messagebox.showinfo("Cómo se usa", tips)

    def show_about(self) -> None:
        messagebox.showinfo(
            "Acerca de",
            f"{APP_NAME} v{__version__}\n\nAgente de IA para crear y corregir imágenes vectoriales (Inkscape) "
            "y mapas de bits (GIMP).\nSoporta OpenAI, Anthropic, Google Gemini, Ollama, LM Studio, OpenRouter y OmniRoute.\n\n"
            "Solo librería estándar de Python 3.9+. Config: " + str(self.cfg.path()) + "\nEspacio de trabajo: " + str(self.cfg.ws()),
        )

    def show_diag(self) -> None:
        lines = [f"{APP_NAME} v{__version__}", f"Python {sys.version.split()[0]} · {sys.platform} · frozen={getattr(sys, 'frozen', False)}",
                 f"Tk {self.root.tk.call('info', 'patchlevel')}", "", self.toolchain.summary(), "",
                 f"Config: {self.cfg.path()} ({'existe' if self.cfg.path().exists() else 'se creará al guardar'})",
                 f"Workspace: {self.cfg.ws()}", ""]
        for pid in PROVIDER_ORDER:
            pc = self.cfg.provider_cfg(pid)
            lines.append(f"{PROVIDERS[pid].label:<10} base={pc.get('base_url')} key={'sí' if pc.get('api_key') else 'no'} model={pc.get('model')}")
        win = tk.Toplevel(self.root)
        win.title("Diagnóstico")
        win.geometry("760x520")
        t = tk.Text(win, font=("Consolas", 10) if sys.platform.startswith("win") else ("Monospace", 10), padx=10, pady=10)
        t.insert("1.0", "\n".join(lines))
        tests = tk.Frame(win)
        tests.pack(fill="x", padx=10)
        for pid in ("ollama", "lmstudio", "omniroute"):
            ttk.Button(tests, text=f"probar {pid}", command=lambda p=pid: self._diag_probe(p, t)).pack(side="left", padx=3)
        t.config(state="normal")

    def _diag_probe(self, pid: str, t: tk.Text) -> None:
        def go() -> None:
            try:
                msg = self.agent.provider(pid).ping()
                t.insert("end", f"\n✓ {msg}")
            except Exception as exc:  # noqa: BLE001
                t.insert("end", f"\n✗ {pid}: {exc}")

        t.insert("end", f"\nprobando {pid}…")
        threading.Thread(target=go, daemon=True).start()

    def stop(self) -> None:
        if self.busy:
            self.stop_flag.set()
            self._log("◇ cancelación pedida: se detendrá tras el paso actual…")

    # --------------------------------------------------------------- poller --
    def _poll(self) -> None:
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self._log(payload)
                elif kind == "delta":
                    self.status.config(text="recibiendo tokens…")
                elif kind == "models":
                    models, note = payload
                    self._apply_models(models, note)
                elif kind == "exported":
                    self._set_busy(False, "exportado")
                    if payload:
                        self.show_preview(Path(payload))
                    self.refresh_files()
                elif kind == "done":
                    self._on_done(payload)
                elif kind == "fatal":
                    self._log("✗ " + payload)
                    self._set_busy(False, "error")
                    messagebox.showerror(APP_NAME, str(payload)[:1200])
        except queue.Empty:
            pass
        self.root.after(70, self._poll)

    def on_close(self) -> None:
        try:
            self.stop_flag.set()
            self._persist()
        finally:
            self.root.destroy()


def ws_dir(f: Path) -> Path:
    return f.parent if f.parent.exists() else Path(".")


def main() -> None:
    root = tk.Tk()
    AgentGUI(root)
    root.mainloop()


if __name__ == "__main__":  # pragma: no cover
    main()
