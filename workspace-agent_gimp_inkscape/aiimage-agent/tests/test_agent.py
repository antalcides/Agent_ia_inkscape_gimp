"""Pruebas del AI Image Agent (sin red, sin Inkscape/GIMP instalados).

Ejecutar:  python -m unittest discover -s tests -v      (o `pytest tests`)
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import mock_llm  # noqa: E402
from tool_stubs import write_stubs  # noqa: E402

from aiimage_agent.core import net, prompts  # noqa: E402
from aiimage_agent.core.agent import Agent  # noqa: E402
from aiimage_agent.core.config import Config  # noqa: E402
from aiimage_agent.core.plan import Step, parse_plan, plan_to_json, render_plan  # noqa: E402
from aiimage_agent.core.runner import Toolchain, discover, run_plan, run_step, security_scan  # noqa: E402
from aiimage_agent.providers import PROVIDER_ORDER, get_provider  # noqa: E402
from aiimage_agent.providers.base import ProviderError, openai_style_base  # noqa: E402

BASE = ""


def setUpModule() -> None:  # noqa: N802
    global BASE
    BASE = mock_llm.MockLLM.start()
    os.environ["OPENAI_API_KEY"] = "sk-test"
    os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test"
    os.environ["GEMINI_API_KEY"] = "g-test"
    os.environ["OPENROUTER_API_KEY"] = "or-test"


def tearDownModule() -> None:  # noqa: N802
    mock_llm.MockLLM.stop()


def prov(pid: str, **kw):
    url = {"openai": f"{BASE}/v1", "openrouter": f"{BASE}/api/v1", "lmstudio": f"{BASE}/v1",
           "omniroute": f"{BASE}/v1", "ollama": BASE, "anthropic": BASE, "gemini": f"{BASE}/v1beta"}[pid]
    return get_provider(pid, base_url=kw.pop("base_url", url), api_key=kw.pop("api_key", "k-test"),
                        timeout=25.0, **kw)


# --------------------------------------------------------------------------
class ProviderContractTest(unittest.TestCase):

    def test_gemini_sin_clave_avisa_claramente(self):
        """Sin key en la config ni en el entorno hay que explicar qué falta (y no romper)."""
        guard = {k: os.environ.pop(k) for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY") if k in os.environ}
        try:
            p = get_provider("gemini", base_url="https://generativelanguage.googleapis.com/v1beta",
                            api_key="")
            with self.assertRaises(ProviderError) as cm:
                p.headers()
            self.assertIn("Gemini", str(cm.exception))
            self.assertIn("GEMINI_API_KEY", str(cm.exception))
        finally:
            os.environ.update(guard)

    def test_gemini_rama_propia_no_es_nameerror(self):
        """Regresión: la rama propia de Gemini lanzaba `ProviderError` sin importarlo.

        Se fuerza `needs_key = False` para llegar a ella (si no, la clase base ya avisa antes).
        """
        guard = {k: os.environ.pop(k) for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY") if k in os.environ}
        try:
            p = get_provider("gemini", base_url="https://h/v1beta", api_key="")
            p.needs_key = False
            with self.assertRaises(ProviderError) as cm:
                p.headers()
            self.assertIn("AI Studio", str(cm.exception))
        finally:
            os.environ.update(guard)

    def test_gemini_con_clave_usa_x_goog_api_key(self):
        p = get_provider("gemini", base_url="https://h/v1beta", api_key="AIza-demo")
        self.assertEqual(p.headers().get("x-goog-api-key"), "AIza-demo")


    def setUp(self) -> None:
        mock_llm.MockLLM.requests = []
        mock_llm.MockLLM.plan = dict(mock_llm.PLAN_OK)
        mock_llm.MockLLM.raw_response = None
        mock_llm.MockLLM.fail_status = 0

    def test_all_providers_stream_and_parse(self):
        for pid in PROVIDER_ORDER:
            with self.subTest(provider=pid):
                p = prov(pid)
                text = p.complete([{"role": "system", "content": "S"}, {"role": "user", "content": "hola", "images": []}],
                                  model="m-test", json_mode=True)
                self.assertIn('"steps"', text, f"{pid}: texto incompleto")
                plan = parse_plan(text)
                self.assertEqual(len(plan.steps), 2)
                # hay un solo POST de chat y llegó al path correcto
                posts = [r for r in mock_llm.MockLLM.requests if r["method"] == "POST"]
                self.assertEqual(len(posts), 1, f"{pid}: número de peticiones POST")
                path = posts[0]["path"]
                expect = {"openai": "/v1/chat/completions", "openrouter": "/api/v1/chat/completions",
                          "lmstudio": "/v1/chat/completions", "omniroute": "/v1/chat/completions",
                          "ollama": "/api/chat", "anthropic": "/v1/messages",
                          "gemini": "/v1beta/models/m-test:streamGenerateContent"}[pid]
                self.assertTrue(path.startswith(expect), f"{pid}: path {path} != {expect}")
                mock_llm.MockLLM.requests = []

    def test_wire_format_per_provider(self):
        p = prov("openai")
        payload = p.build_payload([{"role": "system", "content": "SYS"},
                                   {"role": "user", "content": "U", "images": []}], "m", stream=True,
                                  temperature=0.3, max_tokens=100, json_mode=True)
        self.assertEqual(payload["messages"][0], {"role": "system", "content": "SYS"})
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertTrue(payload["stream"])

        p = prov("anthropic")
        payload = p.build_payload([{"role": "system", "content": "SYS"}, {"role": "user", "content": "U"}],
                                  "m", stream=True, temperature=0.3, max_tokens=100, json_mode=True)
        self.assertEqual(payload["system"], "SYS")
        self.assertNotIn("response_format", payload)
        self.assertEqual(payload["max_tokens"], 100)

        p = prov("gemini")
        payload = p.build_payload([{"role": "system", "content": "SYS"}, {"role": "user", "content": "U"},
                                  {"role": "assistant", "content": "A"}], "m", stream=True,
                                 temperature=0.3, max_tokens=100, json_mode=True)
        self.assertEqual(payload["systemInstruction"]["parts"][0]["text"], "SYS")
        self.assertEqual([c["role"] for c in payload["contents"]], ["user", "model"])
        self.assertEqual(payload["generationConfig"]["responseMimeType"], "application/json")

        p = prov("ollama")
        payload = p.build_payload([{"role": "user", "content": "U"}], "m", stream=True,
                                  temperature=0.3, max_tokens=100, json_mode=True)
        self.assertEqual(payload["format"], "json")
        self.assertEqual(payload["options"]["num_predict"], 100)
        self.assertNotIn("temperature", payload)  # va en options

        p = prov("lmstudio")
        payload = p.build_payload([{"role": "user", "content": "U"}], "m", stream=True,
                                  temperature=0.3, max_tokens=100, json_mode=True)
        self.assertNotIn("response_format", payload)  # locales: json_mode no soportado

    def test_auth_headers(self):
        cases = {
            "openai": ("authorization", "Bearer k-test"),
            "openrouter": ("authorization", "Bearer k-test"),
            "anthropic": ("x-api-key", "k-test"),
            "gemini": ("x-goog-api-key", "k-test"),
        }
        for pid, (hdr, val) in cases.items():
            p = prov(pid)
            got = {k.lower(): v for k, v in p.headers().items()}
            self.assertEqual(got.get(hdr), val, pid)
        self.assertEqual(prov("openrouter").extra_headers().get("X-Title"), "AI Image Agent")
        for local in ("ollama", "lmstudio", "omniroute"):
            self.assertNotIn("Authorization", prov(local, api_key="").headers(), local)

    def test_missing_key_raises(self):
        os.environ.pop("OPENAI_API_KEY", None)
        self.addCleanup(os.environ.__setitem__, "OPENAI_API_KEY", "sk-test")
        p = prov("openai", api_key="")
        with self.assertRaises(ProviderError) as ctx:
            p.complete([{"role": "user", "content": "x", "images": []}], model="m")
        self.assertIn("API key", str(ctx.exception))

    def test_models_endpoints(self):
        for pid, first in (("openai", "gpt-4.1-mini"), ("ollama", "qwen2.5-coder:7b"),
                           ("gemini", "gemini-2.5-flash"), ("anthropic", "claude-sonnet-4.5")):
            with self.subTest(pid):
                models = prov(pid).list_models()
                self.assertIn(first, [m.id for m in models])
        m = prov("ollama").list_models()
        self.assertIn("4.7 GB", m[0].label)  # tamaño legible en el combobox

    def test_fallback_when_endpoint_down(self):
        p = prov("omniroute", base_url="http://127.0.0.1:1/v1")
        models, note = p.list_models_or_fallback()
        self.assertTrue(models)
        self.assertIn("sugerida", note)
        self.assertIn("auto", [m.id for m in models])

    def test_http_error_surfaces(self):
        mock_llm.MockLLM.fail_status = 401
        mock_llm.MockLLM.plan = mock_llm.PLAN_OK
        with self.assertRaises((net.NetError, ProviderError)) as ctx:
            prov("openai").complete([{"role": "user", "content": "x", "images": []}], model="m")
        self.assertIn("HTTP 401", str(ctx.exception))
        self.assertIn("fallo simulado", str(ctx.exception))
        mock_llm.MockLLM.fail_status = 0

    def test_vision_payloads(self):
        with tempfile.TemporaryDirectory() as d:
            png = Path(d) / "foto.png"
            png.write_bytes(base64_png())
            for pid, probe in (
                ("openai", lambda pl: pl["messages"][0]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")),
                ("anthropic", lambda pl: pl["messages"][0]["content"][0]["source"]["type"] == "base64"),
                ("gemini", lambda pl: "inline_data" in pl["contents"][0]["parts"][1]),
                ("ollama", lambda pl: len(pl["messages"][0]["images"]) == 1),
            ):
                with self.subTest(pid):
                    p = prov(pid)
                    pl = p.build_payload([{"role": "user", "content": "mira", "images": [str(png)]}],
                                         "m", stream=False, temperature=0.1, max_tokens=10, json_mode=False)
                    self.assertTrue(probe(pl), f"{pid}: imagen no incluida")

    def test_ping(self):
        msg = prov("ollama").ping()
        self.assertIn("OK", msg)

    def test_base_url_normalization(self):
        self.assertEqual(openai_style_base("https://api.openai.com"), "https://api.openai.com/v1")
        self.assertEqual(openai_style_base("https://api.openai.com/v1/"), "https://api.openai.com/v1")
        self.assertEqual(openai_style_base("https://gw.local/api"), "https://gw.local/api/v1")
        self.assertEqual(openai_style_base("https://openrouter.ai/api/v1"), "https://openrouter.ai/api/v1")
        self.assertEqual(prov("openai", base_url=f"{BASE}").base_url, f"{BASE}/v1")


def base64_png() -> bytes:
    import base64

    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg=="
    )


# --------------------------------------------------------------------------


class PlanParsingTest(unittest.TestCase):
    def test_plain_json(self):
        plan = parse_plan(json.dumps(mock_llm.PLAN_OK))
        self.assertEqual(len(plan.steps), 2)
        self.assertEqual(plan.steps[1].app, "gimp")
        self.assertEqual(plan.steps[0].kind, "svg")

    def test_fenced_and_prose(self):
        txt = "Claro, aquí tienes:\n\n```json\n" + json.dumps(mock_llm.PLAN_OK) + "\n```\n\n¿Quieres que ajuste colores?"
        plan = parse_plan(txt)
        self.assertEqual(len(plan.steps), 2)

    def test_truncated_json(self):
        txt = json.dumps(mock_llm.PLAN_OK)
        plan = parse_plan(txt[: len(txt) - 25])
        self.assertGreaterEqual(len(plan.steps), 1)

    def test_trailing_commas_and_single_steps(self):
        messy = '{"summary": "s", "steps": [{"app":"inkscape","kind":"svg","code":"<svg xmlns=\\"http://www.w3.org/2000/svg\\"/>","output":"a.svg",}],}'
        plan = parse_plan(messy)
        self.assertEqual(plan.steps[0].output, "a.svg")

    def test_kind_synonyms_and_guessing(self):
        ok = {"summary": "x", "steps": [
            {"app": "gimp", "kind": "scheme", "code": "(define (f) (gimp-image-new 1 1 0))", "output": "o.png"},
            {"app": "inkscape", "kind": "python", "code": "import xml.etree.ElementTree as ET\nprint(1)", "output": "o.svg"},
            {"app": "inkscape", "kind": "weirdo", "code": "<?xml version=\"1.0\"?><svg xmlns=\"http://www.w3.org/2000/svg\"/>", "output": "v.svg"},
        ]}
        plan = parse_plan(json.dumps(ok))
        self.assertEqual([s.kind for s in plan.steps], ["script-fu", "python-svg", "svg"])
        self.assertEqual(plan.steps[0].app, "gimp")

    def test_bad_output_names_sanitized(self):
        bad = {"summary": "x", "steps": [{"app": "inkscape", "kind": "svg", "code": "<svg xmlns=\"http://www.w3.org/2000/svg\"/>",
                                          "output": "../../etc/passwd"}]}
        plan = parse_plan(json.dumps(bad))
        self.assertNotIn("/", plan.steps[0].output)
        self.assertNotIn("..", plan.steps[0].output)

    def test_gimp_quit_stripped_and_collision_warning(self):
        bad = {"summary": "x", "steps": [
            {"app": "gimp", "kind": "script-fu", "code": "(begin (gimp-quit 0) (file-png-save))", "output": "a.png", "input": "a.png"},
            {"app": "gimp", "kind": "script-fu", "code": "(define (z) 1)", "output": "a.png"},
        ]}
        plan = parse_plan(json.dumps(bad))
        self.assertNotIn("gimp-quit", plan.steps[0].code)
        self.assertTrue(any("sobreescribe" in w for w in plan.warnings), plan.warnings)
        self.assertTrue(any("input == output" in w for w in plan.warnings), plan.warnings)

    def test_unsafe_tokens_detected(self):
        bad = {"summary": "x", "steps": [{"app": "gimp", "kind": "script-fu",
                                          "code": "(begin (gimp-image-new 1 1 0)) ; import subprocess is here", "output": "a.png"}]}
        plan = parse_plan(json.dumps(bad))
        self.assertIn("subprocess", security_scan(plan.steps[0]))  # 'subprocess' debe bloquearse
        step = Step(app="gimp", kind="script-fu", code="os.system('rm -rf /')", output="a.png")
        self.assertIn("os.system", security_scan(step))
        self.assertEqual(security_scan(Step(kind="svg", code="<svg/>import subprocess")), [])

    def test_empty_steps_is_valid_but_warns(self):
        plan = parse_plan('{"summary":"no puedo","steps":[],"explanation":"falta el archivo"}')
        self.assertEqual(plan.steps, [])
        self.assertTrue(any("no propuso pasos" in w for w in plan.warnings))

    def test_garbage_raises(self):
        with self.assertRaises(ValueError):
            parse_plan("Lo siento, no puedo generar ese archivo.")

    def test_workspace_files_become_write_steps(self):
        data = dict(mock_llm.PLAN_OK)
        data["workspace_files"] = [{"name": "base.svg", "content": "<svg xmlns=\"http://www.w3.org/2000/svg\"/>"}]
        plan = parse_plan(json.dumps(data))
        self.assertEqual(plan.steps[0].kind, "file")
        self.assertEqual(plan.steps[0].output, "base.svg")

    def test_render_and_roundtrip(self):
        plan = parse_plan(json.dumps(mock_llm.PLAN_OK))
        txt = render_plan(plan)
        self.assertIn("PLAN", txt)
        again = parse_plan(plan_to_json(plan))
        self.assertEqual([s.kind for s in again.steps], [s.kind for s in plan.steps])
        self.assertEqual(again.steps[1].code, plan.steps[1].code)

    def test_prompt_contract(self):
        sysp = prompts.build_system_prompt()
        self.assertIn('"steps"', sysp)
        self.assertIn("INKSCAPE", sysp)
        msgs = prompts.build_messages("haz un logo", mode="crear", apps=["inkscape"], workspace="/tmp/w",
                                      history=[{"role": "user", "content": "prev"},
                                               {"role": "assistant", "content": "{}"},
                                               {"role": "tool", "content": "ignorado"}])
        self.assertEqual([m["role"] for m in msgs], ["system", "user", "assistant", "user"])
        self.assertIn("haz un logo", msgs[-1]["content"])
        self.assertIn("modo", msgs[-1]["content"].lower())


# --------------------------------------------------------------------------
class RunnerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="aia-tools-")
        cls.bindir = Path(cls.tmp) / "bin"
        write_stubs(cls.bindir)
        cls._oldpath = os.environ["PATH"]
        os.environ["PATH"] = str(cls.bindir) + os.pathsep + cls._oldpath
        # Aísla la prueba de un Inkscape/GIMP reales instalados en la máquina
        cls._oldhints = (os.environ.get("AIA_INKSCAPE"), os.environ.get("AIA_GIMP"))
        os.environ["AIA_INKSCAPE"] = str(cls.bindir / "inkscape")
        os.environ["AIA_GIMP"] = str(cls.bindir / ("gimp.bat" if os.name == "nt" else "gimp"))
        cls.ws = Path(cls.tmp) / "ws"
        cls.ws.mkdir(parents=True, exist_ok=True)
        cls.tc = discover()

    @classmethod
    def tearDownClass(cls):
        os.environ["PATH"] = cls._oldpath
        for k, v in zip(("AIA_INKSCAPE", "AIA_GIMP"), cls._oldhints):
            if v:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_discovery_finds_stubs(self):
        self.assertTrue(self.tc.inkscape_ok, self.tc.summary())
        self.assertTrue(self.tc.gimp_ok, self.tc.summary())
        self.assertIn("mock", self.tc.inkscape_ver)
        self.assertIn("2.10", self.tc.gimp_ver)
        self.assertTrue(self.tc.python, "Python del sistema no detectado")

    def test_svg_step_writes_and_previews(self):
        plan = parse_plan(json.dumps(mock_llm.PLAN_OK))
        res = run_plan(plan, self.ws, self.tc, timeout=60)
        self.assertEqual(len(res), 2, [r.error for r in res])
        self.assertTrue(res[0].ok, res[0].error)
        svg = self.ws / "logo.svg"
        self.assertTrue(svg.is_file())
        body = svg.read_text(encoding="utf-8")
        self.assertIn("<circle", body)
        self.assertTrue(body.lstrip().startswith("<?xml"))
        previews = [f for f in res[0].files if f.endswith(".preview.png")]
        self.assertTrue(previews, "no se exportó previsualización")
        # y el paso de GIMP corrió de verdad con el stub
        self.assertTrue(res[1].ok, res[1].error + "|" + res[1].stderr)
        self.assertTrue((self.ws / "logo.png").is_file())
        self.assertLess(res[1].duration, 12.0,
                        "el runner no mató al proceso colgado tras ver la salida")
        self.assertIn("_ai_step.scm", res[1].command)
        gimp_log = (self.ws / "_gimp_calls.log").read_text(encoding="utf-8")
        self.assertIn("plug-in-script-fu-eval", gimp_log)
        self.assertIn("-b", gimp_log)

    def test_scm_gets_absolute_paths_not_markers(self):
        plan = parse_plan(json.dumps(mock_llm.PLAN_OK))
        run_plan(plan, self.ws, self.tc, timeout=60)
        scm = (self.ws / "_ai_step.scm").read_text(encoding="utf-8")
        self.assertNotIn("{INPUT}", scm)
        self.assertIn(str(self.ws), scm)

    def test_actions_need_no_input_file(self):
        plan = parse_plan(json.dumps({"summary": "s", "steps": [
            {"app": "inkscape", "kind": "inkscape-actions", "output": "align.svg",
             "code": "select-all;\nobject-align-horizontal-center;"}]}))
        res = run_plan(plan, self.ws, self.tc, timeout=60)
        self.assertTrue(res[0].ok, res[0].error)
        calls = (self.ws / "_inkscape_calls.log").read_text(encoding="utf-8")
        self.assertIn("object-align-horizontal-center", calls)
        self.assertIn("_ai_blank.svg", calls)

    def test_python_svg_step(self):
        code = ("import xml.etree.ElementTree as ET, shutil\n"
                "tree = ET.parse(INPUT)\nroot = tree.getroot()\n"
                "root.set('width', '300')\nET.ElementTree(root).write(OUTPUT)\n"
                "print('python-svg ok')\n")
        plan = parse_plan(json.dumps({"summary": "s", "steps": [
            {"app": "inkscape", "kind": "svg", "code": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"100\" height=\"100\"/>", "output": "in.svg"},
            {"app": "inkscape", "kind": "python-svg", "code": code, "input": "in.svg", "output": "edited.svg"}]}))
        res = run_plan(plan, self.ws, self.tc, timeout=60)
        self.assertTrue(res[1].ok, res[1].error + res[1].stdout + res[1].stderr)
        self.assertIn("python-svg ok", res[1].stdout)
        self.assertIn('width="300"', (self.ws / "edited.svg").read_text(encoding="utf-8"))

    def test_safe_mode_skips_code(self):
        plan = parse_plan(json.dumps(mock_llm.PLAN_OK))
        res = run_plan(plan, self.ws, self.tc, timeout=30, safe_mode=True)
        self.assertTrue(res[0].ok)          # escribir SVG sigue permitido
        self.assertFalse(res[1].ok)         # gimp no se ejecuta
        self.assertIn("Modo seguro", res[1].skipped)

    def test_unsafe_code_blocked(self):
        plan = parse_plan(json.dumps({"summary": "s", "steps": [
            {"app": "inkscape", "kind": "python-svg", "input": "", "output": "x.svg",
             "code": "import subprocess\nsubprocess.run(['ls'])\n"}]}))
        res = run_plan(plan, self.ws, self.tc, timeout=30)
        self.assertIn("Bloqueado por seguridad", res[0].error)
        res2 = run_plan(plan, self.ws, self.tc, timeout=30, allow_unsafe=True)
        self.assertNotIn("Bloqueado", res2[0].error)

    def test_gimp_failure_is_reported(self):
        bad = {"summary": "s", "steps": [{"app": "gimp", "kind": "script-fu", "output": "never.png",
                                          "code": "; SIMULA_ERROR\n"}]}
        res = run_plan(parse_plan(json.dumps(bad)), self.ws, self.tc, timeout=30)
        self.assertFalse(res[0].ok)
        self.assertIn("procedure Error", res[0].stderr)
        self.assertIn("No se generó never.png", res[0].error)

    def test_el_modelo_no_puede_fijar_la_salida(self):
        """`export-filename`/`export-type` como acción: se ignoran y lo manda el paso."""
        (self.ws / "keep2.svg").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"/>', encoding="utf-8")
        plan = parse_plan(json.dumps({"summary": "s", "steps": [
            {"app": "inkscape", "kind": "inkscape-actions", "input": "keep2.svg", "output": "keep2.png",
             "code": "export-area-page;\nexport-type:pdf;\nexport-filename:/etc/pwn.svg;\n"}]}))
        logs = []
        res = run_step(plan.steps[0], self.ws, self.tc, timeout=30, export_preview=False,
                       log=lambda m: logs.append(m))
        self.assertTrue(res.ok, res.error)
        self.assertIn("lo fija el agente", "\n".join(logs), "debe avisar de las acciones ignoradas")
        self.assertNotIn("/etc/pwn", res.command, "el destino del modelo no puede ganar")
        self.assertIn("keep2.png", res.command)
        self.assertNotIn("--export-type pdf", res.command)
        self.assertIn("--export-type png", res.command)

    def test_input_output_collision_copies(self):
        src = self.ws / "keep.svg"
        src.write_text("<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"1\" height=\"1\"/>", encoding="utf-8")
        plan = parse_plan(json.dumps({"summary": "s", "steps": [
            {"app": "inkscape", "kind": "inkscape-actions", "input": "keep.svg", "output": "keep.svg",
             "code": "select-all;"}]}))
        before = src.read_text(encoding="utf-8")
        res = run_plan(plan, self.ws, self.tc, timeout=30)
        self.assertTrue(res[0].ok, res[0].error)
        calls = (self.ws / "_inkscape_calls.log").read_text(encoding="utf-8")
        self.assertIn("_ai_in_keep.svg", calls, "debe leer de una copia del original")
        self.assertTrue(res[0].backup, "debe quedar un .bak con los bytes originales")
        bak = Path(res[0].backup)
        self.assertEqual(bak.read_text(encoding="utf-8"), before, "el .bak debe tener los bytes originales")
        line = [l for l in calls.splitlines() if "_ai_in_keep.svg" in l]
        self.assertEqual(len(line), 1, "una sola llamada a Inkscape")
        self.assertIn(f"'--export-filename', '{self.ws / 'keep.svg'}'", line[0],
                      "se lee de la copia y se escribe el archivo pedido")

    def test_missing_toolchain_reports_not_crashes(self):
        tc = Toolchain()
        res = run_plan(parse_plan(json.dumps(mock_llm.PLAN_OK)), self.ws, tc, timeout=10,
                       export_preview=False)
        self.assertIn("GIMP no está disponible", res[1].error)
        self.assertTrue(res[0].ok)  # crear SVG sí funciona sin Inkscape (solo falta la preview)


# --------------------------------------------------------------------------
class AgentIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        mock_llm.MockLLM.requests = []
        mock_llm.MockLLM.plan = dict(mock_llm.PLAN_OK)
        mock_llm.MockLLM.raw_response = None
        self.tmp = tempfile.mkdtemp(prefix="aia-agent-")
        self.bindir = Path(self.tmp) / "bin"
        write_stubs(self.bindir)
        self._oldpath = os.environ["PATH"]
        os.environ["PATH"] = str(self.bindir) + os.pathsep + self._oldpath
        self._oldhints = (os.environ.get("AIA_INKSCAPE"), os.environ.get("AIA_GIMP"))
        os.environ["AIA_INKSCAPE"] = str(self.bindir / "inkscape")
        os.environ["AIA_GIMP"] = str(self.bindir / ("gimp.bat" if os.name == "nt" else "gimp"))
        self.cfg = Config()
        self.cfg.workspace = str(Path(self.tmp) / "ws")
        self.cfg.provider = "openai"
        self.cfg.set_provider("openai", base_url=f"{BASE}/v1", api_key="sk-test", model="gpt-4.1-mini")
        self.cfg.timeout = 30.0
        self.cfg.auto_run = True
        self.cfg.safe_mode = False   # aquí sí se ejecutan los stubs de Inkscape/GIMP
        self.cfg.repair_rounds = 1

    def tearDown(self) -> None:
        os.environ["PATH"] = self._oldpath
        for k, v in zip(("AIA_INKSCAPE", "AIA_GIMP"), self._oldhints):
            if v:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_full_flow_creates_files(self):
        agent = Agent(self.cfg)
        run = agent.run("crea un logo cuadrado y conviértelo a PNG", apps=["inkscape", "gimp"], mode="crear")
        self.assertFalse(run.error, run.error)
        self.assertTrue(run.ok, run.log[-6:])
        self.assertEqual(len(run.files()), 3, run.files())
        self.assertTrue(any(f.endswith("logo.png") for f in run.files()))
        posts = [r for r in mock_llm.MockLLM.requests if r["method"] == "POST"]
        self.assertEqual(len(posts), 1)
        sent = json.dumps(posts[0]["body"])
        self.assertIn("crea un logo cuadrado", sent)
        self.assertIn("RUN-NONINTERACTIVE", mock_llm.PLAN_OK["steps"][1]["code"])

    def test_repair_round_after_failure(self):
        mock_llm.MockLLM.plan = {"summary": "mal", "steps": [
            {"app": "gimp", "kind": "script-fu", "output": "never.png", "code": "; SIMULA_ERROR\n"}]}
        agent = Agent(self.cfg)
        run = agent.run("arregla esto", apps=["gimp"], mode="corregir")
        posts = [r for r in mock_llm.MockLLM.requests if r["method"] == "POST"]
        self.assertEqual(len(posts), 2, "no se pidió una segunda vuelta al modelo")
        second = json.dumps(posts[1]["body"])
        self.assertIn("TU PLAN ANTERIOR FALL", second)
        self.assertIn("SIMULA_ERROR", second)          # el plan fallido viaja al modelo
        self.assertIn("procedure Error", second)       # y también el error real de GIMP
        self.assertEqual(run.rounds, 2)
        self.assertFalse(run.ok)

    def test_no_execute_when_auto_run_off(self):
        self.cfg.auto_run = False
        agent = Agent(self.cfg)
        run = agent.run("haz algo", apps=["inkscape"])
        self.assertEqual(run.results, [])
        self.assertTrue(run.plan is not None)
        self.assertFalse((Path(self.cfg.ws()) / "logo.svg").exists())  # nada ejecutado
        self.assertFalse([f for f in Path(self.cfg.ws()).glob("_ai_*")])

    def test_local_provider_selection_via_cli(self):
        cfg = Config()
        cfg.provider = "ollama"
        cfg.set_provider("ollama", base_url=BASE, api_key="", model="qwen2.5-coder:7b")
        agent = Agent(cfg)
        text = agent.ask([{"role": "user", "content": "hola", "images": []}], model="qwen2.5-coder:7b")
        self.assertIn('"steps"', text)
        rec = mock_llm.MockLLM.last("/api/chat")
        self.assertEqual(rec["body"]["model"], "qwen2.5-coder:7b")


# --------------------------------------------------------------------------
class CliTest(unittest.TestCase):
    def test_cli_headless_run(self):
        mock_llm.MockLLM.requests = []
        mock_llm.MockLLM.plan = dict(mock_llm.PLAN_OK)
        mock_llm.MockLLM.raw_response = None
        tmp = tempfile.mkdtemp(prefix="aia-cli-")
        bindir = Path(tmp) / "bin"
        write_stubs(bindir)
        env = dict(os.environ)
        env["PATH"] = str(bindir) + os.pathsep + env["PATH"]
        env["OPENAI_API_KEY"] = "sk-test"
        env["PYTHONPATH"] = str(ROOT)
        env["AIA_INKSCAPE"] = str(bindir / "inkscape")
        env["AIA_GIMP"] = str(bindir / ("gimp.bat" if os.name == "nt" else "gimp"))
        try:
            base = mock_llm.MockLLM.port
            proc = subprocess.run(
                [sys.executable, "-m", "aiimage_agent", "--cli", "--json", "--provider", "openai",
                 "--base-url", f"http://127.0.0.1:{base}/v1", "--model", "gpt-4.1-mini",
                 "-p", "logo para la prueba CLI", "--app", "inkscape", "--app", "gimp",
                 "--execute", "-w", str(Path(tmp) / "ws")],
                capture_output=True, text=True, timeout=180, env=env, cwd=str(ROOT))
            self.assertEqual(proc.returncode, 0, proc.stdout[-3000:] + "\n" + proc.stderr[-3000:])
            out = json.loads(proc.stdout)
            self.assertTrue(out["ok"], out["log"][-6:])
            self.assertFalse(out["error"])
            self.assertEqual(len(out["files"]), 3, out["files"])
            self.assertTrue((Path(tmp) / "ws" / "logo.png").is_file())
            self.assertTrue((Path(tmp) / "ws" / "logo.svg").is_file())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_cli_providers_and_tools_exit_clean(self):
        env = dict(os.environ, PYTHONPATH=str(ROOT))
        for flag in ("--providers", "--tools", "--version"):
            proc = subprocess.run([sys.executable, "-m", "aiimage_agent", flag], capture_output=True,
                                  text=True, timeout=60, env=env, cwd=str(ROOT))
            self.assertEqual(proc.returncode, 0, proc.stderr[-800:])
            self.assertTrue(proc.stdout.strip())


# --------------------------------------------------------------------------
class ImagesTest(unittest.TestCase):
    def test_png_gif_bmp_sizes(self):
        from aiimage_agent.core.images import describe, image_size, sniff, write_png

        with tempfile.TemporaryDirectory() as d:
            png = write_png(Path(d) / "a.png", 120, 80)
            self.assertEqual(image_size(png), (120, 80))
            self.assertEqual(sniff(png), "png")
            self.assertIn("120×80 px", describe(png))
            # GIF 87a
            gif = Path(d) / "b.gif"
            import struct
            gif.write_bytes(b"GIF87a" + struct.pack("<HH", 33, 44) + b"\x00" * 10)
            self.assertEqual(image_size(gif), (33, 44))
            # BMP
            bmp = Path(d) / "c.bmp"
            hdr = b"BM" + b"\x00" * 16 + struct.pack("<ii", 55, -66) + b"\x00" * 8
            bmp.write_bytes(hdr)
            self.assertEqual(image_size(bmp), (55, 66))
            # JPEG (SOF0)
            jpeg = Path(d) / "d.jpg"
            seg = b"\xff\xc0" + struct.pack(">H", 17) + b"\x08" + struct.pack(">HH", 200, 100) + b"\x03" + b"\x01" * 4
            jpeg.write_bytes(b"\xff\xd8" + seg + b"\xff\xd9")
            self.assertEqual(image_size(jpeg), (100, 200))
            # SVG y basura
            svg = Path(d) / "e.svg"
            svg.write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
            self.assertEqual(sniff(svg), "svg")
            self.assertIsNone(image_size(svg))
            junk = Path(d) / "f.png"
            junk.write_bytes(b"no soy un png")
            self.assertIsNone(image_size(junk))

    def test_prompt_gets_bitmap_dimensions(self):
        from aiimage_agent.core.images import write_png
        from aiimage_agent.core.prompts import describe_inputs

        with tempfile.TemporaryDirectory() as d:
            png = write_png(Path(d) / "foto.png", 1920, 1080)
            txt = describe_inputs([str(png)])
            self.assertIn("1920", txt)
            self.assertIn("1080", txt)
            self.assertIn("foto.png", txt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
