# -*- coding: utf-8 -*-
"""
Agente de IA para Inkscape y GIMP - Interfaz grafica (Tkinter).

Muestra:
  - Selector de PROVEEDOR (OpenAI, Anthropic, Gemini, OpenRouter, OmniRoute,
    Ollama, LM Studio, Personalizado)
  - Selector de MODELO (se puede cargar dinamicamente desde el proveedor)
  - Area amplia de texto para escribir el pedido
  - Ventana grande de resultados con vista previa
  - Botones: Generar, Corregir, Cargar imagen, Guardar, Enviar a Inkscape/GIMP

Se ejecuta con:  python -m ui.app   o   python agent.py
"""

from __future__ import annotations

import os
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core import bitmap_tools as bt                      # noqa: E402
from core import providers as P                          # noqa: E402
from core import svg_tools as st                         # noqa: E402
from core.config import (default_output_dir, load_config, save_config,  # noqa: E402
                         unique_path)

APP_TITLE = "Agente IA para Inkscape y GIMP"
BG = "#1e1f26"
FG = "#e8eaf0"
ACCENT = "#4f8cff"
PANEL = "#2a2c36"

MODES = [
    ("vector", "Vectorial (SVG / Inkscape)"),
    ("bitmap", "Bitmap (imagen PNG / GIMP)"),
    ("corregir_svg", "Corregir vectorial existente"),
    ("corregir_bitmap", "Corregir bitmap existente"),
    ("script", "Generar script GIMP / Python"),
    ("chat", "Consulta libre (solo texto)"),
]


class AgentApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.cfg = load_config()
        self.title(APP_TITLE)
        self.geometry("1180x820")
        self.minsize(980, 680)
        self.configure(bg=BG)

        self.current_svg = ""
        self.current_image_path = ""
        self.last_result_path = ""
        self._busy = False

        self._setup_style()
        self._build_layout()
        self.refresh_providers()
        self.refresh_models()

    # ------------------------------------------------------------------ estilo
    def _setup_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", background=BG, foreground=FG, fieldbackground=PANEL,
                        bordercolor="#3a3d49")
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=FG, font=("Segoe UI", 10))
        style.configure("Header.TLabel", font=("Segoe UI", 15, "bold"), foreground="#fff")
        style.configure("Hint.TLabel", foreground="#9aa0b4", font=("Segoe UI", 9))
        style.configure("TButton", padding=6, font=("Segoe UI", 10))
        style.configure("Accent.TButton", padding=8, font=("Segoe UI", 10, "bold"))
        style.map("Accent.TButton", background=[("active", ACCENT)])
        style.configure("TCombobox", padding=4)
        style.configure("TLabelframe", background=BG, foreground=FG)
        style.configure("TLabelframe.Label", background=BG, foreground=FG,
                        font=("Segoe UI", 10, "bold"))

    # --------------------------------------------------------------- estructura
    def _build_layout(self):
        top = ttk.Frame(self, padding=(14, 12, 14, 6))
        top.pack(fill="x")
        ttk.Label(top, text=APP_TITLE, style="Header.TLabel").pack(side="left")
        ttk.Label(top, text="  modelos locales y en la nube - vectorial y bitmap",
                  style="Hint.TLabel").pack(side="left")
        ttk.Button(top, text="Ajustes / Claves", command=self.open_settings)\
            .pack(side="right")

        # ---- barra de proveedor / modelo ----------------------------------
        sel = ttk.LabelFrame(self, text="Proveedor y modelo", padding=10)
        sel.pack(fill="x", padx=14, pady=6)

        ttk.Label(sel, text="Proveedor:").grid(row=0, column=0, sticky="w")
        self.provider_var = tk.StringVar()
        self.provider_box = ttk.Combobox(sel, textvariable=self.provider_var,
                                         state="readonly", width=34)
        self.provider_box.grid(row=1, column=0, padx=(0, 10), sticky="we")
        self.provider_box.bind("<<ComboboxSelected>>", self.on_provider_change)

        ttk.Label(sel, text="Modelo:").grid(row=0, column=1, sticky="w")
        self.model_var = tk.StringVar()
        self.model_box = ttk.Combobox(sel, textvariable=self.model_var, width=42)
        self.model_box.grid(row=1, column=1, padx=(0, 10), sticky="we")

        ttk.Button(sel, text="Cargar modelos", command=self.reload_models)\
            .grid(row=1, column=2, padx=(0, 10))
        ttk.Label(sel, text="Tarea:").grid(row=0, column=3, sticky="w")
        self.mode_var = tk.StringVar(value=MODES[0][1])
        mode_box = ttk.Combobox(sel, textvariable=self.mode_var, state="readonly",
                                width=30, values=[m[1] for m in MODES])
        mode_box.grid(row=1, column=3, sticky="we")

        sel.columnconfigure(0, weight=1)
        sel.columnconfigure(1, weight=2)
        self.status_var = tk.StringVar(value="Listo.")
        ttk.Label(self, textvariable=self.status_var, style="Hint.TLabel")\
            .pack(anchor="w", padx=16)

        # ---- panel central: pedido + resultado -----------------------------
        mid = ttk.Frame(self, padding=(14, 4))
        mid.pack(fill="both", expand=True)
        mid.columnconfigure(0, weight=1, uniform="c")
        mid.columnconfigure(1, weight=1, uniform="c")
        mid.rowconfigure(1, weight=1)

        ttk.Label(mid, text="Escribe tu pedido (en lenguaje natural)").grid(
            row=0, column=0, sticky="w")
        self.prompt_text = tk.Text(mid, height=10, wrap="word", bg=PANEL, fg=FG,
                                   insertbackground=FG, relief="flat",
                                   font=("Consolas", 11), padx=8, pady=8)
        self.prompt_text.grid(row=1, column=0, sticky="nsew", padx=(0, 8))
        if self.cfg.get("last_prompt"):
            self.prompt_text.insert("1.0", self.cfg["last_prompt"])

        ttk.Label(mid, text="Resultado / vista previa").grid(
            row=0, column=1, sticky="w")
        self.result_text = tk.Text(mid, height=10, wrap="word", bg=PANEL, fg=FG,
                                   insertbackground=FG, relief="flat",
                                   font=("Consolas", 10), padx=8, pady=8)
        self.result_text.grid(row=1, column=1, sticky="nsew")
        self.result_text.configure(state="disabled")

        # ---- botones -------------------------------------------------------
        bar = ttk.Frame(self, padding=(14, 6))
        bar.pack(fill="x")
        self.run_btn = ttk.Button(bar, text="Generar / Ejecutar",
                                  style="Accent.TButton", command=self.run_task)
        self.run_btn.pack(side="left")
        ttk.Button(bar, text="Cargar archivo (SVG/PNG)",
                   command=self.load_input).pack(side="left", padx=6)
        ttk.Button(bar, text="Guardar resultado",
                   command=self.save_result).pack(side="left", padx=6)
        ttk.Button(bar, text="Enviar a Inkscape",
                   command=self.send_to_inkscape).pack(side="left", padx=6)
        ttk.Button(bar, text="Enviar a GIMP",
                   command=self.send_to_gimp).pack(side="left", padx=6)
        ttk.Button(bar, text="Abrir carpeta de salida",
                   command=self.open_output).pack(side="left", padx=6)
        ttk.Button(bar, text="Limpiar", command=self.clear_all).pack(side="right")

        # ---- barra de estado inferior -------------------------------------
        bottom = ttk.Frame(self, padding=(14, 0, 14, 10))
        bottom.pack(fill="x")
        self.info_var = tk.StringVar(
            value="Proveedor: %s | Modelo: %s" % (self.cfg.get("provider"),
                                                  self.cfg.get("model") or "-"))
        ttk.Label(bottom, textvariable=self.info_var, style="Hint.TLabel").pack(
            side="left")

    # ------------------------------------------------------------- utilidades
    def set_status(self, text):
        self.status_var.set(text)
        self.update_idletasks()

    def _write_result(self, text):
        self.result_text.configure(state="normal")
        self.result_text.delete("1.0", "end")
        self.result_text.insert("1.0", text)
        self.result_text.configure(state="disabled")

    def _mode_key(self):
        label = self.mode_var.get()
        for key, text in MODES:
            if text == label:
                return key
        return "vector"

    def _provider_id(self):
        label = self.provider_var.get()
        for pid, conf in P.PROVIDERS.items():
            if conf["label"] == label:
                return pid
        return self.cfg.get("provider", "ollama")

    # ------------------------------------------------------------ proveedores
    def refresh_providers(self):
        labels = [conf["label"] for conf in P.PROVIDERS.values()]
        self.provider_box["values"] = labels
        pid = self.cfg.get("provider", "ollama")
        self.provider_var.set(P.PROVIDERS.get(pid, P.PROVIDERS["ollama"])["label"])

    def on_provider_change(self, _event=None):
        pid = self._provider_id()
        self.cfg["provider"] = pid
        self.cfg["model"] = ""
        save_config(self.cfg)
        self.refresh_models()
        conf = P.provider_conf(self.cfg, pid)
        self.set_status("Proveedor %s - %s" % (conf["label"], conf["notes"]))

    def refresh_models(self):
        pid = self._provider_id()
        conf = P.provider_conf(self.cfg, pid)
        models = list(conf.get("models") or [])
        saved = self.cfg.get("model")
        if saved and saved not in models:
            models.insert(0, saved)
        self.model_box["values"] = models
        if saved:
            self.model_var.set(saved)
        elif models:
            self.model_var.set(models[0])
        else:
            self.model_var.set("")
        self.info_var.set("Proveedor: %s | Modelo: %s" % (pid, self.model_var.get() or "-"))

    def reload_models(self):
        pid = self._provider_id()

        def worker():
            try:
                models = P.list_models(self.cfg, pid)
                self.after(0, lambda: self._apply_models(models))
            except Exception as exc:  # noqa: BLE001
                self.after(0, lambda: messagebox.showerror("Modelos", str(exc)))

        self.set_status("Consultando modelos de %s..." % pid)
        threading.Thread(target=worker, daemon=True).start()

    def _apply_models(self, models):
        self.model_box["values"] = models
        if models:
            self.model_var.set(models[0])
        self.set_status("Se cargaron %d modelos." % len(models))

    # -------------------------------------------------------------- ajustes
    def open_settings(self):
        win = tk.Toplevel(self)
        win.title("Ajustes de proveedores y claves")
        win.geometry("760x560")
        win.configure(bg=BG)

        ttk.Label(win, text="Claves de API y URLs base", style="Header.TLabel")\
            .pack(anchor="w", padx=14, pady=(12, 2))
        ttk.Label(win, text="Deja la clave vacia para usar variables de entorno "
                            "(OPENAI_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY...).",
                  style="Hint.TLabel").pack(anchor="w", padx=14)

        body = ttk.Frame(win, padding=14)
        body.pack(fill="both", expand=True)

        keys_entries = {}
        urls_entries = {}
        ttk.Label(body, text="Proveedor").grid(row=0, column=0, sticky="w")
        ttk.Label(body, text="URL base").grid(row=0, column=1, sticky="w")
        ttk.Label(body, text="Clave de API").grid(row=0, column=2, sticky="w")
        for row, (pid, conf) in enumerate(P.PROVIDERS.items(), start=1):
            ttk.Label(body, text=conf["label"]).grid(row=row, column=0, sticky="w",
                                                     pady=3, padx=(0, 10))
            url_var = tk.StringVar(
                value=(self.cfg.get("base_url_override", {}) or {}).get(pid, ""))
            ttk.Entry(body, textvariable=url_var, width=38).grid(
                row=row, column=1, sticky="we", padx=(0, 10))
            key_var = tk.StringVar(
                value=(self.cfg.get("api_keys", {}) or {}).get(pid, ""))
            ttk.Entry(body, textvariable=key_var, width=30, show="*").grid(
                row=row, column=2, sticky="we")
            keys_entries[pid] = key_var
            urls_entries[pid] = url_var
        body.columnconfigure(1, weight=1)

        adv = ttk.LabelFrame(win, text="Avanzado", padding=10)
        adv.pack(fill="x", padx=14, pady=6)
        ttk.Label(adv, text="Temperatura:").grid(row=0, column=0, sticky="w")
        temp_var = tk.StringVar(value=str(self.cfg.get("temperature", 0.2)))
        ttk.Entry(adv, textvariable=temp_var, width=8).grid(row=0, column=1, padx=6)
        ttk.Label(adv, text="Max tokens:").grid(row=0, column=2, sticky="w")
        tokens_var = tk.StringVar(value=str(self.cfg.get("max_tokens", 8192)))
        ttk.Entry(adv, textvariable=tokens_var, width=10).grid(row=0, column=3, padx=6)
        ttk.Label(adv, text="Tamano de imagen:").grid(row=0, column=4, sticky="w")
        size_var = tk.StringVar(value=self.cfg.get("image_size", "1024x1024"))
        ttk.Combobox(adv, textvariable=size_var, width=12,
                     values=["512x512", "1024x1024", "1024x1536", "1536x1024"])\
            .grid(row=0, column=5, padx=6)

        def persist():
            try:
                self.cfg["temperature"] = float(temp_var.get())
                self.cfg["max_tokens"] = int(tokens_var.get())
            except ValueError:
                messagebox.showerror("Ajustes", "Temperatura y tokens deben ser numeros.")
                return
            self.cfg["image_size"] = size_var.get()
            self.cfg["api_keys"] = {pid: var.get().strip()
                                    for pid, var in keys_entries.items()
                                    if var.get().strip()}
            self.cfg["base_url_override"] = {pid: var.get().strip()
                                             for pid, var in urls_entries.items()
                                             if var.get().strip()}
            path = save_config(self.cfg)
            self.set_status("Ajustes guardados en %s" % path)
            win.destroy()

        ttk.Button(win, text="Guardar ajustes", style="Accent.TButton",
                   command=persist).pack(pady=10)

    # ----------------------------------------------------------- entrada/salida
    def load_input(self):
        path = filedialog.askopenfilename(
            title="Elegir SVG o imagen",
            filetypes=[("SVG", "*.svg"), ("Imagenes", "*.png *.jpg *.jpeg *.webp"),
                       ("Todos", "*.*")])
        if not path:
            return
        if path.lower().endswith(".svg"):
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                self.current_svg = fh.read()
            self.set_status("SVG cargado: %s (%d caracteres)"
                            % (os.path.basename(path), len(self.current_svg)))
        else:
            self.current_image_path = path
            size = bt.image_size(path)
            self.set_status("Imagen cargada: %s %s" % (
                os.path.basename(path),
                ("%dx%d" % size) if size else ""))
        self._write_result("Entrada lista:\n%s" % path)

    def save_result(self):
        if not self.last_result_path or not os.path.exists(self.last_result_path):
            messagebox.showinfo("Guardar", "Todavia no hay un resultado que guardar.")
            return
        ext = os.path.splitext(self.last_result_path)[1]
        target = filedialog.asksaveasfilename(defaultextension=ext,
                                              initialfile=os.path.basename(
                                                  self.last_result_path))
        if not target:
            return
        with open(self.last_result_path, "rb") as src, open(target, "wb") as dst:
            dst.write(src.read())
        self.set_status("Guardado en %s" % target)

    def open_output(self):
        folder = default_output_dir(self.cfg)
        bt.open_in_default_app(folder)

    def clear_all(self):
        self.prompt_text.delete("1.0", "end")
        self._write_result("")
        self.current_svg = ""
        self.current_image_path = ""
        self.last_result_path = ""
        self.set_status("Limpio.")

    def send_to_inkscape(self):
        if not self.last_result_path or not self.last_result_path.endswith(".svg"):
            messagebox.showinfo("Inkscape",
                                "No hay un SVG generado. Ejecuta una tarea "
                                "vectorial primero.")
            return
        ok = bt.open_in_default_app(self.last_result_path)
        self.set_status("Enviado a Inkscape: %s" % self.last_result_path
                        if ok else "Abre manualmente: %s" % self.last_result_path)

    def send_to_gimp(self):
        if not self.last_result_path or not os.path.exists(self.last_result_path):
            messagebox.showinfo("GIMP", "No hay imagen generada para abrir.")
            return
        ok = bt.open_in_default_app(self.last_result_path)
        self.set_status("Abierto para GIMP: %s" % self.last_result_path
                        if ok else "Abre manualmente: %s" % self.last_result_path)

    # -------------------------------------------------------------- ejecucion
    def run_task(self):
        if self._busy:
            return
        prompt = self.prompt_text.get("1.0", "end").strip()
        if not prompt:
            messagebox.showinfo("Pedido", "Escribe primero que quieres crear o corregir.")
            return
        pid = self._provider_id()
        model = self.model_var.get().strip() or P.provider_conf(self.cfg, pid) \
            .get("image_model", "")
        mode = self._mode_key()
        self.cfg["model"] = self.model_var.get().strip()
        self.cfg["last_prompt"] = prompt
        save_config(self.cfg)

        self._busy = True
        self.run_btn.configure(state="disabled")
        self.set_status("Consultando a %s (%s)..." % (pid, model or "sin modelo"))
        threading.Thread(target=self._worker,
                         args=(pid, model, mode, prompt), daemon=True).start()

    def _worker(self, pid, model, mode, prompt):
        try:
            text, path = self._dispatch(pid, model, mode, prompt)
            self.after(0, lambda: self._finish(text, path, None))
        except Exception as exc:  # noqa: BLE001
            self.after(0, lambda: self._finish("", "", exc))

    def _finish(self, text, path, error):
        self._busy = False
        self.run_btn.configure(state="normal")
        if error is not None:
            self.set_status("Error: %s" % error)
            self._write_result("ERROR\n\n%s" % error)
            return
        self.last_result_path = path or ""
        self._write_result(text)
        self.set_status("Listo. %s" % (path or ""))

    def _dispatch(self, pid, model, mode, prompt):
        cfg = self.cfg
        out_dir = default_output_dir(cfg)
        temperature = cfg.get("temperature", 0.2)
        max_tokens = cfg.get("max_tokens", 8192)
        timeout = cfg.get("timeout", 600)

        # ---------------- vectorial: crear SVG -------------------------------
        if mode in ("vector", "corregir_svg"):
            context = ""
            if mode == "corregir_svg":
                source = self.current_svg
                if not source and self.last_result_path \
                        and self.last_result_path.endswith(".svg"):
                    with open(self.last_result_path, "r", encoding="utf-8",
                              errors="replace") as fh:
                        source = fh.read()
                if not source:
                    raise P.ProviderError(
                        "Para corregir un SVG, carga un archivo SVG con el boton "
                        "'Cargar archivo (SVG/PNG)'.")
                context = st.describe_svg(source)
            user = prompt if not context else (
                "%s\n\nDocumento SVG actual que debes corregir y devolver completo:\n%s"
                % (prompt, context))
            messages = [
                {"role": "system", "content": st.SVG_SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ]
            answer = P.chat(cfg, pid, model, messages, temperature=temperature,
                            max_tokens=max_tokens, timeout=timeout)
            svg = st.clean_svg(st.extract_svg(answer))
            if not svg:
                raise P.ProviderError(
                    "El modelo no devolvio un SVG valido. Respuesta recibida:\n\n%s"
                    % answer[:1500])
            if not st.is_valid_svg(svg):
                raise P.ProviderError(
                    "El SVG devuelto no se pudo parsear. Se guarda igualmente para "
                    "revision.\n\n%s" % svg[:600])
            self.current_svg = svg
            path = unique_path(out_dir, "vector", "svg")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(svg)
            preview = svg[:2500]
            return "SVG generado y validado correctamente.\n\nGuardado en:\n%s\n\n%s" \
                % (path, preview), path

        # ---------------- bitmap: generar imagen -----------------------------
        if mode == "bitmap":
            conf = P.provider_conf(cfg, pid)
            if not conf.get("supports_image"):
                # El proveedor no genera bitmaps: pedimos un script de GIMP.
                return self._script_mode(pid, model, prompt,
                                         "El proveedor no genera imagenes bitmap; "
                                         "se genero un script de GIMP equivalente.")
            art = P.chat(cfg, pid, model,
                         [{"role": "system", "content": st.BITMAP_PROMPT_SYSTEM},
                          {"role": "user", "content": prompt}],
                         temperature=0.4, max_tokens=1200, timeout=timeout)
            blob = P.generate_image(cfg, pid, model, art or prompt,
                                    size=cfg.get("image_size", "1024x1024"),
                                    timeout=timeout)
            ext = bt.guess_extension(blob)
            path = unique_path(out_dir, "bitmap", ext)
            bt.save_bytes(blob, path)
            size = bt.image_size(path)
            return ("Imagen generada correctamente.\n\nGuardado en:\n%s\nTamano: %s\n"
                    "Peso: %s\n\nPrompt tecnico usado:\n%s"
                    % (path, ("%dx%d" % size) if size else "n/d",
                       bt.human_size(os.path.getsize(path)), art)), path

        # ---------------- bitmap: corregir imagen existente ------------------
        if mode == "corregir_bitmap":
            if not self.current_image_path or not os.path.exists(self.current_image_path):
                raise P.ProviderError(
                    "Para corregir un bitmap, carga primero una imagen PNG/JPG con "
                    "el boton 'Cargar archivo (SVG/PNG)'.")
            conf = P.provider_conf(cfg, pid)
            with open(self.current_image_path, "rb") as fh:
                blob = fh.read()
            if conf.get("supports_image_edit"):
                edited = P.edit_image(cfg, pid, model, blob, prompt,
                                      size=cfg.get("image_size", "1024x1024"),
                                      filename=os.path.basename(self.current_image_path),
                                      timeout=timeout)
                ext = bt.guess_extension(edited)
                path = unique_path(out_dir, "corregido", ext)
                bt.save_bytes(edited, path)
                return ("Imagen corregida con el modelo de imagen.\n\nGuardado en:\n"
                        "%s" % path), path
            # Sin edicion por API: analisis de vision + script de GIMP
            analysis = ""
            try:
                analysis = P.describe_image(
                    cfg, pid, model, blob,
                    "Analiza esta imagen y describe con precision que habria que "
                    "corregir para: %s. Detalla defectos, colores, ruido y pasos." 
                    % prompt, timeout=timeout)
            except Exception as exc:  # noqa: BLE001
                analysis = "(No se pudo usar vision: %s)" % exc
            return self._script_mode(
                pid, model,
                "Analiza de la imagen:\n%s\n\nPeticion del usuario:\n%s\n\n"
                "Genera un script de GIMP/Python que corrija esta imagen "
                "(ajustes de color, ruido, nitidez, tamano, recorte, etc.)."
                % (analysis, prompt),
                "El proveedor no edita bitmaps por API; se genero un script de GIMP.")

        # ---------------- script de GIMP / Python ----------------------------
        if mode == "script":
            return self._script_mode(pid, model, prompt,
                                     "Script de GIMP/Python generado.")

        # ---------------- consulta libre -------------------------------------
        answer = P.chat(cfg, pid, model,
                        [{"role": "user", "content": prompt}],
                        temperature=temperature, max_tokens=max_tokens, timeout=timeout)
        return answer, None

    def _script_mode(self, pid, model, prompt, headline):
        system = (
            "Eres un experto en automatizacion de GIMP y de edicion de imagenes con "
            "Python. Genera codigo Python correcto y autoejecutable. Prefiere las "
            "librerias Pillow o numpy para tareas de procesado y, cuando sea propio de "
            "GIMP, el estilo de Python-Fu. Incluye comentarios en espanol y guarda el "
            "resultado en un archivo PNG. Devuelve el codigo en un bloque ```python```, "
            "sin explicaciones fuera del bloque."
        )
        answer = P.chat(self.cfg, pid, model,
                        [{"role": "system", "content": system},
                         {"role": "user", "content": prompt}],
                        temperature=0.2, max_tokens=self.cfg.get("max_tokens", 8192),
                        timeout=self.cfg.get("timeout", 600))
        import re
        code = answer
        fence = re.search(r"```(?:python)?\s*(.*?)```", answer, re.DOTALL)
        if fence:
            code = fence.group(1).strip()
        out_dir = default_output_dir(self.cfg)
        path = unique_path(out_dir, "script_gimp", "py")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(code)
        return ("%s\n\nGuardado en:\n%s\n\n%s" % (headline, path, code[:2500])), path


def main():
    app = AgentApp()
    app.mainloop()


if __name__ == "__main__":
    main()
