---
type: regex
target: mock_calls
pattern: '"tool":"[^"]*__(upsert_custom_dashboard|upsert_dashboard|upsert_chart|render_chart|run_dashboard|get_artifact|upsert_artifact|test_artifact|save_artifact_edit|run_artifact)"'
match: not_contains
---
