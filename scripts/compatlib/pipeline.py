"""Qué hacer con el plugin cuando cambia lo que sirve un despliegue de Datalum.

`evaluate` no publica nada. Confirma el despliegue contra el servidor, consigue su
contrato, lo compara con lo que el plugin necesita y deja en el árbol de trabajo los
archivos derivados y, si hace falta, la versión nueva. Lo que devuelve dice qué sigue:

  nada        el despliegue ya estaba procesado
  registrar   sólo hay que anotar el resultado en el registro
  publicar    hay una versión nueva que probar y publicar
  avisar      algo impide comprobar o publicar; se anota y se abre un aviso
  proponer    el cambio pide una decisión de una persona; se anota y se abre la propuesta
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable, Optional

from . import contract, ledger, production, versioning

ORIGINS = {"aviso", "reconciliacion", "manual"}
ENVIRONMENTS = {"prod", "qa"}


class EventError(ValueError):
    """El aviso recibido no tiene la forma esperada."""


def paths(root: Path) -> dict:
    compat = root / "compat"
    return {
        "requirements": compat / "requisitos.json",
        "current": compat / "contrato-produccion.json",
        "contracts": compat / "contratos",
        "instructions": compat / "instrucciones",
        "ledger": compat / "registro.jsonl",
        "environments": compat / "entornos.json",
        "facts": root / "client" / "contract-facts.json",
        "mcp": root / ".mcp.json",
    }


def load_json(path: Path) -> Optional[dict]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def mcp_url(root: Path, environment: str) -> str:
    """La dirección de cada entorno vive en el repositorio. Producción es la que
    instala el plugin; las demás, las de compat/entornos.json."""
    if environment == "prod":
        return load_json(paths(root)["mcp"])["mcpServers"]["datalum"]["url"]
    environments = load_json(paths(root)["environments"]) or {}
    url = (environments.get(environment) or {}).get("mcp")
    if not url:
        raise EventError(f"compat/entornos.json no tiene la dirección de «{environment}»")
    return url


def validate_event(event: dict) -> dict:
    if not isinstance(event, dict):
        raise EventError("el aviso tiene que ser un objeto")
    environment = event.get("entorno")
    if environment not in ENVIRONMENTS:
        raise EventError(f"entorno desconocido: {environment!r}")
    origin = event.get("origen")
    if origin not in ORIGINS:
        raise EventError(f"origen desconocido: {origin!r}")
    sha = event.get("sha") or None
    if sha is not None and not (isinstance(sha, str) and contract.SHA40.match(sha)):
        raise EventError("sha tiene que ser un commit completo de 40 caracteres")
    if origin == "aviso" and sha is None:
        raise EventError("un aviso de despliegue tiene que decir qué commit desplegó")
    summary = event.get("contrato") or None
    if summary is not None:
        contract.validate(summary)
    clean = {"entorno": environment, "origen": origin, "sha": sha, "contrato": summary}
    for key in ("release", "corrida", "actor"):
        value = event.get(key)
        clean[key] = value if isinstance(value, str) and value and len(value) <= 300 else None
    return clean


def confirm_deployment(prod, sha: Optional[str], *, attempts: int, wait: Callable[[float], None]) -> dict:
    """Espera a que el servidor conteste sano y sirviendo el commit del aviso."""
    last: dict = {}
    for attempt in range(attempts):
        try:
            last = prod.health()
        except production.ProductionError as e:
            last = {"ok": False, "sha": None, "release": None, "error": str(e)}
        if last.get("ok") and (sha is None or last["sha"] == sha):
            return dict(last, confirmado=True)
        if attempt + 1 < attempts:
            wait(10)
    return dict(last, confirmado=False)


def evaluate(
    root: Path,
    event: dict,
    *,
    prod,
    today: str,
    attempts: int = 6,
    wait: Callable[[float], None] = time.sleep,
) -> dict:
    root = Path(root)
    event = validate_event(event)
    where = paths(root)
    entries = ledger.read(where["ledger"])
    version = versioning.read_version(root)
    deployment = {k: event[k] for k in ("entorno", "origen", "sha", "release", "corrida", "actor")}
    evaluation: dict = {
        "despliegue": deployment,
        "contrato": {"huella": None, "verificacion": None},
        "version_actual": version,
        "version_nueva": None,
        "motivos": [],
        "notas": [],
    }

    def stop(result: str, action: str, detail: str) -> dict:
        evaluation.update(resultado=result, accion=action, detalle=detail)
        waiting = action in ("avisar", "proponer")
        if waiting and ledger.same_news(entries, event["entorno"], deployment["sha"], result, evaluation["motivos"]):
            # Ya está anotado y avisado, y nada cambió desde entonces.
            evaluation.update(accion="nada", detalle="sin novedad desde la última comprobación")
        return evaluation

    health = confirm_deployment(prod, event["sha"], attempts=attempts, wait=wait)
    if not health["confirmado"]:
        served = health.get("sha")
        if not health.get("ok"):
            # El motivo no lleva el texto del error: cambia de una hora a otra y haría
            # parecer novedad lo que es la misma caída.
            reason = "el servidor no pasa su comprobación de salud"
            detail = reason + (f": {health['error']}" if health.get("error") else "")
        else:
            reason = detail = f"el servidor sirve {served[:12]} y el aviso decía {event['sha'][:12]}"
        deployment["sha"] = event["sha"] or served
        evaluation["motivos"] = [reason]
        return stop("despliegue_no_confirmado", "avisar", detail)
    deployment["sha"] = health["sha"]
    deployment["release"] = health["release"] or event["release"]

    kind = ledger.classify_event(entries, event["entorno"], health["sha"])
    deployment["tipo"] = kind
    if kind == "duplicado":
        return stop(None, "nada", "este despliegue ya estaba procesado")

    stored = where["contracts"] / f"{health['sha'][:12]}.json"
    summary = event["contrato"]
    source = "aviso"
    if summary is None and stored.exists():
        summary, source = contract.validate(load_json(stored)), "registro"
    live = None
    if getattr(prod, "has_token", False):
        try:
            live = prod.full_contract()
        except production.ProductionError as e:
            evaluation["notas"].append(f"no se pudo leer el catálogo completo del servidor: {e}")
    if summary is None and live is not None:
        summary, source = live, "servidor"
    if summary is None:
        return stop(
            "contrato_no_disponible",
            "avisar",
            "el servidor sirve un commit del que no hay contrato: falta el aviso del "
            "despliegue o una credencial de lectura",
        )
    evaluation["contrato"]["huella"] = summary["huella"]
    evaluation["contrato"]["origen"] = source

    try:
        greeting = prod.greeting()
        problems = production.cross_check(summary, greeting, prod.tools(auth=False))
    except production.ProductionError as e:
        return stop("despliegue_no_confirmado", "avisar", f"no se pudo cotejar el contrato: {e}")
    if live is not None and live["huella"] != summary["huella"]:
        problems.append("el catálogo completo que sirve el despliegue no es el del contrato recibido")
    if problems:
        evaluation["motivos"] = problems
        return stop("contrato_no_coincide", "avisar", problems[0])
    evaluation["contrato"]["verificacion"] = "completa" if live is not None else "parcial"
    # El contrato y las instrucciones cotejadas se guardan siempre: sirven para
    # reintentar, para comprobar un rollback y para que una persona lea lo que cambió.
    if not stored.exists():
        write_json(stored, summary)
    text = where["instructions"] / f"{summary['instrucciones_sha256'][:12]}.txt"
    if not text.exists():
        text.parent.mkdir(parents=True, exist_ok=True)
        text.write_text(greeting["instrucciones"], encoding="utf-8")

    comparison = contract.compare(
        summary,
        load_json(where["requirements"]),
        previous=load_json(where["current"]),
        current_facts=load_json(where["facts"]),
    )
    evaluation["clase"] = comparison["clase"]
    evaluation["notas"].extend(comparison["notas"])
    evaluation["contrato_resumen"] = summary

    if comparison["clase"] == "incompatible":
        evaluation["motivos"] = comparison["incompatible"] + comparison["revision"]
        return stop("incompatible", "proponer", comparison["incompatible"][0])
    if comparison["clase"] == "revision":
        evaluation["motivos"] = comparison["revision"]
        return stop("revision_requerida", "proponer", comparison["revision"][0])

    # Un entorno previo prepara la candidata: deja en el árbol la misma versión que
    # saldría en producción, para probarla y empaquetarla. Nada de eso se publica ni
    # llega a `main`; sólo queda anotado con qué contenido pasó las pruebas.
    candidate = event["entorno"] != "prod"

    if comparison["clase"] == "sin_cambios":
        if candidate:
            return stop("candidata_lista", "registrar", "el entorno previo sirve el contrato ya comprobado")
        return stop("compatible_sin_cambios", "registrar", "el contrato es el mismo que el último comprobado")

    if not candidate:
        write_json(where["current"], summary)
    if not comparison["derivados_cambian"]:
        if candidate:
            return stop("candidata_lista", "registrar", "el contrato del entorno previo cambia en partes que el plugin no usa")
        return stop(
            "compatible_sin_cambios",
            "registrar",
            "el contrato cambió en partes que el plugin no usa",
        )

    before = load_json(where["facts"]) or {}
    write_json(where["facts"], comparison["hechos"])
    new_version = versioning.next_patch(version)
    versioning.set_version(root, version, new_version)
    served = deployment["release"] or deployment["sha"][:12]
    versioning.add_changelog(
        root, new_version, today, changelog_body(before, comparison["hechos"], served, summary["huella"])
    )
    evaluation["version_nueva"] = new_version
    if candidate:
        return stop("candidata_lista", "registrar", f"candidata {new_version} preparada con el contrato de {served}")
    promoted = ledger.candidate_for(entries, summary["huella"])
    if promoted:
        evaluation["candidata"] = promoted
    return stop("actualizado", "publicar", f"los controles del cliente siguen al contrato de {served}")


def changelog_body(before: dict, after: dict, served: str, fingerprint: str) -> str:
    old, new = set(before.get("sin_selection_context", [])), set(after["sin_selection_context"])
    changes = []
    if new - old:
        changes.append(f"dejan de llevar el contexto de la conversación: {', '.join(sorted(new - old))}")
    if old - new:
        changes.append(f"pasan a llevar el contexto de la conversación: {', '.join(sorted(old - new))}")
    detail = "; ".join(changes) if changes else "se regeneró la lista de herramientas que usan los controles"
    return (
        "Versión generada por la comprobación automática tras un despliegue de Datalum.\n\n"
        "### Cambiado\n\n"
        f"- Los controles del cliente siguen al catálogo del servidor: {detail}.\n\n"
        "### Servidor\n\n"
        f"- Comprobada contra el despliegue {served} de producción (contrato `{fingerprint[:12]}`).\n\n"
        "### Cómo recibirla\n\n"
        "- Como cualquier versión: los pasos por aplicación están en `ACTUALIZAR.md`."
    )


def ledger_entry(evaluation: dict, *, now: str, plugin: dict, result: Optional[str] = None, detail: Optional[str] = None) -> dict:
    return {
        "fecha": now,
        "despliegue": {k: v for k, v in evaluation["despliegue"].items() if v is not None},
        "contrato": {k: v for k, v in evaluation["contrato"].items() if v is not None},
        "plugin": plugin,
        "resultado": result or evaluation["resultado"],
        "detalle": detail or evaluation["detalle"],
        **({"candidata": evaluation["candidata"]} if evaluation.get("candidata") else {}),
        **({"motivos": evaluation["motivos"]} if evaluation.get("motivos") else {}),
    }


def proposal(evaluation: dict) -> dict:
    """El texto del aviso o de la propuesta que se abre para una persona."""
    deployment = evaluation["despliegue"]
    served = deployment.get("release") or (deployment.get("sha") or "desconocido")[:12]
    result = evaluation["resultado"]
    titles = {
        "incompatible": f"El plugin no es compatible con el despliegue {served}",
        "revision_requerida": f"El despliegue {served} cambió texto que el plugin sigue: hace falta leerlo",
        "contrato_no_disponible": f"No hay contrato del despliegue {served}",
        "contrato_no_coincide": f"El contrato recibido no es el que sirve el despliegue {served}",
        "despliegue_no_confirmado": f"No se pudo confirmar el despliegue {served}",
        "pruebas_fallidas": f"Las pruebas del plugin fallan contra el despliegue {served}",
        "publicacion_fallida": f"La publicación del plugin tras el despliegue {served} no terminó",
        "paquete_no_coincide": f"El paquete publicado tras el despliegue {served} no es el que se probó",
        "retirada_fallida": f"Una versión del plugin con archivos que no se probaron sigue publicada tras el despliegue {served}",
    }
    lines = [
        f"Entorno: `{deployment['entorno']}` · commit `{deployment.get('sha')}` · versión del plugin: "
        f"`{evaluation['version_actual']}`.",
        "",
        f"Resultado: `{result}`. {evaluation['detalle'].capitalize()}.",
    ]
    if evaluation.get("motivos"):
        lines += ["", "Motivos:"] + [f"- {m}" for m in evaluation["motivos"]]
    if evaluation.get("notas"):
        lines += ["", "Cambios del catálogo:"] + [f"- {n}" for n in evaluation["notas"]]
    if result == "retirada_fallida":
        lines += ["", "Hay que retirarla ya: devolverla a borrador en Releases, o volver a lanzar la comprobación, que la retira sola. Los pasos están en `MANTENER.md`."]
    else:
        lines += ["", "No se publicó ninguna versión del plugin. La última publicada sigue vigente."]
    if result == "incompatible":
        lines += [
            "",
            "Antes de publicar una adaptación hay que decidir el comportamiento nuevo y la "
            "transición: qué versión del plugin funciona con los dos contratos, cuánto tiempo "
            "conserva el servidor el contrato anterior y cómo se avisa a quienes actualizan a "
            "mano. La guía está en `MANTENER.md`, sección «Cambios incompatibles».",
        ]
    if result == "revision_requerida":
        lines += [
            "",
            "Quien revise lee el texto nuevo contra la Skill y, si no cambia nada, añade la "
            "huella a `compat/requisitos.json`. Los pasos están en `MANTENER.md`.",
        ]
    return {"titulo": titles.get(result, f"Comprobación de compatibilidad: {result}"), "cuerpo": "\n".join(lines)}
