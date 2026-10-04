"""Lo que un despliegue de Datalum dice de sí mismo desde fuera.

Tres lecturas, todas contra el servidor desplegado y ninguna contra el repositorio:

  salud      GET <origen>/health, público. Trae el commit y la versión que sirve la
             imagen en ese momento. Un rollback devuelve el commit anterior.
  saludo     initialize del MCP, público. Trae la versión del protocolo y el texto de
             las instrucciones del servidor.
  catálogo   tools/list del MCP. Sin credencial sirve tres herramientas; con una
             credencial de lectura sirve el catálogo completo.

La dirección sale de la configuración del plugin, nunca del aviso de un despliegue.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Callable, Optional
from urllib.parse import urlsplit

from . import contract

Fetch = Callable[[str, str, dict, Optional[bytes]], tuple]
TIMEOUT = 20
CLIENT = {"name": "datalum-plugin-compat", "version": "1"}


class ProductionError(RuntimeError):
    """El servidor no contestó lo esperado."""


def http_fetch(method: str, url: str, headers: dict, body: Optional[bytes]) -> tuple:
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ProductionError(f"sin respuesta de {urlsplit(url).netloc}: {e}") from e


class Production:
    def __init__(self, mcp_url: str, *, fetch: Fetch = http_fetch, token: Optional[str] = None) -> None:
        parts = urlsplit(mcp_url)
        if parts.scheme != "https" or not parts.netloc:
            raise ProductionError(f"la dirección del servidor tiene que ser https: {mcp_url!r}")
        self.mcp_url = mcp_url
        self.health_url = f"https://{parts.netloc}/health"
        self._fetch = fetch
        self._token = token

    @property
    def has_token(self) -> bool:
        return bool(self._token)

    def health(self) -> dict:
        status, text = self._fetch("GET", self.health_url, {"accept": "application/json"}, None)
        if status != 200:
            raise ProductionError(f"/health contestó {status}")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ProductionError("/health no devolvió JSON") from e
        build = data.get("build") if isinstance(data, dict) else None
        if not isinstance(build, dict) or not isinstance(build.get("sha"), str):
            raise ProductionError("/health no trae build.sha")
        sha = build["sha"].lower()
        if not contract.SHA40.match(sha):
            raise ProductionError("build.sha no es un commit completo")
        release = build.get("release")
        return {
            "ok": data.get("ok") is True,
            "sha": sha,
            "release": release if isinstance(release, str) and release else None,
        }

    def _rpc(self, method: str, params: Optional[dict], *, auth: bool) -> dict:
        headers = {
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
        }
        if auth:
            if not self._token:
                raise ProductionError("no hay credencial de lectura configurada")
            headers["authorization"] = f"Bearer {self._token}"
        payload = {"jsonrpc": "2.0", "id": 1, "method": method}
        if params is not None:
            payload["params"] = params
        status, text = self._fetch("POST", self.mcp_url, headers, json.dumps(payload).encode("utf-8"))
        if status != 200:
            raise ProductionError(f"{method} contestó {status}")
        message = _parse_rpc(text)
        if "result" not in message:
            raise ProductionError(f"{method} devolvió un error del servidor")
        return message["result"]

    def greeting(self) -> dict:
        result = self._rpc(
            "initialize",
            {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": CLIENT},
            auth=False,
        )
        instructions = result.get("instructions")
        if not isinstance(instructions, str) or not instructions:
            raise ProductionError("el saludo no trae instrucciones")
        return {
            "protocolo": result.get("protocolVersion"),
            "version": (result.get("serverInfo") or {}).get("version"),
            "instrucciones": instructions,
            "instrucciones_sha256": contract.sha256_text(instructions),
        }

    def tools(self, *, auth: bool) -> list:
        result = self._rpc("tools/list", None, auth=auth)
        tools = result.get("tools")
        if not isinstance(tools, list):
            raise ProductionError("tools/list no trae una lista")
        return tools

    def full_contract(self) -> dict:
        """El resumen del contrato leído del servidor con la credencial de lectura."""
        greeting = self.greeting()
        return contract.summarize(
            self.tools(auth=True),
            protocol=greeting["protocolo"],
            instructions=greeting["instrucciones"],
        )


def _parse_rpc(text: str) -> dict:
    """Una respuesta JSON-RPC puede venir como JSON o como un flujo de eventos."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None
        for line in text.splitlines():
            if line.startswith("data:"):
                try:
                    data = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
                if isinstance(data, dict) and ("result" in data or "error" in data):
                    break
    if not isinstance(data, dict):
        raise ProductionError("la respuesta del MCP no se pudo leer")
    return data


def cross_check(summary: dict, greeting: dict, public_tools: list) -> list:
    """Coteja un contrato recibido en un aviso con lo que el servidor desplegado
    contesta sin credencial. Devuelve las diferencias; vacío si todo coincide.

    No prueba el catálogo completo: sólo las instrucciones, el protocolo y las
    herramientas que el servidor anuncia sin sesión."""
    problems = []
    if greeting["instrucciones_sha256"] != summary["instrucciones_sha256"]:
        problems.append("las instrucciones que sirve el despliegue no son las del contrato recibido")
    if greeting["protocolo"] != summary["protocolo"]:
        problems.append("la versión del protocolo no es la del contrato recibido")
    known = contract.by_name(summary)
    for tool in public_tools:
        name = tool.get("name")
        if name not in known:
            problems.append(f"el despliegue anuncia `{name}` y el contrato recibido no la trae")
    return problems
