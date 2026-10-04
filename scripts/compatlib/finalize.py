"""Cerrar una comprobación: publicar si toca, anotar el resultado y mover `main`.

Llega aquí un árbol de trabajo con los cambios que dejó `evaluate`, ya probados. Lo
primero es comprobar que ese árbol es el que se probó; después se publica, se escribe
la línea del registro y se lleva `main` al resultado. Un fallo al publicar deja `main`
sin la versión nueva y con la línea que cuenta el fallo.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

from . import ledger, packaging, pipeline, publish, versioning


class Git:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def run(self, *args: str) -> str:
        return subprocess.run(
            ("git",) + args, cwd=self.root, capture_output=True, text=True, check=True
        ).stdout.strip()

    def head(self) -> str:
        return self.run("rev-parse", "HEAD")

    def commit_all(self, message: str) -> Optional[str]:
        self.run("add", "-A")
        if not self.run("status", "--porcelain"):
            return None
        self.run("commit", "-m", message)
        return self.head()

    def discard(self, base: str) -> None:
        self.run("reset", "--hard", base)
        self.run("clean", "-fd", "--", "compat", "client")


def finalize(
    root: Path,
    evaluation: dict,
    *,
    forge,
    assets: dict,
    tested_digest: str,
    now: str,
    tests_passed: bool = True,
) -> dict:
    """Devuelve la línea escrita en el registro, con `main` (cómo quedó la rama) y,
    si se publicó, `publicacion`."""
    root = Path(root)
    git = Git(root)
    where = pipeline.paths(root)
    base = git.head()
    action = evaluation["accion"]
    version = evaluation["version_actual"]
    package = publish.file_sha256(assets["datalum-skill.zip"]) if "datalum-skill.zip" in assets else None

    def plugin(current_version: str) -> dict:
        info = {"version": current_version, "contenido": versioning.shipped_digest(root)}
        if package:
            info["paquete"] = package
        return info

    def close(result: Optional[str], detail: Optional[str], plugin_info: dict, **extra) -> dict:
        entry = ledger.append(
            where["ledger"],
            pipeline.ledger_entry(evaluation, now=now, plugin=plugin_info, result=result, detail=detail),
        )
        deployment = evaluation["despliegue"]
        # Un despliegue que no se pudo confirmar puede no tener commit conocido.
        short = (deployment.get("sha") or "desconocido")[:12]
        served = deployment.get("release") or short
        commit = git.commit_all(f"Compatibilidad: {served} de {deployment['entorno']}, {entry['resultado']}")
        entry["main"] = forge.advance_main(
            commit or git.head(),
            branch=f"auto/compat-{short}-{entry['secuencia']}",
            title=f"Compatibilidad con el despliegue {served}",
            body=f"Resultado: `{entry['resultado']}`. {entry['detalle'].capitalize()}.",
        )
        entry.update(extra)
        return entry

    def discard_keeping_evidence() -> None:
        # Se vuelve al árbol de partida, pero los contratos e instrucciones cotejados
        # se conservan: sirven para reintentar y para comprobar un rollback.
        kept = {p: p.read_bytes() for p in _evidence(where)}
        git.discard(base)
        for path, content in kept.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)

    def fail(result: str, detail: str) -> dict:
        # Nada de la versión nueva llega a `main`: sólo queda la línea del fallo.
        discard_keeping_evidence()
        return close(result, detail, plugin(version))

    if evaluation["despliegue"]["entorno"] != "prod":
        # Candidata de un entorno previo: se anota con qué contenido pasó las pruebas
        # y se descarta. A `main` sólo llegan el contrato guardado y la línea.
        info = plugin(evaluation.get("version_nueva") or version)
        if evaluation["resultado"] == "candidata_lista":
            info["candidata"] = True
        discard_keeping_evidence()
        if not tests_passed:
            return close("pruebas_fallidas", "las pruebas del plugin no pasan con el contrato del entorno previo", info)
        return close(None, None, info)

    if action == "publicar":
        if not tests_passed:
            return fail("pruebas_fallidas", "las pruebas del plugin no pasan con el contrato nuevo")
        digest = versioning.shipped_digest(root)
        if digest != tested_digest:
            return fail("paquete_no_coincide", "el contenido a publicar no es el que se probó")
        new_version = evaluation["version_nueva"]
        tag = f"v{new_version}"
        wrong = packaging.verify(assets["datalum-skill.zip"], new_version)
        if wrong:
            return fail("paquete_no_coincide", wrong[0])
        commit = git.commit_all(f"Versión {new_version}: sigue al contrato del despliegue de Datalum")
        try:
            outcome = publish.publish(
                forge,
                tag=tag,
                commit=commit,
                digest=digest,
                title=f"Datalum {new_version}",
                notes=_notes(root, new_version),
                assets=assets,
            )
        except publish.PackageMismatch as e:
            return fail("paquete_no_coincide", str(e))
        except (publish.Immutable, subprocess.CalledProcessError, OSError) as e:
            return fail("publicacion_fallida", _reason(e))
        info = plugin(new_version)
        if evaluation.get("candidata"):
            # ¿Lo que se publica es lo que el entorno previo ya había probado?
            evaluation["candidata"]["promovida"] = evaluation["candidata"]["contenido"] == info["contenido"]
        return close(None, None, info, publicacion=outcome)

    if not tests_passed and action == "registrar":
        return fail("pruebas_fallidas", "las pruebas del plugin no pasan contra este contrato")
    return close(None, None, plugin(version))


def _evidence(where: dict) -> list:
    """Los contratos e instrucciones cotejados se conservan aunque falle lo demás."""
    files = []
    for folder in (where["contracts"], where["instructions"]):
        if folder.is_dir():
            files.extend(p for p in folder.iterdir() if p.is_file())
    return files


def _notes(root: Path, version: str) -> str:
    return versioning.changelog_section(root, version) or f"Versión {version}."


def _reason(error: Exception) -> str:
    if isinstance(error, subprocess.CalledProcessError):
        tail = (error.stderr or "").strip().splitlines()
        return f"falló `{' '.join(map(str, error.cmd[:3]))}`" + (f": {tail[-1]}" if tail else "")
    return str(error)
