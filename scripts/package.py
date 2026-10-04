#!/usr/bin/env python3
"""Empaqueta la Skill para subirla a mano en Claude (web y escritorio) y en ChatGPT.

Deja dist/datalum-skill.zip con una sola carpeta, datalum/, que es lo que piden los dos
productos. El archivo sale igual byte a byte cada vez que se empaqueta el mismo contenido.
Al lado deja dist/publicacion.json, que dice de qué versión y de qué contenido salió.

  python3 scripts/package.py
"""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from compatlib import packaging  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    try:
        assets = packaging.build(ROOT)
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        return 1
    record = json.loads(assets["publicacion.json"].read_text(encoding="utf-8"))
    with zipfile.ZipFile(assets["datalum-skill.zip"]) as zf:
        count = len(zf.namelist())
    print(f"dist/datalum-skill.zip · {count} archivos · sha256 {record['paquete']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
