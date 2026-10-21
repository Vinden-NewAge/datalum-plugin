"""Pruebas de las evaluaciones de entregables.

Las evaluaciones de evals/ corren con un modelo real y cuestan; estas pruebas no corren
ningún modelo. Miran que cada caso de entregables tenga los calificadores de la regla
de las gráficas y que esos calificadores hagan lo que dicen: aprueban una corrida que
cumple y reprueban la corrida en la que el asistente dibuja por su cuenta, llama lo que
no debe o escribe el archivo que no debe. Los calificadores con rúbrica (llm) no se
pueden correr aquí: sólo se comprueba que cada caso tiene uno y, en el informe, que uno
mira el archivo.

Los patrones se corren con Python y `claude plugin eval` los corre con JavaScript: una
prueba coteja que los dos motores dicen lo mismo para cada texto de la prueba.

Las evaluaciones miden el texto y las llamadas del asistente. Lo que dibuje la
aplicación con sus propias herramientas fuera de eso no lo ven.

Las corridas de mentira imitan lo que `claude plugin eval` le da a cada calificador:
la última respuesta, las llamadas al conector simulado (una por línea, en JSON sin
espacios, con `tool`, `input`, `output` y `verdict`), los archivos que cambiaron en la
carpeta de trabajo y el contenido de un archivo.
"""

from __future__ import annotations

import json
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVALS = ROOT / "evals"
ENTREGABLES = EVALS / "entregables"
MOCKS = EVALS / "mocks" / "datalum"
PREFIX = "mcp__plugin_datalum_datalum__"

CASOS = (
    "anfitrion-sin-archivos",
    "cliente-sin-imagenes",
    "documento-con-archivos",
    "grafica-guardada",
    "indicador-activo-sin-grafica",
    "pide-un-tablero",
    "sin-indicador-creativo",
    "sin-indicador-institucional",
    "tablero-html-externo",
)

# Respuestas en las que el asistente dibuja una gráfica por su cuenta, cada una con la
# alternativa del patrón que la caza. Cada una tiene que reprobar el calificador que lo
# prohíbe en todos los casos, y el patrón no tiene alternativas sin su dibujo ni dibujos
# de alternativas que ya no tiene: quitar una alternativa o sumar una sin probarla deja
# la prueba en rojo.
DIBUJOS = {
    "svg": ("<svg", 'Aquí está:\n<svg width="300" height="120"><rect x="0" y="0" width="80" height="40"/></svg>'),
    "svg en mayúsculas": ("<svg", '<SVG WIDTH="300"><RECT WIDTH="80" HEIGHT="40"/></SVG>'),
    "canvas": ("<canvas", '<canvas id="g"></canvas>'),
    "página html": ("<html", "<html><body><p>Ventas de septiembre</p></body></html>"),
    "doctype": ("<!doctype", "<!DOCTYPE html>\n<title>Ventas</title>"),
    "div con ancho": (r"<div[^>]*(width|height)\s*:", '<div style="width: 62%">Centro</div>'),
    "bloque html": (r"<div[^>]*(width|height)\s*:", '<div class="barra" style="height: 40px"></div>'),
    "mermaid": (r"```\s*(mermaid|vega|vega-lite|echarts|plotly|chart|html|svg)",
                "```mermaid\npie title Ventas\n\"Norte\" : 4210500\n```"),
    "Chart.js en mayúsculas": (r"chart\.js", "Con Chart.js quedaría así: una barra por región."),
    "chart.js en código": (r"new Chart\(", "const g = new Chart(ctx, { type: 'bar' });"),
    "Plotly en mayúsculas": ("plotly", "Plotly.newPlot('g', [{ x: regiones, y: valores }]);"),
    "matplotlib": ("matplotlib", "import matplotlib.pyplot as plt\nplt.bar(regiones, valores)"),
    "seaborn": ("seaborn", "import seaborn as sns\nsns.barplot(x=regiones, y=valores)"),
    "ggplot": ("ggplot", "ggplot(ventas, aes(region, valor)) + geom_col()"),
    "bokeh": ("bokeh", "from bokeh.plotting import figure"),
    "highcharts": ("highcharts", "Highcharts.chart('g', { series: [{ data: [4210500, 6380200, 2145300] }] });"),
    "apexcharts": ("apexcharts", "new ApexCharts(el, { series: [{ data: [4210500, 6380200] }] }).render();"),
    "echarts": ("echarts", "echarts.init(dom).setOption({ series: [{ data: [4210500, 6380200, 2145300] }] });"),
    "recharts": ("recharts", "import { BarChart, Bar } from 'recharts';"),
    "d3": (r"d3\.(select|scale)", "d3.select('#g').selectAll('rect').data(valores)"),
    "pyplot sin importar": (r"plt\.\w+\(", "plt.barh(regiones, valores)\nplt.show()"),
    "vega-lite en json": (r"\bvega(-?lite|-?embed|\.github\.io)",
                          '```json\n{"$schema": "https://vega.github.io/schema/vega-lite/v5.json", "mark": "bar"}\n```'),
    "configuración de gráfica": (r"\b(type|mark)\W{0,3}:\W{0,3}(bar|line|pie|doughnut|radar|scatter|bubble|polararea|arc|area)\b",
                                 '{"type": "bar", "data": {"labels": ["Norte", "Centro", "Sur"]}}'),
    "imagen incrustada": ("data:image/", "![Ventas](data:image/svg+xml;base64,PHN2ZyB4bWxucz0i)"),
    "svg en base64": ("PHN2Zy", "Copia esto en un archivo: PHN2ZyB3aWR0aD0iMzAwIiBoZWlnaHQ9IjEyMCI+"),
    "png en base64": ("iVBORw0KGgo", "La imagen en base64: iVBORw0KGgoAAAANSUhEUgAAASwAAAB4"),
    "servicio de gráficas": ("quickchart",
                             "![Ventas](https://quickchart.io/chart?c={type:'bar',data:{labels:['Norte','Centro','Sur']}})"),
    "image-charts": ("image-charts", "![Ventas](https://image-charts.com/chart?cht=bvs&chd=t:42,63,21)"),
    "google charts": (r"chart\.googleapis", "![Ventas](https://chart.googleapis.com/chart?cht=p&chd=t:42,63,21)"),
    "google charts viejo": (r"chart\.apis\.google", "![Ventas](http://chart.apis.google.com/chart?cht=bvs&chd=t:42,63,21)"),
    "mermaid.ink": (r"mermaid\.ink", "![Ventas](https://mermaid.ink/img/cGllIHRpdGxlIFZlbnRhcw)"),
    "kroki": (r"kroki\.io", "![Ventas](https://kroki.io/plantuml/svg/eNpLzkksLlZwzslPTlVIzs8rSc0rAQA)"),
    "cifras en la dirección de una imagen": (r"!\[[^\]]*\]\([^)]*[?&](c|chart|cht|chd|data)=",
                                             "![Ventas](https://graficas.ejemplo.invalid/render?chart=bar&data=4210500,6380200)"),
    "barras de texto": ("[▀-▟■-▱━]{2,}", "Norte  ████████ 4,210,500\nCentro ████████████ 6,380,200"),
    "barras de fracción": ("[▀-▟■-▱━]{2,}", "Centro ▉▉▉▉▉▉▉▉▉▉▉▍ 6,380,200"),
    "media barra": ("[▀-▟■-▱━]{2,}", "Sur ▐▐▐▐ 2,145,300"),
    "barras de bloques": ("[▀-▟■-▱━]{2,}", "Sur ▇▇▇▇ 2,145,300"),
    "chispa": ("[▀-▟■-▱━]{2,}", "Tendencia del año: ▁▂▃▅▇"),
    "cuadros": ("[▀-▟■-▱━]{2,}", "Norte ■■■■ 33%"),
    "trazo grueso": ("[▀-▟■-▱━]{2,}", "Centro ━━━━━━━━ 6,380,200"),
    "cuadros de colores": ("(?:🟥|🟧|🟨|🟩|🟦|🟪|🟫|⬛|⬜){2,}", "Norte 🟦🟦🟦🟦 4,210,500"),
    "barras de almohadillas": (r"[^\s#=*|-][ \t]*(#{5,}|={5,}|\*{5,}|\|{5,})", "Norte: ##########\nCentro: ###############"),
    "barras de iguales": (r"[^\s#=*|-][ \t]*(#{5,}|={5,}|\*{5,}|\|{5,})", "Norte [==========          ] 33%"),
    "barra corta": (r"\S[ \t]+(#{3,}|={4,}|\*{3,}|\|{4,})[ \t]+\d", "Sur ### 2,145,300"),
    "barra de asteriscos": (r"\S[ \t]+(#{3,}|={4,}|\*{3,}|\|{4,})[ \t]+\d", "Norte **** 4,210,500"),
    "cifra y barra": (r"\d[ \t]+(#{3,}|={4,}|\*{3,}|\|{4,})", "4,210,500 ||||"),
    "barra en la tabla": (r"\|[ \t]*(#{3,}|={3,}|\*{3,})[ \t]*\|", "| Norte | ### | 4,210,500 |"),
}

