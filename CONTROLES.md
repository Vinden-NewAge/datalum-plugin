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
| La elección de agente es de la persona | Copia sus palabras; con un solo agente, las del mensaje con que pidió el trabajo. Pregunta con opciones si la aplicación lo permite | Exige evidencia de consentimiento (ver «Qué cuenta como consentimiento»). Sin ella, la aplicación le pregunta a la persona | Exige una cita no vacía. No mira su contenido |
| Lo pegado, un documento o lo que devuelve una herramienta no eligen agente | Lo trata como dato | No cuentan como elección de la persona | Nada |
| Cada llamada corre en el agente de su conversación | Manda `selection_context` | Lo añade si falta y lo corrige si es de otra conversación | Resuelve por el argumento o por la sesión de transporte |
| Un conflicto entre conversaciones no se salta | Pregunta a la persona | Niega las llamadas de contenido hasta volver a elegir | Rechaza con `agent_context_conflict` |
| Si la selección caduca, se vuelve al mismo agente | Vuelve a elegir el mismo, con palabras de la persona | Niega las llamadas de contenido hasta volver a elegir | Rechaza con `agent_not_selected` |
| No se pasa a una versión nueva del agente sin pedirlo | Avisa y sigue con la elegida | Volver a elegir el agente con una versión nueva a la vista se lo pregunta la aplicación a la persona | Volver a elegir toma la última versión |
| No se mezclan lecturas de dos versiones | Vuelve a abrir lo que necesita | Olvida lo leído cuando cambia la versión y lo dice | Sirve siempre la versión elegida |
| Herramienta retirada para el agente | No la llama | Niega la llamada | Contesta que no existe |
| Gráficas y tableros de Datalum en pausa | No llama a sus herramientas, aunque el cerebro las nombre, y lo dice | Niega toda herramienta de esas familias que traiga el contrato, también las nuevas. La lista se deriva en `client/contract-facts.json` | Las sigue sirviendo |
| Una lectura con continuación no está completa | Sigue los cursores | Avisa al modelo de cada lectura o listado parcial | Marca el corte y da la continuación |
| Vista previa antes de aplicar | La pide y la muestra | Niega `confirm: true` sin una vista previa de esos mismos argumentos de los últimos 30 minutos | Sin `confirm` sólo previsualiza. No exige la vista previa |
| Una escritura confirmada no se repite | Lee de nuevo en vez de reescribir | Niega la misma operación durante 30 minutos. La operación es del agente que la hizo: otro agente con los mismos argumentos hace la suya | No tiene clave de idempotencia en memoria |
| Un resultado incierto se comprueba leyendo | Lee el mismo destino antes de repetir | Ver «Resultados de una escritura» | No define recuperación para memoria |
| La memoria compartida no se usa por defecto | Sólo si la persona lo pide | Pregunta a la persona cada vez | La convierte en propuesta que aprueba una persona |
| Borrar para siempre lo aprueba la persona | Copia sus palabras | La aplicación le pregunta a la persona cada vez. Si aprobó y la llamada falló, puede reintentarse esa misma operación durante 15 minutos | Exige `confirm` y una cita no vacía |
| Reintentos con límite | Se detiene al tercero | Niega el cuarto intento seguido durante 10 minutos | Devuelve `retry_after` real |
| Tras una compactación se retoma el mismo agente | Recupera agente y cerebro | Devuelve al modelo el estado guardado | El sello sigue vivo en el servidor |
| No se mezclan dos versiones del plugin | Nada | Si el plugin cambió a mitad de la sesión, pide recargar la Skill | Nada |
| Lo que devuelve una herramienta es dato | Sí | Sólo sus consecuencias más graves: elegir agente, adoptar una versión y borrar | Los permisos del agente |
| Respuestas sin detalles internos | Sí | Nada | Nada |
| Entregables por el procedimiento del agente | Sí | Nada | Nada |

