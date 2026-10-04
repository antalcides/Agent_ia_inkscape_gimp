#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lanzador del agente de IA para Inkscape y GIMP."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ui.app import main  # noqa: E402

if __name__ == "__main__":
    main()
