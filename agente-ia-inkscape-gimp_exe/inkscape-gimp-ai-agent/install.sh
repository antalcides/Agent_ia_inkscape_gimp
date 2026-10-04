#!/usr/bin/env bash
# Instalador para Linux (Debian 12 / Debian 13) y derivados.
# Uso:  bash install.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

info()  { printf '\033[36m[INFO]\033[0m  %s\n' "$1"; }
ok()    { printf '\033[32m[ OK ]\033[0m  %s\n' "$1"; }
warn()  { printf '\033[33m[AVISO]\033[0m %s\n' "$1"; }

info "Agente IA para Inkscape y GIMP - instalacion en Linux (Debian 12/13)"

# --- 1. Dependencias del sistema -----------------------------------------
if command -v apt-get >/dev/null 2>&1; then
    info "Paquetes recomendados: python3, python3-tk, python3-lxml, python3-gi"
    if ! python3 -c "import tkinter" >/dev/null 2>&1; then
        warn "Falta tkinter. Ejecuta:  sudo apt-get install -y python3-tk"
    fi
    if ! python3 -c "import lxml" >/dev/null 2>&1; then
        warn "Falta lxml (lo usa el nucleo de Inkscape). Ejecuta:  sudo apt-get install -y python3-lxml"
    fi
fi

# --- 2. Extension de Inkscape --------------------------------------------
INK_EXT="${HOME}/.config/inkscape/extensions"
mkdir -p "$INK_EXT"
cp -f "${ROOT}/inkscape_ext/agente_ia_inkscape.inx" "$INK_EXT/"
cp -f "${ROOT}/inkscape_ext/agente_ia_inkscape.py"  "$INK_EXT/"
chmod +x "$INK_EXT/agente_ia_inkscape.py"
rm -rf "$INK_EXT/core"
cp -r "${ROOT}/core" "$INK_EXT/core"
ok "Extension de Inkscape instalada en: $INK_EXT"

# --- 3. Plug-in de GIMP ---------------------------------------------------
GIMP_BASE="${HOME}/.config/GIMP"
installed=0
if [ -d "$GIMP_BASE" ]; then
    for ver_dir in "$GIMP_BASE"/*/; do
        [ -d "$ver_dir" ] || continue
        ver="$(basename "$ver_dir")"
        plug_dir="${ver_dir}plug-ins/agente_ia_gimp"
        mkdir -p "$plug_dir/core"
        cp -r "${ROOT}/core/." "$plug_dir/core/"
        if [[ "$ver" == 3* ]]; then
            cp -f "${ROOT}/gimp_plugin/agente_ia_gimp.py" "$plug_dir/"
            chmod +x "$plug_dir/agente_ia_gimp.py"
        else
            cp -f "${ROOT}/gimp_plugin/agente_ia_gimp_210.py" "$plug_dir/"
            chmod +x "$plug_dir/agente_ia_gimp_210.py"
        fi
        ok "Plug-in de GIMP instalado en: $plug_dir"
        installed=1
    done
fi
if [ "$installed" -eq 0 ]; then
    warn "No se encontro $GIMP_BASE. Crea la carpeta y copia manualmente:"
    warn "  mkdir -p ~/.config/GIMP/3.0/plug-ins/agente_ia_gimp"
    warn "  cp gimp_plugin/agente_ia_gimp.py ~/.config/GIMP/3.0/plug-ins/agente_ia_gimp/"
    warn "  cp -r core ~/.config/GIMP/3.0/plug-ins/agente_ia_gimp/"
fi

# --- 4. Lanzador de la interfaz grafica ----------------------------------
LAUNCH="${ROOT}/iniciar_agente.sh"
cat > "$LAUNCH" <<'EOF'
#!/usr/bin/env bash
cd "$(dirname "$0")"
python3 agent.py
EOF
chmod +x "$LAUNCH"
ok "Lanzador creado: $LAUNCH"

printf '\n'
ok "Instalacion terminada. Reinicia Inkscape y GIMP."
printf 'Inkscape: Extensiones > Agente IA\n'
printf 'GIMP:     Filtros > IA\n'
printf 'Interfaz: bash %s\n' "$LAUNCH"
