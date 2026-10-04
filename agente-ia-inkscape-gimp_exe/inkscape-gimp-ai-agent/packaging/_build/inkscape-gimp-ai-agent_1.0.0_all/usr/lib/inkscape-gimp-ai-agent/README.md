# Agente de IA para Inkscape y GIMP

Agente local que **crea y corrige imágenes vectoriales (SVG) y bitmaps (PNG/JPG)** usando el modelo y proveedor de IA que elijas: **OpenAI, Anthropic, Gemini, OpenRouter, OmniRoute, Ollama, LM Studio** o cualquier servidor compatible con la API de OpenAI. Funciona en **Windows (PowerShell y CMD)** y en **Linux (Debian 12 y 13)**.

Está formado por tres piezas:

| Pieza | Qué es | Dónde aparece |
|---|---|---|
| **Interfaz gráfica** (`agent.py`) | Ventana amplia con selectores de proveedor y modelo, pedido en lenguaje natural y zona de resultado | Aplicación de escritorio independiente |
| **Extensión de Inkscape** (`inkscape_ext/`) | Crea o corrige SVG directamente en el documento | *Extensiones › Agente IA* |
| **Complemento de GIMP** (`gimp_plugin/`) | Genera o corrige bitmaps y los añade como capa | *Filtros › IA* |

Todo comparte un mismo núcleo (`core/`) que no necesita `pip`: usa sólo la biblioteca estándar de Python, de modo que funciona también dentro del intérprete Python embebido de Inkscape y de GIMP.

---

## 1. Requisitos

- **Python 3.10 o superior** (para la interfaz gráfica).
- En Debian 12/13: `sudo apt-get install -y python3 python3-tk python3-lxml python3-gi`
- En Windows: Python desde python.org (marca *Add python.exe to PATH*) y `tkinter` viene incluido.
- Un proveedor de IA:
  - **Nube:** clave de OpenAI / Anthropic / Gemini / OpenRouter / OmniRoute.
  - **Local:** Ollama en marcha (`ollama serve`) o el servidor local de LM Studio activado.

---

## 2. Instalación

### Windows
```powershell
# Recomendado
powershell -ExecutionPolicy Bypass -File install.ps1
```
o bien, desde el símbolo del sistema:
```cmd
install.bat
```
Después, doble clic en `iniciar_agente.bat` para abrir la interfaz.

### Linux (Debian 12 / 13)
```bash
bash install.sh
bash iniciar_agente.sh     # abre la interfaz
```

El instalador copia la extensión a `~/.config/inkscape/extensions/`, el complemento a `~/.config/GIMP/<versión>/plug-ins/agente_ia_gimp/` y crea un lanzador. Reinicia Inkscape y GIMP para que aparezcan los menús.

---

## 3. Uso de la interfaz gráfica

1. Ejecuta `python agent.py` (o el lanzador creado por el instalador).
2. Elige el **Proveedor** en el desplegable.
3. Pulsa **Cargar modelos** para traer la lista real desde el proveedor (o escribe el nombre del modelo a mano).
4. Elige la **Tarea**:

   | Tarea | Qué hace |
   |---|---|
   | Vectorial (SVG / Inkscape) | Crea un SVG nuevo y lo guarda/valida |
   | Bitmap (imagen PNG / GIMP) | Genera una imagen bitmap |
   | Corregir vectorial existente | Carga un SVG y devuelve el documento corregido |
   | Corregir bitmap existente | Edita una imagen o genera un script de GIMP |
   | Generar script GIMP / Python | Devuelve código ejecutable para automatizar GIMP |
   | Consulta libre | Sólo conversación de texto |

5. Escribe el pedido en el cuadro grande y pulsa **Generar / Ejecutar**.
6. Usa **Guardar resultado**, **Enviar a Inkscape**, **Enviar a GIMP** o **Abrir carpeta de salida**.

