# Cambios

Cada versión del plugin de Datalum dice qué cambia para quien usa la Skill, contra qué
versión del servidor se comprobó y qué hay que hacer para recibirla. La más reciente va
primero.

## [1.0.0] - 2026-09-18

### Añadido

- La Skill `datalum`, la misma para Grok Build, Claude (web, escritorio y Claude Code) y
  ChatGPT.
- La conexión al servidor de Datalum en `https://mcp.datahub.vinden.cc/mcp`.
- La regla de que Datalum manda: sus instrucciones, el contexto del agente elegido y la
  descripción de cada herramienta están por encima de esta Skill y del conocimiento
  general del modelo. Las cifras sólo salen de Datalum.

### Servidor

- Comprobada contra la versión publicada v2.229.0 del servidor: 94 herramientas.

### Cómo recibirla

- Es la primera versión: se instala como dice `INSTALAR.md`.
