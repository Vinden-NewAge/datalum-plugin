# Mantener el plugin

Guía para el equipo de Vinden. Dice qué hay en el repositorio, cómo sale una versión,
cómo se comprueba el plugin después de cada despliegue de Datalum y qué hacer cuando
esa comprobación no termina sola.

## Qué hay aquí

| Carpeta o archivo | Qué es | ¿Llega a una instalación? |
|---|---|---|
| `skills/datalum/` | La Skill y la ficha de ChatGPT | Sí. Es lo que va en `datalum-skill.zip` |
| `client/`, `hooks/` | Los controles que corren en el cliente | Sí, en las aplicaciones que cargan el plugin entero |
| `.claude-plugin/`, `.mcp.json` | Manifiesto, catálogo y dirección del servidor | Sí |
| `compat/` | Lo que el plugin necesita del servidor, el último contrato comprobado y el registro | No |
| `scripts/` | Comprobador, empaquetador y automatización | No |
| `tests/`, `evals/` | Pruebas de código, pruebas documentales y evaluaciones con modelo | No |
| `integracion-servidor/` | Qué tiene que mandar el despliegue de Datalum al terminar | No |

Un cambio en lo que llega a una instalación es una versión nueva. Un cambio en lo demás
no lo es.

## La comprobación después de cada despliegue

El flujo `compat.yml` corre cuando un despliegue de Datalum avisa que terminó, cada
hora por su cuenta y cuando una persona lo lanza. Hace siempre lo mismo:

1. Le pregunta al servidor desplegado qué commit sirve y si pasa su salud (`/health`).
   La dirección la toma de `.mcp.json`, nunca del aviso. Si el aviso habla de un commit
   que el servidor no sirve, lo anota como no confirmado y termina.
2. Consigue el contrato de ese commit: del aviso, de `compat/contratos/` si ese commit
   ya se había visto, o del propio servidor si hay credencial de lectura.
3. Coteja ese contrato con lo que el servidor contesta sin sesión: las instrucciones y
   el protocolo. Con credencial de lectura coteja el catálogo completo.
4. Lo compara con `compat/requisitos.json` y con el último contrato comprobado.
5. Si hace falta, regenera `client/contract-facts.json` y sube la versión.
6. Corre `check.py`, las pruebas y el empaquetado sobre el resultado.
7. Publica: etiqueta, borrador con los archivos, descarga y cotejo, publicación, segunda
   descarga y cotejo.
8. Añade una línea a `compat/registro.jsonl` y lleva `main` a ese punto.

La comparación sale en una de cuatro clases:

| Clase | Cuándo | Qué hace el flujo |
|---|---|---|
| `sin_cambios` | El contrato es el mismo que el último comprobado | Anota la compatibilidad. La versión del plugin no cambia |
| `compatible` | Cambió algo que el plugin no usa, o algo que se resuelve regenerando archivos derivados | Si lo derivado cambió, publica una versión de parche. Si no, sólo anota |
| `revision` | Cambió el texto de las instrucciones del servidor o la definición de una herramienta que el plugin usa | No publica. Guarda el texto nuevo y abre un issue para que una persona lo lea |
| `incompatible` | Falta una herramienta o un argumento que el plugin usa, o hay un argumento obligatorio nuevo | No publica. Abre un issue con la propuesta |

Un entorno previo a producción (`qa`) recorre los mismos pasos, prepara la versión que
saldría en producción, la prueba y la empaqueta, y termina en `candidata_lista`. Nunca
publica y nada de la candidata llega a `main`: quedan el contrato guardado y una línea
con la huella del contenido que pasó las pruebas. Un cambio incompatible se ve ahí,
antes de producción. Cuando producción sirve ese mismo contrato, el flujo vuelve a
construir y a probar, y la línea del registro dice si lo publicado es lo mismo que probó
el entorno previo (`candidata.promovida`).

### Los resultados del registro

