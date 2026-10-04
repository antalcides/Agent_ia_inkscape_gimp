#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# Construye el paquete .deb (Arquitectura: all) para Debian 12 (Bookworm) y 13 (Trixie).
# Uso:  bash packaging/build_deb.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="1.0.0"
NAME="inkscape-gimp-ai-agent"
BUILD="${ROOT}/packaging/_build"
PKG="${BUILD}/${NAME}_${VERSION}_all"
DIST="${ROOT}/../dist"

rm -rf "$BUILD"
mkdir -p "$PKG/DEBIAN" \
         "$PKG/usr/lib/${NAME}" \
         "$PKG/usr/bin" \
         "$PKG/usr/share/applications" \
         "$PKG/usr/share/inkscape/extensions" \
         "$PKG/usr/lib/gimp/3.0/plug-ins/agente_ia_gimp" \
         "$PKG/usr/lib/gimp/2.10/plug-ins/agente_ia_gimp" \
         "$PKG/usr/share/doc/${NAME}"

# --------------------------------------------------------------------------
# 1. Aplicacion principal en /usr/lib/<pkg>
# --------------------------------------------------------------------------
cp -r "${ROOT}/agent.py" "${ROOT}/ui" "${ROOT}/core" \
      "${ROOT}/config.example.json" "${ROOT}/README.md" \
      "$PKG/usr/lib/${NAME}/"
find "$PKG/usr/lib/${NAME}" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find "$PKG/usr/lib/${NAME}" -name "*.pyc" -delete 2>/dev/null || true

# --------------------------------------------------------------------------
# 2. Extension de Inkscape (sistema) + nucleo junto a ella
# --------------------------------------------------------------------------
cp "${ROOT}/inkscape_ext/agente_ia_inkscape.inx" \
   "${ROOT}/inkscape_ext/agente_ia_inkscape.py" \
   "$PKG/usr/share/inkscape/extensions/"
cp -r "${ROOT}/core" "$PKG/usr/share/inkscape/extensions/core"
chmod 0755 "$PKG/usr/share/inkscape/extensions/agente_ia_inkscape.py"

# --------------------------------------------------------------------------
# 3. Complemento de GIMP (sistema): 3.0 y 2.10
# --------------------------------------------------------------------------
cp "${ROOT}/gimp_plugin/agente_ia_gimp.py" \
   "$PKG/usr/lib/gimp/3.0/plug-ins/agente_ia_gimp/"
cp -r "${ROOT}/core" "$PKG/usr/lib/gimp/3.0/plug-ins/agente_ia_gimp/core"
chmod 0755 "$PKG/usr/lib/gimp/3.0/plug-ins/agente_ia_gimp/agente_ia_gimp.py"

cp "${ROOT}/gimp_plugin/agente_ia_gimp_210.py" \
   "$PKG/usr/lib/gimp/2.10/plug-ins/agente_ia_gimp/"
cp -r "${ROOT}/core" "$PKG/usr/lib/gimp/2.10/plug-ins/agente_ia_gimp/core"
chmod 0755 "$PKG/usr/lib/gimp/2.10/plug-ins/agente_ia_gimp/agente_ia_gimp_210.py"

# --------------------------------------------------------------------------
# 4. Lanzador /usr/bin/agente-ia
# --------------------------------------------------------------------------
cat > "$PKG/usr/bin/agente-ia" <<'LAUNCH'
#!/bin/sh
# Lanzador del Agente IA para Inkscape y GIMP
PYBIN=python3
command -v "$PYBIN" >/dev/null 2>&1 || PYBIN=python3.11
exec "$PYBIN" /usr/lib/inkscape-gimp-ai-agent/agent.py "$@"
LAUNCH
chmod 0755 "$PKG/usr/bin/agente-ia"

