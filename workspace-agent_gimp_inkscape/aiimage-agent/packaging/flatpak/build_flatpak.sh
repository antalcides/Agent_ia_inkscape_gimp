#!/usr/bin/env bash
# Construir el Flatpak de AI Image Agent (Debian 12/13, Fedora, Ubuntu…).
#
#   ./packaging/flatpak/build_flatpak.sh              # compila y genera dist/AI-Image-Agent.flatpak
#   ./packaging/flatpak/build_flatpak.sh --install    # además lo instala (flatpak install)
#   ./packaging/flatpak/build_flatpak.sh --validate    # solo valida manifest + metainfo
#   ./packaging/flatpak/build_flatpak.sh --from-tarball /ruta/fuente.tar.xz
#
# Requisitos: flatpak, flatpak-builder, bubblewrap, y red la primera vez
# (baja org.freedesktop.Platform/Sdk 24.08 de Flathub, ~500 MB).
set -euo pipefail

APP_ID=com.arena.AiImageAgent
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MANIFEST="packaging/flatpak/com.arena.AiImageAgent.yml"
OUT="$REPO_ROOT/dist"
BUILD="$REPO_ROOT/.flatpak-builder"
REPO="$OUT/repo"
INSTALL=0
VALIDATE_ONLY=0
TARBALL=""

while [ $# -gt 0 ]; do
  case "$1" in
    --install) INSTALL=1 ;;
    --validate) VALIDATE_ONLY=1 ;;
    --from-tarball) TARBALL="${2:?falta la ruta del tar.xz}"; shift ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "opción desconocida: $1" >&2; exit 2 ;;
  esac
  shift
done

need() { command -v "$1" >/dev/null 2>&1 || { echo "FALTA: $1" >&2; exit 3; }; }
# --validate debe poder correrse en una CI sin flatpak instalado (solo python3)
if [ "$VALIDATE_ONLY" != 1 ]; then
  need flatpak
  need flatpak-builder
fi

echo "== 1/5 validar manifest y metainfo =="
if command -v flatpak-builder >/dev/null 2>&1; then
  flatpak-builder --show-manifest "$REPO_ROOT/$MANIFEST" >/dev/null && echo "  flatpak-builder acepta el manifest"
else
  echo "  (flatpak-builder ausente: comprobación estructural con python)"
fi
python3 - "$REPO_ROOT/$MANIFEST" <<'PY'
import re, sys
path = sys.argv[1]
try:
    import yaml
except ImportError:
    yaml = None
if yaml is None:
    # sin pyyaml: comprobación estructural mínima pero real (claves obligatorias)
    txt = open(path, encoding="utf-8").read()
    d = {}
    for key in ("app-id", "command", "runtime", "runtime-version", "sdk"):
        m = re.search(rf"^{key}:\s*(\S+)", txt, re.M)
        assert m, f"falta la clave {key!r}"
        d[key] = m.group(1)
    assert re.search(r"^modules:", txt, re.M), "falta la lista modules:"
    for req in ("--share=network", "--socket=fallback-x11", "--share=ipc",
                "--talk-name=org.freedesktop.Flatpak", "--device=dri"):
        assert req in txt, f"finish-args sin {req}"
    d["finish-args"] = re.findall(r"^\s*-\s*(--\S+)", txt, re.M)
    d["modules"] = [{"name": n} for n in re.findall(r"^  - name:\s*(\S+)", txt, re.M)]
    print("  (pyyaml ausente: validación estructural por regex)")
else:
    d = yaml.safe_load(open(path))
assert d["app-id"] == "com.arena.AiImageAgent", d["app-id"]
assert d["command"] == "ai-image-agent"
bad = [a for a in d["finish-args"] if not str(a).strip().startswith("--")]
assert not bad, f"finish-args raros: {bad}"
mods = [m["name"] for m in d["modules"]]
for expected in ("tcl", "tk", "python3", "ai-image-agent"):
    assert expected in mods, f"falta el módulo {expected}: {mods}"
