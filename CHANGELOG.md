# Cambios

Cada versión del plugin de Datalum dice qué cambia para quien usa la Skill, contra qué
versión del servidor se comprobó y qué hay que hacer para recibirla. La más reciente va
primero.

## [2.0.3] - 2026-10-05

La producción de Datalum se muda a `datalum.ai`. Las reglas de la Skill y de los
controles no cambian.

### Cambiado

- El conector apunta a `https://mcp.datalum.ai/mcp`: `.mcp.json`, la ficha de ChatGPT,
  la Skill, `INSTALAR.md` y el README. El inicio de sesión pasa a `api.datalum.ai` y el
  panel a `app.datalum.ai`.
- `https://mcp.datahub.vinden.cc/mcp` queda como qa en `compat/entornos.json`: un aviso
  de ese entorno prepara y prueba la candidata sin publicar.

### Servidor

- El contrato de la v2.244.0, armado del código del servidor, es igual al de la
  v2.243.0 guardado (`11e81846335d`, 94 herramientas).

### Cómo recibirla

- En Grok Build y Claude Code el conector llega con el plugin. En Claude (web y
  escritorio) y en ChatGPT el conector se agregó a mano: hay que cambiar su dirección
  por la nueva. Los pasos están en `INSTALAR.md`.
- La producción nueva no trae las cuentas ni los datos de la anterior: hace falta una
  cuenta en ella.

## [2.0.2] - 2026-10-05

Corrige los pendientes que la auditoría de la 2.0.1 encontró con pruebas adicionales.
La Skill cambia un paso de memoria; el contrato con Datalum no cambia.

### Corregido

- Después de soltar un agente, una respuesta vieja de la persona que seguía en la
  conversación volvía a elegirlo. Ahora cada elección sirve una vez: la que ya eligió un
  agente no vuelve a elegirlo tras soltarlo ni elige a otro, y tras soltar tampoco se da
  por elegido el único agente de la lista. La elección que la persona hace para cambiar
  de agente sigue valiendo aunque el modelo suelte el anterior antes de elegir el nuevo,
  como indica la Skill.
- Al migrar un estado de la 2.0.0, todas las escrituras pendientes se atribuían al
  agente elegido en ese momento. Ahora sólo las posteriores a su elección; las
  anteriores quedan sin dueño y repetirlas lo decide la persona. Lo que la persona eligió
  antes de actualizar tampoco vuelve a elegir.
- La recuperación de una escritura incierta no reconocía la forma real de la memoria
  que devuelve Datalum: el archivo enmarcado con cada línea prefijada, el «no existe»
  como `agent_memory_not_found` y el detalle anidado cuando se lee por la ruta del
  cerebro. Un guardado comprobable podía seguir contando como incierto.
- Una propuesta de memoria presentada por `brain_write` se anunciaba como guardada: el
  cliente buscaba el recibo en la raíz y `brain_write` lo devuelve dentro de `memory`.
  Ahora lee cada respuesta según su contrato y distingue cuatro casos: escrita,
  propuesta que espera la aprobación de una persona, resultado incierto y escrita cuya
  relectura falló. Una propuesta no se puede presentar dos veces.
- Una lectura del detalle de otro agente, o el «no existe» de una memoria compartida,
  resolvía una escritura incierta. Ahora no: una propuesta puede estar esperando
  aprobación. Repetirla lo decide la persona, avisada de que puede duplicarla.
- Los avisos de recuperación del cliente mandaban usar `list_memories`. Ahora remiten al
  procedimiento de memoria del cerebro del agente, y el paso de memoria de la Skill
  tampoco nombra una herramienta. El cliente sigue reconociendo las dos rutas.
- Al retirar una versión publicada con archivos que no se probaron, se ignoraba el
  rechazo de GitHub y no se comprobaba la retirada; un fallo no se podía recuperar.
  Ahora se lee el estado en GitHub: si sigue a la vista, el resultado es
  `retirada_fallida`; si no se puede leer, `retirada_incierta`. El reintento del mismo
  despliegue recupera las dos antes de publicar lo probado. Una descarga fallida ya no
  se confunde con archivos distintos.

