# Mantener el plugin

Guía para el equipo de Vinden. Dice cuándo hay que sacar una versión nueva y cómo llega a
cada producto.

## Cuándo sacar una versión

- **Cambió el catálogo del servidor.** Una herramienta nueva, retirada o renombrada, una
  herramienta que gana o pierde `confirm`, o un argumento que la Skill menciona.
- **Cambió una regla de uso.** El arranque, la aprobación de cambios o lo que el
  servidor exige en sus instrucciones.
- **Algo de la Skill se entiende mal.** Un asistente la aplicó distinto de lo esperado.

## Pasos

1. **Lista de herramientas, si cambió el servidor.** En el repositorio del servidor,
   cámbiate a la etiqueta publicada (`git checkout vA.B.C`) y, desde
   `supabase/functions`, corre:
   ```bash
   deno eval --no-check 'import { buildToolsList } from "./mcp/interfaces/tools.ts"; for (const d of buildToolsList({ allowedTools: [] } as never).sort((a, b) => a.name.localeCompare(b.name))) console.log(d.inputSchema?.properties && "confirm" in d.inputSchema.properties ? `${d.name} confirm` : d.name);'
   ```
   Pega la salida en `scripts/server-tools.txt`, debajo del encabezado, y pon en el
   encabezado la versión y el commit del servidor. El diff muestra qué herramientas
   entraron, salieron o cambiaron de `confirm`.
2. **Skill.** Edita `skills/datalum/SKILL.md`. Si cambió el servidor, comprueba en su
   código lo que la Skill afirma y `check.py` no mide: los campos de la respuesta de
   `use_agent`, los códigos de error que nombra y las dos herramientas que no llevan
   `selection_context`.
3. **Versión.** Sube el mismo número X.Y.Z en tres lugares:
   - `.claude-plugin/plugin.json` → `version`
   - `skills/datalum/SKILL.md` → `metadata.version`
   - `skills/datalum/SKILL.md` → la línea «This is version X.Y.Z of the Datalum skill.»
4. **CHANGELOG.** Agrega arriba de todo la sección `## [X.Y.Z] - AAAA-MM-DD`: qué cambia
   para quien usa la Skill, contra qué versión del servidor se comprobó y qué tiene que
   hacer para recibirla.
5. **Comprobar.** Desde la raíz del repositorio:
   ```bash
   python3 scripts/check.py
   python3 scripts/package.py
   claude plugin validate .
   ```
6. **PR.** En una rama nueva:
   ```bash
   git switch -c version/X.Y.Z
   git commit -am "Versión X.Y.Z: <qué cambia>"
   git push -u origin version/X.Y.Z
   gh pr create --fill
   ```
   La revisión automática corre `check.py` y el empaquetado.
7. **Publicar.** Tras fusionar el PR, etiqueta el `main` actualizado:
   ```bash
   git switch main
   git pull
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
| Claude (web y escritorio) y ChatGPT | El equipo de Vinden avisa a los clientes con la sección del CHANGELOG; cada uno descarga el zip nuevo y reemplaza el anterior. En ChatGPT de empresa lo hace el administrador |

## Reglas

- **Una sola Skill para todos los productos.** No se hacen copias por producto: dos copias
  del mismo texto terminan diciendo cosas distintas.
- **La Skill remite al servidor y al agente.** Sólo repite lo mínimo para que el
  asistente arranque. La dirección del servidor vive en `.mcp.json`, y `scripts/check.py`
  exige que los demás archivos la repitan igual.
- **Las reglas de Datalum sólo acotan lo que el asistente hace con Datalum.** La Skill no
  pide ponerlas por encima de la persona, de las instrucciones del producto ni de sus
  reglas de seguridad: xAI rechaza una Skill que lo pida.
- **Sin secretos.** El repositorio es público: ni claves, ni datos de clientes, ni código
  del servidor.
- **La Skill no nombra un producto de IA** salvo cuando la instrucción sólo vale para él.
  OpenAI lo exige para aceptar Skills.
