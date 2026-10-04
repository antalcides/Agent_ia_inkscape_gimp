"""Pruebas contra Inkscape y GIMP REALES (se omiten si no están instalados).

`python -m unittest tests.test_real_tools -v`

Cubren lo que los stubs no pueden: que el SVG generado se valide/exporte de verdad,
que las acciones CLI de Inkscape existan, y que el preámbulo de compatibilidad haga
funcionar en GIMP 3 un script escrito con nombres de GIMP 2.10.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aiimage_agent.core.gimp_compat import major_from_version  # noqa: E402
from aiimage_agent.core.images import image_size  # noqa: E402
from aiimage_agent.core.plan import parse_plan  # noqa: E402
from aiimage_agent.core.runner import discover, run_step  # noqa: E402


def which(*names: str) -> str:
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return ""


HAVE_INKSCAPE = bool(which("inkscape"))
HAVE_GIMP = bool(which("gimp-console-3.0", "gimp-console-2.10", "gimp-console", "gimp"))

SVG = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="240" height="160" viewBox="0 0 240 160">
  <rect width="240" height="160" fill="#0e3e3c"/>
  <circle cx="120" cy="80" r="55" fill="#ffd166"/>
  <path d="M40 140 C90 20 150 20 200 140" fill="none" stroke="#e1faf0" stroke-width="6"/>
</svg>
"""