### Documentación

- `INSTALAR.md` y el README dicen que el plugin no instala los recursos de entrega de un
  agente, como `datalum-entregables` o el formato del Builder: los nombra su cerebro.

### Servidor

- Sin cambios de contrato: la misma producción, v2.243.0 (contrato `11e81846335d`).

### Cómo recibirla

- Como la 2.0.1: los pasos por aplicación están en `ACTUALIZAR.md`. Los estados
  guardados por la 2.0.1 se leen sin cambios.

## [2.0.1] - 2026-10-05

Corrige cuatro defectos de los controles del cliente de la 2.0.0. La Skill cambia en dos
párrafos; el contrato con Datalum no cambia.

### Corregido

- Leer una memoria liberaba las escrituras inciertas de otras memorias. Ahora sólo las
  resuelve una lectura completa del mismo destino, del mismo agente y posterior a la
  escritura. Si muestra lo que se intentó escribir, la escritura cuenta como aplicada; si
  la memoria no existe o sigue la misma de antes, se permite un reintento; con cualquier
  otra lectura sigue incierta y repetirla lo decide la persona.
- Una cita auténtica bastaba para elegir un agente o borrar: «No uses el agente Finanzas»
  permitía elegir Finanzas y «hola» permitía un borrado. Ahora cuenta como elección lo que
  la persona eligió en una pregunta de la aplicación, un mensaje suyo que es sólo el
  nombre del agente, el único agente de su lista o lo que aprobó en el diálogo de la
  aplicación. Adoptar una versión nueva y cada borrado se le preguntan a la persona; si
  aprobó un borrado y la llamada falló, esa misma operación se puede reintentar durante
  15 minutos sin volver a preguntar.
- Proponer un agente por `brain_write` vuelve a estar protegido contra duplicados, como
  en la 1.x.
- El estado del cliente guardaba la frase con que se eligió el agente. Ya no guarda
  palabras de la persona, ni nombres o títulos de lo escrito, y el registro de errores ya
  no copia la entrada. Los estados de la 2.0.0 se migran al leerlos sin perder el agente
  ni las escrituras pendientes.
- Los mismos argumentos con otro agente se bloqueaban como duplicado. Ahora una operación
  se identifica por agente, ámbito, destino, operación y contenido. Renovar el contexto
  del mismo agente conserva la protección.
- Si los archivos de una versión publicada no coincidían con los probados, la versión se
  quedaba a la vista como versión preliminar. Ahora vuelve a borrador.

### Cambiado

- Con varios agentes, la Skill pide preguntar con opciones cuando la aplicación lo
  permite, y advierte que la aplicación puede pedir a la persona que confirme.
- `CONTROLES.md` explica qué cuenta como consentimiento, cómo se resuelve un resultado
  incierto, qué guarda el cliente y los límites de cada modo de permisos.

### Servidor

- Sin cambios de contrato: comprobada contra la misma producción que la 2.0.0, v2.243.0
  (contrato `11e81846335d`).

### Cómo recibirla

- Los pasos por aplicación están en `ACTUALIZAR.md`. En Claude Code las conversaciones
  abiertas conservan su agente: el estado de la 2.0.0 se migra solo.

## [2.0.0] - 2026-10-03

El plugin deja de explicar el oficio. Conecta a la persona, le pregunta con qué agente
trabaja, carga el cerebro de ese agente tal como lo sirve Datalum y lo sigue.

### Cambiado

- La Skill ya no trae un catálogo de herramientas ni tablas de «qué herramienta para qué
  encargo». Nombra las que usa para arrancar, cargar el cerebro y leer la memoria; lo
  demás lo descubre en el conector y en el procedimiento del agente.
