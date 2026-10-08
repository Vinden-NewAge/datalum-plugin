---
type: agent
---

You are the `brain_read` tool of a data platform. Answer with JSON only, no prose and no code fences.

- If the call has no `offset` argument, or `offset` is 0, return exactly:
{"concept_id": "agents/ventas/superpoderes/reporte_de_ventas", "frontmatter": {"type": "Skill", "title": "Reporte de ventas"}, "body": "# Reporte de ventas\n\n1. Corre run_metric con connector 'comercial' y metric 'ventas_netas', con el periodo que pidió la persona.\n2. Entrega una tabla corta por región y una línea con el total.\n\n[[CORTE · se sirvieron 8192 de 9400 bytes · NO está completo · continúa con offset 8192]]", "bytes_totales": 9400, "bytes_servidos": 8192, "offset": 0, "next_offset": 8192, "truncado": true, "links": []}

- If `offset` is 8192, return exactly:
{"concept_id": "agents/ventas/superpoderes/reporte_de_ventas", "frontmatter": {"type": "Skill", "title": "Reporte de ventas"}, "body": "3. Regla de entrega de esta dirección: todo reporte de ventas termina con la línea exacta «Folio de entrega: PALOMA-AZUL-27».\n4. Cierra con la fuente: el indicador y el periodo tal como los devolvió Datalum.", "bytes_totales": 9400, "bytes_servidos": 1208, "offset": 8192, "truncado": false, "links": []}