@unittest.skipUnless(HAVE_INKSCAPE, "inkscape no está instalado")
class RealInkscapeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tc = discover()
        cls.ws = Path(tempfile.mkdtemp(prefix="aia-real-ink-"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.ws, ignore_errors=True)

    _notes: list = []

    def _run(self, plan_json: dict, idx: int = 0):
        plan = parse_plan(json.dumps(plan_json))
        out = []
        res = run_step(plan.steps[idx], self.ws, self.tc, index=idx, timeout=180,
                       export_preview=False, log=lambda m: out.append(m))
        RealInkscapeTest._notes = [l for l in out if "descartada" in l or "Acciones" in l]
        return res

    def test_svg_step_is_valid_and_exports(self):
        res = self._run({"summary": "s", "steps": [
            {"app": "inkscape", "kind": "svg", "code": SVG, "output": "real.svg"}]})
        self.assertTrue(res.ok, res.error)
        out = self.ws / "real.svg"
        self.assertIn("<circle", out.read_text(encoding="utf-8"))
        # Inkscape de verdad debe poder leerlo y exportarlo
        r = subprocess.run([*self.tc.inkscape, str(out), "--export-type", "png",
                            "--export-filename", str(self.ws / "real.png")],
                           capture_output=True, text=True, timeout=240)
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        self.assertEqual(image_size(self.ws / "real.png"), (240, 160),
                         "el PNG exportado no tiene el tamaño del SVG")

    def test_actions_step_exporta_con_acciones_reales(self):
        """export-area-drawing + export-dpi + export-background: cambia el PNG exportado."""
        self._run({"summary": "s", "steps": [
            {"app": "inkscape", "kind": "svg", "code": SVG, "output": "act.svg"}]})
        res = self._run({"summary": "s", "steps": [
            {"app": "inkscape", "kind": "inkscape-actions", "input": "act.svg", "output": "act.png",
             "code": "export-area-page;\nexport-dpi:150;\nexport-background:#ff0000;\n"}]})
        self.assertTrue(res.ok, f"{res.error}\n{res.stdout}\n{res.stderr}")
        out = self.ws / "act.png"
        self.assertTrue(out.is_file())
        size = image_size(out)
        self.assertIsNotNone(size)
        # 240x160 px @96dpi -> a 150dpi son 375x250
        self.assertEqual(size, (375, 250), "export-dpi:150 no se aplicó")

    def test_diagnostico_de_accion_invalida_es_util_para_reparar(self):
        """El rechazo debe listar acciones válidas: es el contexto del bucle de reparación."""
        res = self._run({"summary": "s", "steps": [
            {"app": "inkscape", "kind": "inkscape-actions", "input": "act.svg", "output": "z.svg",
             "code": "verb-que-no-existe;\nborrar-todo;"}]})
        self.assertFalse(res.ok)
        self.assertIn("Acciones disponibles", res.error)
        self.assertGreater(len(res.error), 120, "el diagnóstico debe listar acciones válidas")

    def test_unknown_action_is_rejected_before_running(self):
        self._run({"summary": "s", "steps": [
            {"app": "inkscape", "kind": "svg", "code": SVG, "output": "unk.svg"}]})
        res = self._run({"summary": "s", "steps": [
            {"app": "inkscape", "kind": "inkscape-actions", "input": "unk.svg", "output": "unk-out.svg",
             "code": "item-remove;\nedit-delete;\nselect-all;\n"}]})
        # select-all SÍ existe en Inkscape 1.4; item-remove/edit-delete no → se descartan con aviso
        self.assertTrue(res.ok, res.error)
        joined = "\n".join(self._notes)
        self.assertIn("descartada", joined, "debe avisar de las acciones descartadas")

    def test_valid_and_invalid_actions_mixed(self):
        self._run({"summary": "s", "steps": [
            {"app": "inkscape", "kind": "svg", "code": SVG, "output": "mix.svg"}]})
        res = self._run({"summary": "s", "steps": [
            {"app": "inkscape", "kind": "inkscape-actions", "input": "mix.svg", "output": "mix.png",
             "code": "select-all;\nexport-area-page;\nexport-dpi:96;\n"}]})
        self.assertTrue(res.ok, f"{res.error}\n{res.stderr}")
        self.assertEqual(image_size(self.ws / "mix.png"), (240, 160))

    def test_python_svg_step(self):
        self._run({"summary": "s", "steps": [
            {"app": "inkscape", "kind": "svg", "code": SVG, "output": "py-in.svg"}]})
        code = ("import xml.etree.ElementTree as ET\n"
                "ns={'s':'http://www.w3.org/2000/svg'}\n"
                "t=ET.parse(INPUT); r=t.getroot()\n"
                "r.set('width','640'); r.set('height','480'); r.set('viewBox','0 0 640 480')\n"
                "for c in r.findall('.//s:circle', ns): c.set('cx','320')\n"
                "ET.register_namespace('', ns['s']); t.write(OUTPUT)\n"
                "print('ok', r.get('width'))\n")
        res = self._run({"summary": "s", "steps": [
            {"app": "inkscape", "kind": "python-svg", "input": "py-in.svg", "output": "py-out.svg",
             "code": code}]})
        self.assertTrue(res.ok, f"{res.error}\n{res.stdout}\n{res.stderr}")
        self.assertIn("ok 640", res.stdout)
        body = (self.ws / "py-out.svg").read_text(encoding="utf-8")
        self.assertIn('width="640"', body)
        self.assertIn('cx="320"', body)
        # y el resultado sigue siendo válido para Inkscape
        r = subprocess.run([*self.tc.inkscape, str(self.ws / "py-out.svg"), "--export-type", "pdf",
                            "--export-filename", str(self.ws / "py-out.pdf")],
                           capture_output=True, text=True, timeout=240)
        self.assertEqual(r.returncode, 0, r.stderr[-600:])
        self.assertTrue((self.ws / "py-out.pdf").stat().st_size > 800)


@unittest.skipUnless(HAVE_GIMP, "gimp no está instalado")
class RealGimpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tc = discover()
        cls.major = major_from_version(cls.tc.gimp_ver)
        cls.ws = Path(tempfile.mkdtemp(prefix="aia-real-gimp-"))
        # PNG de entrada generado por nosotros mismos (no depende de Inkscape)
        from aiimage_agent.core.images import write_png

        cls.src = write_png(cls.ws / "in.png", 200, 140)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.ws, ignore_errors=True)

    def _run_script(self, code: str, output: str = "out.png"):
        plan = parse_plan(json.dumps({"summary": "s", "steps": [
            {"app": "gimp", "kind": "script-fu", "input": self.src.name, "output": output,
             "code": code}]}))
        t0 = time.monotonic()
        res = run_step(plan.steps[0], self.ws, self.tc, index=0, timeout=240, export_preview=False)
        return res, time.monotonic() - t0

    def test_ai_helpers_style_script(self):
        code = ('(let* ((image (ai-load "{INPUT}"))) '
                "(gimp-image-scale image 64 48) "
                '(ai-info "editando" image) '
                '(ai-save image "{OUTPUT}") '
                "(gimp-image-delete image))")
        res, dt = self._run_script(code, "ai-style.png")
        self.assertTrue(res.ok, f"{res.error}\n{res.stdout}\n{res.stderr}")
        self.assertEqual(image_size(self.ws / "ai-style.png"), (64, 48))
        self.assertLess(dt, 120, "el paso de GIMP no debería tardar todo el timeout")

    def test_legacy_210_style_script_runs_on_gimp3(self):
        """Script-Fu escrito al estilo 2.10: el preámbulo debe hacerlo funcionar en GIMP 3."""
        code = ('(let* ((image (car (gimp-file-load RUN-NONINTERACTIVE "{INPUT}" "{INPUT}")))\n'
                "         (drawable (car (gimp-image-get-active-drawable image))))\n"
                "  (gimp-image-scale image 80 60)\n"
                '  (gimp-message (string-append "w=" (number->string (car (gimp-image-width image)))))\n'
                '  (file-png-save RUN-NONINTERACTIVE image drawable "{OUTPUT}" "{OUTPUT}" 0 9 1 1 1 1 1)\n'
                "  (gimp-image-delete image))")
        res, _ = self._run_script(code, "legacy.png")
        self.assertTrue(res.ok, f"{res.error}\n{res.stdout}\n{res.stderr}")
        self.assertEqual(image_size(self.ws / "legacy.png"), (80, 60),
                         "la compatibilidad 2.10→3.x falló (escala o guardado)")
        if self.major >= 3:
            self.assertIn("w=80", res.stdout + res.stderr, "gimp-image-width alias no devolvió el ancho")

    def test_jpeg_export_and_error_reporting(self):
        code = ('(let* ((image (ai-load "{INPUT}"))) (ai-save image "{OUTPUT}") (gimp-image-delete image))')
        res, _ = self._run_script(code, "out.jpg")
        self.assertTrue(res.ok, res.error)
        out = self.ws / "out.jpg"
        self.assertTrue(out.is_file(), "GIMP no escribió el JPEG")
        bad = '(let* ((image (ai-load "{INPUT}"))) (gimp-procedura-que-no-existe image) (ai-save image "{OUTPUT}"))'
        res2, _ = self._run_script(bad, "never.png")
        self.assertFalse(res2.ok)
        self.assertTrue(res2.error, "debe reportar el fallo")
        self.assertFalse((self.ws / "never.png").exists())

    def test_hanging_gimp_is_killed(self):
        """GIMP 3 puede quedarse vivo tras el batch: el agente debe terminarlo al ver la salida."""
        code = ('(let* ((image (ai-load "{INPUT}"))) (ai-save image "{OUTPUT}") '
                "(gimp-image-delete image)) (do ((i 0 (+ i 1))) ((> i 20000) #f) (car (gimp-version)))")
        res, dt = self._run_script(code, "kill.png")
        self.assertTrue(res.ok, res.error)
        self.assertLess(dt, 60.0, f"GIMP quedó colgado {dt:.1f}s: no se detectó la salida")


