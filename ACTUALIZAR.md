# Cómo llega una versión nueva a cada aplicación

Publicar una versión del plugin y que una persona la esté usando son cuatro pasos
distintos, y cada aplicación resuelve cada uno a su manera.

1. Publicación. La versión queda etiquetada en este repositorio, con
   `datalum-skill.zip` en Releases y `main` en esa versión.
2. Catálogo. El catálogo de la aplicación se entera de que hay versión nueva.
3. Instalación. La copia instalada en la cuenta o en la máquina cambia a esa versión.
4. Sesión. Una conversación que ya estaba abierta empieza a usarla.

El paso 1 lo hace este repositorio, solo o a mano (`MANTENER.md`). Los demás dependen
de la aplicación. Ninguna aplicación documenta que una conversación abierta cambie de
versión por su cuenta.

## Por aplicación

Lo que sigue sale de la documentación de cada producto, leída el 3 de octubre de 2026.
En esta tarea no se instaló el plugin en ninguna aplicación, así que ningún camino de
actualización se ejercitó de punta a punta. La columna «Automático» dice lo que ocurre
sin que nadie haga nada después de la publicación.

| Aplicación | Catálogo | Instalación existente | Sesión abierta | Automático |
|---|---|---|---|---|
| Claude Code | Este repositorio es su catálogo. Compara el campo `version` | `claude plugin update datalum@datalum`, o `/plugin marketplace update datalum`. La actualización automática viene apagada en catálogos de terceros; se enciende en `/plugin` > Marketplaces y corre al iniciar una sesión | Sigue con la versión cargada hasta `/reload-plugins` o una sesión nueva | Sólo si la persona encendió la actualización automática |
| Claude (web y escritorio), Skill subida por la persona | No hay | En Personalizar > Skills se borra la anterior y se sube el zip nuevo | Sin documentar | No |
| Claude, plugin de la organización | Configuración de la organización > Plugins y skills | «Upload new version», con historial y reversión. Si la organización enlazó este repositorio, se sincroniza con «Re-sync» o en cada push con webhook | Sin documentar | Sólo con el repositorio enlazado y el webhook puesto |
| Claude, directorio público | El directorio sigue una rama del repositorio. Cada versión pasa validación y, por defecto, un revisor la publica | Quien lo tiene instalado la recibe sola | Sin documentar | Sí, después de la revisión. Datalum no está en el directorio |
| ChatGPT, Skill subida | No hay | La documentación no describe cómo se reemplaza una Skill suelta | Las skills se toman al empezar un chat nuevo | No |
| ChatGPT, plugin importado por el administrador | Admin > Plugins > Import marketplace, desde GitHub | Se sincroniza una vez al día, o con «Sync now» | Chat nuevo | Sí, al día siguiente. Un plugin que declara su servidor en `.mcp.json` queda sólo para escritorio |
| ChatGPT, conector | Aparte de la Skill | La lista de herramientas queda fija hasta que un administrador pulsa Refresh; lo nuevo llega desactivado. En Business hay que recrear la app | Chat nuevo | No |
| Grok Build | Un PR en el catálogo de xAI fija un commit. Un proceso diario abre el PR cuando cambia `version`; la revisión es manual | `grok plugin update` | Sin documentar | No: cada versión espera la revisión de xAI. La solicitud de alta sigue abierta y sin revisar |

Fuentes: [Claude Code, instalar y actualizar plugins](https://code.claude.com/docs/en/plugins/install),
[Claude, skills](https://claude.com/docs/skills/how-to),
[Claude, plugins de la organización](https://claude.com/docs/plugins/admin),
[Claude, publicar en el directorio](https://claude.com/docs/plugins/submit),
[ChatGPT, skills](https://help.openai.com/en/articles/20001066-skills-in-chatgpt),
[ChatGPT, gestión de plugins](https://learn.chatgpt.com/docs/enterprise/plugin-management),
[ChatGPT, modo desarrollador y apps MCP](https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt),
[Grok Build, plugins](https://docs.x.ai/build/features/skills-plugins-marketplaces),
[catálogo de xAI](https://github.com/xai-org/plugin-marketplace/blob/main/CONTRIBUTING.md).

## El paso mínimo cuando no es automático

| Tienes | Haz esto |
|---|---|
| Claude Code | Escribe `/plugin marketplace update datalum` y después `/reload-plugins` |
| Claude con la Skill subida | Descarga el [zip nuevo](https://github.com/Vinden-NewAge/datalum-plugin/releases/latest/download/datalum-skill.zip), borra la Skill anterior en Personalizar > Skills y sube la nueva |
| ChatGPT con la Skill subida | Descarga el zip nuevo y reemplaza la Skill en Plugins > Skills. En un espacio de trabajo lo hace el administrador |
| ChatGPT cuando el asistente dice que una función de Datalum no existe | El administrador pulsa Refresh en Workspace settings > Apps |
| Grok Build | `grok plugin update`, cuando xAI haya aceptado la versión |

Para saber qué versión tienes, pregúntale al asistente «¿Qué versión de la Skill de
Datalum tienes?». La más reciente es la primera de
[Releases](https://github.com/Vinden-NewAge/datalum-plugin/releases).

## Lo que una actualización del plugin no toca

- El agente que eligió una conversación, ni su versión. Cambiar de agente o pasar a una
  versión nueva lo pide la persona.
- Los cerebros de los agentes. El plugin no los edita ni los guarda.
- Los permisos de nadie, ni en Datalum ni en la aplicación.
- La conexión. El conector no se reinstala al actualizar.
- Otras skills o herramientas instaladas en la máquina. El plugin no instala ni
  actualiza dependencias.

## Una conversación no mezcla dos versiones

Las instrucciones de una Skill se cargan al usarla y se quedan en la conversación. Si el
plugin se actualiza mientras una conversación está abierta, esa conversación sigue con
las instrucciones que cargó hasta que se recarga.

En Claude Code los controles del cliente lo vigilan: si después de `/reload-plugins` la
versión del plugin ya no es la que la conversación tenía, le dicen al modelo que vuelva
a cargar la Skill antes del siguiente paso con Datalum. En las demás aplicaciones lo
seguro es empezar una conversación nueva después de actualizar.
