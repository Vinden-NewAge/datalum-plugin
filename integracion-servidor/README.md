# El aviso de despliegue

El flujo `compat.yml` comprueba el plugin contra lo que sirve producción. Para hacerlo
completo necesita que el despliegue de Datalum le avise cuando termina y le diga qué
contrato sirve ese commit. Esta página describe ese aviso. El cambio concreto en el
repositorio del servidor lo tiene el equipo de la plataforma y no vive aquí: el plugin
se construyó con permiso de sólo lectura sobre ese repositorio.

## Por qué hace falta

- Que la publicación terminó sólo lo sabe el último paso del despliegue, cuando todas
  sus piezas pasaron la comprobación de salud.
- El catálogo completo de herramientas sólo se entrega a una conexión con sesión
  iniciada. Desde fuera no se puede leer sin una credencial.

Sin el aviso, el plugin sigue vigilando producción con una lectura de `/health` cada
hora. Esa lectura ve que el commit cambió y ve un rollback, pero ante un commit nuevo
sólo puede anotar que le falta el contrato.

## Qué manda el despliegue

El último paso del despliegue lanza `compat.yml` en este repositorio, sobre `main`, con
estas entradas:

| Entrada | Valor |
|---|---|
| `entorno` | `prod`, o `qa` para preparar la candidata antes de producción |
| `sha` | El commit desplegado, completo |
| `release` | La etiqueta de la versión, si la hay |
| `corrida` | La dirección de la corrida de despliegue |
| `contrato` | El resumen del contrato de ese commit, en JSON |

Para lanzarlo basta un token limitado a este repositorio con el permiso Actions en
lectura y escritura. Con ese permiso se puede lanzar un flujo; no se puede empujar
código ni publicar versiones.

## El resumen del contrato

Un objeto JSON con lo que el servidor contesta a `initialize` y a `tools/list` con
sesión iniciada, reducido a nombres y huellas:

```json
{
  "esquema": 1,
  "protocolo": "2025-06-18",
  "instrucciones_sha256": "<sha256 del texto de instructions>",
  "herramientas": [
    {"n": "use_agent", "h": "<sha256 de su definición>", "p": ["agent", "selection_context", "user_choice_quote"], "r": ["agent", "user_choice_quote"]}
  ],
  "huella": "<sha256 del objeto {protocolo, instrucciones_sha256, herramientas}>"
}
```

- `herramientas` va ordenada por nombre. `p` son los argumentos de la herramienta y `r`
  los obligatorios, ordenados.
- `h` es el sha256 de la definición completa de la herramienta, tal como sale en
  `tools/list`, escrita como JSON con las claves ordenadas, sin espacios y sin escapar
  los caracteres no ASCII. `huella` se calcula igual.
- No lleva descripciones ni esquemas. El de producción en v2.243.0 pesa 17,8 KB; una
  entrada de `workflow_dispatch` admite hasta 65 535 caracteres.

`scripts/compatlib/contract.py` valida esa forma y recalcula la huella. Con un
`tools/list` completo guardado en un archivo, `python3 scripts/compat.py resumir` arma
el mismo resumen.

## Qué vuelve a comprobar el plugin

El aviso es un indicio. El plugin no toma de él la dirección del servidor: usa la de su
`.mcp.json`. Antes de hacer nada le pregunta a producción qué commit sirve y si pasa su
salud, y compara las instrucciones y el protocolo del aviso con los que producción
contesta sin sesión. Un aviso de un commit que producción no sirve se anota como no
confirmado y no cambia nada.

## Opcional, en este repositorio

| Qué | Para qué |
|---|---|
| Variable `COMPAT_ACTORES` | Aceptar avisos de despliegue sólo de la cuenta dueña del token |
| Secreto `DATALUM_COMPAT_TOKEN` | Una credencial de sólo lectura de una cuenta de Datalum sin agentes. Con ella el flujo lee el catálogo completo del servidor desplegado y lo coteja entero contra el aviso |

## Lo que el aviso no cubre

Un rollback hecho a mano no emite nada. El plugin lo ve en su lectura de cada hora y lo
comprueba con el contrato que guardó de ese commit. Quien revierte puede lanzar
`compat.yml` a mano, sin argumentos, para no esperar.
