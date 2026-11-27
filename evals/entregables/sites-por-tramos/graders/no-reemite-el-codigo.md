---
type: regex
target: mock_calls
pattern: '"edits":\[[\s\S]*__upsert_artifact"[^\n]*"template":'
match: not_contains
---
