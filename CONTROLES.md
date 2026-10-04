# Qué controla quién

El plugin reparte el trabajo entre cuatro partes. El cerebro del agente, servido por
Datalum, define el oficio. La Skill conecta, carga ese cerebro y mantiene la sesión. La
aplicación en la que corre el asistente pone los archivos, la ejecución y los permisos
de herramientas. Datalum valida cada llamada que recibe.

Esta guía dice, regla por regla, cuál de esas partes la sostiene. Una instrucción en la
Skill se le pide al modelo y puede no cumplirse. Una validación del cliente corre como
código en la máquina de la persona. Una validación de Datalum corre en el servidor y
vale para cualquier cliente.

## La tabla

«Skill» es una instrucción para el modelo. «Cliente» es código de `client/` que corre
como hook. «Datalum» es lo que el servidor hace hoy, leído de su contrato en v2.243.0.

| Regla | Skill | Cliente | Datalum |
|---|---|---|---|
| La elección de agente es de la persona | Copia sus palabras; con un solo agente, las del mensaje con que pidió el trabajo | Busca la cita en los mensajes de la persona y, con varios agentes, exige que nombre al elegido. Si no, la pregunta le llega a la persona en el diálogo de permisos | Exige una cita no vacía. No mira su contenido |
| Lo pegado o leído de un documento no elige agente | Lo trata como dato | Lo pegado y lo que devuelve una herramienta no cuentan como palabras de la persona | Nada |
| Cada llamada corre en el agente de su conversación | Manda `selection_context` | Lo añade si falta y lo corrige si es de otra conversación | Resuelve por el argumento o por la sesión de transporte |
| Un conflicto entre conversaciones no se salta | Pregunta a la persona | Niega las llamadas de contenido hasta volver a elegir | Rechaza con `agent_context_conflict` |
| Si la selección caduca, se vuelve al mismo agente | Vuelve a elegir el mismo, con palabras de la persona | Niega las llamadas de contenido hasta volver a elegir | Rechaza con `agent_not_selected` |
| No se pasa a una versión nueva del agente sin pedirlo | Avisa y sigue con la elegida | Para volver a elegir pide un mensaje de la persona posterior al aviso | Volver a elegir toma la última versión |
| No se mezclan lecturas de dos versiones | Vuelve a abrir lo que necesita | Olvida lo leído cuando cambia la versión y lo dice | Sirve siempre la versión elegida |
| Herramienta retirada para el agente | No la llama | Niega la llamada | Contesta que no existe |
| Una lectura con continuación no está completa | Sigue los cursores | Avisa al modelo de cada lectura o listado parcial | Marca el corte y da la continuación |
| Vista previa antes de aplicar | La pide y la muestra | Niega `confirm: true` sin una vista previa de esos mismos argumentos de los últimos 30 minutos | Sin `confirm` sólo previsualiza. No exige la vista previa |
| Una escritura confirmada no se repite | Lee de nuevo en vez de reescribir | Niega la misma escritura durante 30 minutos | No tiene clave de idempotencia en memoria |
| Un resultado incierto se comprueba leyendo | Lee antes de repetir | Niega repetir hasta que haya una lectura que muestre si se aplicó: la memoria para una memoria, el catálogo o la vista previa para un cambio del catálogo | No define recuperación para memoria |
| La memoria compartida no se usa por defecto | Sólo si la persona lo pide | Pregunta a la persona cada vez | La convierte en propuesta que aprueba una persona |
| Borrar para siempre lo pide la persona | Copia sus palabras | Busca la cita en sus mensajes | Exige `confirm` y una cita no vacía |
| Reintentos con límite | Se detiene al tercero | Niega el cuarto intento seguido durante 10 minutos | Devuelve `retry_after` real |
| Tras una compactación se retoma el mismo agente | Recupera agente y cerebro | Devuelve al modelo el estado guardado | El sello sigue vivo en el servidor |
| No se mezclan dos versiones del plugin | Nada | Si el plugin cambió a mitad de la sesión, pide recargar la Skill | Nada |
| Lo que devuelve una herramienta es dato | Sí | Sólo sus consecuencias más graves: elegir agente y borrar | Los permisos del agente |
| Respuestas sin detalles internos | Sí | Nada | Nada |
| Entregables por el procedimiento del agente | Sí | Nada | Nada |

Lo que sólo sostiene la Skill se mide con las evaluaciones de `evals/`, que corren un
modelo real contra un conector simulado. Miden muestras: un caso que pasa tres veces
dice que el modelo cumplió esas tres veces.

## Dónde corre el cliente

