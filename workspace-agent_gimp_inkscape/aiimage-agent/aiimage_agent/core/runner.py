"""Motor de ejecución: localiza Inkscape/GIMP/Python y corre los pasos del plan.

Diseño pensado para no colgarse: GIMP en modo batch a veces no sale solo, así que el
runner vigila el archivo de salida y termina el proceso en cuanto aparece (y mata el
árbol de procesos si nada responde).
"""

from __future__ import annotations

import dataclasses
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .plan import Plan, Step

LOG = Callable[[str], None]

BLOCKED_TOKENS = (
    "subprocess", "os.system", "os.popen", "os.exec", "__import__", "eval(", "exec(",
    "shutil.rmtree", "os.remove", "webbrowser", "socket", "ctypes", "winreg",
    "os.environ", "input(", "Popen",
)
INKSCAPE_FLATPAK = "org.inkscape.Inkscape"
GIMP_FLATPAK = "org.gimp.GIMP"

BLANK_SVG = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"
     width="210mm" height="297mm" viewBox="0 0 744.094 1052.362">
  <g inkscape:label="Capa 1" inkscape:groupmode="layer" id="layer1" />
</svg>
"""


def is_windows() -> bool:
    return os.name == "nt"


@dataclasses.dataclass
class StepResult:
    index: int
    step: Step
    backup: str = ""                        # copia .bak si se escribió sobre la entrada
    ok: bool = False
    command: str = ""
    stdout: str = ""
    stderr: str = ""
    files: List[str] = dataclasses.field(default_factory=list)
    error: str = ""
    skipped: str = ""
    duration: float = 0.0


@dataclasses.dataclass
class Toolchain:
    inkscape: List[str] = dataclasses.field(default_factory=list)
    gimp: List[str] = dataclasses.field(default_factory=list)
    python: List[str] = dataclasses.field(default_factory=list)
    inkscape_ver: str = ""
    gimp_ver: str = ""
    notes: List[str] = dataclasses.field(default_factory=list)
    via_flatpak: Tuple[bool, bool] = (False, False)  # (inkscape, gimp)
    inkscape_actions: List[str] = dataclasses.field(default_factory=list)

    @property
    def inkscape_ok(self) -> bool:
        return bool(self.inkscape)

    @property
    def gimp_ok(self) -> bool:
        return bool(self.gimp)

    def summary(self) -> str:
        lines = [
            f"Inkscape : {self.inkscape_cmdline() or 'NO ENCONTRADO'}   {self.inkscape_ver}",
            f"GIMP     : {self.gimp_cmdline() or 'NO ENCONTRADO'}   {self.gimp_ver}",
            f"Python   : {' '.join(self.python) or 'NO ENCONTRADO (los pasos python no correrán)'}",
        ]
        lines += [f"! {n}" for n in self.notes]
        return "\n".join(lines)

    def inkscape_cmdline(self) -> str:
        return " ".join(self.inkscape)

    def gimp_cmdline(self) -> str:
        return " ".join(self.gimp)


# ---------------------------------------------------------------------------
# Descubrimiento de binarios
# ---------------------------------------------------------------------------
def _which(name: str) -> Optional[str]:
    return shutil.which(name)


def _win_candidates(app: str, patterns: Sequence[str]) -> List[str]:
    roots = []
    for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if base:
            roots.append(Path(base))
    out: List[str] = []
    for root in roots:
        for pat in patterns:
            if root.exists():
                out += [str(p) for p in sorted(root.glob(pat))]
    return out


def flatpak_apps() -> List[str]:
    if is_windows() or not _which("flatpak"):
        return []
    try:
        p = subprocess.run(["flatpak", "list", "--app", "--columns=application"],
                           capture_output=True, text=True, timeout=12)
    except (OSError, subprocess.SubprocessError):
        return []
    if p.returncode != 0:
        return []
    return [ln.strip() for ln in p.stdout.splitlines() if ln.strip()]


def _probe(cmd: Sequence[str], args: Sequence[str], timeout: float = 12.0) -> str:
    try:
        p = subprocess.run([*cmd, *args], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return ""
    return ((p.stdout or "") + (p.stderr or "")).strip().splitlines()[0] if (p.stdout or p.stderr) else ""


def _env_hint(name: str, hint: str) -> str:
    """AIA_INKSCAPE / AIA_GIMP / AIA_PYTHON tienen prioridad sobre la pista de Ajustes."""
    return (os.environ.get(name) or "").strip() or (hint or "").strip()


def find_inkscape(hint: str = "") -> Tuple[List[str], str, Optional[str]]:
    """Devuelve (cmd, versión, nota). `hint` o $AIA_INKSCAPE ganan sobre el PATH."""
    hint = _env_hint("AIA_INKSCAPE", hint)
    cands: List[List[str]] = []
    if hint:
        cands.append([hint] if os.path.isabs(hint) else shlex.split(hint))
    w = _which("inkscape")
    if w:
        cands.append([w])
    if is_windows():
        cands += [[c] for c in _win_candidates("inkscape", ("Inkscape/bin/inkscape.exe",
                                                             "Inkscape*/bin/inkscape.exe",
                                                             "Programs/Inkscape/bin/inkscape.exe"))]
    else:
        if os.path.exists("/snap/bin/inkscape"):
            cands.append(["/snap/bin/inkscape"])
        if INKSCAPE_FLATPAK in flatpak_apps():
            cands.append(["flatpak", "run", INKSCAPE_FLATPAK])
    for cmd in cands:
        out = _probe(cmd, ["--version"])
        if "Inkscape" in out or (os.path.exists(cmd[0]) and cmd[0].endswith(("inkscape", "inkscape.exe"))):
            return cmd, out or "versión desconocida", None
    return [], "", "Inkscape no encontrado: instala Inkscape 1.2+ o indica la ruta en Ajustes."


def find_gimp(hint: str = "") -> Tuple[List[str], str, Optional[str]]:
    hint = _env_hint("AIA_GIMP", hint)
    cands: List[List[str]] = []
    if hint:
        cands.append([hint] if os.path.isabs(hint) else shlex.split(hint))
    if is_windows():
        cands += [[c] for c in _win_candidates("gimp", ("GIMP*/bin/gimp-console-*.exe",
                                                         "GIMP*/bin/gimp-*.exe"))]
    else:
        for name in ("gimp-console-3.0", "gimp-console-2.99", "gimp-console", "gimp-2.10", "gimp"):
            w = _which(name)
            if w:
                cands.append([w])
        apps = flatpak_apps()
        if GIMP_FLATPAK in apps:
            cands.append(["flatpak", "run", GIMP_FLATPAK])
        if os.path.exists("/snap/bin/gimp"):
            cands.append(["/snap/bin/gimp"])
    for cmd in cands:
        out = _probe(cmd, ["--version"])
        if "GNU Image Manipulation" in out or "GIMP" in out:
            return cmd, out, None
    return [], "", "GIMP no encontrado: instala gimp (con gimp-console) o indica la ruta en Ajustes."


def find_python() -> List[str]:
    """Interpreteur para pasos `python-svg`. En un .exe congelado no vale sys.executable."""
    forced = _env_hint("AIA_PYTHON", "")
    if forced:
        return [forced] if os.path.isabs(forced) else shlex.split(forced)
    if getattr(sys, "frozen", False):
        for name in ("python3", "python", "py"):
            w = _which(name)
            if w:
                return [w]
        return []
    exe = sys.executable
    if exe and os.path.exists(exe):
        return [exe]
    for name in ("python3", "python"):
        w = _which(name)
        if w:
            return [w]
    return []


def list_inkscape_actions(cmd: Sequence[str]) -> List[str]:
    """Nombres de acción que admite este Inkscape (`inkscape --action-list`)."""
    if not cmd:
        return []
    try:
        p = subprocess.run([*cmd, "--action-list"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return []
    names: List[str] = []
    for line in (p.stdout or "").splitlines():
        # formato real: "nombre        :  Descripción…" (las descripciones pueden seguir en
        # líneas sin dos puntos, que NO deben contar como nombres)
        m = re.match(r"^\s*([a-z0-9][a-z0-9-]*)\s*:", line)
        if m and m.group(1) != "action-list" and m.group(1) not in names:
            names.append(m.group(1))
    return names


def discover(inkscape_hint: str = "", gimp_hint: str = "") -> Toolchain:
    tc = Toolchain()
    tc.inkscape, tc.inkscape_ver, n1 = find_inkscape(inkscape_hint)  # type: ignore[assignment]
    tc.gimp, tc.gimp_ver, n2 = find_gimp(gimp_hint)  # type: ignore[assignment]
    tc.python = find_python()
    for n in (n1, n2):
        if n:
            tc.notes.append(n)
    for i, app in enumerate((INKSCAPE_FLATPAK, GIMP_FLATPAK)):
        if tc.inkscape and tc.inkscape[0] == "flatpak" or tc.gimp and tc.gimp[0] == "flatpak":
            pass
    if tc.inkscape and tc.inkscape[0] == "flatpak":
        tc.via_flatpak = (True, tc.via_flatpak[1])
        tc.notes.append("Inkscape se invocará vía Flatpak (se pasa ruta absoluta dentro del sandbox).")
    if tc.gimp and tc.gimp[0] == "flatpak":
        tc.via_flatpak = (tc.via_flatpak[0], True)
        tc.notes.append("GIMP se invocará vía Flatpak.")
    tc.inkscape_actions = list_inkscape_actions(tc.inkscape)
    if tc.inkscape and not tc.inkscape_actions:
        tc.notes.append("No se pudo leer `inkscape --action-list`: las acciones no se validan por adelantado.")
    if not tc.python:
        tc.notes.append("Sin Python del sistema: los pasos 'python-svg' no se ejecutarán (usa 'svg' o 'inkscape-actions').")
    return tc


def major_version(text: str) -> int:
    m = re.search(r"(\d+)\.(\d+)", text or "")
    return int(m.group(1)) if m else 0


# ---------------------------------------------------------------------------
# Utilidades de pasos
# ---------------------------------------------------------------------------
def security_scan(step: Step) -> List[str]:
    """Tokens peligrosos en código que el agente no debería ejecutar."""
    if step.kind in ("file", "svg"):
        return []
    found = [t for t in BLOCKED_TOKENS if t in step.code]
    if step.kind == "script-fu" and re.search(r"\(gimp-quit", step.code):
        found.append("gimp-quit (controlado por el agente)")
    return found


def substitute(code: str, workspace: Path, step: Step) -> str:
    inp = workspace / (step.input or "")
    out = workspace / step.output
    rep = {
        "{INPUT}": str(inp if step.input else ""),
        "{OUTPUT}": str(out),
        "{WORKSPACE}": str(workspace),
        "{INPUT_PATH}": str(inp if step.input else ""),
        "{OUTPUT_PATH}": str(out),
        "{input}": str(inp if step.input else ""),
        "{output}": str(out),
    }
    for k, v in rep.items():
        code = code.replace(k, v.replace("\\", "/") if not is_windows() else v.replace("\\", "\\\\"))
    return code


def _actions_list(code: str) -> List[str]:
    acts: List[str] = []
    for chunk in re.split(r"[;\n]+", code or ""):
        chunk = chunk.strip().strip(";")
        chunk = re.sub(r"^(select-all|item-\S+|edit-\S+)\s*$", r"\1", chunk)
        if not chunk or chunk.startswith("#") or chunk.startswith("inkscape"):
            continue
        chunk = chunk.replace("--actions=", "").replace("--actions", "").strip(" =\"")
        if chunk:
            acts.append(chunk)
    return acts


def ensure_input(workspace: Path, step: Step, log: Optional[LOG] = None) -> Path:
    """El paso necesita un archivo de entrada; si falta, crea un lienzo en blanco."""
    if step.input:
        p = workspace / step.input
        if p.exists():
            return p
    created = workspace / "_ai_blank.svg"
    if not created.exists():
        created.write_text(BLANK_SVG, encoding="utf-8")
    if step.input:  # entra por un nombre que no existe -> copiamos la plantilla
        shutil.copyfile(created, workspace / step.input)
        return workspace / step.input
    if log:
        log("  (sin entrada: se crea un lienzo A4 en blanco _ai_blank.svg)")
    return created


def copy_if_same_input_output(workspace: Path, step: Step) -> str:
    """Nunca sobrescribir el original: si input == output, trabajamos sobre una copia."""
    if step.input and step.input.lower() == step.output.lower():
        src = workspace / step.input
        if src.exists():
            tmp = workspace / f"_ai_in_{src.name}"
            shutil.copyfile(src, tmp)
            return tmp.name
    return step.input


def backup_original(workspace: Path, step: Step) -> Optional[Path]:
    """Si el plan escribe sobre el propio archivo de entrada, guardamos antes una copia `.bak`.

    Editar «en el sitio» es legítimo («arréglame este SVG»), pero perder los bytes originales
    nunca lo es. Devuelve la ruta de la copia, o None si no hacía falta.
    """
    if not step.input or not step.output or step.input.lower() != step.output.lower():
        return None
    dst = workspace / step.output
    if not dst.is_file():
        return None
    bak = dst.with_name(f"{dst.name}.{time.strftime('%Y%m%d-%H%M%S')}.bak")
    try:
        shutil.copyfile(dst, bak)
    except OSError:
        return None
    return bak


# ---------------------------------------------------------------------------
# Comandos por tipo de paso
# ---------------------------------------------------------------------------
def build_cmd(step: Step, workspace: Path, tc: Toolchain) -> Tuple[Sequence[str], List[Path], str, List[str]]:
    """Devuelve (argv, rutas_de_salida_esperadas, texto_para_mostrar, notas).

    Escribe en disco los scripts que el comando necesita (py/scm) y devuelve sus rutas.
    """
    out = workspace / step.output
    notes: List[str] = []
    if step.kind == "file":
        return [], [out], f"(escribir archivo) {step.output}", notes
    if step.kind == "svg":
        return [], [out], f"(escribir SVG) {step.output}", notes

    if step.kind == "inkscape-actions":
        if not tc.inkscape:
            return [], [], "", ["Inkscape no está disponible"]
        name = copy_if_same_input_output(workspace, step)
        src = ensure_input(workspace, dataclasses.replace(step, input=name), None)
        raw = _actions_list(step.code)
        known = set(tc.inkscape_actions)
        # la salida la controla el agente (por la extensión de `output`): si el modelo fija
        # export-filename/export-type como acción, Inkscape recibiría dos destinos y ganaría el raro
        reserved = ("export-type", "export-filename", "export-overwrite", "export-do")
        acts, dropped, hijacked = [], [], []
        for a in raw:
            head = a.split(":", 1)[0].strip()
            if head in reserved:
                hijacked.append(head)
                continue
            if known and head and head not in known:
                dropped.append(head)
                continue
            acts.append(a)
        notes = [f"acción no soportada por este Inkscape y descartada: `{d}`" for d in dropped]
        notes += [f"`{h}` lo fija el agente según el archivo de salida: ignorado en las acciones" for h in hijacked]
        if not acts:
            if known:
                hint = "Acciones disponibles (muestra): " + ", ".join(sorted(known)[:18])
            else:
                hint = "No se pudo obtener la lista de acciones de este Inkscape."
            return [], [], "", [f"ninguna acción es válida para este Inkscape. {hint}"]
        argv = [*tc.inkscape, str(src), "--actions", ";".join(acts), "--batch-process"]
        ext = out.suffix.lstrip(".").lower() or "svg"
        argv += ["--export-type", ext, "--export-filename", str(out)]
        if name and Path(name).name == out.name:
            argv += ["--export-overwrite"]
        return argv, [out], _show(argv), notes

    if step.kind in ("python-svg", "inkex-python"):
        if not tc.python:
            return [], [], "", ["Sin intérprete Python del sistema para 'python-svg'"]
        interp = tc.python
        if step.kind == "inkex-python":
            interp = _python_with_inkex(tc)
            if not interp:
                return [], [], "", [
                    "No se encontró un Python con `inkex` instalable. Alternativa: convierte el paso a "
                    "'python-svg' (solo librería estándar) o 'inkscape-actions'."]
        name = copy_if_same_input_output(workspace, step)
        src = ensure_input(workspace, dataclasses.replace(step, input=name), None)
        code = substitute(step.code, workspace, dataclasses.replace(step, input=src.name))
        script = workspace / "_ai_step.py"
        prelude = (
            "# -*- coding: utf-8 -*-\n# generado por AI Image Agent\n"
            f"import os, sys\n"
            f"WORKSPACE = {str(workspace)!r}\nINPUT = {str(src)!r}\nOUTPUT = {str(out)!r}\n"
            "os.chdir(WORKSPACE)\nsys.argv = [INPUT, OUTPUT]\n"
        )
        script.write_text(prelude + code, encoding="utf-8")
        return [*interp, str(script)], [out], _show([*interp, script.name]), notes

    if step.kind == "script-fu":
        if not tc.gimp:
            return [], [], "", ["GIMP no está disponible"]
        from .gimp_compat import compat_warnings, major_from_version, wrap_script

        major = major_from_version(tc.gimp_ver)
        name = copy_if_same_input_output(workspace, step)
        inp = workspace / name if name else None
        if inp is None:
            inp = ensure_input(workspace, step, None)
        # el modelo escribe rutas con marcadores; se sustituyen ANTES de traducir
        code = substitute(step.code, workspace, dataclasses.replace(step, input=inp.name))
        wrapped, notes = wrap_script(code, major)
        for w in compat_warnings(code, major):
            notes.append(w)
        script = workspace / "_ai_step.scm"
        script.write_text(wrapped, encoding="utf-8")
        load = str(script).replace("\\", "/")
        argv = [*tc.gimp, "-i", "--batch-interpreter=plug-in-script-fu-eval", "-b", f'(load "{load}")']
        argv += ["--quit"] if major >= 3 else ["-b", "(gimp-quit 0)"]
        return argv, [out], _show(argv), notes

    if step.kind == "python-fu":
        if not tc.gimp:
            return [], [], "", ["GIMP no está disponible"]
        name = copy_if_same_input_output(workspace, step)
        code = substitute(step.code, workspace, dataclasses.replace(step, input=name or ""))
        script = workspace / "_ai_step_gimp.py"
        script.write_text(code, encoding="utf-8")
        p = str(script).replace("\\", "/")
        from .gimp_compat import major_from_version

        g3 = major_from_version(tc.gimp_ver) >= 3
        interp = "plug-in-python-eval" if g3 else "python-fu-eval"
        runner = f"exec(open(r'{p}').read())" if not g3 else f"exec(open('{p}').read())"
        argv = [*tc.gimp, "-i", f"--batch-interpreter={interp}", "-b", runner]
        argv += ["--quit"] if g3 else ["-b", "(gimp-quit 0)"]
        notes.append(f"intérprete de batch: {interp} (GIMP {'3.x' if g3 else '2.x'}); "
                     "si GIMP no tiene Python-Fu, cambia el paso a 'script-fu'.")
        return argv, [out], _show(argv), notes

    if step.kind == "shell-export":
        argvs, notes2 = _parse_shell_export(step, workspace, tc)
        if not argvs:
            return [], [], "", ["Ninguna línea de 'shell-export' era un comando Inkscape/GIMP reconocido"]
        argv = argvs[0]
        outs = [workspace / m for m in re.findall(r"--export-filename[= ]\"?([A-Za-z0-9_.\-/\\]+)", step.code)]
        return argv, outs or [out], _show(argv), notes2

    return [], [], "", [f"kind no soportado: {step.kind}"]


def _parse_shell_export(step: Step, workspace: Path, tc: Toolchain) -> Tuple[List[Sequence[str]], List[str]]:
    """Reescribe `inkscape ...` / `gimp ...` usando las rutas detectadas (nunca un PATH arbitrario)."""
    res: List[Sequence[str]] = []
    notes: List[str] = []
    for line in substitute(step.code, workspace, step).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        line = line.replace("\\", "/") if not is_windows() else line
        try:
            toks = shlex.split(line)
        except ValueError:
            notes.append(f"línea sin comillas balanceadas, ignorada: {line[:60]}")
            continue
        head = Path(toks[0]).name.lower().replace(".exe", "")
        if head.startswith("inkscape"):
            res.append([*tc.inkscape, *toks[1:]] if tc.inkscape else [])
        elif head.startswith(("gimp", "script-fu")):
            res.append([*tc.gimp, "-i", *toks[1:]] if tc.gimp else [])
        else:
            notes.append(f"comando no permitido en shell-export: {toks[0]!r}")
    return [r for r in res if r], notes


def _python_with_inkex(tc: Toolchain) -> List[str]:
    """Busca un Python donde `import inkex` funcione (necesario para inkex-python)."""
    cands: List[List[str]] = []
    if tc.python:
        cands.append(list(tc.python))
    for name in ("python3", "python"):
        w = _which(name)
        if w and [w] not in cands:
            cands.append([w])
    if is_windows():
        for exe in _win_candidates("inkscape", ("Inkscape*/bin/python.exe", "Inkscape*/bin/python3.exe")):
            if [exe] not in cands:
                cands.append([exe])
    for cmd in cands:
        if "Inkscape" in _probe(cmd, ["-c", "import inkex, sys; print(inkex.__file__)"], 20.0) or \
           _probe(cmd, ["-c", "import inkex; print('inkex-ok')"], 20.0).strip().endswith("inkex-ok"):
            return cmd
    return []


def _show(argv: Sequence[str]) -> str:
    return subprocess.list2cmdline(list(argv)) if is_windows() else " ".join(shlex.quote(a) for a in argv)


# ---------------------------------------------------------------------------
# Ejecución
# ---------------------------------------------------------------------------
def _popen(argv: Sequence[str], workspace: Path) -> subprocess.Popen:
    kw: Dict[str, object] = dict(cwd=str(workspace), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True, encoding="utf-8", errors="replace")
    if is_windows():
        kw["creationflags"] = 0x08000000 | 0x00000200  # CREATE_NO_WINDOW | NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    return subprocess.Popen(list(argv), **kw)  # type: ignore[arg-type]


def _kill(proc: subprocess.Popen) -> None:
    try:
        if is_windows():
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                           capture_output=True, text=True, timeout=10)
        else:
            import signal

            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            time.sleep(0.6)
            if proc.poll() is None:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        try:
            proc.kill()
        except OSError:
            pass


def _wait(proc: subprocess.Popen, expected: List[Path], timeout: float,
          log: Optional[LOG] = None) -> str:
    """Espera a que aparezca la salida o muera el proceso. Devuelve 'exit'|'killed'|'timeout'."""
    deadline = time.monotonic() + timeout
    stable_since: Optional[float] = None
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return "exit"
        if expected and all(p.exists() and p.stat().st_size > 0 for p in expected):
            now = time.monotonic()
            if stable_since is None:
                stable_since = now
            elif now - stable_since > 1.0:
                return "killed"
        else:
            stable_since = None
        time.sleep(0.25)
    return "timeout"


def run_step(step: Step, workspace: Path, tc: Toolchain, *, index: int = 0,
             timeout: float = 180.0, safe_mode: bool = False, allow_unsafe: bool = False,
             export_preview: bool = True, log: Optional[LOG] = None) -> StepResult:
    res = StepResult(index=index, step=step)
    t0 = time.monotonic()
    say = log or (lambda _s: None)

    blocked = security_scan(step)
    if blocked and not allow_unsafe:
        res.error = ("Bloqueado por seguridad: el código contiene " + ", ".join(f"`{b}`" for b in blocked)
                     + ". Desactiva 'Modo seguro' o corrige el paso en el editor.")
        say(f"[{index + 1}] {res.error}")
        res.duration = time.monotonic() - t0
        return res

    if safe_mode and step.kind not in ("file", "svg"):
        res.skipped = ("Modo seguro: solo se prepararon los archivos; no se ejecutó. "
                       "Desactiva «Modo seguro» (o usa --execute) para correr Inkscape/GIMP.")
        say(f"[{index + 1}] {step.kind} · omitido por Modo seguro")
        res.duration = time.monotonic() - t0
        return res

    bak = backup_original(workspace, step)
    if bak:
        res.backup = str(bak)
        say(f"[{index + 1}] la salida pisa la entrada: original a salvo en {bak.name}")

    if step.kind == "file":
        (workspace / step.output).parent.mkdir(parents=True, exist_ok=True)
        (workspace / step.output).write_text(step.code, encoding="utf-8")
        res.ok, res.files = True, [str(workspace / step.output)]
        res.command = f"escribir {step.output}"
        say(f"[{index + 1}] archivo escrito: {step.output} ({len(step.code)} chars)")
        res.duration = time.monotonic() - t0
        return res

    if step.kind == "svg":
        ok, msg = _write_svg(workspace / step.output, step.code)
        if not ok:
            res.error = msg
            say(f"[{index + 1}] SVG inválido: {msg}")
        else:
            res.ok = True
            res.files = [str(workspace / step.output)]
            res.command = f"escribir {step.output}"
            say(f"[{index + 1}] SVG escrito: {step.output}")
            if export_preview and tc.inkscape_ok:
                png = _export_preview(workspace, step.output, tc, timeout=min(timeout, 60))
                if png:
                    res.files.append(png)
                    say(f"      previsualización PNG: {os.path.basename(png)}")
                else:
                    say("      (no se pudo exportar la previsualización)")
        res.duration = time.monotonic() - t0
        return res

    argv, expected, show, notes = build_cmd(step, workspace, tc)
    for n in notes:
        say(f"[{index + 1}] ! {n}")
    if not argv:
        res.error = "; ".join(notes) or "No se pudo armar el comando"
        res.duration = time.monotonic() - t0
        return res
    res.command = show
    say(f"[{index + 1}] {step.app} · {step.kind} → {step.output}")
    say(f"      $ {show}")
    try:
        proc = _popen(argv, workspace)
    except OSError as exc:
        res.error = f"No se pudo lanzar el comando: {exc}"
        res.duration = time.monotonic() - t0
        return res
    state = _wait(proc, expected, timeout, log)
    if state in ("killed", "timeout"):
        _kill(proc)
        try:
            out, err = proc.communicate(timeout=8)
        except subprocess.TimeoutExpired:  # pragma: no cover
            out, err = "", ""
    else:
        try:
            out, err = proc.communicate(timeout=15)
        except subprocess.TimeoutExpired:  # pragma: no cover
            _kill(proc)
            out, err = "", ""
    res.stdout = (out or "").strip()
    res.stderr = (err or "").strip()
    for line in (res.stdout + ("\n" + res.stderr if res.stderr else "")).splitlines():
        if line.strip():
            say("      | " + line[:400])
    produced = [str(p) for p in expected if p.exists() and p.stat().st_size > 0]
    res.files = produced
    code = proc.returncode if proc.returncode is not None else 0
    hard = ("Error:" in (res.stderr or "")) or ("could not find action" in (res.stderr or ""))
    res.ok = bool(produced) and code == 0 and not hard
    if not res.ok and produced:
        res.error = (f"Se generó la salida pero el proceso terminó con código {code}. "
                     "Revisa la consola.")
        res.ok = True  # tolerante: GIMP suele devolver 0 con warnings
    if not res.ok and not produced and state == "timeout":
        res.error = f"Timeout de {timeout:.0f}s sin generar {step.output}."
    if not res.ok and not produced and not res.error:
        res.error = f"No se generó {step.output}. Código {code}."
    res.duration = time.monotonic() - t0
    say(f"      {'OK' if res.ok else 'FALLO'} en {res.duration:.1f}s"
        + (f" → {', '.join(os.path.basename(f) for f in produced)}" if produced else ""))
    return res


SVG_NS_RE = re.compile(r"<svg[^>]*xmlns\s*=\s*[\"']http://www\.w3\.org/2000/svg[\"']", re.I)


def _write_svg(path: Path, code: str) -> Tuple[bool, str]:
    """Valida lo mínimo y escribe el SVG. Devuelve (ok, mensaje)."""
    import xml.etree.ElementTree as ET

    txt = (code or "").strip()
    if txt.startswith("```"):
        txt = re.sub(r"^```[a-zA-Z]*\s*\n?", "", txt)
        txt = re.sub(r"```\s*$", "", txt).strip()
    if "<svg" not in txt.lower():
        return False, "el bloque no contiene <svg>"
    i = txt.lower().find("<?xml")
    j = txt.find("<svg")
    start = i if 0 <= i < j else j
    body = txt[start:]
    if not SVG_NS_RE.search(body):
        if "xmlns" in body[:400].lower():
            return False, "el <svg> no declara el namespace http://www.w3.org/2000/svg"
        body = body.replace("<svg ", '<svg xmlns="http://www.w3.org/2000/svg" ', 1)
    if re.search(r"<script|<foreignObject|javascript\s*:", body, re.I):
        return False, "el SVG contiene <script>/<foreignObject>/javascript: (bloqueado)"
    try:
        ET.fromstring(body)
    except ET.ParseError as exc:
        return False, f"XML mal formado: {exc}"
    if not body.lstrip().startswith("<?xml"):
        body = '<?xml version="1.0" encoding="UTF-8"?>\n' + body
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return True, ""


def _export_preview(workspace: Path, svg_name: str, tc: Toolchain, timeout: float) -> Optional[str]:
    src = workspace / svg_name
    png = workspace / (os.path.splitext(svg_name)[0] + ".preview.png")
    argv = [*tc.inkscape, str(src), "--export-type", "png", "--export-filename", str(png),
            "--export-dpi", "96"]
    try:
        proc = _popen(argv, workspace)
    except OSError:
        return None
    try:
        _wait(proc, [png], timeout, None)
        if proc.poll() is None:
            _kill(proc)
        try:
            proc.communicate(timeout=5)
        except (subprocess.TimeoutExpired, ValueError):  # pragma: no cover
            pass
    finally:
        for pipe in (proc.stdout, proc.stderr):
            try:
                if pipe is not None and not pipe.closed:
                    pipe.close()
            except OSError:  # pragma: no cover
                pass
    return str(png) if png.exists() else None


def run_plan(plan: Plan, workspace: Path, tc: Toolchain, *, timeout: float = 180.0,
             safe_mode: bool = False, allow_unsafe: bool = False, export_preview: bool = True,
             log: Optional[LOG] = None, should_stop: Optional[Callable[[], bool]] = None) -> List[StepResult]:
    workspace.mkdir(parents=True, exist_ok=True)
    results: List[StepResult] = []
    for i, step in enumerate(plan.steps):
        if not step.enabled:
            continue
        if should_stop and should_stop():
            results.append(StepResult(index=i, step=step, skipped="cancelado por el usuario"))
            break
        results.append(run_step(step, workspace, tc, index=i, timeout=timeout, safe_mode=safe_mode,
                                allow_unsafe=allow_unsafe, export_preview=export_preview, log=log))
    return results


def results_to_text(results: List[StepResult]) -> str:
    lines = []
    for r in results:
        status = "OK" if r.ok else ("OMITIDO" if r.skipped else "ERROR")
        lines.append(f"[{r.index + 1}] {r.step.app}/{r.step.kind} · {r.step.output} → {status}"
                     + (f" ({r.duration:.1f}s)" if r.duration else ""))
        if r.skipped:
            lines.append(f"    {r.skipped}")
        if r.error:
            lines.append(f"    ! {r.error}")
        if (r.stderr or r.stdout) and (not r.ok or "rror" in (r.stderr or "")):
            tail = ((r.stderr + "\n" + r.stdout).strip()[-900:]) if r.stderr else r.stdout.strip()[-900:]
            lines.append("    salida:\n" + "\n".join("      " + l for l in tail.splitlines()[:12]))
        for f in r.files:
            lines.append(f"    → {f}")
        if r.backup:
            lines.append(f"    ⛨ original respaldado en {Path(r.backup).name}")
    return "\n".join(lines)
