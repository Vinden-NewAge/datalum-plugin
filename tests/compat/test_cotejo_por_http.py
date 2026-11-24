"""El cotejo contra un servidor HTTP de verdad, en local.

`Production` habla con un servidor que escucha en 127.0.0.1 y que imita las conductas
de Datalum sin credencial:

  anterior          hasta la v2.296.0: el saludo y una lista corta sin credencial
  pide_credencial   desde la v2.296.1: todo POST sin credencial recibe 401 con
                    `WWW-Authenticate: Bearer realm=…, resource_metadata=…`
  sin_cabecera      un 401 sin `WWW-Authenticate`
  sin_metadatos     un 401 con `WWW-Authenticate` sin `resource_metadata`
  otro_servidor     un 401 cuyo `resource_metadata` apunta a otro servidor
  metadatos_http    un 401 cuyo `resource_metadata` está en http
  esquema_basic     un 401 con `WWW-Authenticate: Basic …, resource_metadata=…`
  parametro_parecido un 401 con `xresource_metadata=…` y no `resource_metadata`
  prohibido         un 403 con su `WWW-Authenticate`

Con la credencial de prueba todos sirven el saludo y el catálogo completo; con otra
credencial contestan 401. Las
peticiones viajan por urllib y por un socket de verdad; sólo cambia la dirección, que
`Production` exige en https y el servidor de prueba sirve en http.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import os
import threading
import unittest
from pathlib import Path
from unittest import mock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from .support import INSTRUCTIONS, SCRIPTS, SHA_B, Repo, base_tools, git, summary_of

from compatlib import contract, pipeline, production  # noqa: E402

TOKEN = "credencial-de-prueba-que-no-sale-en-ningun-registro"
MCP = "https://mcp.example.invalid/mcp"
METADATA = "https://mcp.example.invalid/.well-known/oauth-protected-resource"
REAL_PRODUCTION = production.Production


def _cli():
    """scripts/compat.py cargado por su ruta, para llamar a sus órdenes."""
    spec = importlib.util.spec_from_file_location("compat_cli_de_prueba", SCRIPTS / "compat.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Servidor:
    """Un despliegue de Datalum en local con la conducta que se le pida."""

    def __init__(self, conducta: str, *, tools: list = None, instructions: str = INSTRUCTIONS,
                 host: str = "mcp.example.invalid") -> None:
        self.conducta = conducta
        metadata = f"https://{host}/.well-known/oauth-protected-resource"
        self.tools = tools if tools is not None else base_tools()
        self.instructions = instructions
        self.peticiones: list = []
        servidor = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:
                pass

            def _send(self, status: int, data: dict, headers: dict = None) -> None:
                body = json.dumps(data).encode("utf-8")
                self.send_response(status)
                self.send_header("content-type", "application/json")
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                if self.path == "/health":
                    return self._send(200, {"ok": True, "build": {"sha": SHA_B, "release": "v9.0.0"}})
                self._send(404, {})

            def do_POST(self) -> None:
                auth = self.headers.get("authorization")
                servidor.peticiones.append({"ruta": self.path, "auth": auth})
                with_token = auth == f"Bearer {TOKEN}"
                if auth is not None and not with_token:
                    return self._send(401, _error(), {"www-authenticate": f'Bearer error="invalid_token", resource_metadata="{metadata}"'})
                if not with_token and servidor.conducta != "anterior":
                    # La v2.296.1 responde antes de leer el cuerpo.
                    headers = {
                        "pide_credencial": {"www-authenticate": f'Bearer realm="vinden-datahub", resource_metadata="{metadata}"'},
                        "sin_cabecera": {},
                        "sin_metadatos": {"www-authenticate": 'Bearer realm="vinden-datahub"'},
                        "otro_servidor": {"www-authenticate": 'Bearer realm="x", resource_metadata="https://otro.example.invalid/.well-known/oauth-protected-resource"'},
                        "metadatos_http": {"www-authenticate": f'Bearer realm="x", resource_metadata="{metadata.replace("https:", "http:")}"'},
                        "esquema_basic": {"www-authenticate": f'Basic realm="x", resource_metadata="{metadata}"'},
                        "parametro_parecido": {"www-authenticate": f'Bearer realm="x", xresource_metadata="{metadata}"'},
                        "prohibido": {"www-authenticate": f'Bearer realm="x", resource_metadata="{metadata}"'},
                    }[servidor.conducta]
                    return self._send(403 if servidor.conducta == "prohibido" else 401, _error(), headers)
                length = int(self.headers.get("content-length") or 0)
                message = json.loads(self.rfile.read(length))
                method = message.get("method")
                if method == "initialize":
                    result = {
                        "protocolVersion": "2025-06-18",
                        "serverInfo": {"name": "datalum", "version": "9.0.0"},
                        "capabilities": {"tools": {}},
                        "instructions": servidor.instructions,
                    }
                elif method == "tools/list":
                    result = {"tools": servidor.tools if with_token else servidor.tools[:1]}
                else:
                    return self._send(200, {"jsonrpc": "2.0", "id": message.get("id"), "error": {"code": -32601, "message": "no"}})
                self._send(200, {"jsonrpc": "2.0", "id": message.get("id"), "result": result})

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self._httpd.server_address[1]}"
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join()

    def fetch(self, method, url, headers, body):
        return production.http_fetch(method, self.base + urlsplit(url).path, headers, body)

    def production(self, *, token, url: str = MCP) -> production.Production:
        """`token` True manda la credencial de prueba; una cadena, esa credencial."""
        value = TOKEN if token is True else (token or None)
        return REAL_PRODUCTION(url, fetch=self.fetch, token=value)


def _error() -> dict:
    return {"jsonrpc": "2.0", "id": None, "error": {"code": -32001, "message": "Authentication required"}}


def aviso(summary=None, origin="aviso"):
    return {
        "entorno": "prod", "origen": origin, "sha": SHA_B if origin == "aviso" else None,
        "release": "v9.0.0", "corrida": None, "actor": "despliegue", "contrato": summary,
    }


class Cotejo(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Repo()
        self.addCleanup(self.repo.close)

    def servidor(self, conducta: str, **kw) -> Servidor:
        s = Servidor(conducta, **kw)
        self.addCleanup(s.close)
        return s

    def evaluar(self, servidor: Servidor, ev: dict, *, token: bool) -> dict:
        git(self.repo.root, "reset", "--hard", "HEAD")
        evaluation = pipeline.evaluate(
            self.repo.root, ev, prod=servidor.production(token=token),
            today="2026-11-24", attempts=1, wait=lambda _: None,
        )
        self.assertNotIn(TOKEN, json.dumps(evaluation, ensure_ascii=False))
        self.assertNotIn(TOKEN, json.dumps(pipeline.proposal(dict(evaluation, resultado=evaluation["resultado"] or "x")), ensure_ascii=False))
        return evaluation

    # La v2.296.1: sin credencial, 401 con dónde iniciar sesión.

    def test_v2_296_1_con_credencial_el_cotejo_es_completo(self):
        s = self.servidor("pide_credencial")
        ev = self.evaluar(s, aviso(summary_of(base_tools())), token=True)
        self.assertEqual(ev["resultado"], "compatible_sin_cambios", ev["detalle"])
        self.assertEqual(ev["contrato"]["verificacion"], "completa")
        self.assertEqual(ev["contrato"]["sin_credencial"], "pide_credencial")
        # El saludo y el catálogo van con la credencial; la propiedad del 401 se mide sin ella.
        self.assertIn(None, [p["auth"] for p in s.peticiones])
        self.assertIn(f"Bearer {TOKEN}", [p["auth"] for p in s.peticiones])

    def test_v2_296_1_sin_credencial_un_401_con_su_cabecera_no_es_un_fallo(self):
        s = self.servidor("pide_credencial")
        ev = self.evaluar(s, aviso(summary_of(base_tools())), token=False)
        self.assertEqual(ev["resultado"], "compatible_sin_cambios", ev["detalle"])
        self.assertEqual(ev["contrato"]["sin_credencial"], "pide_credencial")
        self.assertEqual(ev["contrato"]["verificacion"], "minima")
        self.assertTrue(all(p["auth"] is None for p in s.peticiones))

    def test_v2_296_1_con_credencial_el_contrato_sale_del_servidor_sin_aviso(self):
        s = self.servidor("pide_credencial")
        ev = self.evaluar(s, aviso(None, origin="reconciliacion"), token=True)
        self.assertEqual(ev["contrato"].get("origen"), "servidor", ev["detalle"])
        self.assertEqual(ev["resultado"], "compatible_sin_cambios")
        self.assertEqual(ev["contrato"]["verificacion"], "completa")

    def test_v2_296_1_el_catalogo_completo_distinto_del_aviso_se_rechaza(self):
        s = self.servidor("pide_credencial", tools=base_tools()[:4])
        ev = self.evaluar(s, aviso(summary_of(base_tools())), token=True)
        self.assertEqual(ev["resultado"], "contrato_no_coincide", ev["detalle"])

    def test_v2_296_1_instrucciones_distintas_del_aviso_se_rechazan(self):
        s = self.servidor("pide_credencial", instructions="Otras instrucciones.")
        ev = self.evaluar(s, aviso(summary_of(base_tools())), token=True)
        self.assertEqual(ev["resultado"], "contrato_no_coincide", ev["detalle"])

    # La conducta anterior, mientras dura el despliegue.

    def test_anterior_sin_credencial_coteja_el_saludo_publico_y_lo_dice(self):
        s = self.servidor("anterior")
        ev = self.evaluar(s, aviso(summary_of(base_tools())), token=False)
        self.assertEqual(ev["resultado"], "compatible_sin_cambios", ev["detalle"])
        self.assertEqual(ev["contrato"]["sin_credencial"], "saludo_publico")
        self.assertEqual(ev["contrato"]["verificacion"], "parcial")

    def test_anterior_sin_credencial_instrucciones_distintas_se_rechazan(self):
        s = self.servidor("anterior", instructions="Otras instrucciones.")
        ev = self.evaluar(s, aviso(summary_of(base_tools())), token=False)
        self.assertEqual(ev["resultado"], "contrato_no_coincide", ev["detalle"])

    def test_anterior_con_credencial_el_cotejo_es_completo(self):
        s = self.servidor("anterior")
        ev = self.evaluar(s, aviso(summary_of(base_tools())), token=True)
        self.assertEqual(ev["resultado"], "compatible_sin_cambios", ev["detalle"])
        self.assertEqual(ev["contrato"]["sin_credencial"], "saludo_publico")
        self.assertEqual(ev["contrato"]["verificacion"], "completa")

    # Lo que sigue siendo un fallo.

    def test_un_401_sin_www_authenticate_es_un_fallo(self):
        s = self.servidor("sin_cabecera")
        ev = self.evaluar(s, aviso(summary_of(base_tools())), token=True)
        self.assertEqual(ev["resultado"], "contrato_no_coincide", ev["detalle"])
        self.assertIn("401 sin WWW-Authenticate", ev["detalle"])

    def test_un_401_sin_resource_metadata_es_un_fallo(self):
        s = self.servidor("sin_metadatos")
        ev = self.evaluar(s, aviso(summary_of(base_tools())), token=False)
        self.assertEqual(ev["resultado"], "contrato_no_coincide", ev["detalle"])
        self.assertIn("WWW-Authenticate sin resource_metadata", ev["detalle"])

    def test_un_401_que_manda_a_iniciar_sesion_en_otro_servidor_es_un_fallo(self):
        s = self.servidor("otro_servidor")
        ev = self.evaluar(s, aviso(summary_of(base_tools())), token=True)
        self.assertEqual(ev["resultado"], "contrato_no_coincide", ev["detalle"])
        self.assertIn("no apunta a este mismo servidor", ev["detalle"])

    def test_la_salida_dice_que_conducta_vio(self):
        for conducta, frase in (("pide_credencial", "401"), ("anterior", "contesta el saludo")):
            with self.subTest(conducta=conducta):
                s = self.servidor(conducta)
                ev = self.evaluar(s, aviso(summary_of(base_tools()), origin="aviso"), token=False)
                ev = dict(ev, resultado="contrato_no_disponible", detalle="d")
                self.assertIn(frase, pipeline.proposal(ev)["cuerpo"])

    # Una credencial que el servidor rechaza no impide cotejar sin ella (R2).

    def test_anterior_con_credencial_rechazada_coteja_sin_ella_y_lo_dice(self):
        s = self.servidor("anterior")
        ev = self.evaluar(s, aviso(summary_of(base_tools())), token="otra-credencial")
        self.assertEqual(ev["resultado"], "compatible_sin_cambios", ev["detalle"])
        self.assertEqual(ev["contrato"]["verificacion"], "parcial")
        self.assertEqual(ev["contrato"]["sin_credencial"], "saludo_publico")
        self.assertEqual(ev["contrato"]["credencial"], "rechazada")
        self.assertTrue(any("credencial de lectura no vale" in n for n in ev["notas"]), ev["notas"])

    def test_v2_296_1_con_credencial_rechazada_coteja_sin_ella(self):
        s = self.servidor("pide_credencial")
        ev = self.evaluar(s, aviso(summary_of(base_tools())), token="otra-credencial")
        self.assertEqual(ev["resultado"], "compatible_sin_cambios", ev["detalle"])
        self.assertEqual(ev["contrato"]["verificacion"], "minima")
        self.assertEqual(ev["contrato"]["credencial"], "rechazada")
        # Rechazada una vez, no se vuelve a mandar en cada petición.
        self.assertEqual(sum(1 for p in s.peticiones if p["auth"]), 1)

    def test_con_la_credencial_aceptada_no_se_anota_nada(self):
        s = self.servidor("pide_credencial")
        ev = self.evaluar(s, aviso(summary_of(base_tools())), token=True)
        self.assertNotIn("credencial", ev["contrato"])

    # La forma del 401 (R3).

    def test_un_resource_metadata_en_http_es_un_fallo(self):
        s = self.servidor("metadatos_http")
        ev = self.evaluar(s, aviso(summary_of(base_tools())), token=False)
        self.assertEqual(ev["resultado"], "contrato_no_coincide", ev["detalle"])
        self.assertIn("no apunta a este mismo servidor en https", ev["detalle"])

    def test_un_www_authenticate_que_no_es_bearer_es_un_fallo(self):
        s = self.servidor("esquema_basic")
        ev = self.evaluar(s, aviso(summary_of(base_tools())), token=False)
        self.assertEqual(ev["resultado"], "contrato_no_coincide", ev["detalle"])
        self.assertIn("que no es Bearer", ev["detalle"])

    def test_un_parametro_que_sólo_termina_en_resource_metadata_no_cuenta(self):
        s = self.servidor("parametro_parecido")
        ev = self.evaluar(s, aviso(summary_of(base_tools())), token=False)
        self.assertEqual(ev["resultado"], "contrato_no_coincide", ev["detalle"])
        self.assertIn("WWW-Authenticate sin resource_metadata", ev["detalle"])

    def test_un_403_sin_credencial_no_es_pedir_credencial(self):
        s = self.servidor("prohibido")
        ev = self.evaluar(s, aviso(summary_of(base_tools())), token=False)
        self.assertEqual(ev["resultado"], "despliegue_no_confirmado", ev["detalle"])
        self.assertIn("403", ev["detalle"])

    # Lo que dice la salida (R4).

    def evaluar_por_la_orden(self, servidor: Servidor, ev: dict, environ: dict, url: str = MCP) -> tuple:
        """`compat.py evaluar` contra el servidor local; devuelve su salida y la evaluación."""
        cli = _cli()
        seen = {}

        def build(mcp_url, *, token=None):
            seen["url"], seen["token"] = mcp_url, token
            return REAL_PRODUCTION(mcp_url, fetch=servidor.fetch, token=token)

        evento, salida = self.repo.root / "evento.json", self.repo.root / "salida.json"
        evento.write_text(json.dumps(ev), encoding="utf-8")
        out = io.StringIO()
        with mock.patch.object(cli, "ROOT", self.repo.root), \
                mock.patch.object(cli.production, "Production", build), \
                mock.patch.dict(os.environ, environ, clear=False), \
                contextlib.redirect_stdout(out):
            for name in ("DATALUM_COMPAT_TOKEN", "DATALUM_COMPAT_TOKEN_QA"):
                if name not in environ:
                    os.environ.pop(name, None)
            code = cli.cmd_evaluar(argparse.Namespace(evento=str(evento), salida=str(salida)))
        self.assertEqual(code, 0, out.getvalue())
        self.assertEqual(seen["url"], url)
        self.assertNotIn(TOKEN, out.getvalue())
        return out.getvalue(), json.loads(salida.read_text(encoding="utf-8")), seen

    def test_la_orden_evaluar_dice_el_cotejo_y_su_conducta(self):
        for conducta, frase in (
            ("pide_credencial", "Cotejo minima: sin credencial el servidor contesta 401"),
            ("anterior", "Cotejo parcial: sin credencial el servidor contesta el saludo"),
        ):
            with self.subTest(conducta=conducta):
                s = self.servidor(conducta)
                out, _, _ = self.evaluar_por_la_orden(s, aviso(summary_of(base_tools())), {})
                self.assertIn(frase, out)

    def test_la_orden_evaluar_dice_si_la_credencial_no_vale(self):
        s = self.servidor("pide_credencial")
        out, ev, _ = self.evaluar_por_la_orden(s, aviso(summary_of(base_tools())), {"DATALUM_COMPAT_TOKEN": "otra-credencial"})
        self.assertEqual(ev["contrato"]["credencial"], "rechazada")
        self.assertIn("la credencial de lectura no vale", out)

    def test_la_credencial_de_produccion_no_viaja_a_qa(self):
        s = self.servidor("pide_credencial", host="qa.example.invalid")
        ev = dict(aviso(summary_of(base_tools())), entorno="qa")
        _, _, seen = self.evaluar_por_la_orden(s, ev, {"DATALUM_COMPAT_TOKEN": TOKEN}, url="https://qa.example.invalid/mcp")
        self.assertIsNone(seen["token"])
        self.assertTrue(all(p["auth"] is None for p in s.peticiones))
        _, out, seen = self.evaluar_por_la_orden(
            s, ev, {"DATALUM_COMPAT_TOKEN": "otra", "DATALUM_COMPAT_TOKEN_QA": TOKEN}, url="https://qa.example.invalid/mcp")
        self.assertEqual(seen["token"], TOKEN)
        self.assertEqual(out["contrato"]["verificacion"], "completa")

    # Instrucciones nuevas en minima: el texto se guarda antes de aprobar la huella (R1).

    def test_minima_la_huella_no_se_aprueba_sin_guardar_su_texto(self):
        root = self.repo.root
        nuevas = "Instrucciones nuevas del servidor."
        aviso_nuevo = aviso(summary_of(base_tools(), nuevas))
        huella = contract.sha256_text(nuevas)
        texto = root / "compat" / "instrucciones" / f"{huella[:12]}.txt"
        self.repo.write(f"compat/instrucciones/{contract.sha256_text(INSTRUCTIONS)[:12]}.txt", INSTRUCTIONS)
        self.assertEqual(pipeline.instruction_texts(root), [])

        s = self.servidor("pide_credencial", instructions=nuevas)
        run = lambda ev: pipeline.evaluate(root, ev, prod=s.production(token=False),
                                           today="2026-11-24", attempts=1, wait=lambda _: None)
        ev = run(aviso_nuevo)
        self.assertEqual((ev["resultado"], ev["contrato"]["verificacion"]), ("revision_requerida", "minima"), ev["detalle"])
        self.assertFalse(texto.exists())
        cuerpo = pipeline.proposal(ev)["cuerpo"]
        self.assertIn(f"compat/instrucciones/{huella[:12]}.txt", cuerpo)
        self.assertIn("en el mismo PR", cuerpo)

        # Quien revisa añade la huella sin el texto: la comprobación del PR lo para.
        requisitos = json.loads((root / "compat/requisitos.json").read_text(encoding="utf-8"))
        requisitos["instrucciones_revisadas"].append(huella)
        self.repo.write_json("compat/requisitos.json", requisitos)
        problemas = pipeline.instruction_texts(root)
        self.assertEqual(len(problemas), 1, problemas)
        self.assertIn(f"compat/instrucciones/{huella[:12]}.txt", problemas[0])

        # Un texto que no es el de la huella tampoco vale.
        self.repo.write(f"compat/instrucciones/{huella[:12]}.txt", "Otro texto.")
        self.assertIn("no corresponde a su huella", " ".join(pipeline.instruction_texts(root)))

        # Con el texto leído en el conector, la lectura siguiente promueve el contrato y
        # la comprobación del paso de pruebas pasa.
        self.repo.write(f"compat/instrucciones/{huella[:12]}.txt", nuevas)
        self.assertEqual(pipeline.instruction_texts(root), [])
        ev = run(dict(aviso(None, origin="reconciliacion")))
        self.assertEqual(ev["resultado"], "compatible_sin_cambios", ev["detalle"])
        vigente = json.loads((root / "compat/contrato-produccion.json").read_text(encoding="utf-8"))
        self.assertEqual(vigente["instrucciones_sha256"], huella)
        self.assertEqual(pipeline.instruction_texts(root), [])

    def test_el_contrato_vigente_sin_su_texto_no_pasa(self):
        problemas = pipeline.instruction_texts(self.repo.root)
        self.assertTrue(any("contrato vigente" in p for p in problemas), problemas)

if __name__ == "__main__":
    unittest.main()