# --------------------------------------------------------------------------
# 5. Entrada de menu de escritorio
# --------------------------------------------------------------------------
cat > "$PKG/usr/share/applications/agente-ia.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Version=1.0
Name=Agente IA para Inkscape y GIMP
GenericName=Asistente de IA grafico
Comment=Crea y corrige imagenes vectoriales (SVG) y bitmaps (PNG/JPG) con IA
Exec=agente-ia
Terminal=false
Icon=applications-graphics
Categories=Graphics;2DGraphics;VectorGraphics;RasterGraphics;
Keywords=IA;AI;Inkscape;GIMP;SVG;imagen;vector;bitmap;
StartupNotify=true
DESKTOP
chmod 0644 "$PKG/usr/share/applications/agente-ia.desktop"

# --------------------------------------------------------------------------
# 6. Documentacion y copyright
# --------------------------------------------------------------------------
cp "${ROOT}/README.md" "$PKG/usr/share/doc/${NAME}/README.md"
cat > "$PKG/usr/share/doc/${NAME}/copyright" <<'COPY'
Formato: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: inkscape-gimp-ai-agent
Source: https://example.org/inkscape-gimp-ai-agent

Files: *
Copyright: 2026 Agente IA
License: MIT
COPY
gzip -9 -n -c "$PKG/usr/share/doc/${NAME}/README.md" \
     > "$PKG/usr/share/doc/${NAME}/README.md.gz"
rm -f "$PKG/usr/share/doc/${NAME}/README.md"

# --------------------------------------------------------------------------
# 7. Metadatos DEBIAN/control
# --------------------------------------------------------------------------
cat > "$PKG/DEBIAN/control" <<CONTROL
Package: ${NAME}
Version: ${VERSION}
Section: graphics
Priority: optional
Architecture: all
Depends: python3 (>= 3.11), python3-tk, python3-lxml
Recommends: inkscape, gimp
Suggests: python3-pil, python3-numpy
Installed-Size: 260
Maintainer: Agente IA <soporte@example.org>
Homepage: https://example.org/inkscape-gimp-ai-agent
Description: Agente de IA para Inkscape y GIMP
 Crea y corrige imagenes vectoriales (SVG) y bitmaps (PNG/JPG) usando el
 modelo y proveedor de IA que se elija: OpenAI, Anthropic, Google Gemini,
 OpenRouter, OmniRoute, Ollama, LM Studio o cualquier servidor compatible
 con la API de OpenAI (modelos locales o en la nube).
 .
 Incluye una interfaz grafica de escritorio con selectores de proveedor y
 modelo y un area amplia para escribir el pedido; una extension para
 Inkscape (menu Extensiones > Agente IA) y un complemento para GIMP
 (menu Filtros > IA) para las versiones 3.0 y 2.10.
 .
 El nucleo usa unicamente la biblioteca estandar de Python, por lo que
 funciona tambien dentro del interprete embebido de Inkscape y de GIMP.
CONTROL

cat > "$PKG/DEBIAN/postinst" <<'POSTINST'
#!/bin/sh
set -e
# Precompila el nucleo para acelerar el primer arranque (no es critico).
if command -v python3 >/dev/null 2>&1; then
    python3 -m compileall -q /usr/lib/inkscape-gimp-ai-agent/core >/dev/null 2>&1 || true
fi
# Actualiza la cache del menu de escritorio si esta disponible.
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q /usr/share/applications >/dev/null 2>&1 || true
fi
exit 0
POSTINST
chmod 0755 "$PKG/DEBIAN/postinst"

cat > "$PKG/DEBIAN/prerm" <<'PRERM'
#!/bin/sh
set -e
exit 0
PRERM
chmod 0755 "$PKG/DEBIAN/prerm"

# --------------------------------------------------------------------------
# 8. Construccion del .deb
# --------------------------------------------------------------------------
mkdir -p "$DIST"
dpkg-deb --build --root-owner-group "$PKG" "${DIST}/${NAME}_${VERSION}_all.deb"
echo "Paquete generado: ${DIST}/${NAME}_${VERSION}_all.deb"
