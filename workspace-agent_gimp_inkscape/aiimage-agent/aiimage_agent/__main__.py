"""Punto de entrada: `python -m aiimage_agent` abre la GUI; `--cli` abre la consola."""

from __future__ import annotations

import sys


def _bootstrap() -> None:
    if sys.version_info < (3, 9):  # pragma: no cover
        sys.exit("AI Image Agent requiere Python 3.9 o superior (tienes %s)." % sys.version.split()[0])
    # En Windows, Tk necesita que stdout no falle con emojis/acentos.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            pass


def main() -> int:
    _bootstrap()
    from .cli import main as cli_main

    return cli_main()


if __name__ == "__main__":
    raise SystemExit(main())
