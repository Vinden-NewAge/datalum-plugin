# Mantener el plugin

Guía para el equipo de Vinden. Dice cuándo hay que sacar una versión nueva y cómo llega a
cada producto.

## Cuándo sacar una versión

- **Cambió el catálogo del servidor.** Una herramienta nueva, retirada o renombrada, o un
  argumento que la Skill menciona. `scripts/check.py` falla si la Skill no nombra todas
  las herramientas que anuncia el servidor o si nombra una que ya no existe.
- **Cambió una regla de uso.** El arranque, la confirmación de cambios o lo que el
  servidor exige en sus instrucciones.
- **Algo de la Skill se entiende mal.** Un asistente la aplicó distinto de lo esperado.

## Pasos

1. Actualiza la lista de herramientas si cambió el servidor. Sale del repositorio del
   servidor, en la versión publicada, con la función que arma la lista anunciada. Se
   copia a `scripts/server-tools.txt` junto con la versión del servidor en el
   encabezado.
2. Edita `skills/datalum/SKILL.md`.
3. Sube la versión en dos lugares, con el mismo número X.Y.Z:
   - `.claude-plugin/plugin.json` → `version`
   - `skills/datalum/SKILL.md` → `metadata.version`
4. Agrega la sección `## [X.Y.Z] - AAAA-MM-DD` arriba de todo en `CHANGELOG.md`: qué
   cambia para quien la usa, contra qué versión del servidor se comprobó y qué tiene que
   hacer para recibirla.
5. Comprueba y empaqueta:
   ```bash
   python3 scripts/check.py
   python3 scripts/package.py
   ```
6. Abre un PR. La revisión automática corre las mismas comprobaciones.
7. Tras fusionar, etiqueta la versión y súbela:
   ```bash
   git tag vX.Y.Z
   git push origin vX.Y.Z
   ```
   La publicación automática vuelve a comprobar, empaqueta la Skill y crea la versión en
   GitHub con `datalum-skill.zip` y las notas del CHANGELOG. El enlace
   `releases/latest/download/datalum-skill.zip` pasa a entregar la nueva.

## Cómo llega a cada producto

| Producto | Qué pasa después de publicar |
|---|---|
| Grok Build | Una vez al día, xAI revisa los plugins cuya versión cambió y abre por su cuenta el cambio en su catálogo. Lo revisan a mano antes de aceptarlo |
| Claude Code | Los usuarios la reciben con `/plugin marketplace update datalum` o con la actualización automática |
| Claude (web y escritorio) y ChatGPT | Hay que avisar a los clientes: cada uno descarga el zip nuevo y reemplaza el anterior. En ChatGPT de empresa lo hace el administrador |

## Reglas

- **Una sola Skill para todos los productos.** No se hacen copias por producto: dos copias
  del mismo texto terminan diciendo cosas distintas.
- **Nada de valores copiados que otra fuente gobierna.** La Skill remite al servidor y al
  agente; sólo repite lo mínimo para que el asistente arranque. La dirección del servidor
  vive en `.mcp.json` y `scripts/check.py` exige que los demás archivos la repitan igual.
- **Sin secretos.** El repositorio es público: ni claves, ni datos de clientes, ni código
  del servidor.
- **La Skill no nombra un producto de IA** salvo cuando la instrucción sólo vale para él.
  OpenAI lo exige para aceptar Skills.