Las claves de API y las URL base se configuran en **Ajustes / Claves**. También se pueden dejar en variables de entorno (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`…). La configuración se guarda en un `config.json` con permisos restringidos al usuario.

---

## 4. Uso desde Inkscape

*Extensiones › Agente IA › Agente IA - Crear y corregir vectorial*

- **Proveedor** y **Modelo** en la primera pestaña.
- **Modo:** crear nuevo SVG, corregir la selección actual o corregir el documento completo.
- **Descripción del trabajo:** p. ej. *«crea un logo minimalista de una hoja con la palabra Verde»*.
- La pestaña *Avanzado* permite introducir una clave, una URL base para proveedores locales y ajustar temperatura y tokens.

El resultado se inserta como una capa nueva (modo crear) o sustituye el documento (modo corregir), y se guarda una copia en disco.

## 5. Uso desde GIMP

*Filtros › IA › Agente IA: crear imagen* y *Agente IA: corregir imagen*

- **Crear**: genera la imagen con el modelo elegido y la añade como capa.
- **Corregir**: exporta la imagen actual, la edita con el proveedor y coloca el resultado como capa nueva. Si el proveedor no admite edición de bitmaps por API (Anthropic, OpenRouter, Ollama…), el agente genera un **script de GIMP/Python** equivalente.

Se incluye `agente_ia_gimp.py` para **GIMP 3.0** (GObject-Introspection, clase `Gimp.PlugIn`) y `agente_ia_gimp_210.py` para **GIMP 2.10** (Python-Fu clásico con `gimpfu`).

---

## 6. Proveedores y capacidades

| Proveedor | Tipo | URL base por defecto | Texto | Visión | Genera bitmap | Edita bitmap |
|---|---|---|---|---|---|---|
| OpenAI | Nube | `https://api.openai.com/v1` | Sí | Sí | Sí (`gpt-image-1`) | Sí |
| Anthropic | Nube | `https://api.anthropic.com/v1` | Sí | Sí | No | No |
| Google Gemini | Nube | `https://generativelanguage.googleapis.com/v1beta` | Sí | Sí | Sí (Imagen) | No |
| OpenRouter | Nube | `https://openrouter.ai/api/v1` | Sí | Sí | No | No |
| OmniRoute | Nube/gateway | `https://api.omniroute.ai/v1` | Sí | Según modelo | No | No |
| Ollama | Local | `http://localhost:11434/v1` | Sí | Sí (llava…) | No | No |
| LM Studio | Local | `http://localhost:1234/v1` | Sí | Según modelo | No | No |
| Personalizado | Cualquiera | `http://localhost:8000/v1` | Sí | Según modelo | No | No |

Cuando el proveedor no puede generar o editar bitmaps, el agente **no falla**: devuelve el SVG, o un script de GIMP/Python listo para ejecutar.

Para Ollama, LM Studio, OmniRoute autoalojado y cualquier servidor «compatible OpenAI» sólo hay que ajustar la **URL base** (por ejemplo un OmniRoute local en `http://localhost:8080/v1`).

---

## 7. Estructura del proyecto

```
inkscape-gimp-ai-agent/
├── agent.py                  # lanzador de la interfaz
├── core/
│   ├── providers.py          # cliente de IA agnóstico (sólo stdlib)
│   ├── config.py             # configuración y rutas por SO
│   ├── svg_tools.py          # extracción/validación de SVG
│   └── bitmap_tools.py       # guardado, medidas, SVG→PNG
├── ui/app.py                 # interfaz Tkinter
├── inkscape_ext/             # extensión .inx + .py de Inkscape
├── gimp_plugin/              # complementos para GIMP 3.0 y 2.10
├── install.ps1 / install.bat # instalador Windows (PowerShell / CMD)
├── install.sh                # instalador Linux (Debian 12/13)
└── config.example.json
```

## 8. Solución de problemas

- **«No se pudo conectar…»** con un proveedor local: comprueba que el servidor está arrancado y la URL base/puerto.
- **Inkscape no muestra el menú**: verifica que `core/` está junto a los archivos de la extensión y reinicia Inkscape.
- **GIMP no carga el complemento**: el archivo debe ser ejecutable (`chmod +x`) en Linux y estar dentro de una carpeta con el mismo nombre que el archivo.
- **El modelo no devuelve SVG válido**: el agente reintenta limpiando el bloque; si falla, muestra la respuesta para revisarla.