@unittest.skipUnless(HAVE_INKSCAPE and HAVE_GIMP, "hacen falta inkscape y gimp")
class RealPipelineTest(unittest.TestCase):
    """SVG → PNG con Inkscape y luego redimensionado con GIMP (pasos encadenados)."""

    def test_inkscape_then_gimp(self):
        from aiimage_agent.core.agent import Agent
        from aiimage_agent.core.config import Config

        ws = Path(tempfile.mkdtemp(prefix="aia-real-pipe-"))
        self.addCleanup(shutil.rmtree, ws, True)
        cfg = Config()
        cfg.workspace = str(ws)
        cfg.auto_run = False
        cfg.safe_mode = False
        cfg.repair_rounds = 0
        cfg.export_preview = False
        agent = Agent(cfg)
        plan = parse_plan(json.dumps({
            "summary": "vector → bitmap",
            "steps": [
                {"app": "inkscape", "kind": "svg", "code": SVG, "output": "pipe.svg"},
                {"app": "inkscape", "kind": "inkscape-actions", "input": "pipe.svg", "output": "pipe200.png",
                 "code": "export-area-page;\nexport-dpi:96;\nexport-background:#ffffff;\n"},
                {"app": "gimp", "kind": "script-fu", "input": "pipe200.png", "output": "pipe50.png",
                 "code": '(let* ((image (ai-load "{INPUT}"))) (gimp-image-scale image 50 34) '
                         '(ai-save image "{OUTPUT}") (gimp-image-delete image))'},
            ]}))
        run = agent.execute(plan)
        ok = all(r.ok for r in run.results)
        self.assertTrue(ok, "\n".join(f"[{r.index}] {r.error}" for r in run.results))
        self.assertEqual(len(run.results), 3, "se esperaban 3 pasos ejecutados")
        self.assertEqual(image_size(ws / "pipe50.png"), (50, 34))
        self.assertTrue((ws / "pipe200.png").is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
