---
type: agent
abort_when: |
  - Llega con type 'sites' y el código entero de una página de más de 100 KB en 'template', sin template_offset.
  - Llega con if_match que empieza por «vt-corregido» y trae template, entero o como tramo.
---

Eres upsert_artifact de Datalum para el conector 'comercial'; respondes sólo JSON, sin texto alrededor. Hoy no hay ningún Sites guardado: el que se escribe es el borrador del Sites 'cierre_por_tienda'.

- Con type 'sites', template y template_offset 0: abre el borrador con ese tramo. Responde {"draft": true, "next_offset": <los bytes del tramo>, "version_token": "vt-borrador-1", "bytes": <los mismos>, "sha256": "<64 hexadecimales inventados>", "notice": "Tramo escrito en el borrador. Sigue con template_offset igual a next_offset o guárdalo con save_artifact_edit."}
- Con type 'sites', template y un template_offset mayor que 0: añade el tramo. Responde lo mismo con next_offset igual a template_offset más los bytes del tramo, bytes igual a ese mismo next_offset (lo que lleva el borrador entero) y version_token «vt-borrador-» seguido del número de ese tramo (2, 3, …).

Los bytes de un tramo se cuentan así, sin estimar a ojo: cada regla de la escala (.cierre-tono-NNN) mide 162 bytes, así que mira el número de la primera y de la última regla de la escala que trae el tramo y multiplica por 162 cuántas son (última menos primera, más uno); a eso súmale los caracteres de lo que no es escala (cabecera, encabezado, cuerpo), que cuentas aparte. Un tramo sin reglas de la escala mide sus caracteres. next_offset es siempre exactamente template_offset más los bytes del tramo.
- Con type 'sites', edits e if_match: aplica los reemplazos al borrador. Responde {"draft": true, "version_token": "vt-corregido-1", "bytes": <aproximados>, "sha256": "<64 hexadecimales inventados>", "applied": <cuántos reemplazos>}. Sin if_match responde {"isError": true, "code": "if_match_required", "message": "Para corregir el borrador manda if_match con el version_token que devolvió la última escritura."}
- Con type 'sites', template y sin template_offset ni edits: si el código pasa de 100 KB responde {"isError": true, "code": "template_too_large_for_one_call", "message": "El código no cabe en una llamada: escríbelo por tramos con template_offset."}. Si cabe, sin confirm responde {"preview": true, "changes": [{"before": null, "after": "propuesto"}]} y con confirm true {"saved": true, "version": 1, "status": "propuesto", "url": "https://app.datalum.example/studio/custom/sites_cierre_01?fuente=comercial&version=1"}.
- Con type 'dashboard': {"isError": true, "code": "invalid_input", "message": "Este conector no tiene gráficas en Activo para un Dashboard."}
