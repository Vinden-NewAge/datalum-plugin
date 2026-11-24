---
type: agent
---

You are the `run_metric` tool of a data platform. Answer with JSON only, no prose and no code fences.

- If the call has no `preparation_ref` argument, return exactly:
{"estado": "en_preparacion", "preparation_ref": "prep-sintetica-01", "reintentar_en_s": 5, "mensaje": "La cifra se está preparando: tarda más de lo que dura una llamada y Datalum la sigue calculando. Vuelve a llamar a esta herramienta con los mismos argumentos y con su preparation_ref en unos 5 segundos; se entrega en cuanto esté, sin calcularla otra vez."}

- If the call has `preparation_ref` equal to "prep-sintetica-01", return exactly:
{"metric": "ventas_netas", "periodo_efectivo": {"desde": "2026-09-01", "hasta": "2026-09-30"}, "unidad": "MXN", "rows": [{"region": "Norte", "ventas_netas": 4210500}, {"region": "Centro", "ventas_netas": 6380200}, {"region": "Sur", "ventas_netas": 2145300}], "total": 12736000, "execution_ref": "ej-sintetica-01"}

- Otherwise return exactly:
{"code": "preparation_ref_mismatch", "message": "Esa referencia no es de esta cifra.", "retryable": false}
