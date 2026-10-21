"""Pruebas de las evaluaciones de entregables.

Las evaluaciones de evals/ corren con un modelo real y cuestan; estas pruebas no corren
ningún modelo. Miran que cada caso de entregables tenga los calificadores de la regla
de las gráficas y que esos calificadores hagan lo que dicen: aprueban una corrida que
cumple y reprueban la corrida en la que el asistente dibuja por su cuenta, llama lo que
no debe o escribe el archivo que no debe. Los calificadores con rúbrica (llm) no se
pueden correr aquí: sólo se comprueba que cada caso tiene uno.

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

# Respuestas en las que el asistente dibuja una gráfica por su cuenta. Cada una tiene que
# reprobar el calificador que lo prohíbe en todos los casos.
DIBUJOS = {
    "svg": 'Aquí está:\n<svg width="300" height="120"><rect x="0" y="0" width="80" height="40"/></svg>',
    "página html": "<!DOCTYPE html>\n<html><body><div style=\"width: 62%\">Centro</div></body></html>",
    "bloque html": "```html\n<div class=\"barra\" style=\"height: 40px\"></div>\n```",
    "mermaid": "```mermaid\npie title Ventas\n\"Norte\" : 4210500\n```",
    "chart.js": "const g = new Chart(ctx, { type: 'bar' });",
    "barras de texto": "Norte  ████████ 4,210,500\nCentro ████████████ 6,380,200",
    "barras de bloques": "Sur ▇▇▇▇ 2,145,300",
    "matplotlib": "import matplotlib.pyplot as plt\nplt.bar(regiones, valores)",
    "canvas": "<canvas id=\"g\"></canvas>",
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
            self.assertEqual((fm["type"], fm.get("match"), fm.get("target", "last_message")),
                             ("regex", "not_contains", "last_message"), case)
            patterns.add((fm["pattern"], fm.get("flags", "")))
            self.assertIn("sin-detalles-internos", g, case)
        self.assertEqual(len(patterns), 1, "los casos no prohíben dibujar con el mismo patrón")

    def test_cada_caso_tiene_un_calificador_de_rubrica(self):
        for case in CASOS:
            kinds = [fm["type"] for fm, _ in graders(case).values()]
            self.assertIn("llm", kinds, case)
            for name, (fm, body) in graders(case).items():
                if fm["type"] == "llm":
                    self.assertIn("PASS if", body, f"{case}/{name}")
                    self.assertIn("FAIL if", body, f"{case}/{name}")

    def test_con_archivos_ningun_caso_deja_un_archivo_de_grafica(self):
        for case in CASOS:
            fm, _ = parse(ENTREGABLES / case / "prompt.md")
            if "con-archivos" not in fm["tags"]:
                continue
            checks = [g for g, _ in graders(case).values() if g.get("target") == "files" and g.get("match") == "not_contains"]
            self.assertTrue(checks, f"{case} no mira los archivos que deja")
            for g in checks:
                self.assertIsNotNone(re.search(g["pattern"], "grafica.svg", re.I), case)


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
            for name, reply in DIBUJOS.items():
                corrida = con(lo_que_cumple(case), last_message=reply)
                with self.subTest(caso=case, dibujo=name):
                    self.assertReprueba(case, "no-dibuja-por-su-cuenta", corrida)

    def test_una_respuesta_con_tabla_y_su_fuente_no_cuenta_como_dibujo(self):
        g = graders("grafica-guardada")["no-dibuja-por-su-cuenta"]
        for reply in (TABLA_VENTAS, TABLA_TICKET, "La gráfica de Datalum muestra a Centro arriba de Norte y Sur."):
            self.assertTrue(passes(g, run(reply)))

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
        for name, dibujo in DIBUJOS.items():
            informe = base["contents"]["informe-ventas-septiembre.md"] + "\n\n" + dibujo
            with self.subTest(dibujo=name):
                self.assertReprueba(case, "el-informe-no-lleva-una-grafica-propia",
                                    con(base, contents={"informe-ventas-septiembre.md": informe}))
        imagen = run(base["last_message"], base["tool_calls"], ["informe-ventas-septiembre.md", "grafica.png"], base["contents"])
        self.assertReprueba(case, "no-escribe-archivos-de-grafica", imagen)


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

    def test_una_grafica_que_no_existe_se_simula_como_error(self):
        for case in CASOS:
            path = ENTREGABLES / case / "mocks" / "datalum" / "render_chart.md"
            if path.is_file() and "not_found" in path.read_text(encoding="utf-8"):
                fm, _ = parse(path)
                self.assertIs(fm.get("error"), True, case)

    def test_los_argumentos_del_conector_simulado_salen_del_contrato(self):
        """Salvo los que todavía no sirve producción: los de la herramienta de gráficas
        para dibujar un indicador activo. Cuando el contrato los traiga, esta lista se
        vacía."""
        provisionales = {"render_chart": {"metric", "group_by"}}
        summary = json.loads((ROOT / "compat" / "contrato-produccion.json").read_text(encoding="utf-8"))
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
