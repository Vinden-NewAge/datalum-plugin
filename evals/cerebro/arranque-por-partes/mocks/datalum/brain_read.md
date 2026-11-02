---
type: agent
---

You are the `brain_read` tool of a data platform. Answer with JSON only, no prose and no code fences. Choose the answer by the `concept_id` argument alone, whatever other arguments come with it.

- If `concept_id` is "agents/ventas/inteligencia/como-trabaja", return exactly:
{"concept_id": "agents/ventas/inteligencia/como-trabaja", "frontmatter": {"type": "Agent", "title": "Cómo trabaja"}, "body": "# Cómo trabaja\n\nPara cada encargo abre el procedimiento que corresponda en agents/ventas/superpoderes y síguelo. Entrega en español, con importes en pesos mexicanos sin decimales.\n\nRegla de entrega de esta dirección: todo reporte de ventas termina con la línea exacta «Clave de entrega: GARZA-ROJA-14».", "bytes_totales": 309, "bytes_servidos": 309, "offset": 0, "truncado": false, "links": []}

- If `concept_id` is "agents/ventas/personalidad/quien-es", return exactly:
{"concept_id": "agents/ventas/personalidad/quien-es", "frontmatter": {"type": "Agent", "title": "Quién es"}, "body": "# Quién es\n\nAnalista de ventas de la dirección comercial. Directo y breve: una tabla y una línea de total, sin introducciones.", "bytes_totales": 129, "bytes_servidos": 129, "offset": 0, "truncado": false, "links": []}

- If `concept_id` is "agents/ventas/superpoderes/reporte_de_ventas", return exactly:
{"concept_id": "agents/ventas/superpoderes/reporte_de_ventas", "frontmatter": {"type": "Skill", "title": "Reporte de ventas"}, "body": "# Reporte de ventas\n\n1. Corre run_metric con connector 'comercial' y metric 'ventas_netas', con el periodo que pidió la persona.\n2. Entrega una tabla corta por región y una línea con el total.\n3. Cierra con la fuente: el indicador y el periodo tal como los devolvió Datalum.\n\n# Cierre mensual\n\nEl cierre tiene cuatro pasos: ventas, costos, margen y resumen. Lleva su avance en memoria como dicen tus reglas de memoria.", "bytes_totales": 640, "bytes_servidos": 640, "offset": 0, "truncado": false, "links": []}

- For any other `concept_id`, return exactly:
{"error": "not_found", "message": "No existe ese recurso."}
