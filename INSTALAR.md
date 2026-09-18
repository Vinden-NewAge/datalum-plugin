# Instalar Datalum en tu asistente

Datalum se instala en dos partes:

- **El conector**, que une tu asistente con el servidor de Datalum. Sin él, el asistente
  no ve ningún dato.
- **La Skill**, que le enseña al asistente cómo trabajar con Datalum: pedirte primero con
  qué agente trabajar, mostrarte cada cambio antes de hacerlo y sacar las cifras sólo de
  Datalum.

En Grok Build y en Claude Code las dos partes llegan juntas. En Claude (web y escritorio)
y en ChatGPT se agregan por separado.

## Antes de empezar

- Una cuenta de Datalum.
- Al menos un agente que el administrador de tu empresa te haya otorgado.
- La dirección del servidor: `https://mcp.datahub.vinden.cc/mcp`
- La Skill empaquetada:
  https://github.com/Vinden-NewAge/datalum-plugin/releases/latest/download/datalum-skill.zip

## Claude (web y escritorio)

Planes Pro, Max, Team y Enterprise, con la ejecución de código activada.

1. **Conector.** Entra a Personalizar > Conectores (Customize > Connectors) y elige
   Agregar conector personalizado (Add custom connector). Nombre: `Datalum`. Dirección:
   `https://mcp.datahub.vinden.cc/mcp`. Después pulsa Conectar e inicia sesión con tu
   cuenta de Datalum.
   - En Team y Enterprise, primero el propietario de la organización lo agrega en
     Configuración de la organización > Conectores (Organization settings > Connectors).
     Después cada persona lo conecta en Personalizar > Conectores.
2. **Skill.** Descarga `datalum-skill.zip`, entra a Personalizar > Skills (Customize >
   Skills) y súbelo tal cual, sin descomprimirlo.
3. **Prueba.** En una conversación nueva escribe «¿Qué agentes tengo en Datalum?».

## Claude Code

En la terminal de Claude Code:

```
/plugin marketplace add Vinden-NewAge/datalum-plugin
/plugin install datalum@datalum
```

Luego escribe `/mcp`, elige `datalum` e inicia sesión con tu cuenta de Datalum en el
navegador.

## ChatGPT

Planes Business, Enterprise, Healthcare y Edu, según lo que permita el administrador del
espacio de trabajo.

1. **Conector.** Activa Configuración > Seguridad e inicio de sesión > Modo desarrollador
   (Settings > Security and login > Developer mode). Luego entra a Plugins, pulsa el
   botón +, escribe el nombre `Datalum` y la dirección
   `https://mcp.datahub.vinden.cc/mcp`, y crea la conexión.
   - En un espacio de trabajo, el administrador decide si se permite. Cuando Datalum
     cambia sus funciones, el administrador tiene que pulsar Refresh en la
     configuración del espacio de trabajo (Workspace settings > Apps); ChatGPT no se
     actualiza solo.
2. **Skill.** Entra a Plugins, pestaña Skills, elige Crear > Subir desde tu computadora
   (Create > Upload from your computer) y sube `datalum-skill.zip`. ChatGPT la revisa
   antes de activarla.
   - El administrador puede subirla una vez para todo el espacio de trabajo desde la
     página Skills del centro de administración e instalarla a los miembros.
3. **Prueba.** En una conversación nueva, con Datalum activado en el menú de
   herramientas, escribe «¿Qué agentes tengo en Datalum?».

## Grok Build

Cuando xAI publique Datalum en su catálogo: escribe `/marketplace`, busca **Datalum** e
instálalo. La primera vez que el asistente use Datalum se abre el navegador para que
inicies sesión.

## Qué versión tienes y cómo actualizar

Cada versión se publica en https://github.com/Vinden-NewAge/datalum-plugin/releases con lo
que cambió. La versión que tienes instalada aparece en el encabezado de la Skill
(`metadata.version`).

| Producto | Cómo recibes una versión nueva |
|---|---|
| Grok Build | xAI la revisa y la publica en su catálogo; Grok la ofrece como actualización |
| Claude Code | `/plugin marketplace update datalum`, o activa la actualización automática en `/plugin` > Marketplaces |
| Claude (web y escritorio) | Descarga el zip nuevo. En Personalizar > Skills borra la versión anterior y sube la nueva |
| ChatGPT | Descarga el zip nuevo. En Plugins > Skills borra la versión anterior y sube la nueva. En un espacio de trabajo lo hace el administrador |

El conector no se reinstala al actualizar la Skill.