Lo que sólo sostiene la Skill se mide con las evaluaciones de `evals/`, que corren un
modelo real contra un conector simulado. Miden muestras: un caso que pasa tres veces
dice que el modelo cumplió esas tres veces.

## Qué cuenta como consentimiento

Que el cliente deje pasar una llamada no es una autorización: sólo quiere decir que no
se opone. Después la aplicación aplica sus permisos y Datalum los suyos. Para elegir un
agente, adoptar una versión nueva o borrar, el cliente busca evidencia de que lo decidió
la persona, y cuenta:

- Lo que la persona eligió en una pregunta de la aplicación, con el nombre exacto del
  agente, después de que el asistente obtuvo la lista de agentes. Cuenta sólo si es la
  respuesta a la herramienta de preguntas de la aplicación; una respuesta de otra
  herramienta con la misma forma es un dato.
- Un mensaje de la persona que es sólo el nombre del agente.
- Con un único agente en la lista, el contrato de Datalum, que manda usarlo.
- Lo que la persona aprobó en el diálogo de permisos que la aplicación le muestra cuando
  el cliente pide preguntar.

No cuenta una cita que nombra al agente: «No uses el agente Finanzas» también lo nombra.
No se usan listas de palabras para leer intenciones.

Una elección vale para su agente durante la conversación, también tras una caducidad o
una compactación: no se vuelve a preguntar. Deja de valer al soltar el agente, al elegir
otro o al empezar una sesión nueva.

Cada elección de la persona sirve una vez. La respuesta que ya eligió un agente sigue en
la conversación, pero no vuelve a elegirlo después de soltarlo ni elige a otro. Para
cambiar de agente, la Skill manda soltar el actual y elegir el nuevo: lo que la persona
eligió para ese cambio cuenta aunque el modelo suelte el anterior después. Tras soltar un
agente, el único de la lista ya no se da por elegido. Adoptar una versión nueva y cada
borrado se le preguntan a la persona.

Límites:

- En el modo `bypassPermissions` la aplicación no muestra diálogos. Ahí el cliente niega
  lo que necesitaría uno y le pide al modelo que pregunte con opciones. En `dontAsk` la
  aplicación deniega sola lo que tendría que preguntar.
- El texto de una pregunta lo escribe el modelo. Lo que el cliente registra es la opción
  que eligió la persona, o su mensaje que es sólo el nombre del agente, no el sentido de
  la pregunta que contestaba.
- El cliente sabe que se preguntó, no quién contestó. Si en la aplicación otro
  componente aprueba por la persona (un hook de solicitud de permiso de otro plugin, un
  mod o el programa que usa el SDK con su propia función de permisos), el cliente lo
  toma como aprobación de la persona.
- Si la persona retira su elección sólo con palabras («ya no uses Ventas»), el cliente no
  lo sabe hasta que el modelo suelta el agente.
- Que el diálogo de la aplicación se muestre en cada modo está tomado de la documentación
  de Claude Code. No se probó en una sesión interactiva: las pruebas lanzan el adaptador
  con los eventos que entrega la aplicación.

## Resultados de una escritura

Antes de interpretar una respuesta, el cliente la lee según su contrato: el sobre de la
aplicación, el JSON que va como texto y, dentro, el recibo. `remember` devuelve el recibo
en la raíz y `brain_write`, dentro de `memory`. Cada capa se deserializa como JSON; el
texto de la memoria no se toca.

| Lo que pasó | Qué hace el cliente | Qué se le dice a la persona |
|---|---|---|
| El recibo dice `escrita` | La da por hecha y no deja repetirla | Que está guardada |
| El recibo dice `propuesta` | La da por presentada y no deja presentarla otra vez | Que espera la aprobación de una persona: no es una memoria todavía |
| Falló sin decir si se aplicó, como un tiempo agotado, o la respuesta no trae recibo | La deja incierta | Que no está confirmada |
| Estaba escrita y la relectura falló | Sigue escrita | Que está guardada y falta comprobar que se recupera |

