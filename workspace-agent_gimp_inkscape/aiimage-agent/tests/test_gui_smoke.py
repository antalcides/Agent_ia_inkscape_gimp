"""Prueba de GUI real: lanza `scripts/gui_probe.py` bajo Xvfb y comprueba sus aserciones.

Cada escenario corre en su **propio proceso** (varios `Tk()` en un mismo proceso abortan).
Se salta automáticamente si no hay DISPLAY ni Xvfb (así pasa en Windows y en CI sin cabeza).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "scripts" / "gui_probe.py"

SCENARIOS = ("full_flow", "buttons", "error_dialog", "safe_mode")


def _xvfb_prefix() -> list[str] | None:
    """`xvfb-run -a` si no hay DISPLAY y Xvfb está instalado."""
    if os.environ.get("DISPLAY"):
        return []
    xvfb = shutil.which("xvfb-run")
    return [xvfb, "-a", "-s", "-screen 0 1500x980x24"] if xvfb else None


@unittest.skipIf(PROBE.exists() is False, "falta scripts/gui_probe.py")
class GuiProbeTest(unittest.TestCase):
    """Ejecuta la app Tk completa contra el LLM simulado y las herramientas simuladas."""

    @classmethod
    def setUpClass(cls):
        cls.prefix = _xvfb_prefix()
        if cls.prefix is None:
            raise unittest.SkipTest("sin DISPLAY y sin Xvfb: prueba de GUI no aplicable")
        cls.tmp = tempfile.mkdtemp(prefix="aia-guitest-")
        from tests import tool_stubs

        cls.bindir = Path(cls.tmp) / "bin"
        tool_stubs.write_stubs(cls.bindir)
        env = dict(os.environ)
        env["PATH"] = str(cls.bindir) + os.pathsep + env["PATH"]
        env["PYTHONPATH"] = str(ROOT)
        env["AIA_INKSCAPE"] = str(cls.bindir / "inkscape")
        env["AIA_GIMP"] = str(cls.bindir / ("gimp.bat" if os.name == "nt" else "gimp"))
        env["PYTHONUTF8"] = "1"
        env["OPENAI_API_KEY"] = ""
        cls.env = env

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _run_scenario(self, name: str, screenshot: Path | None = None) -> str:
        # la sonda crea su mundo bajo AIA_GUI_TMP (stubs, workspace, config)
        env = dict(self.env)
        env["AIA_GUI_TMP"] = str(Path(self.tmp) / name)
        env["HOME"] = self.tmp
        env["USERPROFILE"] = self.tmp
        if screenshot is not None:
            env["AIA_SCREENSHOT"] = str(screenshot)
        proc = subprocess.run(
            self.prefix + [sys.executable, str(PROBE), name],
            env=env, cwd=str(ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=180,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        self.assertEqual(proc.returncode, 0, f"[{name}] → {out[-2500:]}")
        self.assertIn("GUI_PROBE_OK", out, f"[{name}] → {out[-2500:]}")
        self.assertIn("FAILS=0", out, f"[{name}] → {out[-2500:]}")
        return out

    def test_01_buttons(self):
        out = self._run_scenario("buttons")
        n = int(out.split("PROBES=")[1].split()[0])
        self.assertGreaterEqual(n, 12, "se esperaban ≥12 comprobaciones de widgets")

    def test_02_safe_mode(self):
        out = self._run_scenario("safe_mode")
        self.assertIn("PROBES=4", out)
        ws = Path(self.tmp) / "safe_mode" / "ws"
        self.assertTrue((ws / "logo.svg").exists(), "el modo seguro debe escribir el SVG")
        self.assertFalse((ws / "logo.png").exists(), "en modo seguro NO se ejecuta Inkscape")

    def test_03_error_dialog(self):
        self.assertIn("PROBES=3", self._run_scenario("error_dialog"))

    def test_04_full_flow(self):
        shot = Path(self.tmp) / "screenshot.png"
        out = self._run_scenario("full_flow", screenshot=shot)
        self.assertIn("PROBES=24", out)
        ws = Path(self.tmp) / "full_flow" / "ws"
        self.assertTrue((ws / "logo.svg").exists(), "el plan debe haber creado logo.svg")
        self.assertTrue((ws / "logo.png").exists(), "el export simulado debe existir")
        self.assertTrue((ws / "logo-editado.svg").exists(), "el plan editado a mano debe crear su salida")
        self.assertTrue((ws / "_ai_step.scm").exists(), "debe escribir el script de GIMP")
        calls = (ws / "_inkscape_calls.log").read_text(encoding="utf-8")
        self.assertIn("--export-type", calls, "el export debe ir por la CLI de Inkscape")
        self.assertIn("logo.preview.png", calls, "debe generar la previsualización")
        # icono: la app debe encontrar el .ico incluso desde un directorio prestado
        self.assertTrue((ROOT / "assets" / "icon.ico").exists(), "falta assets/icon.ico")
        if shot.exists():
            self.assertGreater(shot.stat().st_size, 4000, "la captura quedó vacía")


if __name__ == "__main__":
    unittest.main(verbosity=2)