# Las que sólo caza la bandera «i»: sin ella, el patrón las deja pasar.
MAYUSCULAS = ("svg en mayúsculas", "Chart.js en mayúsculas", "Plotly en mayúsculas")

# Archivos que una gráfica propia deja en la carpeta de trabajo, cada uno con la
# alternativa del patrón de archivos que lo caza. Valen igual en los tres casos con
# archivos: ninguno pide un archivo de gráfica ni un tablero.
ARCHIVOS_DE_GRAFICA = {
    "svg": (r"\.(html?|svg|png|jpe?g|gif|webp|py|ipynb|r|js|v[lg]\.json)\b", "ventas.svg"),
    "html": (r"\.(html?|svg|png|jpe?g|gif|webp|py|ipynb|r|js|v[lg]\.json)\b", "ventas-septiembre.html"),
    "htm": (r"\.(html?|svg|png|jpe?g|gif|webp|py|ipynb|r|js|v[lg]\.json)\b", "ventas.htm"),
    "png": (r"\.(html?|svg|png|jpe?g|gif|webp|py|ipynb|r|js|v[lg]\.json)\b", "ventas.png"),
    "jpg": (r"\.(html?|svg|png|jpe?g|gif|webp|py|ipynb|r|js|v[lg]\.json)\b", "ventas.jpg"),
    "gif": (r"\.(html?|svg|png|jpe?g|gif|webp|py|ipynb|r|js|v[lg]\.json)\b", "ventas.gif"),
    "webp": (r"\.(html?|svg|png|jpe?g|gif|webp|py|ipynb|r|js|v[lg]\.json)\b", "ventas.webp"),
    "python": (r"\.(html?|svg|png|jpe?g|gif|webp|py|ipynb|r|js|v[lg]\.json)\b", "ventas.py"),
    "cuaderno": (r"\.(html?|svg|png|jpe?g|gif|webp|py|ipynb|r|js|v[lg]\.json)\b", "ventas.ipynb"),
    "r": (r"\.(html?|svg|png|jpe?g|gif|webp|py|ipynb|r|js|v[lg]\.json)\b", "ventas.r"),
    "javascript": (r"\.(html?|svg|png|jpe?g|gif|webp|py|ipynb|r|js|v[lg]\.json)\b", "ventas.js"),
    "vega-lite": (r"\.(html?|svg|png|jpe?g|gif|webp|py|ipynb|r|js|v[lg]\.json)\b", "ventas.vl.json"),
    "vega": (r"\.(html?|svg|png|jpe?g|gif|webp|py|ipynb|r|js|v[lg]\.json)\b", "ventas.vg.json"),
    "nombre de gráfica": ("gr[aá]fic", "grafica-ventas.md"),
    "nombre con acento": ("gr[aá]fic", "Gráfica de ventas.txt"),
    "nombre de chart": ("chart", "chart-data.md"),
    "nombre de plot": ("plot", "plot.txt"),
    "nombre de vega": ("vega", "vega-spec.json"),
    "tablero": ("tablero", "tablero-ventas-septiembre.md"),
    "dashboard": ("dashboard", "dashboard.md"),
}


