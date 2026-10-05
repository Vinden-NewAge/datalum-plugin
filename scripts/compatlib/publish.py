"""Publicar una versión del plugin sin duplicarla ni cambiar una ya publicada.

El orden es: etiqueta, borrador con los archivos, descarga y cotejo, publicación,
segunda descarga y cotejo. `main` se mueve después, así que si algo falla antes las
instalaciones siguen recibiendo la última versión válida.

Cada paso mira primero qué existe. Por eso el mismo despliegue se puede reintentar tras
un fallo: lo hecho se reconoce y no se repite. Una etiqueta con otro contenido detiene
todo, y una versión publicada con otros archivos también, salvo que la haya dejado así
un intento anterior de este mismo proceso (`recover`): entonces se retira y se publica
lo probado. Retirar es devolverla a borrador, y se comprueba que quedó retirada.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from . import versioning


class Immutable(RuntimeError):
    """La versión ya existe con otro contenido."""


class PackageMismatch(RuntimeError):
    """Lo descargado no es lo que se probó."""


class WithdrawFailed(RuntimeError):
    """Una versión con archivos que no se probaron sigue a la vista."""


class DownloadFailed(RuntimeError):
    """No se pudieron descargar los archivos de una versión para cotejarlos."""


def withdraw(forge, tag: str) -> None:
    """Devuelve la versión a borrador y comprueba que lo está."""
    forge.unpublish(tag)
    if forge.release_state(tag) != "draft":
        raise WithdrawFailed(f"la versión {tag}, con archivos que no se probaron, sigue publicada")


def file_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def publish(
    forge, *, tag: str, commit: str, digest: str, title: str, notes: str, assets: dict, recover: bool = False
) -> dict:
    """`assets` es {nombre: ruta} de los archivos ya probados. `digest` es la huella
    del contenido publicable del commit probado. `recover` permite retirar una versión
    publicada con otros archivos que dejó un intento anterior de este mismo proceso."""
    expected = {name: file_sha256(path) for name, path in sorted(assets.items())}

    existing = forge.remote_tag(tag)
    if existing is None:
        forge.push_tag(tag, commit)
    if forge.tag_digest(tag) != digest:
        raise Immutable(f"la etiqueta {tag} ya existe con otro contenido")

    state = forge.release_state(tag)
    if state == "published":
        if forge.release_assets(tag) == expected:
            return {"estado": "ya_publicada", "activos": expected}
        if not recover:
            raise Immutable(f"la versión {tag} ya está publicada con otros archivos")
        # La etiqueta tiene el contenido probado y el empaquetado es reproducible: lo
        # publicado no es lo que sale de ese contenido. Se retira y se publica bien.
        withdraw(forge, tag)
        state = "draft"
    if state == "draft" and forge.release_assets(tag) != expected:
        forge.delete_draft(tag)
        state = None
    if state is None:
        forge.create_draft(tag, title, notes, assets)

    if forge.release_assets(tag) != expected:
        raise PackageMismatch(f"los archivos del borrador de {tag} no son los que se probaron")
    forge.publish(tag)
    if forge.release_assets(tag) != expected:
        # Vuelve a borrador: deja de verse y deja de ser «la última». Si no lo consigue,
        # lo dice, para no dejar a la vista sin aviso una versión que no se probó.
        withdraw(forge, tag)
        raise PackageMismatch(f"los archivos publicados de {tag} no son los que se probaron")
    return {"estado": "publicada", "activos": expected}


class GhForge:
    """La forja real: git contra `origin` y la CLI de GitHub."""

    def __init__(self, root: Path, *, remote: str = "origin", main: str = "main") -> None:
        self.root = Path(root)
        self.remote = remote
        self.main = main

    def _run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(args, cwd=self.root, capture_output=True, text=True, check=check)

    def remote_tag(self, tag: str) -> Optional[str]:
        out = self._run("git", "ls-remote", "--tags", self.remote, f"refs/tags/{tag}").stdout.split()
        return out[0] if out else None

    def push_tag(self, tag: str, commit: str) -> None:
        self._run("git", "tag", tag, commit)
        self._run("git", "push", self.remote, f"refs/tags/{tag}")

    def tag_digest(self, tag: str) -> str:
        self._run("git", "fetch", "--no-tags", self.remote, f"+refs/tags/{tag}:refs/compat-check/{tag}")
        with tempfile.TemporaryDirectory() as tmp:
            archive = subprocess.run(
                ["git", "archive", "--format=tar", f"refs/compat-check/{tag}"],
                cwd=self.root, capture_output=True, check=True,
            )
            subprocess.run(["tar", "-x", "-C", tmp], input=archive.stdout, check=True)
            return versioning.shipped_digest(Path(tmp))

    def release_state(self, tag: str) -> Optional[str]:
        result = self._run("gh", "release", "view", tag, "--json", "isDraft", check=False)
        if result.returncode != 0:
            return None
        return "draft" if json.loads(result.stdout)["isDraft"] else "published"

    def release_assets(self, tag: str) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run("gh", "release", "download", tag, "--dir", tmp, check=False)
            if result.returncode != 0:
                if self.release_state(tag) is None:
                    return {}
                # La versión existe y no se pudo descargar: eso no es «otros archivos».
                raise DownloadFailed(f"no se pudieron descargar los archivos de {tag}")
            return {p.name: file_sha256(p) for p in sorted(Path(tmp).iterdir()) if p.is_file()}

    def create_draft(self, tag: str, title: str, notes: str, assets: dict) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write(notes)
        self._run(
            "gh", "release", "create", tag, *[str(path) for _, path in sorted(assets.items())],
            "--draft", "--verify-tag", "--title", title, "--notes-file", f.name,
        )

    def delete_draft(self, tag: str) -> None:
        self._run("gh", "release", "delete", tag, "--yes")

    def publish(self, tag: str) -> None:
        self._run("gh", "release", "edit", tag, "--draft=false", "--latest")

    def unpublish(self, tag: str) -> None:
        self._run("gh", "release", "edit", tag, "--draft=true", check=False)

    def advance_main(self, commit: str, *, branch: str, title: str, body: str) -> str:
        """Lleva `main` al commit. Si las reglas del repositorio no dejan empujar,
        deja una rama y abre el PR para que siga el camino que las reglas pidan."""
        pushed = self._run("git", "push", self.remote, f"{commit}:refs/heads/{self.main}", check=False)
        if pushed.returncode == 0:
            return "ok"
        self._run("git", "push", self.remote, f"{commit}:refs/heads/{branch}")
        pr = self._run(
            "gh", "pr", "create", "--base", self.main, "--head", branch,
            "--title", title, "--body", body, check=False,
        )
        if pr.returncode == 0:
            return f"pendiente: {pr.stdout.strip()}"
        return f"pendiente: rama {branch} sin PR ({pr.stderr.strip().splitlines()[-1] if pr.stderr.strip() else 'sin detalle'})"
