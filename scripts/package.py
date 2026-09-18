#!/usr/bin/env python3
"""Empaqueta la Skill para subirla a mano en Claude (web y escritorio) y en ChatGPT.

Deja dist/datalum-skill.zip con una sola carpeta, datalum/, que es lo que piden los dos
productos. El archivo sale igual byte a byte cada vez que se empaqueta el mismo contenido.

  python3 scripts/package.py
"""

from __future__ import annotations

import hashlib
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = ROOT / "skills" / "datalum"
OUT = ROOT / "dist" / "datalum-skill.zip"
FIXED_TIME = (2026, 1, 1, 0, 0, 0)
SKIP = {".DS_Store"}


def main() -> int:
    files = sorted(p for p in SKILL_DIR.rglob("*") if p.is_file() and p.name not in SKIP)
    if not (SKILL_DIR / "SKILL.md") in files:
        print("Falta skills/datalum/SKILL.md", file=sys.stderr)
        return 1
    OUT.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(OUT, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            arcname = f"datalum/{path.relative_to(SKILL_DIR).as_posix()}"
            info = zipfile.ZipInfo(arcname, date_time=FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, path.read_bytes())
    digest = hashlib.sha256(OUT.read_bytes()).hexdigest()
    print(f"{OUT.relative_to(ROOT)} · {len(files)} archivos · sha256 {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
