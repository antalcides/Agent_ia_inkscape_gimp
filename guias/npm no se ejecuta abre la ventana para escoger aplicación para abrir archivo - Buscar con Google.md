---
created: 2026-09-19T10:02:14 (UTC -05:00)
tags: []
source: https://www.google.com/search?client=firefox-b-d&q=npm+no+se+ejecuta+abre+la+ventana+para+escoger+aplicaci%C3%B3n+para+abrir+archivo
author: 
---

# npm no se ejecuta abre la ventana para escoger aplicación para abrir archivo - Buscar con Google

> ## Excerpt
> El problema ocurre porque Windows perdió la asociación predeterminada para los archivos con extensión .js y ahora intenta abrirlos con un programa externo en lugar de ejecutarlos mediante Node.js.

---
### Respuesta del Modo IA para npm no se ejecuta abre la ventana para escoger aplicación para abrir archivo

El problema ocurre porque Windows perdió la asociación predeterminada para los archivos con extensión `.js` y ahora intenta abrirlos con un programa externo en lugar de ejecutarlos mediante Node.js.[](https://www.google.com/goto?url=CAESowEB6zswFbMeBiretWPowDS0TyNNWewvBT14d6_O5x0XcD1lrY9SLVQ67kt5h16GwRFj2HqE7UGYZtqyMh2T0gsV0LompWRjObSQbJbe9n5_dw9ibrGzqxY7yf7PtDLGEpdlmSpOgJ-LFZ0eCIthMLzFQXPR5Tu7U-CS9txB5GzU6TnjuqZqDB2ZBsv9A-hzCQM0gEgt8xz3YSpd7aTv0kH8UBLs)

Para solucionarlo, debes reasociar correctamente los archivos `.js` en tu sistema operativo:

Pasos para solucionarlo en Windows

-   Abre el **Explorador de archivos** de Windows.

-   Busca cualquier archivo que tenga extensión `.js` (o créalo temporalmente con el bloc de notas como `prueba.js`).

-   Haz clic derecho sobre el archivo `.js`.

-   Selecciona **Abrir con** y luego **Elegir otra aplicación** (o "Cambiar aplicación predestinada").

-   En la lista de programas, busca y selecciona **Node.js** (`node.exe`). Si no aparece a primera vista, haz clic en "Buscar otra aplicación en el equipo" y busca la ruta de instalación de Node, usualmente en `C:\Program Files\nodejs\node.exe`.

-   Marca la casilla que dice **"Usar siempre esta aplicación para abrir archivos .js"**.

Una vez hecho esto, la asociación se reparará y podrás volver a tu terminal (como PowerShell o VS Code) a ejecutar tus comandos de `npm` con normalidad.[](https://www.google.com/goto?url=CAESowEB6zswFbMeBiretWPowDS0TyNNWewvBT14d6_O5x0XcD1lrY9SLVQ67kt5h16GwRFj2HqE7UGYZtqyMh2T0gsV0LompWRjObSQbJbe9n5_dw9ibrGzqxY7yf7PtDLGEpdlmSpOgJ-LFZ0eCIthMLzFQXPR5Tu7U-CS9txB5GzU6TnjuqZqDB2ZBsv9A-hzCQM0gEgt8xz3YSpd7aTv0kH8UBLs)

Si el problema persiste o te aparece algún **error específico en la terminal** después de hacer esto, dime cuál es y te ayudo a revisarlo.

-   npm siempre activa el diálogo "Abrir con" – los archivos .js no ...
    
    7/08/2025 — Solución para la ventana emergente "Elige un programa para abrir este archivo" al ejecutar npm run build en Windows (VS Code / Pow...