- Las gráficas, los tableros y los archivos se entregan como diga el agente elegido. La
  versión anterior mandaba esos encargos a las herramientas del catálogo de Datalum,
  también cuando el agente los entrega como archivos HTML hechos en la aplicación.
- Con un solo agente en el llavero, el asistente dice cuál es y lo usa, con el mensaje
  en el que la persona pidió el trabajo como cita. Si la persona ya nombró su agente, no
  se le vuelve a preguntar.
- Una aprobación cubre un encargo, no cada llamada. Se vuelve a preguntar cuando el
  encargo tocaría algo que la persona no mencionó, llegaría a otras personas o borraría
  datos.
- La memoria se usa como diga el cerebro del agente. Antes de escribir se busca el
  trabajo que ya existe, se lee completo y se actualiza la misma ficha. La memoria
  compartida no se usa salvo que la persona la pida.
- Las respuestas dicen qué se obtuvo, qué falta y qué se necesita de la persona, sin
  identificadores, nombres de herramientas ni errores crudos.

### Corregido

- Ya no nombra `start_agent_edit`, `finish_agent_edit` ni `publish_bundle`, que el
  servidor retira el 2026-11-04 y que hoy no hacen nada o rechazan siempre.
- Ante un conflicto de contexto entre conversaciones, la versión anterior mandaba quitar
  el contexto y repetir la llamada, que podía correr con el agente de otra conversación.
  Ahora se le pregunta a la persona y se vuelve a elegir.
- Cuando la selección caduca se vuelve a elegir el mismo agente y nunca otro. Si al
  hacerlo cambió la versión, se le dice a la persona y se vuelve a leer el cerebro.
- Pasar a una versión nueva del agente lo pide la persona. La versión anterior lo
  presentaba como un paso que el asistente podía dar al ver el aviso.
- Una lectura con continuación ya no se da por completa: se siguen los cursores del
  cerebro y de la memoria. Un índice de memoria vacío o parcial no prueba que no haya
  memoria.
- Una escritura confirmada no se repite para arreglar una lectura posterior que falló.
  Un resultado incierto se comprueba leyendo antes de repetir.
- El inicio distingue conector sin instalar, herramientas sin cargar, cuenta sin sesión,
  sesión caducada, cuenta sin permiso, llavero vacío, agente otorgado sin activar y
  servicio que no responde, y da a la persona el paso que corresponde a cada uno.

### Añadido

- Controles que corren en el cliente, en las aplicaciones que cargan los hooks de un
  plugin. Comprueban que la elección de agente y los borrados los pidió la persona,
  mantienen cada llamada en el agente de su conversación, piden la vista previa antes
  de aplicar, evitan repetir una escritura confirmada y recuperan el estado tras una
  compactación. Necesitan Node 18 o posterior. Qué hace cada uno: `CONTROLES.md`.
- Comprobación automática después de cada despliegue de Datalum a producción: confirma
  el despliegue contra el servidor, compara su contrato con lo que el plugin usa,
  publica una versión de parche cuando el cambio se resuelve solo y lo anota en
  `compat/registro.jsonl`. Cómo funciona y qué necesita: `MANTENER.md`.
- Evaluaciones con modelo real en `evals/`, contra un conector simulado con datos
  inventados, y pruebas de código de los controles y de la automatización.
- Guías nuevas: `ACTUALIZAR.md`, `CONTROLES.md` y `COMPATIBILIDAD.md`.

### Servidor

- Comprobada contra la producción de Datalum en v2.243.0 (commit `22a5a022caeb`,
  contrato `11e81846335d`): 94 herramientas, las mismas que en v2.242.0.
- `scripts/server-tools.txt` desaparece. La lista vigente es
  `compat/contrato-produccion.json`, que mantiene la comprobación automática.

### Cómo recibirla

- Los pasos por aplicación están en `ACTUALIZAR.md`. Después de actualizar, empieza una
  conversación nueva.
- En Claude Code los controles piden Node 18 o posterior. Sin él, el plugin funciona
  sin controles.

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
