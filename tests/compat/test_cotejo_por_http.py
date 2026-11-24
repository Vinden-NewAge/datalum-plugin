"""El cotejo contra un servidor HTTP de verdad, en local.

`Production` habla con un servidor que escucha en 127.0.0.1 y que imita las conductas
de Datalum sin credencial:

  anterior          hasta la v2.296.0: el saludo y una lista corta sin credencial
  pide_credencial   desde la v2.296.1: todo POST sin credencial recibe 401 con
                    `WWW-Authenticate: Bearer realm=…, resource_metadata=…`
  sin_cabecera      un 401 sin `WWW-Authenticate`
  sin_metadatos     un 401 con `WWW-Authenticate` sin `resource_metadata`
  otro_servidor     un 401 cuyo `resource_metadata` apunta a otro servidor

Con la credencial de prueba los cuatro sirven el saludo y el catálogo completo. Las
peticiones viajan por urllib y por un socket de verdad; sólo cambia la dirección, que
`Production` exige en https y el servidor de prueba sirve en http.
"""

from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from .support import INSTRUCTIONS, SHA_B, Repo, base_tools, git, summary_of

from compatlib import pipeline, production  # noqa: E402

TOKEN = "credencial-de-prueba-que-no-sale-en-ningun-registro"
MCP = "https://mcp.example.invalid/mcp"
METADATA = "https://mcp.example.invalid/.well-known/oauth-protected-resource"


class Servidor:
    """Un despliegue de Datalum en local con la conducta que se le pida."""

    def __init__(self, conducta: str, *, tools: list = None, instructions: str = INSTRUCTIONS) -> None:
        self.conducta = conducta
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
                    return self._send(401, _error(), {"www-authenticate": f'Bearer error="invalid_token", resource_metadata="{METADATA}"'})
                if not with_token and servidor.conducta != "anterior":
                    # La v2.296.1 responde antes de leer el cuerpo.
                    headers = {
                        "pide_credencial": {"www-authenticate": f'Bearer realm="vinden-datahub", resource_metadata="{METADATA}"'},
                        "sin_cabecera": {},
                        "sin_metadatos": {"www-authenticate": 'Bearer realm="vinden-datahub"'},
                        "otro_servidor": {"www-authenticate": 'Bearer realm="x", resource_metadata="https://otro.example.invalid/.well-known/oauth-protected-resource"'},
                    }[servidor.conducta]
                    return self._send(401, _error(), headers)
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

    def production(self, *, token: bool) -> production.Production:
        def fetch(method, url, headers, body):
            return production.http_fetch(method, self.base + urlsplit(url).path, headers, body)

        return production.Production(MCP, fetch=fetch, token=TOKEN if token else None)


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
        self.assertIn("WWW-Authenticate", ev["detalle"])

    def test_un_401_sin_resource_metadata_es_un_fallo(self):
        s = self.servidor("sin_metadatos")
        ev = self.evaluar(s, aviso(summary_of(base_tools())), token=False)
        self.assertEqual(ev["resultado"], "contrato_no_coincide", ev["detalle"])
        self.assertIn("resource_metadata", ev["detalle"])

    def test_un_401_que_manda_a_iniciar_sesion_en_otro_servidor_es_un_fallo(self):
        s = self.servidor("otro_servidor")
        ev = self.evaluar(s, aviso(summary_of(base_tools())), token=True)
        self.assertEqual(ev["resultado"], "contrato_no_coincide", ev["detalle"])
        self.assertIn("resource_metadata", ev["detalle"])

    def test_la_salida_dice_que_conducta_vio(self):
        for conducta, frase in (("pide_credencial", "401"), ("anterior", "contesta el saludo")):
            with self.subTest(conducta=conducta):
                s = self.servidor(conducta)
                ev = self.evaluar(s, aviso(summary_of(base_tools()), origin="aviso"), token=False)
                ev = dict(ev, resultado="contrato_no_disponible", detalle="d")
                self.assertIn(frase, pipeline.proposal(ev)["cuerpo"])

    def test_una_credencial_rechazada_es_un_fallo(self):
        s = self.servidor("pide_credencial")
        prod = s.production(token=True)
        prod._token = "otra-credencial"
        git(self.repo.root, "reset", "--hard", "HEAD")
        ev = pipeline.evaluate(self.repo.root, aviso(summary_of(base_tools())), prod=prod,
                               today="2026-11-24", attempts=1, wait=lambda _: None)
        self.assertNotEqual(ev["resultado"], "compatible_sin_cambios")
        self.assertIn("401", ev["detalle"])


if __name__ == "__main__":
    unittest.main()