| Resultado | Significado | ¿Se reintenta solo? |
|---|---|---|
| `compatible_sin_cambios` | Comprobado. La versión publicada sirve para ese despliegue | Cerrado |
| `actualizado` | Se publicó y se verificó una versión nueva | Cerrado |
| `candidata_lista` | Entorno previo comprobado, con su candidata probada | Cerrado |
| `revision_requerida` | Espera que una persona lea un texto | Cerrado hasta que cambie `requisitos.json` |
| `incompatible` | Espera una decisión | Cerrado hasta que cambie el plugin |
| `despliegue_no_confirmado` | El servidor no pasa salud o sirve otro commit | Sí, con el siguiente aviso o la lectura de la hora siguiente |
| `contrato_no_disponible` | El servidor sirve un commit del que no hay contrato | Sí, cuando llegue el aviso con el contrato |
| `contrato_no_coincide` | El contrato del aviso no es el que sirve el servidor | Sí |
| `pruebas_fallidas` | Las pruebas no pasan con el contrato nuevo | Sí |
| `publicacion_fallida` | Algún paso de la publicación falló | Sí |
| `paquete_no_coincide` | Lo descargado no es lo que se probó; la versión volvió a borrador | Sí |
| `retirada_fallida` | Lo publicado no es lo que se probó y no se pudo devolver a borrador: sigue a la vista | Sí, y el reintento la retira antes de publicar |

Mientras el último despliegue confirmado de producción esté en un resultado cerrado,
repetir el mismo aviso no hace nada. Con un resultado que se reintenta, la lectura de la
hora siguiente vuelve a intentarlo.

### Qué impide cada error

| Riesgo | Cómo se evita |
|---|---|
| Tomar un push, una etiqueta o el inicio de un despliegue por «producción cambió» | Sólo cuenta lo que contesta el servidor desplegado |
| Un aviso falso que apunte a otro servidor | La dirección sale del repositorio |
| Un despliegue viejo que pise al más reciente | Las corridas van en fila por entorno, parten del `main` del momento y cada una vuelve a preguntar qué se sirve |
| Que la lectura de cada hora desplace un aviso en espera | Va en su propio grupo y cede el turno si hay otra comprobación en marcha |
| Dos corridas que escriben a la vez | El cierre parte del mismo commit que la comprobación. Si `main` se movió, no lo pisa: deja una rama, abre el PR si puede y la corrida termina en rojo |
| Dos versiones por el mismo despliegue | Un despliegue cerrado no se vuelve a procesar; una etiqueta que existe se reutiliza |
| Cambiar una versión publicada | Una etiqueta o una versión con otro contenido detiene todo |
| Publicar algo distinto de lo probado | Se compara la huella del contenido antes de etiquetar, y la de los archivos antes y después de publicar. Si lo publicado no coincide, vuelve a borrador y se comprueba que volvió; si no vuelve, el resultado es `retirada_fallida` |
| Confundir una descarga fallida con otros archivos | Si no se pueden descargar los archivos de una versión que existe, el intento termina en `publicacion_fallida` sin retirar nada |
| Anunciar una actualización que no terminó | `main` se mueve al final. Si algo falla antes, la última versión válida sigue siendo la vigente y el flujo termina en rojo |
| Revertir producción por un fallo del plugin | El flujo no tiene permisos ni código para tocar el servidor |

### Lo que hay que configurar

| Qué | Dónde | Para qué | Sin eso |
|---|---|---|---|
| El paso de aviso y la sonda de contrato | Repositorio del servidor | Que el despliegue avise cuando termina, con su contrato | La lectura de cada hora ve el cambio de commit y anota `contrato_no_disponible` |
| Secreto `DATALUM_PLUGIN_DISPATCH_TOKEN` | Repositorio del servidor | Disparar `compat.yml`. Permiso: Actions, lectura y escritura, sólo sobre este repositorio | No hay aviso |
| Variable `COMPAT_ACTORES` | Este repositorio | Aceptar avisos sólo de esa cuenta | Se acepta el aviso de cualquiera que pueda lanzar el flujo. El servidor lo confirma igual |
| Secreto `DATALUM_COMPAT_TOKEN` | Este repositorio | Leer el catálogo completo del servidor desplegado | El cotejo es parcial: commit, instrucciones y protocolo |
| «Allow GitHub Actions to create and approve pull requests» | Ajustes de este repositorio | Abrir el PR cuando `main` no admita el empuje directo | Queda la rama `auto/compat-…` y el flujo lo dice; alguien abre el PR |

