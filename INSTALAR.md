# Instalar Datalum en tu asistente

Datalum se instala en dos partes:

- **El conector**, que une tu asistente con el servidor de Datalum. Sin él, el asistente
  no ve ningún dato.
- **La Skill**, que le enseña al asistente cómo trabajar con Datalum: preguntarte primero
  con qué agente trabajar, pedir tu aprobación antes de cambiar algo y sacar las cifras
  sólo de Datalum.

En Grok Build y en Claude Code las dos partes llegan juntas. En Claude (web y escritorio)
y en ChatGPT se agregan por separado.

## Antes de empezar

- Una cuenta de Datalum.
- Al menos un agente que el administrador de tu empresa te haya otorgado.
- La dirección del servidor: `https://mcp.datahub.vinden.cc/mcp`
- La Skill empaquetada:
  https://github.com/Vinden-NewAge/datalum-plugin/releases/latest/download/datalum-skill.zip
  - En Mac, si al descargar ves una carpeta `datalum` en vez del archivo `.zip`, tu
    navegador lo descomprimió solo. Descárgalo con otro navegador.

## Claude (web y escritorio)

Planes Pro, Max, Team y Enterprise, con la ejecución de código activada en la
configuración de Claude.

1. **Si tu empresa usa Team o Enterprise:** primero el propietario de la organización
   agrega el conector en Configuración de la organización > Conectores (Organization
   settings > Connectors), con el nombre `Datalum` y la dirección del servidor.
2. **Conector.** Entra a Personalizar > Conectores (Customize > Connectors).
   - Si tu empresa ya lo agregó, busca Datalum y pulsa Conectar.
   - Si no, elige Agregar conector personalizado (Add custom connector), con el nombre
     `Datalum` y la dirección `https://mcp.datahub.vinden.cc/mcp`, y pulsa Conectar.

   Inicia sesión con tu cuenta de Datalum y aprueba la conexión.
3. **Skill.** Entra a Personalizar > Skills (Customize > Skills) y sube
   `datalum-skill.zip` tal cual, sin descomprimirlo.
4. **Prueba.** En una conversación nueva escribe «¿Qué agentes tengo en Datalum?». El
   asistente debe mostrarte tus agentes y preguntarte con cuál trabajar.

## Claude Code

Abre Claude Code y escribe en su caja de mensajes, uno por uno:

```
/plugin marketplace add Vinden-NewAge/datalum-plugin
/plugin install datalum@datalum
```

Luego escribe `/mcp`, elige el servidor de Datalum, inicia sesión con tu cuenta de
Datalum en el navegador y aprueba la conexión.

## ChatGPT

Planes Business, Enterprise, Healthcare y Edu, según lo que permita el administrador del
espacio de trabajo.

1. **Conector.** Activa Configuración > Seguridad e inicio de sesión > Modo desarrollador
   (Settings > Security and login > Developer mode). Luego entra a Plugins, pulsa el
   botón +, escribe el nombre `Datalum` y la dirección
   `https://mcp.datahub.vinden.cc/mcp`, y crea la conexión. Inicia sesión con tu cuenta
   de Datalum y aprueba la conexión.
2. **Skill.** Entra a Plugins, pestaña Skills, elige Crear > Subir desde tu computadora
   (Create > Upload from your computer) y sube `datalum-skill.zip`. ChatGPT la revisa
   antes de activarla.
   - El administrador puede subirla una vez para todo el espacio de trabajo desde la
     página Skills del centro de administración e instalarla a los miembros.
3. **Prueba.** En una conversación nueva, activa Datalum en el menú de herramientas y
   escribe «¿Qué agentes tengo en Datalum?». El asistente debe mostrarte tus agentes y
   preguntarte con cuál trabajar.

## Grok Build

Cuando xAI publique Datalum en su catálogo: escribe `/marketplace`, busca **Datalum** e
instálalo. La primera vez que el asistente use Datalum se abre el navegador para que
inicies sesión y apruebes la conexión.

## Si algo no funciona

| Qué pasa | Qué hacer |
|---|---|
| El asistente dice que no tiene acceso a Datalum | Activa el conector de Datalum en el menú de herramientas de la conversación. Si no aparece, vuelve al paso del conector |
| El asistente dice que no tienes agentes | Pide al administrador de Datalum de tu empresa que te otorgue uno |
| El inicio de sesión falla | Comprueba que entras con tu cuenta de Datalum. Si sigue fallando, avisa al administrador de Datalum de tu empresa |
| En ChatGPT, el asistente dice que una función de Datalum no existe | Pide al administrador del espacio de trabajo que pulse Refresh en Workspace settings > Apps. ChatGPT no actualiza solo la lista de funciones |

## Qué versión tienes y cómo actualizar

Pregúntale al asistente «¿Qué versión de la Skill de Datalum tienes?». La más reciente es
la primera de https://github.com/Vinden-NewAge/datalum-plugin/releases, con lo que
cambió.

| Producto | Cómo recibes una versión nueva |
|---|---|
| Grok Build | xAI la revisa y la publica en su catálogo; Grok la ofrece como actualización |
| Claude Code | `/plugin marketplace update datalum`, o activa la actualización automática en `/plugin` > Marketplaces |
| Claude (web y escritorio) | Descarga el zip nuevo. En Personalizar > Skills borra la versión anterior y sube la nueva |
| ChatGPT | Descarga el zip nuevo. En Plugins > Skills borra la versión anterior y sube la nueva. En un espacio de trabajo lo hace el administrador |

El conector no se reinstala al actualizar la Skill.
