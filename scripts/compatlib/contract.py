"""El contrato MCP de un despliegue y su comparación con lo que el plugin necesita.

Un «resumen de contrato» describe lo que anuncia el servidor de Datalum en un commit:
la versión del protocolo, la huella de sus instrucciones y, por herramienta, su nombre,
la huella de su definición completa, sus argumentos y cuáles son obligatorios. No lleva
descripciones ni esquemas completos, así que cabe en el aviso de un despliegue.

`compat/requisitos.json` dice qué usa el plugin de ese contrato. La comparación sale en
una de cuatro clases:

  sin_cambios    el contrato es el mismo que el último comprobado
  compatible     cambió algo que el plugin no usa, o que se resuelve regenerando
                 archivos derivados
  revision       cambió el texto de algo que el plugin sí usa (instrucciones del
                 servidor o la definición de una herramienta requerida); una persona
                 tiene que leerlo antes de publicar nada
  incompatible   falta una herramienta o un argumento que el plugin usa, o apareció un
                 argumento obligatorio que el plugin no manda
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Optional

SCHEMA = 1
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
TOOL_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
ARG_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
MAX_TOOLS = 400
MAX_ARGS = 80


class ContractError(ValueError):
    """El resumen de contrato no tiene la forma esperada."""


def canonical(value: Any) -> str:
    """JSON con claves ordenadas y sin espacios: el mismo texto que produce la sonda
    del servidor con JSON.stringify sobre objetos de claves ordenadas."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def tool_hash(tool: dict) -> str:
    """Huella de la definición completa de una herramienta, tal como la sirve
    tools/list (nombre, descripción, esquema de entrada y lo demás que traiga)."""
    return sha256_text(canonical(tool))


def summarize(tools: list, *, protocol: str, instructions: str) -> dict:
    """Arma el resumen a partir de un tools/list completo y del saludo."""
    entries = []
    for tool in tools:
        schema = tool.get("inputSchema") or {}
        entries.append(
            {
                "n": tool["name"],
                "h": tool_hash(tool),
                "p": sorted((schema.get("properties") or {}).keys()),
                "r": sorted(schema.get("required") or []),
            }
        )
    entries.sort(key=lambda e: e["n"])
    summary = {
        "esquema": SCHEMA,
        "protocolo": protocol,
        "instrucciones_sha256": sha256_text(instructions),
        "herramientas": entries,
    }
    summary["huella"] = fingerprint(summary)
    return summary


def fingerprint(summary: dict) -> str:
    """Huella del contrato. No incluye qué commit lo sirve: dos despliegues con el
    mismo contrato dan la misma huella."""
    body = {
        "protocolo": summary["protocolo"],
        "instrucciones_sha256": summary["instrucciones_sha256"],
        "herramientas": summary["herramientas"],
    }
    return sha256_text(canonical(body))


def validate(summary: Any) -> dict:
    """Comprueba la forma del resumen y que su huella corresponda al contenido.
    Lo que llega en un aviso es dato externo: se valida entero antes de usarlo."""
    if not isinstance(summary, dict):
        raise ContractError("el contrato tiene que ser un objeto")
    if summary.get("esquema") != SCHEMA:
        raise ContractError(f"esquema de contrato desconocido: {summary.get('esquema')!r}")
    protocol = summary.get("protocolo")
    if not isinstance(protocol, str) or not re.match(r"^\d{4}-\d{2}-\d{2}$", protocol):
        raise ContractError("protocolo no tiene la forma AAAA-MM-DD")
    if not isinstance(summary.get("instrucciones_sha256"), str) or not SHA256.match(
        summary["instrucciones_sha256"]
    ):
        raise ContractError("instrucciones_sha256 no es una huella sha256")
    tools = summary.get("herramientas")
    if not isinstance(tools, list) or not tools:
        raise ContractError("herramientas tiene que ser una lista con contenido")
    if len(tools) > MAX_TOOLS:
        raise ContractError(f"demasiadas herramientas: {len(tools)}")
    names = []
    for entry in tools:
        if not isinstance(entry, dict) or set(entry) != {"n", "h", "p", "r"}:
            raise ContractError("cada herramienta lleva exactamente n, h, p y r")
        if not isinstance(entry["n"], str) or not TOOL_NAME.match(entry["n"]):
            raise ContractError(f"nombre de herramienta inválido: {entry.get('n')!r}")
        if not isinstance(entry["h"], str) or not SHA256.match(entry["h"]):
            raise ContractError(f"{entry['n']}: h no es una huella sha256")
        for key in ("p", "r"):
            args = entry[key]
            if (
                not isinstance(args, list)
                or len(args) > MAX_ARGS
                or any(not isinstance(a, str) or not ARG_NAME.match(a) for a in args)
                or args != sorted(set(args))
            ):
                raise ContractError(f"{entry['n']}: {key} tiene que ser una lista ordenada de nombres")
        if not set(entry["r"]) <= set(entry["p"]):
            raise ContractError(f"{entry['n']}: hay obligatorios que no están entre los argumentos")
        names.append(entry["n"])
    if names != sorted(set(names)):
        raise ContractError("las herramientas tienen que venir ordenadas por nombre y sin repetir")
    if summary.get("huella") != fingerprint(summary):
        raise ContractError("la huella no corresponde al contenido del contrato")
    return summary


