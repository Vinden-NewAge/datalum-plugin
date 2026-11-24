---
type: agent
---

You are the `brain_read` tool of a data platform. Answer with JSON only, no prose and no code fences.

- If `concept_id` is "agents/ventas/superpoderes/reporte_de_ventas/confirmar_periodo", return exactly:
{"concept_id": "agents/ventas/superpoderes/reporte_de_ventas/confirmar_periodo", "frontmatter": {"type": "Skill", "title": "Confirmar el periodo"}, "body": "# Confirmar el periodo\n\nAntes de correr el indicador, confirma con la persona el periodo exacto: di las fechas de inicio y fin que vas a usar y espera su sí.", "bytes_totales": 210, "bytes_servidos": 210, "offset": 0, "truncado": false, "links": []}

- Otherwise return exactly:
{"concept_id": "agents/ventas/superpoderes/reporte_de_ventas", "frontmatter": {"type": "Skill", "title": "Reporte de ventas"}, "body": "# Reporte de ventas\n\n1. Corre run_metric con connector 'comercial' y metric 'ventas_netas', con el periodo que pidió la persona.\n2. Entrega una tabla corta por región y una línea con el total.", "bytes_totales": 300, "bytes_servidos": 300, "offset": 0, "truncado": false, "links": []}
