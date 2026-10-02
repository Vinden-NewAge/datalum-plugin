# Cambios

Cada versión del plugin de Datalum dice qué cambia para quien usa la Skill, contra qué
versión del servidor se comprobó y qué hay que hacer para recibirla. La más reciente va
primero.

## [1.1.0] - 2026-10-02

### Corregido

- La Skill decía que configurar un agente en servicio exigía ponerlo en edición con
  `start_agent_edit`, que eso desconectaba a sus usuarios y que había que cerrarlo con
  `finish_agent_edit`. El servidor ya no lo hace: el agente sigue en servicio y el cambio
  se sirve cuando una persona guarda una versión nueva en el panel. Ahora la Skill manda
  a configurarlo directamente.
- La Skill ofrecía `publish_bundle` para poner en vivo gráficas, tableros e indicadores.
  El servidor la rechaza siempre: activar lo hace una persona en el panel.
- Ya no dice que `agent_not_selected` puede venir de un agente en edición, ni que
  `apply_update` desconecta agentes.

### Añadido

- Los cuatro estados del catálogo (Propuesto, Probado, Activo, Retirado), qué pasa al
  editar algo que está en Activo y cómo se recupera algo retirado.
- Los códigos de estado que cambian el 2026-11-04, con la tabla de los viejos y los
  nuevos. Hasta esa fecha la Skill lee los dos.
- El aviso de que `start_agent_edit`, `finish_agent_edit` y `publish_bundle` salen del
  catálogo el 2026-11-04 y que no hay que llamarlas.

### Servidor

- Comprobada contra la versión publicada v2.242.0 del servidor: 94 herramientas, las
  mismas que en v2.229.0 y con la misma vista previa. El 2026-11-04 salen tres; hará
  falta la versión 1.2.0 con la lista nueva.

### Cómo recibirla

- Grok Build: llega sola cuando xAI acepte el plugin en su catálogo.
- Claude Code: `/plugin marketplace update datalum`.
- Claude (web y escritorio) y ChatGPT: descargar el `datalum-skill.zip` nuevo y
  reemplazar el anterior.

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
