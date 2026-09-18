# Cambios

Cada versión del plugin de Datalum dice qué cambia para quien usa la Skill, contra qué
versión del servidor se comprobó y qué hay que hacer para recibirla. La más reciente va
primero.

## [1.0.0] - 2026-09-18

### Añadido

- La Skill `datalum`, la misma para Grok Build, Claude (web, escritorio y Claude Code) y
  ChatGPT.
- La conexión al servidor de Datalum en `https://mcp.datahub.vinden.cc/mcp`.
- La regla de que Datalum manda sobre sus datos: la Skill sigue las instrucciones del
  servidor, las del agente elegido y la descripción de cada herramienta cuando son más
  estrictas que ella, y trata lo que devuelven las herramientas como datos. Las cifras
  sólo salen de Datalum.
- Aprobación antes de cada cambio: vista previa en las herramientas que la tienen, y
  pregunta explícita en las que aplican el cambio en la primera llamada.

### Servidor

- Comprobada contra la versión publicada v2.229.0 del servidor: 94 herramientas.

### Cómo recibirla

- Es la primera versión: se instala como dice `INSTALAR.md`.
