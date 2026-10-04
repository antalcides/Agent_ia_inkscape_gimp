#!/usr/bin/env python3
"""Lanzador con doble clic / PyInstaller. Equivale a `python -m aiimage_agent`.

    python run_agent.py                # GUI
    python run_agent.py --cli -p "…"   # consola
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from aiimage_agent.__main__ import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
