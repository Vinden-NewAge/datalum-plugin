"""El registro de compatibilidad: una línea por despliegue procesado.

compat/registro.jsonl relaciona cada despliegue de Datalum con el contrato que sirve,
la versión del plugin que quedó vigente y el resultado de la comprobación. Sólo se
añade al final; una línea escrita no se cambia.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

# Resultados que cierran un despliegue: repetir el mismo aviso no hace nada.
FINAL = {"compatible_sin_cambios", "actualizado"}
# Resultados que esperan a una persona: se vuelven a evaluar por si ya decidió.
PENDING = {"revision_requerida", "incompatible"}
# Resultados que se pueden reintentar con el mismo aviso.
RETRIABLE = {
    "despliegue_no_confirmado",
    "contrato_no_disponible",
    "contrato_no_coincide",
    "pruebas_fallidas",
    "publicacion_fallida",
    "paquete_no_coincide",
    "retirada_fallida",
    "retirada_incierta",
}
RESULTS = FINAL | PENDING | RETRIABLE | {"candidata_lista"}


def read(path: Path) -> list:
    if not path.exists():
        return []
    entries = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError as e:
            raise ValueError(f"{path.name}: la línea {number} no es JSON") from e
    return entries


def confirmed(entries: list, environment: str) -> list:
    """Las líneas de un entorno cuyo despliegue se confirmó contra el servidor."""
    return [
        e
        for e in entries
        if e["despliegue"]["entorno"] == environment and e["resultado"] != "despliegue_no_confirmado"
    ]


def latest(entries: list, environment: str) -> Optional[dict]:
    lines = confirmed(entries, environment)
    return lines[-1] if lines else None


def classify_event(entries: list, environment: str, served_sha: str) -> str:
    """Qué es, respecto del registro, el commit que el servidor sirve ahora.

    duplicado   el último despliegue confirmado es este mismo y ya quedó cerrado
    pendiente   el último es este mismo y espera la decisión de una persona
    reintento   el último es este mismo y terminó en un resultado reintentable
    rollback    este commit ya se sirvió antes y después se sirvió otro
    nuevo       nunca se había visto
    """
    lines = confirmed(entries, environment)
    if lines and lines[-1]["despliegue"]["sha"] == served_sha:
        result = lines[-1]["resultado"]
        if result in FINAL | {"candidata_lista"}:
            return "duplicado"
        return "pendiente" if result in PENDING else "reintento"
    if any(e["despliegue"]["sha"] == served_sha for e in lines):
        return "rollback"
    return "nuevo"


def append(path: Path, entry: dict) -> dict:
    if entry["resultado"] not in RESULTS:
        raise ValueError(f"resultado desconocido: {entry['resultado']!r}")
    entries = read(path)
    entry = dict(entry, secuencia=(entries[-1]["secuencia"] + 1 if entries else 1))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    return entry


def same_news(entries: list, environment: str, sha, result: str, reasons: list) -> bool:
    """¿La última línea de ese entorno ya dice esto mismo de este commit? Evita que la
    lectura de cada hora repita un aviso que no cambió."""
    lines = [e for e in entries if e["despliegue"]["entorno"] == environment]
    if not lines:
        return False
    last = lines[-1]
    return (
        last["despliegue"].get("sha") == sha
        and last["resultado"] == result
        and last.get("motivos", []) == list(reasons)
    )


def candidate_for(entries: list, fingerprint: str) -> Optional[dict]:
    """La última candidata que un entorno previo probó con ese mismo contrato."""
    for entry in reversed(entries):
        if (
            entry["resultado"] == "candidata_lista"
            and entry["contrato"].get("huella") == fingerprint
            and entry["plugin"].get("candidata")
        ):
            return {"secuencia": entry["secuencia"], "contenido": entry["plugin"]["contenido"]}
    return None
