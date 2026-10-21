---
type: regex
target: { source: file, path: informe-ventas-septiembre.md }
match: not_contains
flags: i
pattern: '<svg|<canvas|<html|<!doctype|<div[^>]*(width|height)\s*:|```\s*(mermaid|vega|vega-lite|echarts|plotly|chart|html|svg)|chart\.js|new Chart\(|plotly|matplotlib|echarts|recharts|d3\.(select|scale)|[█▓▒░▇▆▅▄▃▂▁■▬▮▰]{2,}'
---
