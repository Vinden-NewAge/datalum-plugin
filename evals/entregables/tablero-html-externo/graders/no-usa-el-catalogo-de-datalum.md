---
type: regex
target: mock_calls
pattern: '"tool":"[^"]*__(upsert_custom_dashboard|upsert_dashboard|upsert_chart|render_chart|run_dashboard)"'
match: not_contains
---