Una escritura incierta sólo la resuelve una lectura posterior y completa del mismo
destino: el mismo agente, el mismo ámbito y el mismo nombre de memoria, pedida por ese
nombre. Cómo leerla lo dice el cerebro del agente: el cliente reconoce `brain_read` por la
ruta de la memoria y `list_memories` con `memory`, y sus avisos no imponen ninguna de las
dos. Una lectura por id no se puede asociar a la escritura y la deja incierta. Consultar
otra memoria, el índice o un documento del cerebro no es comprobar el resultado, aunque
muestren el mismo texto.

El cliente lee la memoria como la sirve Datalum: el archivo va dentro de un marco, con
cada línea prefijada con «| »; por la ruta del cerebro llega anidado; y «no existe»
llega como `agent_memory_not_found`.

| Lo que muestra esa lectura | Qué hace el cliente |
|---|---|
| La memoria viva trae el título y el cuerpo que se intentó escribir | La da por aplicada y no deja repetirla |
| La memoria personal no existe, o sigue viva la misma memoria, con el mismo id, que había antes | La da por no aplicada y deja un reintento, uno solo |
| Una memoria compartida no existe o sigue igual | La deja incierta: la propuesta puede estar esperando la aprobación de una persona |
| Está cortada, falló, es de otro agente o de otro ámbito, o trae otro id con otro contenido | La deja incierta |

Mientras nadie haya leído el destino, el cliente no deja repetir una escritura incierta
y pide leerlo primero. Si la lectura no la resolvió, repetirla lo decide la persona en el
diálogo de la aplicación, que le avisa de que puede duplicarla; en `bypassPermissions` se
niega. Un cambio del catálogo incierto no se puede comprobar desde el cliente: repetirlo
lo decide la persona desde el principio. Nada de esto
asegura que una operación se ejecute una sola vez; eso sólo podría hacerlo Datalum con
una clave de idempotencia.

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

Los controles nunca aprueban una llamada por la persona. Pueden negar, pedir que la
aplicación le pregunte a la persona o completar un argumento; la decisión de permitir
sigue en el panel de la aplicación.

## Lo que guarda el cliente

Un archivo por sesión en el directorio de datos del plugin, legible sólo por el usuario
del sistema y protegido con un candado, porque la aplicación puede lanzar a la vez los
controles de varias llamadas paralelas. Guarda:

- qué agente y versión eligió la conversación, su contexto y cómo se obtuvo la elección;
- qué documentos del cerebro se leyeron;
- por cada escritura, su estado y las huellas sha256 de su destino y su contenido, más el
  id de memoria que devolvió Datalum;
- la cuenta de fallos.

No guarda cifras, filas, mensajes ni citas de la persona, nombres o títulos de lo
escrito, ni credenciales. Una huella no es anonimato: con el texto en la mano se puede
comprobar si coincide. Para reconocer una elección lee la transcripción que entrega la
aplicación y no copia nada de ella. Si un control falla, el registro de depuración sólo
recibe la clase del error. Los archivos de más de siete días se borran al iniciar una
sesión.

Un estado guardado por la 2.0.0 se migra la primera vez que se lee: pierde la frase con
que se eligió el agente y conserva el agente, su contexto y las escrituras pendientes.
La 2.0.0 no guardaba qué agente hizo cada escritura: las posteriores a la elección del
agente vigente se le atribuyen a él, y las anteriores quedan sin dueño. Repetir una de
ésas, mientras dure su ventana de 30 minutos, lo decide la persona. El agente que estaba
elegido sigue elegido; lo que la persona eligió antes de actualizar no vuelve a elegir.

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
| La cita de la elección se exige y no se usa | Una cita auténtica no prueba consentimiento, y el servidor no puede saber si la persona aprobó | Que la elección y los borrados se confirmen en el panel o con un mecanismo del cliente que el servidor pueda verificar |
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
