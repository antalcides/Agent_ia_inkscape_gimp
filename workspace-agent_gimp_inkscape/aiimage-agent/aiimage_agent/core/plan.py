"""Conversión de la respuesta del modelo en un PLAN ejecutable (tolerante a errores)."""

from __future__ import annotations

import dataclasses
import json
import os
import re
from typing import Any, Dict, List, Optional

VALID_KINDS = ("svg", "inkscape-actions", "python-svg", "inkex-python", "script-fu", "python-fu",
              "shell-export", "file")
APP_OF_KIND = {
    "file": "inkscape",
    "svg": "inkscape",
    "inkscape-actions": "inkscape",
    "python-svg": "inkscape",
    "inkex-python": "inkscape",
    "shell-export": "inkscape",
    "script-fu": "gimp",
    "python-fu": "gimp",
}
EXT_OF_KIND = {
    "file": "",
    "svg": ".svg",
    "inkscape-actions": ".svg",
    "python-svg": ".svg",
    "inkex-python": ".svg",
    "script-fu": ".png",
    "python-fu": ".png",
    "shell-export": ".png",
}


@dataclasses.dataclass
class Step:
    app: str = "inkscape"
    kind: str = "svg"
    purpose: str = ""
    code: str = ""
    input: str = ""
    output: str = "out.svg"
    enabled: bool = True

    @property
    def needs_run(self) -> bool:
        return self.kind != "svg" or not self.code.strip().startswith("<")


@dataclasses.dataclass
class Plan:
    summary: str = ""
    notes: List[str] = dataclasses.field(default_factory=list)
    steps: List[Step] = dataclasses.field(default_factory=list)
    explanation: str = ""
    warnings: List[str] = dataclasses.field(default_factory=list)
    raw: str = ""

    @property
    def apps(self) -> List[str]:
        seen: List[str] = []
        for s in self.steps:
            if s.app not in seen:
                seen.append(s.app)
        return seen


# ---------------------------------------------------------------------------
# Extracción de JSON
# ---------------------------------------------------------------------------
_FENCE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.DOTALL)


def extract_json(text: str) -> Dict[str, Any]:
    """Busca el objeto JSON de la respuesta, aceptando fences, prosa y comas colgantes."""
    if not text or not text.strip():
        raise ValueError("La respuesta del modelo está vacía.")
    candidates: List[str] = []
    candidates += [m.strip() for m in _FENCE.findall(text)]
    candidates.append(text.strip())
    brace = _find_balanced(text)
    if brace:
        candidates.append(brace)
    for cand in candidates:
        for attempt in (cand, _repair(cand)):
            if not attempt:
                continue
            try:
                obj = json.loads(attempt)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                return obj
            if isinstance(obj, list) and obj and isinstance(obj[0], dict):
                return {"steps": obj, "summary": "Plan generado por el modelo"}
    raise ValueError(
        "El modelo no devolvió el JSON del plan. Inicio de la respuesta:\n"
        + text.strip()[:600]
    )


def _find_balanced(text: str) -> Optional[str]:
    """Devuelve el objeto JSON principal; si está truncado, cierra lo que falte."""
    start = text.find("{")
    if start < 0:
        return None
    stack: List[str] = []
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if not stack:
                return text[start:i + 1]
            if stack[-1] == ("{" if ch == "}" else "["):
                stack.pop()
                if not stack:
                    return text[start : i + 1]
            else:  # delimitador cruzado: JSON roto, devolvemos tal cual
                return text[start : i + 1]
    frag = text[start:]
    if in_str:
        frag += '"'
        frag = frag.rstrip(",")
    # corta comas/':'.colgantes y cierra en orden inverso
    frag = re.sub(r",\s*$", "", frag)
    frag = re.sub(r"[\[{,:]\s*$", "", frag) if re.search(r"[\[{,:]\s*$", frag) else frag
    closer = {"{": "}", "[": "]"}
    frag += "".join(closer[c] for c in reversed(stack))
    return frag


def _repair(s: str) -> str:
    s = re.sub(r",(\s*[}\]])", r"\1", s)                       # comas colgantes
    s = re.sub(r"\bNaN\b|\bInfinity\b|\b-Infinity\b", "null", s)
    s = re.sub(r"^\ufeff", "", s)
    s = "\n".join(line.rstrip() for line in s.splitlines())
    if s.count("{") > s.count("}"):
        s += "}" * (s.count("{") - s.count("}"))
    return s


