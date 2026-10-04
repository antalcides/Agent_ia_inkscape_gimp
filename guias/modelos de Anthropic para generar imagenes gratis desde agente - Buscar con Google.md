`Los modelos de Anthropic (**Claude**) **no pueden generar imágenes rasterizadas (como fotos o ilustraciones JPG/PNG) de forma nativa**`. Anthropic se enfoca en la seguridad y la alineación, evitando riesgos de desinformación o _deepfakes_.[](https://www.cometapi.com/es/can-claude-generate-images/)

Qué sí pueden hacer los agentes de Claude visualmente

-   **Crear SVG y gráficos:** Pueden generar código vectorial y diagramas estructurados.

-   **Claude Design:** Permite maquetas, wireframes y presentaciones, pero orientado a diseño estructural, no a imágenes fotográficas.

-   **Diseñar _prompts_ o usar MCP:** Puedes usar a Claude como agente de razonamiento para planificar y escribir instrucciones detalladas, o conectarlo mediante Model Context Protocol (MCP) a herramientas externas de terceros (como [Higgsfield AI](https://higgsfield.ai/claude-ai-image-generator)) para renderizar imágenes.[](https://www.datacamp.com/es/blog/claude-design)

Si quieres configurar un flujo para crear imágenes usando agentes, dime:

-   ¿Prefieres **conectar una herramienta externa (como MCP)** a Claude?
-   ¿Buscas usar Claude solo para **escribir los _prompts_** que usarás en otro generador?