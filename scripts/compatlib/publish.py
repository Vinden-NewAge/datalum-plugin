"""Publicar una versión del plugin sin duplicarla ni cambiar una ya publicada.

El orden es: etiqueta, borrador con los archivos, descarga y cotejo, publicación,
segunda descarga y cotejo. `main` se mueve después, así que si algo falla antes las
instalaciones siguen recibiendo la última versión válida.

Cada paso mira primero qué existe. Por eso el mismo despliegue se puede reintentar tras
un fallo: lo hecho se reconoce y no se repite. Una etiqueta o una versión publicada con
otro contenido detiene todo; nunca se sobrescriben.
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


def file_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def publish(forge, *, tag: str, commit: str, digest: str, title: str, notes: str, assets: dict) -> dict:
    """`assets` es {nombre: ruta} de los archivos ya probados. `digest` es la huella
    del contenido publicable del commit probado."""
    expected = {name: file_sha256(path) for name, path in sorted(assets.items())}

    existing = forge.remote_tag(tag)
    if existing is None:
        forge.push_tag(tag, commit)
    if forge.tag_digest(tag) != digest:
        raise Immutable(f"la etiqueta {tag} ya existe con otro contenido")

    state = forge.release_state(tag)
    if state == "published":
        if forge.release_assets(tag) != expected:
            raise Immutable(f"la versión {tag} ya está publicada con otros archivos")
        return {"estado": "ya_publicada", "activos": expected}
    if state == "draft" and forge.release_assets(tag) != expected:
        forge.delete_draft(tag)
        state = None
    if state is None:
        forge.create_draft(tag, title, notes, assets)

    if forge.release_assets(tag) != expected:
        raise PackageMismatch(f"los archivos del borrador de {tag} no son los que se probaron")
    forge.publish(tag)
    if forge.release_assets(tag) != expected:
        # Vuelve a borrador: deja de verse y deja de ser «la última». No queda a la
        # vista una versión con archivos que no se probaron.
        forge.unpublish(tag)
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
                return {}
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