Qué tiene que mandar el servidor está en `integracion-servidor/README.md`. GitHub apaga
los flujos programados de un repositorio sin actividad durante 60 días; un aviso de
despliegue o cualquier commit lo evita.

### Lanzarla a mano

Desde la pestaña Actions, «Compatibilidad con Datalum» > Run workflow. Sin argumentos
comprueba lo que producción sirve en ese momento. Con «simular» recorre los pasos sin
publicar ni escribir.

Para darle el contrato de un commit cuando el servidor todavía no avisa, arma el
resumen con la sonda del servidor, o guarda el `tools/list` completo de una sesión
iniciada y pásalo por `python3 scripts/compat.py resumir`. Después:

```bash
gh workflow run compat.yml -f entorno=prod -f sha=<commit de 40 caracteres> -f contrato="$(cat contrato.json)"
```

## Cuando la comprobación no termina sola

| Resultado | Qué hacer |
|---|---|
| `revision_requerida` | Lee el texto nuevo. Las instrucciones quedan en `compat/instrucciones/<huella>.txt` y se comparan con `diff` contra las anteriores; la definición de una herramienta se lee en el conector. Si la Skill y los controles siguen valiendo, añade la huella a `instrucciones_revisadas` o a `definiciones_revisadas` en `compat/requisitos.json`, por PR. Si no, cambia la Skill en ese mismo PR. El despliegue se cierra con la lectura de la hora siguiente |
| `incompatible` | Sigue «Cambios incompatibles», más abajo |
| `contrato_no_disponible` | Lanza el flujo a mano con el contrato, como arriba |
| `contrato_no_coincide` | El aviso se armó con otro árbol que el desplegado. Revisa en el servidor de qué commit salió y vuelve a lanzar con el contrato del commit servido |
| `despliegue_no_confirmado` | Mira `/health`. Si el servidor está sano y sirve otro commit, el aviso era de un despliegue que no quedó: no hay nada que hacer |
| `pruebas_fallidas` | Corre las pruebas en local con el contrato de `compat/contratos/<commit>.json`. El fallo dice qué supuesto del plugin dejó de valer |
| `publicacion_fallida` | Vuelve a lanzar el flujo. Reconoce la etiqueta y el borrador que quedaron y sigue desde ahí. Si el detalle dice que la etiqueta existe con otro contenido, alguien publicó esa versión a mano: sube la versión por PR |
| `paquete_no_coincide` | La versión volvió a borrador. Vuelve a lanzar. Si se repite, compara el zip de la versión con `python3 scripts/package.py` en la etiqueta |
| `retirada_fallida` | Urgente: hay a la vista una versión con archivos que no se probaron. Vuelve a lanzar la comprobación: como el intento anterior fue suyo, la retira, comprueba que quedó en borrador y publica lo probado. Si tampoco puede, devuélvela a borrador a mano en Releases. Para una versión publicada a mano: `python3 scripts/compat.py publicar --tag vX.Y.Z --recuperar` |
| La corrida terminó en rojo con «main no avanzó» | Otra corrida movió `main` mientras ésta trabajaba. Vuelve a lanzar la corrida desde Actions con «Re-run»: conserva las entradas, contrato incluido, y parte del `main` nuevo. Si había publicado una versión, la reconoce y no la duplica. Borra después la rama `auto/compat-…` que quedó |

Tras un rollback de producción la lectura de cada hora ve el commit anterior, usa su
contrato guardado y comprueba el plugin contra él. Si el contenido derivado cambia,
publica una versión de parche nueva; las anteriores siguen publicadas.

## Cambios incompatibles

Un cambio incompatible no se arregla en un solo paso, porque hay instalaciones que no
se actualizan solas y conversaciones abiertas con la versión anterior cargada
(`ACTUALIZAR.md`). El orden es:

