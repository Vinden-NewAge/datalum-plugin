"""Lo que un despliegue de Datalum dice de sí mismo desde fuera.

Cuatro lecturas, todas contra el servidor desplegado y ninguna contra el repositorio:

  salud           GET <origen>/health, público. Trae el commit y la versión que sirve
                  la imagen en ese momento. Un rollback devuelve el commit anterior.
  sin credencial  initialize del MCP sin credencial. Desde Datalum v2.296.1 contesta
                  401 con `WWW-Authenticate` y `resource_metadata`, que es lo que hace
                  a un cliente iniciar sesión. Hasta la v2.296.0 contestaba el saludo.
  saludo          initialize del MCP con la credencial de lectura, o el saludo público
                  de un servidor anterior. Trae la versión del protocolo y el texto de
                  las instrucciones del servidor.
  catálogo        tools/list del MCP con la credencial de lectura: el catálogo completo.

La dirección sale de la configuración del plugin, nunca del aviso de un despliegue. La
credencial sólo viaja en la cabecera `Authorization` y no sale en ningún mensaje. Si el
servidor la rechaza (401 o 403), no se vuelve a mandar y el cotejo sigue sin ella.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Callable, Optional
from urllib.parse import urlsplit

from . import contract

# (método, dirección, cabeceras, cuerpo) -> (estado, texto, cabeceras en minúsculas)
Fetch = Callable[[str, str, dict, Optional[bytes]], tuple]
TIMEOUT = 20
CLIENT = {"name": "datalum-plugin-compat", "version": "1"}


class ProductionError(RuntimeError):
    """El servidor no contestó lo esperado."""


class CredentialRejected(ProductionError):
    """El servidor rechazó la credencial de lectura."""


def http_fetch(method: str, url: str, headers: dict, body: Optional[bytes]) -> tuple:
    """Devuelve el estado, el cuerpo y las cabeceras de la respuesta, con los nombres
    de las cabeceras en minúsculas."""
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.status, response.read().decode("utf-8", "replace"), _headers(response.headers)
    except urllib.error.HTTPError as e:
        with e:
            return e.code, e.read().decode("utf-8", "replace"), _headers(e.headers)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ProductionError(f"sin respuesta de {urlsplit(url).netloc}: {e}") from e


def _headers(message) -> dict:
    return {k.lower(): v for k, v in (message.items() if message is not None else [])}


def challenge_scheme(challenge: Optional[str]) -> Optional[str]:
    """El esquema de un `WWW-Authenticate` (`Bearer`, `Basic`…), o None."""
    return challenge.strip().partition(" ")[0] or None if challenge else None


def resource_metadata(challenge: Optional[str]) -> Optional[str]:
    """La dirección `resource_metadata` de un `WWW-Authenticate: Bearer …`, o None."""
    if (challenge_scheme(challenge) or "").lower() != "bearer":
        return None
    match = _RESOURCE_METADATA.search(challenge.strip().partition(" ")[2])
    return match.group(1) if match else None


_RESOURCE_METADATA = re.compile(r'(?:^|[\s,])resource_metadata\s*=\s*"([^"]*)"', re.IGNORECASE)


class Production:
    def __init__(self, mcp_url: str, *, fetch: Fetch = http_fetch, token: Optional[str] = None) -> None:
        parts = urlsplit(mcp_url)
        if parts.scheme != "https" or not parts.netloc:
            raise ProductionError(f"la dirección del servidor tiene que ser https: {mcp_url!r}")
        self.mcp_url = mcp_url
        self.health_url = f"https://{parts.netloc}/health"
        self._fetch = fetch
        self._token = token
        self._rejected = False

    @property
    def has_token(self) -> bool:
        """Hay una credencial de lectura que el servidor no ha rechazado."""
        return bool(self._token) and not self._rejected

    @property
    def credential_rejected(self) -> bool:
        return self._rejected

    def health(self) -> dict:
        status, text, _ = self._fetch("GET", self.health_url, {"accept": "application/json"}, None)
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

    def _post(self, method: str, params: Optional[dict], *, auth: bool) -> tuple:
        headers = {
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
        }
        if auth:
            if not self.has_token:
                raise ProductionError("no hay credencial de lectura que el servidor acepte")
            headers["authorization"] = f"Bearer {self._token}"
        payload = {"jsonrpc": "2.0", "id": 1, "method": method}
        if params is not None:
            payload["params"] = params
        return self._fetch("POST", self.mcp_url, headers, json.dumps(payload).encode("utf-8"))

    def _rpc(self, method: str, params: Optional[dict], *, auth: bool) -> dict:
        status, text, _ = self._post(method, params, auth=auth)
        if status != 200:
            if auth and status in (401, 403):
                self._rejected = True
                raise CredentialRejected(f"{method} con la credencial de lectura contestó {status}")
            who = "con la credencial de lectura" if auth else "sin credencial"
            raise ProductionError(f"{method} {who} contestó {status}")
        return _result(method, text)

    def anonymous(self) -> dict:
        """Lo que contesta el servidor a un saludo sin credencial.

        `conducta` es `pide_credencial` (401, desde la v2.296.1) o `saludo_publico`
        (200, hasta la v2.296.0; trae `saludo`). Con un 401 devuelve la cabecera
        `WWW-Authenticate` tal como llegó y su `resource_metadata`; si algo
        falta o no vale, lo dice `cross_check`. Cualquier otra respuesta, también un
        403, es un error."""
        status, text, headers = self._post("initialize", INITIALIZE, auth=False)
        if status == 401:
            challenge = headers.get("www-authenticate")
            return {
                "conducta": "pide_credencial",
                "www_authenticate": challenge,
                "resource_metadata": resource_metadata(challenge),
            }
        if status == 200:
            return {"conducta": "saludo_publico", "saludo": _greeting(_result("initialize", text))}
        raise ProductionError(f"initialize sin credencial contestó {status}")

    def greeting(self) -> dict:
        """El saludo con la credencial de lectura."""
        return _greeting(self._rpc("initialize", INITIALIZE, auth=True))

    def tools(self) -> list:
        """El catálogo completo, con la credencial de lectura."""
        result = self._rpc("tools/list", None, auth=True)
        tools = result.get("tools")
        if not isinstance(tools, list):
            raise ProductionError("tools/list no trae una lista")
        return tools

    def full_contract(self) -> dict:
        """El resumen del contrato leído del servidor con la credencial de lectura."""
        greeting = self.greeting()
        return contract.summarize(
            self.tools(),
            protocol=greeting["protocolo"],
            instructions=greeting["instrucciones"],
        )

    def observe(self) -> dict:
        """Lo que el cotejo necesita del servidor: cómo responde sin credencial y el
        saludo, con la credencial si la hay o el público de un servidor anterior. Sin
        credencial y con la conducta nueva no hay saludo (`saludo` es None).

        Si el servidor rechaza la credencial, el cotejo sigue con lo que contesta sin
        ella, como un servidor sin credencial configurada, y `credencial` lo dice."""
        seen = self.anonymous()
        seen["mcp"] = self.mcp_url
        seen.setdefault("saludo", None)
        if self.has_token:
            try:
                seen["saludo"] = self.greeting()
            except CredentialRejected:
                pass
        if self._rejected:
            seen["credencial"] = "rechazada"
        return seen


INITIALIZE = {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": CLIENT}


def _result(method: str, text: str) -> dict:
    message = _parse_rpc(text)
    if "result" not in message:
        raise ProductionError(f"{method} devolvió un error del servidor")
    return message["result"]


def _greeting(result: dict) -> dict:
    instructions = result.get("instructions")
    if not isinstance(instructions, str) or not instructions:
        raise ProductionError("el saludo no trae instrucciones")
    return {
        "protocolo": result.get("protocolVersion"),
        "version": (result.get("serverInfo") or {}).get("version"),
        "instrucciones": instructions,
        "instrucciones_sha256": contract.sha256_text(instructions),
    }


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


def cross_check(summary: dict, seen: dict) -> list:
    """Coteja un contrato con lo que contesta el servidor desplegado (`observe`).
    Devuelve las diferencias; vacío si todo coincide.

    Sin credencial el servidor tiene que pedirla: 401 con `WWW-Authenticate: Bearer` y
    un `resource_metadata` en https sobre el mismo servidor. Mientras dura el
    despliegue de la v2.296.1 también vale la conducta anterior, el saludo público.
    Si hay saludo, sus instrucciones y su protocolo tienen que ser los del contrato. El
    catálogo completo lo coteja quien tenga la credencial, comparando huellas."""
    problems = []
    if seen["conducta"] == "pide_credencial":
        if not seen.get("www_authenticate"):
            problems.append("sin credencial el servidor contesta 401 sin WWW-Authenticate: un cliente no sabe dónde iniciar sesión")
        elif (challenge_scheme(seen["www_authenticate"]) or "").lower() != "bearer":
            problems.append("sin credencial el servidor contesta 401 con un WWW-Authenticate que no es Bearer: un cliente MCP no sabe iniciar sesión")
        elif not seen.get("resource_metadata"):
            problems.append("sin credencial el servidor contesta 401 con un WWW-Authenticate sin resource_metadata: un cliente no sabe dónde iniciar sesión")
        else:
            where, server = urlsplit(seen["resource_metadata"]), urlsplit(seen["mcp"])
            if where.scheme != "https" or where.netloc != server.netloc:
                problems.append("el resource_metadata del 401 no apunta a este mismo servidor en https")
    greeting = seen.get("saludo")
    if greeting is not None:
        if greeting["instrucciones_sha256"] != summary["instrucciones_sha256"]:
            problems.append("las instrucciones que sirve el despliegue no son las del contrato recibido")
        if greeting["protocolo"] != summary["protocolo"]:
            problems.append("la versión del protocolo no es la del contrato recibido")
    return problems


def describe(seen: dict) -> str:
    """Una línea para la salida del cotejo: qué hizo el servidor sin credencial y, si
    la rechazó, que la credencial de lectura no vale."""
    if seen["conducta"] == "saludo_publico":
        line = "sin credencial el servidor contesta el saludo, como hasta Datalum v2.296.0"
    else:
        line = "sin credencial el servidor contesta 401 con dónde iniciar sesión, como desde Datalum v2.296.1"
    if seen.get("credencial") == "rechazada":
        line += "; la credencial de lectura no vale: el servidor la rechazó y el cotejo siguió sin ella"
    return line