# ---------------------------------------------------------------------------
# Normalización
# ---------------------------------------------------------------------------
def safe_name(name: str, default: str) -> str:
    """Deja solo el basename, sin `..` ni rutas raras."""
    name = (name or "").strip().replace("\\", "/").split("/")[-1]
    name = re.sub(r'[<>:"|?*\x00-\x1f]', "_", name).strip(". ")
    if not name:
        return default
    return name[:120]


def parse_plan(text: str, *, default_app: str = "inkscape") -> Plan:
    obj = extract_json(text)
    plan = Plan(raw=text)
    plan.summary = str(obj.get("summary") or obj.get("resumen") or "").strip()
    plan.explanation = str(obj.get("explanation") or obj.get("notes_final") or "").strip()
    notes = obj.get("notes") or obj.get("advertencias") or []
    if isinstance(notes, str):
        notes = [notes]
    plan.notes = [str(n) for n in notes if str(n).strip()][:20]

    steps_raw = obj.get("steps") or obj.get("pasos") or obj.get("actions") or []
    if isinstance(steps_raw, dict):
        steps_raw = [steps_raw]
    for i, s in enumerate(steps_raw):
        if not isinstance(s, dict):
            plan.warnings.append(f"Paso #{i + 1} ignorado: no es un objeto.")
            continue
        code = s.get("code") or s.get("script") or s.get("content") or s.get("python") or s.get("scheme") or ""
        if isinstance(code, list):
            code = "\n".join(str(x) for x in code)
        kind = str(s.get("kind") or s.get("mode") or s.get("type") or "").strip().lower().replace("_", "-")
        app = str(s.get("app") or s.get("target") or "").strip().lower()
        if kind not in VALID_KINDS:
            kind, fixed = _guess_kind(kind, str(code), app)
            if fixed:
                plan.warnings.append(f"Paso #{i + 1}: kind '{kind or '??'}' no válido → '{fixed}'.")
            else:
                plan.warnings.append(f"Paso #{i + 1}: no se reconoce el kind ({kind or 'vacío'}); se omite.")
                continue
            kind = fixed
        app = APP_OF_KIND.get(kind, app or default_app)
        if app not in ("inkscape", "gimp"):
            app = APP_OF_KIND[kind]
        ext = EXT_OF_KIND[kind]
        out = safe_name(str(s.get("output") or s.get("filename") or f"step{i + 1}{ext}"), f"step{i + 1}{ext}")
        if not os.path.splitext(out)[1]:
            out += ext
        inp = safe_name(str(s.get("input") or s.get("in") or ""), "")
        plan.steps.append(Step(app=app, kind=kind, purpose=str(s.get("purpose") or s.get("descripcion") or "").strip(),
                               code=str(code), input=inp, output=out))

    ws_files = obj.get("workspace_files") or obj.get("files") or []
    if isinstance(ws_files, dict):
        ws_files = [{"name": k, "content": v} for k, v in ws_files.items()]
    for f in ws_files:
        if isinstance(f, dict) and f.get("name") and f.get("content") is not None:
            name = safe_name(str(f["name"]), "input.txt")
            app = "inkscape" if name.lower().endswith(".svg") else "gimp"
            plan.steps.insert(0, Step(app=app, kind="file", purpose=f"Archivo inicial {name}",
                                      code=str(f["content"]), input="", output=name))

    if not plan.steps:
        plan.warnings.append("El modelo no propuso pasos; revisa el pedido o elige un modelo más capable.")
    _post_validate(plan)
    return plan


def _guess_kind(kind: str, code: str, app: str) -> tuple[str, str]:
    c = (code or "").lstrip()
    low = (kind or "").lower()
    if low in ("scheme", "script-fu", "tinyscheme"):
        return "script-fu", "script-fu"
    if low in ("py", "python"):
        return "python-svg", "python-svg"
    if "inkex" in c:
        return "inkex-python", "inkex-python"
    if c.startswith("<") or c.startswith("<?xml") or "<svg" in c[:400]:
        return "svg", "svg"
    if c.startswith("(") or "(gimp-" in c[:400] or "script-fu" in low:
        return "script-fu", "script-fu"
    if re.search(r"^\s*(select-all|object-|item-|edit-|layers-|file-)", c) and "inkscape" not in c[:40]:
        return "inkscape-actions", "inkscape-actions"
    if c.startswith("inkscape ") or c.startswith("gimp "):
        return "shell-export", "shell-export"
    if (app or "").lower() == "gimp":
        return "script-fu", "script-fu"
    return "python-svg", "python-svg" if c.startswith(("import ", "from ", "def ", "#")) else "svg"