1. El servidor anuncia el cambio con fecha y conserva el contrato anterior hasta esa
   fecha, como hizo con los códigos de estado del 4 de noviembre.
2. El plugin publica una versión que funciona con los dos contratos. Mientras dure la
   transición, `compat/requisitos.json` declara sólo lo común a los dos.
3. Se avisa a quienes actualizan a mano, con la sección del CHANGELOG.
4. Pasada la fecha, el servidor retira lo anterior y el plugin publica la versión que
   ya no lo menciona.

El aviso del entorno previo sirve para enterarse en el paso 1 y no en producción.

## Sacar una versión a mano

Cuando cambia la Skill, los controles o lo que el plugin necesita del servidor.

1. Edita lo que cambie. Si la Skill nombra una herramienta nueva, declárala en
   `compat/requisitos.json` con los argumentos que usa.
2. Sube el mismo número X.Y.Z en `.claude-plugin/plugin.json`, en `metadata.version` de
   la Skill y en su línea «This is version X.Y.Z of the Datalum skill.»
3. Agrega arriba del CHANGELOG la sección `## [X.Y.Z] - AAAA-MM-DD`.
4. Comprueba:
   ```bash
   python3 scripts/check.py
   ```
   ```bash
   python3 -m unittest discover -s tests -t .
   ```
   ```bash
   node --test tests/client/*.test.js
   ```
   ```bash
   claude plugin validate .
   ```
5. Corre las evaluaciones si cambió la Skill o los controles (ver «Pruebas»).
6. Abre el PR. La revisión automática corre lo del paso 4.
7. Tras fundirlo, etiqueta el `main` actualizado con `vX.Y.Z` y empuja la etiqueta.
   `release.yml` publica con las mismas comprobaciones que el camino automático.

## Pruebas

Hay tres clases y ninguna sustituye a otra.

| Clase | Dónde | Qué prueba | Qué no prueba |
|---|---|---|---|
| Documentales | `tests/docs/` | Que la Skill y las guías dicen lo que tienen que decir | Que alguien lo cumpla |
| De código | `tests/compat/`, `tests/client/` | La automatización, con git real y un servidor de mentira, y los controles del cliente | El comportamiento de un modelo |
| Con modelo real | `evals/` | Que un modelo, con la Skill y los controles, se comporta bien ante cada caso | Otro modelo, otra aplicación, o el servidor de verdad |

Las evaluaciones corren con `claude plugin eval`, que no instala el plugin: lo carga en
una sesión aislada con un conector simulado. Cada corrida es una llamada real al modelo
en la cuenta de quien la lanza.

```bash
claude plugin eval . --tag base --no-publish
```

```bash
claude plugin eval . --tag con-archivos --allow-tools Write --no-publish
```

El conector simulado vive en `evals/mocks/datalum/`. Sus datos son inventados. La
estructura de argumentos de `_tools.json` sale del catálogo real; las descripciones
están escritas para la suite y son más cortas que las del servidor. Para una corrida con
las descripciones reales, guarda ahí el `tools/list` del conector sin versionarlo.

## Reglas

- **Una sola Skill para todos los productos.** Dos copias del mismo texto terminan
  diciendo cosas distintas.
- **El plugin no es un segundo cerebro.** La Skill conecta, carga el cerebro del agente
  y mantiene la sesión. No lleva reglas de negocio ni un catálogo de herramientas.
  `check.py` falla si nombra más de diez.
- **Los controles sólo hacen cumplir lo que el contrato ya dice.** No aprueban llamadas
  por la persona ni deciden por el agente.
- **La dirección del servidor vive en `.mcp.json`.** `check.py` exige que los demás
  archivos la repitan igual.
- **Sin secretos.** El repositorio es público: ni claves, ni datos de clientes, ni
  código del servidor. Los contratos guardados llevan nombres y huellas, sin
  descripciones.
- **Sin carpeta `bin/` en la raíz.** Claude se niega a instalar un plugin que la tenga.
- **La Skill no nombra un producto de IA** salvo cuando la instrucción sólo vale para
  él. OpenAI lo exige para aceptar Skills.
