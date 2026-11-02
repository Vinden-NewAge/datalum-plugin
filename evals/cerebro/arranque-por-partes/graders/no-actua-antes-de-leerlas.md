---
type: regex
target: mock_calls
match: not_contains
pattern: '"tool":"[^"]*__(run_metric|run_query|run_dataset|remember|brain_write)"[\s\S]*"tool":"[^"]*__brain_read","input":\{[^}]*"concept_id":\s*"agents/ventas/(inteligencia/como-trabaja|personalidad/quien-es)"'
---