| Aplicación | ¿Corren los controles? | Cómo se sabe |
|---|---|---|
| Claude Code (terminal, pestaña Code del escritorio, VS Code) | Sí | Comprobado en la versión 2.1.286: corrieron dentro de las evaluaciones y dejaron su estado |
| Codex (CLI, escritorio, ChatGPT Work local) | Sin comprobar | Su documentación dice que lee `hooks/hooks.json` de un plugin y que los omite hasta que la persona confía en ellos |
| Grok Build | Sin comprobar | Su documentación dice que corre hooks de plugins, que sólo `PreToolUse` bloquea y que ignora la salida de los demás eventos. Ahí valdrían las negaciones y no los avisos al modelo |
| Claude (chat web y de escritorio) | No | Los hooks de un plugin se ignoran en el chat |
| ChatGPT (chat) | No | El chat no ejecuta hooks |

Donde no corren, quedan la Skill y Datalum. Los controles necesitan Node 18 o posterior
en la máquina. Si falta, la aplicación sigue sin ellos y no bloquea nada.

Los controles nunca aprueban una llamada por la persona. Pueden negar, preguntarle a la
persona o completar un argumento; la decisión de permitir sigue en el panel de la
aplicación.

## Lo que guarda el cliente

Un archivo por sesión en el directorio de datos del plugin, legible sólo por el usuario
del sistema y protegido con un candado, porque la aplicación puede lanzar a la vez los
controles de varias llamadas paralelas: qué agente y versión eligió la conversación, su contexto, qué documentos
del cerebro se leyeron, qué escrituras quedaron confirmadas o inciertas y la cuenta de
fallos. No guarda cifras, filas, mensajes de la persona ni credenciales. Para comprobar
una cita lee la transcripción que entrega la aplicación y no copia nada de ella. Los
archivos de más de siete días se borran al iniciar una sesión.

## Los paneles de cada aplicación

Cuántas veces se le pide permiso a la persona lo decide la aplicación. El plugin no lo
cambia.

| Aplicación | Qué ofrece su panel | Límite |
|---|---|---|
| Claude (web y escritorio) | Por herramienta o grupo: permitir siempre, pedir aprobación o bloquear. En el aviso: permitir una vez o siempre | Lo configura cada persona, o la organización |
| Claude Code | Reglas de permiso por herramienta, con `mcp__plugin_datalum_datalum__*` para todo el conector | Sin comprobar cómo se combina una regla de permitir con un «preguntar» de los controles |
| ChatGPT | Preguntar siempre, permitir lecturas, permitir acciones de bajo riesgo o permitir todo | «Permitir siempre» no se ofrece a miembros de espacios gestionados. La lista de herramientas del conector queda fija hasta que un administrador pulsa Refresh |
| Grok Build | Modo «Ask» con «Always allow» y «Never allow», y reglas por servidor | Sin comprobar |

Si la aplicación pregunta en cada llamada de lectura, el arreglo está en su panel:
permitir las lecturas de Datalum. Las confirmaciones que pide el asistente en la
conversación son otra cosa y la Skill las acota a una por encargo.

## Lo que todavía pide un cambio de plataforma

Son propuestas para quien administra el servidor. Hoy el plugin cubre cada hueco desde
el cliente, donde puede, o lo deja escrito como límite.

| Hueco | Qué pasa hoy | Propuesta |
|---|---|---|
| Sólo `use_agent` dice bajo qué agente corrió una llamada | Si una llamada corre con el agente de otra conversación, la respuesta no lo delata | Que cada respuesta nombre el agente y la versión con que se sirvió |
| El texto de `agent_context_conflict` manda quitar el contexto y repetir | Seguirlo puede correr la llamada con el agente de otra conversación | Que el rechazo mande volver a elegir |
| La cita de la elección se devuelve y no se guarda | No queda rastro de con qué palabras se eligió | Guardarla en la bitácora |
| Volver a elegir tras una caducidad toma la última versión | Recuperar una sesión puede cambiar de versión sin que nadie lo pida | Permitir volver a elegir conservando la versión |
| La memoria no tiene clave de idempotencia ni recuperación definida ante un tiempo agotado | Repetir una escritura deja una versión invalidada de más | Una clave de idempotencia en `remember` |
| El catálogo no marca qué herramientas leen y cuáles escriben | El cliente sólo reconoce como escritura la memoria y las llamadas con `confirm: true` | Publicar `readOnlyHint` en las anotaciones de cada herramienta |
| No hay un contrato público por despliegue | El plugin depende de un aviso con el resumen | Ver `integracion-servidor/README.md` |

## Lo que nada de esto garantiza

Que un documento del cerebro se haya entregado completo no prueba que el modelo lo
entendió ni que lo va a obedecer. Los controles reducen errores concretos y dejan
rastro; no vuelven determinista a un modelo ni eliminan las respuestas equivocadas. Las
cifras salen de Datalum y los cálculos propios del asistente se hacen con código donde
la aplicación lo permite, pero una respuesta libre se evalúa aparte.