def parse(path: Path) -> tuple[dict, str]:
    """El subconjunto de YAML que usan los casos: `clave: valor`, listas `[a, b]`,
    objetos `{ a: b }` y cadenas entre comillas simples o dobles."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    fields: dict = {}
    for line in lines[1:end]:
        key, _, value = line.partition(":")
        fields[key.strip()] = scalar(value.strip())
    return fields, "\n".join(lines[end + 1:]).strip()


def scalar(value: str):
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        inner = value[1:-1]
        return inner.replace("''", "'") if value[0] == "'" else inner
    if value.startswith("[") and value.endswith("]"):
        return [scalar(v.strip()) for v in value[1:-1].split(",") if v.strip()]
    if value.startswith("{") and value.endswith("}"):
        out = {}
        for part in value[1:-1].split(","):
            k, _, v = part.partition(":")
            out[k.strip()] = scalar(v.strip())
        return out
    if value in ("true", "false"):
        return value == "true"
    if re.fullmatch(r"\d+", value):
        return int(value)
    return value


def graders(case: str) -> dict:
    return {p.stem: parse(p) for p in sorted((ENTREGABLES / case / "graders").glob("*.md"))}


def alternativas(pattern: str) -> list[str]:
    """Las alternativas de primer nivel de un patrón: lo que separa una barra fuera de
    paréntesis y de corchetes."""
    out, cur, depth, in_class, i = [], "", 0, False, 0
    while i < len(pattern):
        c = pattern[i]
        if c == "\\":
            cur += pattern[i:i + 2]
            i += 2
            continue
        if in_class:
            in_class = c != "]"
        elif c == "[":
            in_class = True
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif c == "|" and depth == 0:
            out.append(cur)
            cur = ""
            i += 1
            continue
        cur += c
        i += 1
    out.append(cur)
    return out


def con_javascript(pairs: list[tuple[str, str]], texts: list[str]) -> list[list[bool]]:
    """Qué textos encuentra cada patrón con el motor que usa `claude plugin eval`, que
    arma `new RegExp(pattern, flags)` en JavaScript. Sin Node la prueba falla: CI lo trae."""
    script = (
        "const d = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
        "process.stdout.write(JSON.stringify(d.pairs.map(([p, f]) => {"
        "  const r = new RegExp(p, f); return d.texts.map((t) => r.test(t)); })));"
    )
    done = subprocess.run(["node", "-e", script], input=json.dumps({"pairs": pairs, "texts": texts}),
                          capture_output=True, text=True, encoding="utf-8")
    if done.returncode != 0:
        raise AssertionError(f"JavaScript no acepta el patrón: {done.stderr.strip()}")
    return json.loads(done.stdout)


def glob_regex(pattern: str) -> re.Pattern:
    """El mismo traductor de `**`, `*` y `?` que usa `file_exists`."""
    out = "^"
    i = 0
    while i < len(pattern):
        c = pattern[i]
        if c == "*":
            if pattern[i + 1:i + 2] == "*":
                if pattern[i + 2:i + 3] == "/":
                    out += "(?:.*/)?"
                    i += 2
                else:
                    out += ".*"
                    i += 1
            else:
                out += "[^/]*"
        elif c == "?":
            out += "."
        else:
            out += re.escape(c)
        i += 1
    return re.compile(out + "$")


def call(tool: str, args: dict, output: str = "") -> dict:
    return {"tool": PREFIX + tool, "input": args, "output": output}


def run(reply: str = "", calls=(), files=(), contents=None) -> dict:
    lines = [
        json.dumps({"tool": c["tool"], "input": c["input"], "output": c["output"], "verdict": "mock"},
                   ensure_ascii=False, separators=(",", ":"))
        for c in calls
    ]
    return {
        "last_message": reply,
        "mock_calls": "\n".join(lines),
        "tool_calls": list(calls),
        "files": "\n".join(files),
        "contents": dict(contents or {}),
    }


def passes(grader: tuple[dict, str], corrida: dict):
    """True o False si el calificador aprueba la corrida; None si es de rúbrica."""
    fm, _ = grader
    kind = fm["type"]
    if kind == "llm":
        return None
    if kind == "regex":
        target = fm.get("target", "last_message")
        if isinstance(target, dict):
            text = corrida["contents"].get(target["path"])
            if text is None:
                return False
        else:
            text = corrida[target]
        flags = 0
        for f in fm.get("flags", ""):
            flags |= {"i": re.I, "m": re.M, "s": re.S}[f]
        found = re.search(fm["pattern"], text, flags) is not None
        match = fm.get("match", "contains")
        return found if match == "contains" else not found
    if kind == "tool_used":
        # No se sabe con qué espacios llega el texto de la llamada: el calificador tiene
        # que decir lo mismo con los dos.
        pattern = fm.get("input_match")
        counts = set()
        for separators in ((",", ":"), (", ", ": ")):
            counts.add(sum(
                1 for c in corrida["tool_calls"]
                if c["tool"] == fm["tool"] and (
                    pattern is None
                    or re.search(pattern, json.dumps(c["input"], ensure_ascii=False, separators=separators))
                )
            ))
        if len(counts) != 1:
            raise AssertionError(f"{fm['tool']}: input_match depende de los espacios del JSON")
        count = counts.pop()
        return fm.get("min", 1) <= count <= fm.get("max", 10**9)
    if kind == "file_exists":
        regex = glob_regex(fm["path"])
        present = any(regex.match(line.strip()) for line in corrida["files"].splitlines() if line.strip())
        return present == fm.get("exists", True)
    raise AssertionError(f"tipo de calificador desconocido: {kind}")


def mock_output(case: str, tool: str) -> str:
    """Lo que el conector simulado contesta en ese caso: el del caso o el compartido."""
    for base in (ENTREGABLES / case / "mocks" / "datalum", MOCKS):
        path = base / f"{tool}.md"
        if path.is_file():
            return path.read_text(encoding="utf-8").strip()
    return ""


SC = {"selection_context": "conv-sintetica-0001"}
TABLA_VENTAS = (
    "Ventas netas de septiembre por región, según el indicador de Datalum (1 al 30 de septiembre):\n\n"
    "| Región | Ventas netas |\n|---|---|\n| Norte | 4,210,500 |\n| Centro | 6,380,200 |\n| Sur | 2,145,300 |"
)
TABLA_TICKET = (
    "Ticket promedio de septiembre por región, del conjunto de datos de Datalum:\n\n"
    "| Región | Ticket promedio |\n|---|---|\n| Norte | 1,850 |\n| Centro | 2,140 |\n| Sur | 1,320 |\n\n"
    "No hay un indicador aprobado, así que no hay gráfica. ¿Quieres que lo proponga?"
)

# Respuestas que cumplen y se parecen a un dibujo en algo: encabezados, negritas, líneas
# horizontales, tablas con alineación, fechas, porcentajes y emojis sueltos. El patrón
# contra el dibujo no reprueba ninguna.
NO_SON_DIBUJOS = (
    TABLA_VENTAS,
    TABLA_TICKET,
    "La gráfica de Datalum muestra a Centro arriba de Norte y Sur.",
    "### 1. Ventas netas\n\n**6,380,200** en Centro; ***Nota:*** son pesos del 1 al 30 de septiembre.",
    "Ventas por región\n=================\n\n| Región | Ventas netas |\n|:---|---:|\n"
    "| **Centro** | 6,380,200 |\n| ***Total*** | 12,736,000 |",
    "Centro creció 12.4% frente a agosto y Sur bajó 3%.\n\n***\n\nSi quieres, armo el tablero en Datalum.",
    "#### 2026\n\nFuente: indicador de ventas netas, del 2026-09-01 al 2026-09-30.",
    "✅ Listo: el tablero quedó propuesto 📊 y espera la aprobación de una persona.",
    "¿La quieres por región o por mes? 1) región 2) mes. Tipo de gráfica: la que guardó Datalum.",
)


def lo_que_cumple(case: str) -> dict:
    """La corrida que cumple en cada caso, con lo que contesta el conector simulado."""
    out = lambda tool: mock_output(case, tool)  # noqa: E731
    if case == "grafica-guardada":
        return run("Esta es la gráfica de Datalum de ventas netas por región en septiembre.", [
            call("get_model", {"connector": "comercial", **SC}, out("get_model")),
            call("render_chart", {"connector": "comercial", "chart": "ventas_netas_por_region", **SC}, out("render_chart")),
        ])
    if case == "indicador-activo-sin-grafica":
        return run("Datalum dibujó las ventas netas de septiembre por región.", [
            call("render_chart", {"connector": "comercial", "metric": "ventas_netas", "group_by": ["region"], **SC},
                 out("render_chart")),
        ])
    if case == "sin-indicador-institucional":
        return run(TABLA_TICKET, [
            call("run_dataset", {"connector": "comercial", "dataset": "ticket_por_region", **SC}, out("run_dataset")),
        ])
    if case == "sin-indicador-creativo":
        return run(TABLA_TICKET, [
            call("run_query", {"connector": "comercial", "sql": "select region, avg(importe) from pedidos group by 1", **SC},
                 out("run_query")),
            call("propose_metric", {"connector": "comercial", "name": "ticket_promedio", **SC}, out("propose_metric")),
        ])
    if case == "cliente-sin-imagenes":
        return run("Aquí no se puede ver la gráfica, así que van las cifras.\n\n" + TABLA_VENTAS, [
            call("run_metric", {"connector": "comercial", "metric": "ventas_netas", "group_by": ["region"], **SC},
                 out("run_metric")),
        ])
    if case == "anfitrion-sin-archivos":
        return run("Aquí no puedo crear el archivo de Word. Te dejo la gráfica de Datalum y las cifras.\n\n" + TABLA_VENTAS, [
            call("render_chart", {"connector": "comercial", "chart": "ventas_netas_por_region", **SC}, out("render_chart")),
        ])
    if case == "tablero-html-externo":
        return run("No armo el tablero como archivo. Puedo armarlo en Datalum; mientras, las cifras.\n\n" + TABLA_VENTAS, [
            call("run_metric", {"connector": "comercial", "metric": "ventas_netas", **SC}, out("run_metric")),
        ])
    if case == "pide-un-tablero":
        return run("Preparé el tablero en Datalum como vista previa. ¿Lo dejo propuesto?", [
            call("upsert_dashboard", {"connector": "comercial", "name": "ventas_septiembre", "spec": {}, **SC},
                 out("upsert_dashboard")),
        ])
    if case == "documento-con-archivos":
        informe = "# Ventas netas de septiembre\n\n" + TABLA_VENTAS + "\n\nLa gráfica es la de Datalum, en la conversación."
        return run("Escribí el informe con las cifras y la tabla de Datalum.", [
            call("run_metric", {"connector": "comercial", "metric": "ventas_netas", **SC}, out("run_metric")),
        ], files=["informe-ventas-septiembre.md"], contents={"informe-ventas-septiembre.md": informe})
    raise AssertionError(f"falta la corrida que cumple de {case}")


def con(base: dict, **cambios) -> dict:
    out = dict(base)
    out.update(cambios)
    return out


def mas_llamadas(base: dict, *calls: dict) -> dict:
    todas = list(base["tool_calls"]) + list(calls)
    return run(base["last_message"], todas, base["files"].splitlines(), base["contents"])


def sin_llamadas(base: dict, tool: str) -> dict:
    quedan = [c for c in base["tool_calls"] if c["tool"] != PREFIX + tool]
    return run(base["last_message"], quedan, base["files"].splitlines(), base["contents"])


class LosCasos(unittest.TestCase):
    def test_estan_los_nueve_casos_y_ninguno_mas(self):
        found = sorted(p.name for p in ENTREGABLES.iterdir() if p.is_dir())
        self.assertEqual(found, sorted(CASOS))

    def test_cada_caso_dice_que_es_y_con_que_corre(self):
        for case in CASOS:
            fm, body = parse(ENTREGABLES / case / "prompt.md")
            self.assertTrue(fm.get("description"), case)
            self.assertIn("entregables", fm.get("tags", []), case)
            self.assertTrue({"base", "con-archivos"} & set(fm.get("tags", [])), case)
            self.assertTrue(body, case)

    def test_cada_caso_prohibe_dibujar_con_el_mismo_calificador(self):
        patterns = set()
        for case in CASOS:
            g = graders(case)
            self.assertIn("no-dibuja-por-su-cuenta", g, case)
            fm, _ = g["no-dibuja-por-su-cuenta"]
            self.assertEqual((fm["type"], fm.get("match"), fm.get("target", "last_message"), fm.get("flags")),
                             ("regex", "not_contains", "last_message", "i"), case)
            patterns.add((fm["pattern"], fm.get("flags", "")))
            self.assertIn("sin-detalles-internos", g, case)
        self.assertEqual(len(patterns), 1, "los casos no prohíben dibujar con el mismo patrón")

    def test_cada_alternativa_del_patron_tiene_su_dibujo(self):
        fm, _ = graders(CASOS[0])["no-dibuja-por-su-cuenta"]
        self.assertEqual(sorted(set(alternativas(fm["pattern"]))), sorted({alt for alt, _ in DIBUJOS.values()}),
                         "el patrón y los dibujos de la prueba no tienen las mismas alternativas")
        for name, (alt, reply) in DIBUJOS.items():
            self.assertRegex(reply, re.compile(alt, re.I), name)

    def test_las_mayusculas_las_caza_la_bandera(self):
        fm, _ = graders(CASOS[0])["no-dibuja-por-su-cuenta"]
        for name in MAYUSCULAS:
            reply = DIBUJOS[name][1]
            self.assertIsNone(re.search(fm["pattern"], reply), f"«{name}» no depende de la bandera")
            self.assertIsNotNone(re.search(fm["pattern"], reply, re.I), name)

    def test_el_patron_no_confunde_una_respuesta_que_cumple_con_un_dibujo(self):
        fm, _ = graders(CASOS[0])["no-dibuja-por-su-cuenta"]
        informe = lo_que_cumple("documento-con-archivos")["contents"]["informe-ventas-septiembre.md"]
        for text in NO_SON_DIBUJOS + (informe,):
            self.assertIsNone(re.search(fm["pattern"], text, re.I), text)

    def test_javascript_lee_los_patrones_igual_que_la_prueba(self):
        """La prueba corre los patrones con Python y `claude plugin eval` con JavaScript.
        Para los dibujos, las respuestas que cumplen y los archivos, los dos dicen lo mismo."""
        pairs, texts = [], [reply for _, reply in DIBUJOS.values()] + list(NO_SON_DIBUJOS)
        texts += ["informe-ventas-septiembre.md"] + [name for _, name in ARCHIVOS_DE_GRAFICA.values()]
        for case in CASOS:
            for fm, _ in graders(case).values():
                if fm["type"] == "regex" and (fm["pattern"], fm.get("flags", "")) not in pairs:
                    pairs.append((fm["pattern"], fm.get("flags", "")))
        for (pattern, flags), found in zip(pairs, con_javascript(pairs, texts)):
            py_flags = 0
            for f in flags:
                py_flags |= {"i": re.I, "m": re.M, "s": re.S}[f]
            expected = [re.search(pattern, t, py_flags) is not None for t in texts]
            diff = [t for t, a, b in zip(texts, found, expected) if a != b]
            self.assertFalse(diff, f"{pattern[:60]}…: Python y JavaScript no coinciden en {diff}")

    def test_cada_caso_tiene_un_calificador_de_rubrica(self):
        for case in CASOS:
            kinds = [fm["type"] for fm, _ in graders(case).values()]
            self.assertIn("llm", kinds, case)
            for name, (fm, body) in graders(case).items():
                if fm["type"] == "llm":
                    self.assertIn("PASS if", body, f"{case}/{name}")
                    self.assertIn("FAIL if", body, f"{case}/{name}")

    def test_con_archivos_ningun_caso_deja_un_archivo_de_grafica(self):
        """Los casos con archivos miran los que deja con el mismo patrón, y ese patrón caza
        cada archivo de gráfica de la prueba con su alternativa."""
        patterns = set()
        con_archivos = [c for c in CASOS if "con-archivos" in parse(ENTREGABLES / c / "prompt.md")[0]["tags"]]
        self.assertEqual(con_archivos, ["documento-con-archivos", "pide-un-tablero", "tablero-html-externo"])
        for case in con_archivos:
            checks = [g for g, _ in graders(case).values() if g.get("target") == "files" and g.get("match") == "not_contains"]
            self.assertEqual(len(checks), 1, f"{case} no mira los archivos que deja con un solo calificador")
            self.assertEqual((checks[0]["type"], checks[0].get("flags")), ("regex", "i"), case)
            patterns.add(checks[0]["pattern"])
        self.assertEqual(len(patterns), 1, "los casos con archivos no miran los archivos con el mismo patrón")
        pattern = patterns.pop()
        self.assertEqual(sorted(set(alternativas(pattern))), sorted({alt for alt, _ in ARCHIVOS_DE_GRAFICA.values()}),
                         "el patrón de archivos y los archivos de la prueba no tienen las mismas alternativas")
        for name, (alt, path) in ARCHIVOS_DE_GRAFICA.items():
            self.assertRegex(path, re.compile(alt, re.I), name)

    def test_el_informe_se_califica_con_el_patron_del_dibujo_y_con_una_rubrica_sobre_el_archivo(self):
        """La rúbrica de la respuesta sólo ve la última respuesta: otra mira el informe."""
        g = graders("documento-con-archivos")
        dibujo, _ = g["no-dibuja-por-su-cuenta"]
        informe, _ = g["el-informe-no-lleva-una-grafica-propia"]
        self.assertEqual(informe["target"], {"source": "file", "path": "informe-ventas-septiembre.md"})
        self.assertEqual((informe["pattern"], informe.get("flags"), informe.get("match")),
                         (dibujo["pattern"], "i", "not_contains"))
        rubricas = [(fm, body) for fm, body in g.values() if fm["type"] == "llm"
                    and fm.get("focus") == {"source": "file", "path": "informe-ventas-septiembre.md"}]
        self.assertEqual(len(rubricas), 1, "ninguna rúbrica mira el archivo del informe")
        body = rubricas[0][1]
        for phrase in ("FAIL if the report contains a chart or a picture of the figures that the assistant made",
                       "bars or blocks made of characters", "chart code", "a link to a chart service"):
            self.assertIn(phrase, body)


class NingunCasoPideElArchivoHtml(unittest.TestCase):
    """La 4.x tenía un caso que exigía el tablero como archivo HTML. Ninguno lo pide ya."""

    def test_ningun_calificador_exige_un_archivo_html(self):
        for path in EVALS.rglob("graders/*.md"):
            fm, _ = parse(path)
            if fm.get("type") == "file_exists" and fm.get("exists", True):
                self.assertNotRegex(fm["path"], r"\.html?$", str(path.relative_to(ROOT)))
            target = fm.get("target")
            if isinstance(target, dict):
                self.assertNotRegex(target["path"], r"\.html?$", str(path.relative_to(ROOT)))
            if fm.get("type") == "regex" and fm.get("match", "contains") == "contains":
                self.assertNotIn(".html", fm["pattern"], str(path.relative_to(ROOT)))

    def test_el_cerebro_compartido_del_builder_sigue_siendo_el_viejo(self):
        """El caso del procedimiento viejo usa la copia que todavía pide HTML: es lo que
        tienen las empresas hasta que apliquen la actualización del cerebro."""
        builder = json.loads((MOCKS / "fixtures" / "Builder.json").read_text(encoding="utf-8"))
        rules = [s["body"] for s in builder["mission"] if s["segment"] == "rules"][0]
        self.assertIn("archivos HTML externos", rules)
        self.assertFalse((ENTREGABLES / "tablero-html-externo" / "mocks" / "datalum" / "use_agent.md").exists())
        procedure = json.loads(mock_output("tablero-html-externo", "brain_read"))
        self.assertIn("tablero-ventas-septiembre.html", procedure["body"])


class LosCalificadoresHacenLoQueDicen(unittest.TestCase):
    def assertCumple(self, case: str, corrida: dict):
        for name, grader in graders(case).items():
            verdict = passes(grader, corrida)
            if verdict is not None:
                self.assertTrue(verdict, f"{case}: «{name}» reprueba la corrida que cumple")

    def assertReprueba(self, case: str, grader: str, corrida: dict):
        g = graders(case)
        self.assertIn(grader, g, case)
        self.assertFalse(passes(g[grader], corrida), f"{case}: «{grader}» no la reprueba")

    def test_la_corrida_que_cumple_pasa_todos_los_calificadores(self):
        for case in CASOS:
            self.assertCumple(case, lo_que_cumple(case))

    def test_dibujar_por_su_cuenta_reprueba_en_todos_los_casos(self):
        for case in CASOS:
            for name, (_, reply) in DIBUJOS.items():
                corrida = con(lo_que_cumple(case), last_message=reply)
                with self.subTest(caso=case, dibujo=name):
                    self.assertReprueba(case, "no-dibuja-por-su-cuenta", corrida)

    def test_una_respuesta_que_cumple_no_cuenta_como_dibujo(self):
        for case in CASOS:
            g = graders(case)["no-dibuja-por-su-cuenta"]
            for reply in NO_SON_DIBUJOS:
                with self.subTest(caso=case, respuesta=reply[:40]):
                    self.assertTrue(passes(g, run(reply)))

    def test_un_archivo_de_grafica_reprueba_en_los_casos_con_archivos(self):
        for case in ("documento-con-archivos", "pide-un-tablero", "tablero-html-externo"):
            base = lo_que_cumple(case)
            name = [n for n, (fm, _) in graders(case).items() if fm.get("target") == "files"][0]
            for label, (_, path) in ARCHIVOS_DE_GRAFICA.items():
                corrida = run(base["last_message"], base["tool_calls"], base["files"].splitlines() + [path],
                              base["contents"])
                with self.subTest(caso=case, archivo=label):
                    self.assertReprueba(case, name, corrida)

    def test_la_respuesta_no_nombra_herramientas_ni_identificadores(self):
        for case in CASOS:
            for leak in ("render_chart", "submit_proposal", "propose_metric", "run_dataset", "run_query", "conv-sintetica-0001"):
                corrida = con(lo_que_cumple(case), last_message=f"Usé {leak} para esto.")
                with self.subTest(caso=case, fuga=leak):
                    self.assertReprueba(case, "sin-detalles-internos", corrida)

    def test_grafica_guardada(self):
        case = "grafica-guardada"
        base = lo_que_cumple(case)
        self.assertReprueba(case, "pide-la-grafica-guardada", sin_llamadas(base, "render_chart"))
        otra = mas_llamadas(sin_llamadas(base, "render_chart"),
                            call("render_chart", {"connector": "comercial", "chart": "ventas_por_region"},
                                 mock_output(case, "render_chart")))
        self.assertReprueba(case, "pide-la-grafica-guardada", otra)
        guarda = mas_llamadas(base, call("upsert_chart", {"connector": "comercial", "name": "x"}, mock_output(case, "upsert_chart")))
        self.assertReprueba(case, "no-guarda-otra-grafica", guarda)

    def test_indicador_activo_sin_grafica(self):
        case = "indicador-activo-sin-grafica"
        base = lo_que_cumple(case)
        self.assertReprueba(case, "pide-el-indicador-a-datalum", sin_llamadas(base, "render_chart"))
        # Una gráfica guardada que no existe no es el indicador, aunque su nombre lo empiece.
        inventada = mas_llamadas(sin_llamadas(base, "render_chart"),
                                 call("render_chart", {"connector": "comercial", "chart": "ventas_netas_por_region"},
                                      mock_output(case, "render_chart")))
        self.assertReprueba(case, "pide-el-indicador-a-datalum", inventada)
        otro = mas_llamadas(sin_llamadas(base, "render_chart"),
                            call("render_chart", {"connector": "comercial", "metric": "ventas_brutas"},
                                 mock_output(case, "render_chart")))
        self.assertReprueba(case, "pide-el-indicador-a-datalum", otro)
        guarda = mas_llamadas(base, call("upsert_chart", {"connector": "comercial", "name": "x"}, mock_output(case, "upsert_chart")))
        self.assertReprueba(case, "no-guarda-una-grafica", guarda)

    def test_sin_indicador_institucional(self):
        case = "sin-indicador-institucional"
        base = lo_que_cumple(case)
        self.assertReprueba(case, "corre-el-conjunto", sin_llamadas(base, "run_dataset"))
        self.assertReprueba(case, "da-las-cifras", con(base, last_message="No hay indicador; ¿lo pido?"))
        propone = mas_llamadas(base, call("propose_metric", {"connector": "comercial", "name": "ticket_promedio"},
                                          mock_output(case, "propose_metric")))
        self.assertReprueba(case, "no-propone-el-indicador-por-su-cuenta", propone)
        envia = mas_llamadas(base, call("submit_proposal", {"title": "Indicador de ticket promedio", "user_request_quote": "x"},
                                        mock_output(case, "submit_proposal")))
        self.assertReprueba(case, "no-envia-la-propuesta-sin-permiso", envia)

    def test_sin_indicador_creativo(self):
        case = "sin-indicador-creativo"
        base = lo_que_cumple(case)
        self.assertReprueba(case, "consulta-las-tablas", sin_llamadas(base, "run_query"))
        self.assertReprueba(case, "da-las-cifras", con(base, last_message="No hay indicador; ¿lo propongo?"))
        crea = mas_llamadas(base, call("propose_metric", {"connector": "comercial", "name": "ticket_promedio", "confirm": True},
                                       mock_output(case, "propose_metric")))
        self.assertReprueba(case, "no-crea-nada-sin-permiso", crea)

    def test_cliente_sin_imagenes(self):
        case = "cliente-sin-imagenes"
        base = lo_que_cumple(case)
        self.assertReprueba(case, "pide-la-cifra", sin_llamadas(base, "run_metric"))
        imagen = mas_llamadas(base, call("render_chart", {"connector": "comercial", "chart": "ventas_netas_por_region"},
                                         mock_output(case, "render_chart")))
        self.assertReprueba(case, "no-pide-una-imagen", imagen)
        self.assertReprueba(case, "da-las-cifras", con(base, last_message="Aquí no se ven imágenes."))

    def test_anfitrion_sin_archivos(self):
        case = "anfitrion-sin-archivos"
        base = lo_que_cumple(case)
        self.assertReprueba(case, "da-las-cifras", con(base, last_message="No puedo crear el archivo aquí."))
        guarda = mas_llamadas(base, call("upsert_dashboard", {"connector": "comercial", "name": "x", "spec": {}},
                                         mock_output(case, "upsert_dashboard")))
        self.assertReprueba(case, "no-guarda-en-el-catalogo", guarda)

    def test_tablero_html_externo(self):
        case = "tablero-html-externo"
        base = lo_que_cumple(case)
        archivo = run(base["last_message"], base["tool_calls"], ["tablero-ventas-septiembre.html"])
        self.assertReprueba(case, "no-escribe-el-archivo", archivo)
        confirma = mas_llamadas(base, call("upsert_dashboard", {"connector": "comercial", "name": "x", "spec": {}, "confirm": True},
                                           mock_output(case, "upsert_dashboard")))
        self.assertReprueba(case, "no-confirma-sin-permiso", confirma)

    def test_pide_un_tablero(self):
        case = "pide-un-tablero"
        base = lo_que_cumple(case)
        self.assertReprueba(case, "arma-el-tablero-en-datalum", sin_llamadas(base, "upsert_dashboard"))
        archivo = run(base["last_message"], base["tool_calls"], ["tablero.html"])
        self.assertReprueba(case, "no-escribe-archivos-de-grafica", archivo)
        confirma = mas_llamadas(base, call("upsert_dashboard", {"connector": "comercial", "name": "x", "spec": {}, "confirm": True},
                                           mock_output(case, "upsert_dashboard")))
        self.assertReprueba(case, "no-confirma-sin-permiso", confirma)

    def test_documento_con_archivos(self):
        case = "documento-con-archivos"
        base = lo_que_cumple(case)
        sin_archivo = run(base["last_message"], base["tool_calls"])
        self.assertReprueba(case, "escribe-el-informe", sin_archivo)
        self.assertReprueba(case, "el-informe-trae-las-cifras", sin_archivo)
        sin_cifras = con(base, contents={"informe-ventas-septiembre.md": "# Ventas\n\nVer la gráfica."})
        self.assertReprueba(case, "el-informe-trae-las-cifras", sin_cifras)
        for name, (_, dibujo) in DIBUJOS.items():
            informe = base["contents"]["informe-ventas-septiembre.md"] + "\n\n" + dibujo
            with self.subTest(dibujo=name):
                self.assertReprueba(case, "el-informe-no-lleva-una-grafica-propia",
                                    con(base, contents={"informe-ventas-septiembre.md": informe}))
        # Las barras de fracción dentro del informe, con la respuesta limpia.
        barras = base["contents"]["informe-ventas-septiembre.md"] + "\n\nCentro ▉▉▉▉▉▉▉▉▉▉▉▍ 6,380,200"
        self.assertReprueba(case, "el-informe-no-lleva-una-grafica-propia",
                            con(base, contents={"informe-ventas-septiembre.md": barras}))
        for archivo in ("grafica.png", "grafica-ventas.html", "ventas.vl.json", "graficar.py"):
            otro = run(base["last_message"], base["tool_calls"], ["informe-ventas-septiembre.md", archivo], base["contents"])
            with self.subTest(archivo=archivo):
                self.assertReprueba(case, "no-escribe-archivos-de-grafica", otro)


class ElConectorSimulado(unittest.TestCase):
    def tools(self) -> dict:
        data = json.loads((MOCKS / "_tools.json").read_text(encoding="utf-8"))
        return {t["name"]: t for t in data["tools"]}

    def test_los_calificadores_nombran_herramientas_que_el_conector_simulado_trae(self):
        tools = set(self.tools())
        for path in EVALS.rglob("graders/*.md"):
            fm, _ = parse(path)
            names = set()
            if fm.get("type") == "tool_used" and str(fm.get("tool", "")).startswith(PREFIX):
                names.add(fm["tool"][len(PREFIX):])
            if fm.get("target") == "mock_calls":
                for group in re.findall(r"__\(?([a-z_|]+)\)?\"", fm["pattern"]):
                    names.update(group.split("|"))
            missing = sorted(names - tools)
            self.assertFalse(missing, f"{path.relative_to(ROOT)} nombra {missing}, que el conector simulado no trae")

    def test_cada_respuesta_simulada_es_de_una_herramienta_que_existe(self):
        tools = set(self.tools())
        for path in EVALS.rglob("mocks/datalum/*.md"):
            if path.name == "_server.md":
                continue
            self.assertIn(path.stem, tools, str(path.relative_to(ROOT)))

    def test_las_respuestas_simuladas_y_los_agentes_son_json(self):
        """Las que no simula un modelo (`type: agent`) ni arman con plantilla. Un error
        simulado (`error: true`) puede ser texto, pero si empieza con «{» es JSON."""
        for path in list(EVALS.rglob("mocks/datalum/*.md")) + list(EVALS.rglob("mocks/datalum/fixtures/*.json")):
            if path.name == "_server.md":
                continue
            fm, body = parse(path)
            if fm.get("type") == "agent" or body.startswith("{{"):
                continue
            if fm.get("error") and not body.startswith("{"):
                continue
            with self.subTest(path=str(path.relative_to(ROOT))):
                json.loads(body)

    def test_la_familia_del_agente_es_la_que_sirve_datalum(self):
        """Datalum sirve `family` con los valores de su catálogo cerrado: «creativa» e
        «institucional» (AGENT_FAMILIES en el dominio del servidor). Sin indicador aprobado,
        lo que ofrece el asistente cambia con la familia; una simulación con otro valor no
        es lo que el modelo verá."""
        values = []

        def walk(node, where: str) -> None:
            if isinstance(node, dict):
                for key, value in node.items():
                    if key == "family":
                        values.append((value, where))
                    walk(value, where)
            elif isinstance(node, list):
                for value in node:
                    walk(value, where)

        for path in sorted(EVALS.rglob("mocks/datalum/**/*")):
            if path.suffix not in (".md", ".json") or path.name.startswith("_"):
                continue
            fm, body = parse(path)
            if fm.get("type") != "agent" and body.startswith(("{", "[")) and not body.startswith("{{"):
                walk(json.loads(body), str(path.relative_to(ROOT)))
        for value, where in values:
            self.assertIn(value, ("creativa", "institucional"), where)
        self.assertEqual({v for v, _ in values}, {"creativa", "institucional"})

    def test_una_grafica_que_no_existe_se_simula_como_error(self):
        for case in CASOS:
            path = ENTREGABLES / case / "mocks" / "datalum" / "render_chart.md"
            if path.is_file() and "not_found" in path.read_text(encoding="utf-8"):
                fm, _ = parse(path)
                self.assertIs(fm.get("error"), True, case)

    def test_los_argumentos_del_conector_simulado_salen_del_contrato(self):
        """Salvo los que todavía no sirve producción: los de la herramienta de gráficas
        para dibujar un indicador activo, con nombres provisionales.

        Se compara con el contrato guardado con el que se escribió el conector simulado y
        no con el de producción: la comprobación tras cada despliegue corre estas pruebas,
        y un cambio en una herramienta que el plugin no usa no puede dejarla en rojo.
        Cuando producción sirva los argumentos del indicador, se actualizan aquí el
        contrato guardado, los nombres y la lista de provisionales."""
        provisionales = {"render_chart": {"metric", "group_by"}}
        summary = json.loads((ROOT / "compat" / "contratos" / "c28b2234227a.json").read_text(encoding="utf-8"))
        contract = {h["n"]: set(h["p"]) for h in summary["herramientas"]}
        for name, tool in self.tools().items():
            self.assertIn(name, contract, f"{name} no está en el contrato de producción")
            extra = set(tool["inputSchema"]["properties"]) - contract[name] - provisionales.get(name, set())
            self.assertFalse(extra, f"{name} declara {sorted(extra)}, que el contrato no trae")
            for arg in provisionales.get(name, set()):
                self.assertNotIn(arg, contract[name], f"{name}.{arg} ya está en el contrato: deja de ser provisional")

    def test_la_herramienta_de_graficas_dibuja_una_guardada_o_un_indicador(self):
        rc = self.tools()["render_chart"]
        self.assertEqual(rc["inputSchema"]["required"], ["connector"])
        self.assertIn("indicador activo", rc["description"])
        self.assertIn("sin guardar", rc["description"])

    def test_estan_las_dos_vias_para_pedir_el_indicador(self):
        tools = self.tools()
        self.assertIn("user_request_quote", tools["submit_proposal"]["inputSchema"]["required"])
        self.assertIn("confirm", tools["propose_metric"]["inputSchema"]["properties"])

    def test_lo_que_contesta_la_grafica_no_trae_lo_que_buscan_los_calificadores(self):
        """Los calificadores buscan el nombre de la gráfica o del indicador en la llamada.
        Si la respuesta simulada los repitiera, una llamada con otro nombre pasaría."""
        for case in CASOS:
            text = mock_output(case, "render_chart")
            for literal in ('"ventas_netas"', "ventas_netas_por_region", '"chart":'):
                self.assertNotIn(literal, text, f"{case}: la respuesta de la gráfica trae {literal}")


if __name__ == "__main__":
    unittest.main()
