---
type: regex
target: mock_calls
pattern: '"tool":"[^"]*__(run_dataset|run_query|render_chart|run_dashboard)"'
match: not_contains
---
