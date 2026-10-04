### Respuesta del Modo IA para URL base de Anthropic y Google Gemini

La URL base predeterminada para la API de Anthropic (Claude) es `https://api.anthropic.com`, y para la API de Google Gemini es `https://generativelanguage.googleapis.com`.[](https://platform.claude.com/docs/en/api/overview)

URLs Base y Detalles de las APIs

-   **Anthropic (Claude API)**:
    -   **URL base:** `https://api.anthropic.com`
    -   **Ruta común:** Los métodos principales (como la API de mensajes) se anexan a esta base, por ejemplo, `/v1/messages`.
    -   **Documentación oficial:** Puedes consultar más detalles en la [Descripción general de la API de Claude](https://platform.claude.com/docs/en/api/overview).

-   **Google Gemini API**:
    -   **URL base:** `https://generativelanguage.googleapis.com`
    -   **Ruta común:** Las solicitudes REST usan prefijos de versión como `/v1beta/` (por ejemplo, `/v1beta/models/...`).
    -   **Documentación oficial:** Tienes guías y recursos disponibles en la [Referencia de la API de Gemini](https://ai.google.dev/api).

Si necesitas ayuda para configurar la conexión, dime:

-   ¿Vas a usar **cURL, Python u otro lenguaje**?
-   ¿Requieres un ejemplo de **código de autenticación** para alguna de las dos plataformas?

## Compartido

0 archivos

# Compartido

-   ![](data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAMAAADXqc3KAAAAS1BMVEVHcEwzMS83MzAwMC42MzAuLy0zMS8vMC4xMC4wMC4wMC4wMC4sLy3ad1chKyvNcVS/a1CKVEKtY0tKOjNzSjwMJildQjeeXUflfFqh1K+AAAAAC3RSTlMAxg7HDi7F/l3DDhXGQOgAAAEaSURBVCiRbVKLbsMgDKRdE5IZYxvz+v8vnYE0nbSdogj5fH47517H6eEX/Hm8nGF7wB/sm/nv8xliGP9wMY+nO5a9ippR4c0c7lyP1gWCUo5LCqfzK1DupLFiLdqmyrthBg3BJCWTAneJw3cQ5p5UiYKwT51WBUvROtfWc0uCWKdgElalEKX5oURDuEIZakJEQmxaJVmBgwg5Z/Uxm3lwHVk8LIJpYNiRWy3lDlUMIDwEKTGxvJNDhMwGY1odta0cFkwTtcwZE3KCMhpYRExUNUmliq3xp0FTGMeWpTSsQnOM1xCtQy3cijJH9XOI19ilxjC6zgLX2NeiTBOAc7QFvBf1vFcePvuD3c5h22/mtn9t40z+OZ9v534AXPYdQkwdw0cAAAAASUVORK5CYII=)
    
    Claude Platform
    
    API overview - Claude Platform Docs
    
    API overview. Copy page.. Understand the Claude API's available endpoints, authentication headers, client SDKs, pagination, rate l...
    
    ![](data:image/png;base64,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)
    
-   ![](data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAYAAADgdz34AAADY0lEQVRIibWVXWgcVRTHf3dnZrPZpI2rMdm2EUGCIiktErRoq1YULCJaU6gW2gelFRWpfajVh/qgKcEPBEUQWkQF7UOxYPxAfVCiFootlVqNtBWEJMYtydpN0O7HnZ25x4dkJjO7Xdl98L8vc8+Z8zv3nHvurKIJicggsBbILpouAD8rpX5sJr4RNCMir4jIlDTWpIiMiEimVfh2EfnrP8C1yovItmbhL4uIaQEeyIjIgVqeqoHvBV6L2sx8gcrno7jjp/Fzf4LrYvVmSQ7eQuq+zSS6e2qZe5RSb9YlEJFbge8BO7BVvviE0gfvIK4LCGIMICCACFg2HY89Qfv9Q9EEHrBeKXUSIBFxvBqFlw6/R/Hdt0M4IvX9ND6JK66stdqLrHCBiNwObAiM1V9OUx49EkYkVvaRHtqGff0NYITq+bOUP/qQ9I6dtG3YWJ8Y7hSR25RSx4MdPxT1+ueGUUkbqVSxbxxg+QsjqLZU6LeuuZbUPZsuB45qM3A8aNEdgVWKZ7F7f6Bz669YKzvo3P1cDN6CNsJSz1eF5kvjgJDIVFi2y8bq6Y1FPfh6CQORsxYEUAJH96RpT4ZzswqWDjm8iVLNsxiKSvXVbUsuA0fAACUde/WqaIJCYFVO98LEiOBVpuoLr4WzNLXL2mPX6iIsTVFOKbUCgM4BwPC3vYLnp2xe6s+TTV8dRn26Nx0+5+YNOw+VAehZrkiGQw4iMh1WICJjYQUdA5xsu5vts6v5zXUYOXWQshevHcDz4eDXbrj7df12zB8wEwDGmI+jzrbr9lMyNiJwJn+OXd/s58vJY0z+k+NCMc/Y9AmeHXufExOXFi60BUM3O7EEvu+PQuRT4Xned5ZlheN6aPwIh89/RtDp4CKHa4Quqxv54ymeXN/PA4NOFP6tbdt3hRUAuK67T0S8YP346od5es0OHOUsnHnND4GimePRTbkYXEQ8rfW+sOXRslzXfcZxnDeitovleY7+/hWnZsaZLs6gvSp9nT2sy65lS/+9ZNPdsdZUq9XdyWTyLRpJaz1sjGn5/8AYY7TWLzYER1UqlR7xfH+2Wbjn+bNa661NwQMVCoUurfUBz/MmGoO9Ca31cKFQ6GrEUY0cUc3Nzd2USqXWJBKJXgBjzEylUjmTyWR+amnX/4f+BbuegL25SSGrAAAAAElFTkSuQmCC)
    
    Google AI for Developers
    
    All methods | Gemini API - Google AI for Developers
    
    28/08/2026 — Service: generativelanguage.googleapis.com. To call this service, we recommend that you use the Google-provided client libraries. ...
    

Mostrar todo