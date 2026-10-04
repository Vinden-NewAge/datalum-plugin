"""Empaquetado de la Skill: un zip reproducible y la ficha de lo que se publica."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

from . import versioning

FIXED_TIME = (2026, 1, 1, 0, 0, 0)
SKIP = {".DS_Store"}


def build(root: Path) -> dict:
    """Empaqueta la Skill de `root` y devuelve {nombre: ruta} de lo que se publica."""
    root = Path(root)
    skill_dir = root / "skills" / "datalum"
    out = root / "dist" / "datalum-skill.zip"
    files = sorted(p for p in skill_dir.rglob("*") if p.is_file() and p.name not in SKIP)
    if skill_dir / "SKILL.md" not in files:
        raise FileNotFoundError("Falta skills/datalum/SKILL.md")
    out.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            arcname = f"datalum/{path.relative_to(skill_dir).as_posix()}"
            info = zipfile.ZipInfo(arcname, date_time=FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, path.read_bytes())
    record = {
        "version": versioning.read_version(root),
        "contenido": versioning.shipped_digest(root),
        "paquete": hashlib.sha256(out.read_bytes()).hexdigest(),
    }
    record_path = root / "dist" / "publicacion.json"
    record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"datalum-skill.zip": out, "publicacion.json": record_path}


def verify(zip_path: Path, version: str) -> list:
    """Comprueba que un zip descargado es la Skill de esa versión. Devuelve los
    problemas encontrados; vacío si corresponde."""
    problems = []
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        if "datalum/SKILL.md" not in names:
            return ["el zip no trae datalum/SKILL.md"]
        if any(not n.startswith("datalum/") for n in names):
            problems.append("el zip trae archivos fuera de la carpeta datalum/")
        skill = zf.read("datalum/SKILL.md").decode("utf-8")
    if versioning.VERSION_LINE.format(version=version) not in skill:
        problems.append(f"la Skill del zip no es la versión {version}")
    return problems