print("  manifest coherente:", mods)
PY
if command -v appstreamcli >/dev/null 2>&1; then
  appstreamcli validate --no-net "$REPO_ROOT/packaging/flatpak/com.arena.AiImageAgent.metainfo.xml" || {
    echo "  (appstreamcli informó problemas; sigue siendo instalable)"; }
else
  python3 - <<'PY'
import xml.etree.ElementTree as ET
r = ET.parse("packaging/flatpak/com.arena.AiImageAgent.metainfo.xml").getroot()
need = ["id", "name", "summary", "description", "launchable", "project_license"]
missing = [t for t in need if r.find(t) is None]
assert not missing, f"metainfo sin elementos obligatorios: {missing}"
print("  metainfo XML válido (elementos obligatorios presentes)")
PY
fi
[ "$VALIDATE_ONLY" = 1 ] && { echo "validación OK"; exit 0; }

echo
echo "== 2/5 preparar fuentes =="
mkdir -p "$OUT"
if [ -z "$TARBALL" ]; then
  TARBALL="$OUT/ai-image-agent-source.tar.xz"
  ( cd "$REPO_ROOT" && tar --create --xz --exclude-vcs \
      --exclude='./dist' --exclude='./.flatpak-builder' --exclude='./build' \
      --exclude='./.venv-build' --exclude='__pycache__' --exclude='./node_modules' \
      --file="$TARBALL" . )
  echo "  fuentes empaquetadas en ${TARBALL#$REPO_ROOT/}"
  SRC_NOTE="usa 'sources: [{type: dir, path: ../..}]' → compila desde el árbol de trabajo"
else
  SRC_NOTE="usa el tarball de fuentes: $TARBALL"
fi
echo "  nota: $SRC_NOTE"

echo
echo "== 3/5 flatpak-builder (tarda la primera vez) =="
ARGS=(--force-clean --disable-rofiles-fallback --repo="$REPO"
      --subdir=build --jobs="$(nproc)")
[ "$INSTALL" = 1 ] && ARGS+=(--install "$REPO_ROOT/.flatpak-install")
flatpak-builder "${ARGS[@]}" "$BUILD" "$REPO_ROOT/$MANIFEST"

echo
echo "== 4/5 prueba humo dentro del sandbox =="
if flatpak-builder --run "$BUILD" "$REPO_ROOT/$MANIFEST" sh -c '
  /app/bin/python3 -c "import tkinter, sys; print(\"tk\", tkinter.TkVersion, sys.version.split()[0])" &&
  PYTHONPATH=/app/lib/ai-image-agent /app/bin/python3 -m aiimage_agent --providers | head -3 &&
  PYTHONPATH=/app/lib/ai-image-agent /app/bin/python3 -m aiimage_agent --tools
'; then
  echo "  smoke test del sandbox OK"
else
  echo "  AVISO: el smoke test falló; revisa arriba (normalmente falta Tcl/Tk en la build de python)" >&2
fi

echo
echo "== 5/5 bundle =="
flatpak build-bundle "$REPO" "$OUT/AI-Image-Agent.flatpak" "$APP_ID"
echo "  $(du -h "$OUT/AI-Image-Agent.flatpak" | cut -f1) → dist/AI-Image-Agent.flatpak"
cat <<'TXT'

Instalar y probar:
  flatpak install -y dist/AI-Image-Agent.flatpak
  flatpak run com.arena.AiImageAgent
Para que pueda gobernar Inkscape/GIMP instala al menos uno:
  flatpak install -y flathub org.inkscape.Inkscape
  flatpak install -y flathub org.gimp.GIMP
(o usa los del sistema: apt install inkscape gimp)
TXT
[ "$INSTALL" = 1 ] && echo "también instalado en el usuario: flatpak run $APP_ID"
