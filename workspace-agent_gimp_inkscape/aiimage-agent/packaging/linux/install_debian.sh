#!/usr/bin/env bash
# Instalar AI Image Agent en Debian 12 (bookworm) o Debian 13 (trixie).
#
#   sudo ./packaging/linux/install_debian.sh            # sistema + lanzador + menú
#   ./packaging/linux/install_debian.sh --user          # sin root (~/.local)
#   ./packaging/linux/install_debian.sh --deps          # solo apt: python3-tk inkscape gimp
#   ./packaging/linux/install_debian.sh --pyinstaller   # además genera dist/AI-Image-Agent (binario Linux)
#   ./packaging/linux/install_debian.sh --test           # prueba de humo de la GUI (necesita X)
#
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MODE="system"; DO_DEPS=0; DO_PYI=0; DO_TEST=0
while [ $# -gt 0 ]; do
  case "$1" in
    --user) MODE="user" ;;
    --system) MODE="system" ;;
    --deps) DO_DEPS=1 ;;
    --pyinstaller) DO_PYI=1 ;;
    --test) DO_TEST=1 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "opción desconocida: $1" >&2; exit 2 ;;
  esac
  shift
done

say() { printf '\n== %s ==\n' "$*"; }

if [ "$DO_DEPS" = 1 ]; then
  say "dependencias del sistema (apt)"
  apt-get update
  # python3-tk: GUI · inkscape: vectores · gimp: bits (gimp-console para batch)
  # xdotool/imagemagick solo hacen falta para --test
  apt-get install -y --no-install-recommends python3-tk python3-pip inkscape gimp gimp-data \
    xdg-utils shared-mime-info
  echo "instalado: $(python3 -c 'import tkinter;print("Tk",tkinter.TkVersion)')"
  echo "inkscape: $(command -v inkscape || echo no) · gimp: $(command -v gimp || echo no)"
  [ "$MODE" = "system" ] && [ "$DO_PYI" = 0 ] && exit 0
fi

PYV="$(python3 -c 'import sys;print("%d%02d"%sys.version_info[:2])')"
if [ "$PYV" -lt 39 ]; then echo "necesitas Python 3.9+ (tienes $(python3 -V))" >&2; exit 1; fi

if [ "$MODE" = "system" ]; then
  DEST_LIB="/usr/local/lib/ai-image-agent"
  DEST_BIN="/usr/local/bin/ai-image-agent"
  DEST_SHARE="/usr/local/share"
else
  DEST_LIB="$HOME/.local/lib/ai-image-agent"
  DEST_BIN="$HOME/.local/bin/ai-image-agent"
  DEST_SHARE="$HOME/.local/share"
fi

say "copiando la aplicación a $DEST_LIB"
rm -rf "$DEST_LIB"
mkdir -p "$DEST_LIB"
cp -a "$REPO/aiimage_agent" "$DEST_LIB/"
cp -a "$REPO/assets" "$DEST_LIB/assets"
cp -a "$REPO/run_agent.py" "$DEST_LIB/"
find "$DEST_LIB" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true

mkdir -p "$(dirname "$DEST_BIN")"
cat > "$DEST_BIN" <<EOF
#!/bin/sh
# lanzador de AI Image Agent (generado por install_debian.sh)
exec python3 "$DEST_LIB/run_agent.py" "\$@"
EOF
chmod 755 "$DEST_BIN"

say "integración de escritorio"
install -d "$DEST_SHARE/applications" "$DEST_SHARE/icons/hicolor/256x256/apps" \
           "$DEST_SHARE/icons/hicolor/512x512/apps" "$DEST_SHARE/metainfo"
sed "s|@LAUNCHER@|$DEST_BIN|" "$REPO/packaging/linux/ai-image-agent.desktop" \
  > "$DEST_SHARE/applications/com.arena.AiImageAgent.desktop"
install -m644 "$REPO/assets/icon.png" "$DEST_SHARE/icons/hicolor/256x256/apps/ai-image-agent.png"
install -m644 "$REPO/assets/icon-512.png" "$DEST_SHARE/icons/hicolor/512x512/apps/ai-image-agent.png" 2>/dev/null || true
install -m644 "$REPO/packaging/flatpak/com.arena.AiImageAgent.metainfo.xml" \
  "$DEST_SHARE/metainfo/com.arena.AiImageAgent.metainfo.xml" 2>/dev/null || true
command -v update-desktop-database >/dev/null && update-desktop-database "$DEST_SHARE/applications" || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q "$DEST_SHARE/icons/hicolor" || true

if [ "$DO_PYI" = 1 ]; then
  say "binario único con PyInstaller"
  python3 -m venv "$REPO/.venv-build"
  "$REPO/.venv-build/bin/pip" install --quiet --upgrade pip pyinstaller
  ( cd "$REPO" && AIA_ONEFILE=1 .venv-build/bin/pyinstaller --noconfirm --distpath dist \
      --workpath build packaging/windows/AIImageAgent.spec )
  echo "→ $REPO/dist/AI-Image-Agent (ejecutable Linux)"
fi

if [ "$DO_TEST" = 1 ]; then
  say "prueba de humo"
  "$DEST_BIN" --providers
  "$DEST_BIN" --tools
  "$DEST_BIN" --version
  if command -v xvfb-run >/dev/null; then
    AIA_SCREENSHOT=/tmp/gui-screenshot.png xvfb-run -a -s "-screen 0 1500x980x24" \
      python3 "$REPO/scripts/gui_probe.py" full_flow
  else
    echo "(sin xvfb-run: prueba de GUI omitida; abre 'ai-image-agent' en tu escritorio)"
  fi
fi

say "listo"
cat <<EOF
Arrancar:      $DEST_BIN            (o busca 'AI Image Agent' en el menú)
Modo consola:  $DEST_BIN --cli -p "crea un icono de 512px de una cafetera" -a inkscape -x
Comprobar:     $DEST_BIN --tools    (detección de Inkscape/GIMP)
Config:        ~/.config/ai-image-agent/config.json
Quitar:        rm -rf $DEST_LIB $DEST_BIN $DEST_SHARE/applications/com.arena.AiImageAgent.desktop
EOF
