"""Versión del plugin: dónde vive, cómo sube y qué cuenta como contenido publicado."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

# Lo que llega a una instalación. Un cambio aquí es una versión nueva; un cambio fuera
# (registro de compatibilidad, pruebas, guías) no lo es.
SHIPPED = (".claude-plugin", ".mcp.json", "client", "hooks", "skills")
SKIP_NAMES = {".DS_Store"}

VERSION_LINE = "This is version {version} of the Datalum skill."


def read_version(root: Path) -> str:
    manifest = json.loads((root / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    return manifest["version"]


def next_patch(version: str) -> str:
    major, minor, patch = (int(part) for part in version.split("."))
    return f"{major}.{minor}.{patch + 1}"


def shipped_files(root: Path) -> list:
    files = []
    for name in SHIPPED:
        path = root / name
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files.extend(p for p in path.rglob("*") if p.is_file() and p.name not in SKIP_NAMES)
    return sorted(files)


def shipped_digest(root: Path) -> str:
    """Huella de todo lo que llega a una instalación. Dos árboles con la misma huella
    publican lo mismo."""
    digest = hashlib.sha256()
    for path in shipped_files(root):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        content = path.read_bytes()
        digest.update(len(relative).to_bytes(4, "big") + relative)
        digest.update(len(content).to_bytes(8, "big") + content)
    return digest.hexdigest()


def set_version(root: Path, old: str, new: str) -> None:
    """Sube la versión en sus tres lugares. Falla si alguno no tenía la anterior."""
    manifest_path = root / ".claude-plugin" / "plugin.json"
    text = manifest_path.read_text(encoding="utf-8")
    replaced = re.sub(rf'("version"\s*:\s*"){re.escape(old)}(")', rf"\g<1>{new}\g<2>", text, count=1)
    if replaced == text:
        raise ValueError("plugin.json no tenía la versión anterior")
    manifest_path.write_text(replaced, encoding="utf-8")

    skill_path = root / "skills" / "datalum" / "SKILL.md"
    skill = skill_path.read_text(encoding="utf-8")
    meta_old, meta_new = f'version: "{old}"', f'version: "{new}"'
    line_old, line_new = VERSION_LINE.format(version=old), VERSION_LINE.format(version=new)
    if skill.count(meta_old) != 1 or skill.count(line_old) != 1:
        raise ValueError("SKILL.md no tenía la versión anterior en sus dos lugares")
    skill_path.write_text(skill.replace(meta_old, meta_new).replace(line_old, line_new), encoding="utf-8")


def add_changelog(root: Path, version: str, date: str, body: str) -> None:
    path = root / "CHANGELOG.md"
    text = path.read_text(encoding="utf-8")
    marker = re.search(r"^## \[", text, re.M)
    if not marker:
        raise ValueError("CHANGELOG.md no tiene ninguna versión")
    section = f"## [{version}] - {date}\n\n{body.strip()}\n\n"
    path.write_text(text[: marker.start()] + section + text[marker.start():], encoding="utf-8")


def changelog_section(root: Path, version: str):
    """El texto de la sección de esa versión en CHANGELOG.md, o None si no está."""
    text = (Path(root) / "CHANGELOG.md").read_text(encoding="utf-8")
    m = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)", text, re.M | re.S)
    return m.group(1).strip() if m else None