def by_name(summary: dict) -> dict:
    return {entry["n"]: entry for entry in summary["herramientas"]}


def derive_facts(summary: dict, requirements: dict) -> dict:
    """Lo que los controles del cliente necesitan saber del contrato y se puede sacar
    de él sin interpretar nada. Es el contenido de client/contract-facts.json."""
    tools = by_name(summary)
    quotes = {
        name: arg
        for name, arg in sorted(requirements.get("citas_humanas", {}).items())
        if name in tools and arg in tools[name]["p"]
    }
    # El argumento que nombra el destino de cada herramienta: `name` si es obligatorio;
    # si no, el primer obligatorio que no sea el conector, la confirmación, el contexto
    # ni una cita. Los controles del cliente lo usan para reconocer la misma operación
    # sin conocer los objetos del catálogo.
    skip = {"connector", "confirm", "selection_context"} | set(requirements.get("citas_humanas", {}).values())
    targets = {}
    for entry in summary["herramientas"]:
        required = [arg for arg in entry["r"] if arg not in skip]
        if required:
            targets[entry["n"]] = "name" if "name" in required else required[0]
    facts = {
        "_": "Derivado del contrato de producción por scripts/compat.py. No se edita a mano.",
        "citas_humanas": quotes,
        "destinos": dict(sorted(targets.items())),
        "sin_selection_context": sorted(
            entry["n"] for entry in summary["herramientas"] if "selection_context" not in entry["p"]
        ),
    }
    # Las familias que el plugin tiene en pausa: toda herramienta del contrato con una
    # palabra de la familia en su nombre, en singular o plural, también las que lleguen
    # en un contrato nuevo.
    paused = requirements.get("en_pausa")
    if paused:
        families = set(paused["familias"])

        def in_family(name: str) -> bool:
            return any(word in families or (word.endswith("s") and word[:-1] in families) for word in name.split("_"))

        facts["en_pausa"] = {"herramientas": sorted(name for name in tools if in_family(name)), "aviso": paused["aviso"]}
    return facts


def compare(
    summary: dict,
    requirements: dict,
    *,
    previous: Optional[dict] = None,
    current_facts: Optional[dict] = None,
) -> dict:
    """Compara un contrato con los requisitos del plugin y con el último contrato
    comprobado. Devuelve la clase, los motivos y qué archivos derivados cambian."""
    tools = by_name(summary)
    incompatible: list = []
    review: list = []
    notes: list = []

    for name, need in sorted(requirements.get("herramientas", {}).items()):
        entry = tools.get(name)
        if entry is None:
            incompatible.append(f"falta la herramienta `{name}`, que el plugin usa")
            continue
        missing = sorted(set(need.get("usa", [])) - set(entry["p"]))
        if missing:
            incompatible.append(f"`{name}` ya no acepta {missing}, que el plugin manda")
        known = set(need.get("obligatorios", []))
        surprise = sorted(set(entry["r"]) - known)
        if surprise:
            incompatible.append(f"`{name}` exige ahora {surprise}, que el plugin no manda")

    reviewed = set(requirements.get("instrucciones_revisadas", []))
    if summary["instrucciones_sha256"] not in reviewed:
        review.append(
            "las instrucciones que el servidor manda al conectar cambiaron y nadie las ha "
            "leído contra la Skill"
        )
    reviewed_tools = requirements.get("definiciones_revisadas", {})
    for name in sorted(requirements.get("herramientas", {})):
        entry = tools.get(name)
        if entry is None:
            continue
        if entry["h"] not in set(reviewed_tools.get(name, [])):
            review.append(f"la definición de `{name}` cambió y nadie la ha leído contra la Skill")

    protocols = requirements.get("protocolos", [])
    if protocols and summary["protocolo"] not in protocols:
        review.append(f"el servidor habla la versión {summary['protocolo']} del protocolo, sin comprobar")

    if previous is not None:
        before, after = by_name(previous), tools
        added = sorted(set(after) - set(before))
        removed = sorted(set(before) - set(after))
        changed = sorted(n for n in set(after) & set(before) if after[n]["h"] != before[n]["h"])
        if added:
            notes.append(f"herramientas nuevas: {', '.join(added)}")
        if removed:
            notes.append(f"herramientas que salieron: {', '.join(removed)}")
        if changed:
            notes.append(f"herramientas con definición distinta: {', '.join(changed)}")

    facts = derive_facts(summary, requirements)
    facts_change = current_facts is not None and _facts_body(current_facts) != _facts_body(facts)

    same = previous is not None and previous.get("huella") == summary["huella"]
    if incompatible:
        kind = "incompatible"
    elif review:
        kind = "revision"
    elif same and not facts_change:
        kind = "sin_cambios"
    else:
        kind = "compatible"
    return {
        "clase": kind,
        "incompatible": incompatible,
        "revision": review,
        "notas": notes,
        "derivados_cambian": bool(facts_change),
        "hechos": facts,
    }


def _facts_body(facts: dict) -> dict:
    return {k: v for k, v in facts.items() if k != "_"}