def _post_validate(plan: Plan) -> None:
    seen: Dict[str, int] = {}
    for idx, s in enumerate(plan.steps):
        key = s.output.lower()
        seen[key] = seen.get(key, 0) + 1
        if seen[key] > 1 and idx > 0 and plan.steps[idx - 1].output.lower() == key:
            plan.warnings.append(f"Dos pasos escriben '{s.output}'; el segundo sobreescribe el primero.")
        if s.kind == "python-fu":
            plan.warnings.append("python-fu requiere GIMP 3.x (Python 3). En GIMP 2.10 el script corre con Python 2.")
        if s.kind in ("python-svg", "inkex-python", "script-fu", "python-fu", "shell-export"):
            for bad in ("input(", "os.system", "subprocess", "requests.", "socket", "shutil.rmtree"):
                if bad in s.code:
                    plan.warnings.append(f"'{bad}' en el paso {idx + 1}: el agente lo bloqueará antes de ejecutar.")
        if s.kind == "script-fu" and "gimp-quit" in s.code:
            s.code = s.code.replace("(gimp-quit 0)", "").replace("(gimp-quit)", "")
            plan.warnings.append(f"Paso {idx + 1}: se quitó (gimp-quit) del script; el agente controla la salida.")
        if s.input and s.kind in ("script-fu", "python-fu", "inkscape-actions", "python-svg", "inkex-python") and s.input == s.output:
            plan.warnings.append(f"Paso {idx + 1}: input == output; el agente trabajará sobre una copia.")


# ---------------------------------------------------------------------------
# Serialización / render para la GUI
# ---------------------------------------------------------------------------
def plan_to_dict(plan: Plan) -> Dict[str, Any]:
    return {
        "summary": plan.summary,
        "notes": plan.notes,
        "explanation": plan.explanation,
        "steps": [dataclasses.asdict(s) for s in plan.steps],
    }


def plan_to_json(plan: Plan) -> str:
    return json.dumps(plan_to_dict(plan), ensure_ascii=False, indent=2)


def render_plan(plan: Plan, *, show_code: bool = True, max_code: int = 0) -> str:
    out = [f"PLAN · {len(plan.steps)} paso(s)", "", f"Resumen: {plan.summary or '(sin resumen)'}"]
    if plan.notes:
        out.append("")
        out.append("Notas:")
        out += [f"  • {n}" for n in plan.notes]
    for i, s in enumerate(plan.steps, 1):
        out.append("")
        out.append(f"[{i}] {s.app} · {s.kind}  →  {s.output}"
                   + (f"   (entrada: {s.input})" if s.input else "")
                   + ("   [desactivado]" if not s.enabled else ""))
        if s.purpose:
            out.append(f"    {s.purpose}")
        if show_code and s.code:
            code = s.code if not max_code else s.code[:max_code] + ("…" if len(s.code) > max_code else "")
            for line in code.splitlines():
                out.append(f"    | {line}")
    if plan.warnings:
        out.append("")
        out.append("Advertencias:")
        out += [f"  ! {w}" for w in plan.warnings]
    if plan.explanation:
        out.append("")
        out.append(f"Explicación: {plan.explanation}")
    return "\n".join(out)


def edit_steps_from_text(plan: Plan, text: str) -> Plan:
    """Re-parsea el JSON editado por el usuario en la GUI (pestaña Plan/JSON)."""
    try:
        new = parse_plan(text)
    except ValueError as exc:
        raise ValueError(f"El JSON editado no es válido: {exc}") from None
    new.summary = new.summary or plan.summary
    return new


def plan_from_freeform(app: str, kind: str, code: str, *, output: str, input_name: str = "") -> Plan:
    """Permite ejecutar código escrito a mano (sin pasar por el modelo)."""
    if kind not in VALID_KINDS:
        raise ValueError(f"kind inválido: {kind}")
    plan = Plan(summary="Ejecución manual del código del editor",
                steps=[Step(app=APP_OF_KIND[kind], kind=kind, purpose="Escrito a mano",
                            code=code, input=input_name, output=safe_name(output, f"out{EXT_OF_KIND[kind]}"))])
    _post_validate(plan)
    return plan
