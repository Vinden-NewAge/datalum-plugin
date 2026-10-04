# Instalar Datalum en tu asistente

Con Datalum instalado haces tres cosas: conectas tu cuenta, eliges tu agente y pides el
trabajo. El agente que elijas trae su propia manera de trabajar; el asistente la carga
de Datalum cada vez.

Se instala en dos partes:

- **El conector**, que une tu asistente con el servidor de Datalum. Sin él, el asistente
  no ve ningún dato.
- **La Skill**, que le enseña al asistente a conectarte, a preguntarte con qué agente
  quieres trabajar y a seguir las reglas de ese agente.

En Grok Build y en Claude Code las dos partes llegan juntas. En Claude (web y escritorio)
y en ChatGPT se agregan por separado.

Instalar el plugin no crea cuentas, empresas ni permisos. Eso lo hace el administrador
de Datalum de tu empresa.

## Antes de empezar

- Una cuenta de Datalum.
- Al menos un agente que el administrador de tu empresa te haya otorgado y que esté
  activo.
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
2. **Conector:** entra a Personalizar > Conectores (Customize > Connectors).
   - Si tu empresa ya lo agregó, busca Datalum y pulsa Conectar.
   - Si no, elige Agregar conector personalizado (Add custom connector), con el nombre
     `Datalum` y la dirección `https://mcp.datahub.vinden.cc/mcp`, y pulsa Conectar.

   Inicia sesión con tu cuenta de Datalum y aprueba la conexión.
3. **Skill:** entra a Personalizar > Skills (Customize > Skills) y sube
   `datalum-skill.zip` tal cual, sin descomprimirlo.
4. **Prueba:** en una conversación nueva escribe «Quiero trabajar con mis datos en
   Datalum». Si tienes varios agentes, el asistente te los muestra y te pregunta con
   cuál trabajar. Si tienes uno, te dice cuál es y empieza con él.

## Claude Code

Abre Claude Code y escribe en su caja de mensajes, uno por uno:

```
/plugin marketplace add Vinden-NewAge/datalum-plugin
/plugin install datalum@datalum
```

Luego escribe `/mcp`, elige el servidor de Datalum, inicia sesión con tu cuenta de
Datalum en el navegador y aprueba la conexión.

En Claude Code el plugin trae además unos controles que corren en tu máquina. Comprueban
que la elección de agente la hiciste tú, mantienen cada conversación en su agente y
evitan guardar dos veces lo mismo. Necesitan Node 18 o posterior. Si no lo tienes, el
plugin funciona igual sin ellos. Qué hace cada control: [CONTROLES.md](CONTROLES.md).

## ChatGPT

Planes Business, Enterprise, Healthcare y Edu, según lo que permita el administrador del
espacio de trabajo.

1. **Conector:** activa Configuración > Seguridad e inicio de sesión > Modo desarrollador
   (Settings > Security and login > Developer mode). Luego entra a Plugins, pulsa el
   botón +, escribe el nombre `Datalum` y la dirección
   `https://mcp.datahub.vinden.cc/mcp`, y crea la conexión. Inicia sesión con tu cuenta
   de Datalum y aprueba la conexión.
2. **Skill:** entra a Plugins, pestaña Skills, elige Crear > Subir desde tu computadora
   (Create > Upload from your computer) y sube `datalum-skill.zip`. ChatGPT la revisa
   antes de activarla.
   - El administrador puede subirla una vez para todo el espacio de trabajo desde la
     página Skills del centro de administración e instalarla a los miembros.
3. **Prueba:** en una conversación nueva, activa Datalum en el menú de herramientas y
   escribe «Quiero trabajar con mis datos en Datalum».

## Grok Build

Cuando xAI publique Datalum en su catálogo: escribe `/marketplace`, busca **Datalum** e
instálalo. La primera vez que el asistente use Datalum se abre el navegador para que
inicies sesión y apruebes la conexión. La solicitud de alta en ese catálogo sigue
abierta.

## Si algo no funciona

| Qué pasa | Qué hacer |
|---|---|
| El asistente dice que no tiene acceso a Datalum | Activa el conector de Datalum en el menú de herramientas de la conversación. Si no aparece, vuelve al paso del conector |
| El asistente te pide conectar tu cuenta | Inicia sesión con tu cuenta de Datalum desde el panel de conectores de tu aplicación. Nunca escribas tu contraseña en la conversación |
| Funcionaba y ahora pide conectar otra vez | La sesión caducó. Vuelve a conectar y elige de nuevo tu agente |
| El inicio de sesión funciona pero Datalum dice que tu cuenta no puede conectar | Volver a iniciar sesión no lo arregla. Avisa al administrador de Datalum de tu empresa |
| El asistente dice que no tienes agentes | Pide al administrador de Datalum de tu empresa que te otorgue uno |
| El asistente dice que tienes un agente pero no está activo | El otorgamiento está bien. Pide a quien administra los agentes que lo active en el panel de Datalum |
| El asistente dice que Datalum no responde | Espera unos minutos y vuelve a intentar. Tus datos no cambian por eso |
| La aplicación te pide permiso en cada paso | Es el panel de permisos de tu aplicación. Ahí puedes permitir siempre las lecturas de Datalum. Los detalles por aplicación están en [CONTROLES.md](CONTROLES.md) |
| En ChatGPT, el asistente dice que una función de Datalum no existe | Pide al administrador del espacio de trabajo que pulse Refresh en Workspace settings > Apps. ChatGPT no actualiza solo la lista de funciones |

## Actualizar

Cómo recibe cada aplicación una versión nueva, y qué hacer cuando no es automático:
[ACTUALIZAR.md](ACTUALIZAR.md). El conector no se reinstala al actualizar la Skill.
