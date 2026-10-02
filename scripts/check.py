#!/usr/bin/env python3
"""Comprueba que el plugin de Datalum está completo y coherente antes de publicarlo.

Sin dependencias: sólo la biblioteca estándar de Python 3.9+.

  python3 scripts/check.py                  todas las comprobaciones
  python3 scripts/check.py --tag v1.2.3     además, que la etiqueta coincida con la versión
  python3 scripts/check.py --notes 1.2.3    imprime la sección del CHANGELOG de esa versión
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / ".claude-plugin" / "plugin.json"
MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"
MCP = ROOT / ".mcp.json"
SKILL_DIR = ROOT / "skills" / "datalum"
SKILL = SKILL_DIR / "SKILL.md"
OPENAI = SKILL_DIR / "agents" / "openai.yaml"
SERVER_TOOLS = ROOT / "scripts" / "server-tools.txt"
CHANGELOG = ROOT / "CHANGELOG.md"
README = ROOT / "README.md"
INSTALAR = ROOT / "INSTALAR.md"

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
SKILL_NAME = re.compile(r"^[a-z0-9-]{1,64}$")
# Claude rechaza al subir una Skill cualquier clave fuera de esta lista.
FRONTMATTER_KEYS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
# Nombres entre comillas invertidas que la Skill usa y que no son herramientas:
# argumentos, campos de respuesta y códigos de error del servidor.
NOT_TOOLS = {
    "agent_context_conflict",
    "agent_not_selected",
    "concept_id",
    "execution_ref",
    "expires_at",
    "page_size",
    "partial_write",
    "pending_version",
    "proposals_enabled",
    "rate_limited",
    "resealed_from_version",
    "retry_after",
    "selection_context",
    "sello_posterior",
    "snake_case",
    "user_choice_quote",
    "user_request_quote",
    "zona_utilizable",
}

errors: list[str] = []


def fail(message: str) -> None:
    errors.append(message)


def load_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        fail(f"{path.relative_to(ROOT)}: no se puede leer como JSON ({e})")
        return {}
    if not isinstance(data, dict):
        fail(f"{path.relative_to(ROOT)}: tiene que ser un objeto JSON")
        return {}
    return data


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Lee el subconjunto de YAML que usa la Skill: claves de primer nivel, bloques
    plegados `>-` y un solo nivel de mapa anidado (metadata)."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        fail("SKILL.md: falta el encabezado entre líneas ---")
        return {}, text
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        fail("SKILL.md: el encabezado no se cierra con ---")
        return {}, text
    fields: dict = {}
    i = 1
    while i < end:
        line = lines[i]
        m = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if not m:
            fail(f"SKILL.md: línea {i + 1} del encabezado no se entiende: {line!r}")
            i += 1
            continue
        key, value = m.group(1), m.group(2).strip()
        i += 1
        if value in (">-", ">", "|", "|-"):
            block = []
            while i < end and (lines[i].startswith("  ") or not lines[i].strip()):
                block.append(lines[i].strip())
                i += 1
            fields[key] = " ".join(b for b in block if b)
        elif value == "":
            nested = {}
            while i < end and lines[i].startswith("  "):
                n = re.match(r"^\s+([A-Za-z0-9_-]+):\s*(.*)$", lines[i])
                if n:
                    nested[n.group(1)] = n.group(2).strip().strip('"').strip("'")
                i += 1
            fields[key] = nested
        else:
            fields[key] = value.strip('"').strip("'")
    return fields, "\n".join(lines[end + 1:])


def changelog_section(version: str) -> str | None:
    text = CHANGELOG.read_text(encoding="utf-8")
    m = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)", text, re.M | re.S)
    return m.group(1).strip() if m else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag")
    parser.add_argument("--notes")
    args = parser.parse_args()

    if args.notes:
        section = changelog_section(args.notes)
        if section is None:
            print(f"CHANGELOG.md no tiene la sección [{args.notes}]", file=sys.stderr)
            return 1
        print(section)
        return 0

    manifest = load_json(MANIFEST)
    marketplace = load_json(MARKETPLACE)
    mcp = load_json(MCP)

    # Manifiesto y catálogo de Claude Code.
    name = manifest.get("name")
    version = manifest.get("version", "")
    if name != "datalum":
        fail(f"plugin.json: name es {name!r}; tiene que ser 'datalum'")
    if not SEMVER.match(str(version)):
        fail(f"plugin.json: version {version!r} no tiene la forma X.Y.Z")
    if not str(manifest.get("description", "")).strip():
        fail("plugin.json: falta description")
    logo = manifest.get("logo")
    if logo and not (ROOT / logo).is_file():
        fail(f"plugin.json: el logo {logo} no existe")
    entries = marketplace.get("plugins", [])
    if [e.get("name") for e in entries] != ["datalum"]:
        fail("marketplace.json: tiene que listar un solo plugin, 'datalum'")
    elif entries[0].get("source") != "./":
        fail("marketplace.json: el plugin tiene que apuntar a './'")

    # Servidor MCP.
    servers = mcp.get("mcpServers", {})
    url = ""
    if list(servers) != ["datalum"]:
        fail(".mcp.json: tiene que declarar un solo servidor, 'datalum'")
    else:
        server = servers["datalum"]
        url = server.get("url", "")
        if server.get("type") != "http" or not url.startswith("https://"):
            fail(".mcp.json: el servidor tiene que ser type http con una dirección https://")

    # Skill.
    text = SKILL.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(text)
    unknown = set(fm) - FRONTMATTER_KEYS
    if unknown:
        fail(f"SKILL.md: claves que Claude rechaza al subir la Skill: {sorted(unknown)}")
    skill_name = fm.get("name", "")
    if not SKILL_NAME.match(skill_name) or "claude" in skill_name or "anthropic" in skill_name:
        fail(f"SKILL.md: name {skill_name!r} no es válido")
    if skill_name != SKILL_DIR.name or skill_name != name:
        fail("SKILL.md: name tiene que coincidir con la carpeta y con el plugin")
    description = fm.get("description", "")
    if not description or len(description) > 1024:
        fail(f"SKILL.md: description tiene {len(description)} caracteres; el límite es 1024")
    if "<" in description or ">" in description:
        fail("SKILL.md: description no puede llevar < ni >")
    if len(fm.get("compatibility", "")) > 500:
        fail("SKILL.md: compatibility pasa de 500 caracteres")
    metadata = fm.get("metadata", {})
    if not isinstance(metadata, dict) or metadata.get("version") != version:
        fail(f"SKILL.md: metadata.version tiene que ser {version!r}, igual que plugin.json")
    if url and url not in body:
        fail("SKILL.md: no nombra la dirección del servidor que declara .mcp.json")

    # Cada herramienta que anuncia el servidor aparece en la Skill, y la Skill no
    # nombra herramientas que el servidor ya no anuncia.
    tools: set[str] = set()
    with_confirm: set[str] = set()
    for line in SERVER_TOOLS.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if not parts or line.startswith("#"):
            continue
        tools.add(parts[0])
        if parts[1:] == ["confirm"]:
            with_confirm.add(parts[0])
    missing = sorted(t for t in tools if f"`{t}`" not in body)
    # Con guion bajo se distingue un nombre de herramienta de una palabra suelta.
    named = set(re.findall(r"`([a-z]+(?:_[a-z]+)+)`", body))
    if missing:
        fail(f"SKILL.md: no explica estas herramientas del servidor: {missing}")
    stray = sorted(named - tools - NOT_TOOLS)
    if stray:
        fail(
            "SKILL.md: nombra algo que el servidor no anuncia (si es un argumento, "
            f"agrégalo a NOT_TOOLS en scripts/check.py): {stray}"
        )

    # Los ejemplos de herramientas con vista previa tienen que tener `confirm` de verdad.
    m = re.search(r"\*\*With a `confirm` argument\*\*(.*?)\*\*Without a `confirm` argument\*\*", body, re.S)
    if not m:
        fail("SKILL.md: falta la explicación de herramientas con y sin `confirm`")
    else:
        examples = set(re.findall(r"`([a-z]+(?:_[a-z]+)*)`", m.group(1))) & tools
        wrong = sorted(examples - with_confirm)
        if wrong:
            fail(f"SKILL.md: pone como ejemplo de vista previa herramientas sin `confirm`: {wrong}")

    if f"This is version {version} of the Datalum skill." not in body:
        fail(f"SKILL.md: falta la línea «This is version {version} of the Datalum skill.»")

    # Ficha de ChatGPT.
    openai = OPENAI.read_text(encoding="utf-8")
    if f'url: "{url}"' not in openai:
        fail("agents/openai.yaml: la dirección del servidor no coincide con .mcp.json")
    for icon in re.findall(r'icon_\w+:\s*"\./([^"]+)"', openai):
        if not (SKILL_DIR / icon).is_file():
            fail(f"agents/openai.yaml: el ícono {icon} no existe")

    # Documentación.
    for doc in (README, INSTALAR):
        if url and url not in doc.read_text(encoding="utf-8"):
            fail(f"{doc.name}: no nombra la dirección del servidor")
    headings = re.findall(r"^## \[(\d+\.\d+\.\d+)\]", CHANGELOG.read_text(encoding="utf-8"), re.M)
    if not headings or headings[0] != version:
        fail(f"CHANGELOG.md: la primera versión tiene que ser [{version}]")

    if args.tag and args.tag != f"v{version}":
        fail(f"la etiqueta {args.tag} no coincide con la versión v{version}")

    if errors:
        print("El plugin no está listo:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print(f"Plugin datalum {version} listo: {len(tools)} herramientas cubiertas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
