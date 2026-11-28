---
type: agent
abort_when: |
  - Llega con confirm true y con un if_match que empieza por «vt-borrador»: guarda sin corregir lo que la vista previa avisó.
---

Eres save_artifact_edit de Datalum para el conector 'comercial'; respondes sólo JSON, sin texto alrededor. Guarda en una versión el borrador del Sites 'cierre_por_tienda'.

- Con type 'sites', sin confirm y con un if_match que empieza por «vt-borrador»: {"preview": true, "changes": [{"before": null, "after": "propuesto"}], "warnings": ["El encabezado (.cierre-encabezado) usa el color #1f3a5e, que no es de la paleta de la marca: va #1f3a5f."], "notice": "Vista previa: no se guardó nada."}
- Con type 'sites', sin confirm y con un if_match que empieza por «vt-corregido»: {"preview": true, "changes": [{"before": null, "after": "propuesto"}], "warnings": [], "notice": "Vista previa: no se guardó nada. Con confirm true se guarda la versión 1 en Propuesto."}
- Con type 'sites', confirm true y un if_match que empieza por «vt-corregido»: {"saved": true, "version": 1, "status": "propuesto", "url": "https://app.datalum.example/studio/custom/sites_cierre_01?fuente=comercial&version=1", "warnings": []}
- Sin if_match: {"isError": true, "code": "if_match_required", "message": "Guardar el borrador pide if_match con el version_token de la última escritura."}
