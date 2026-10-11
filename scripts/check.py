#!/usr/bin/env python3
"""Comprueba que el plugin de Datalum está completo y coherente antes de publicarlo.

Sin dependencias: sólo la biblioteca estándar de Python 3.9+.

  python3 scripts/check.py                  todas las comprobaciones
  python3 scripts/check.py --tag v1.2.3     además, que la etiqueta coincida con la versión
  python3 scripts/check.py --notes 1.2.3    imprime la sección del CHANGELOG de esa versión

Es una comprobación de estructura: mira que las piezas encajen entre sí y con el último
contrato de producción comprobado. No dice si un asistente se comporta bien con la
Skill; eso lo miden las pruebas de tests/ y las evaluaciones de evals/.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from compatlib import contract, ledger, versioning  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / ".claude-plugin" / "plugin.json"
MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"
MCP = ROOT / ".mcp.json"
HOOKS = ROOT / "hooks" / "hooks.json"
SKILL_DIR = ROOT / "skills" / "datalum"
SKILL = SKILL_DIR / "SKILL.md"
OPENAI = SKILL_DIR / "agents" / "openai.yaml"
FACTS = ROOT / "client" / "contract-facts.json"
REQUIREMENTS = ROOT / "compat" / "requisitos.json"
CURRENT = ROOT / "compat" / "contrato-produccion.json"
LEDGER = ROOT / "compat" / "registro.jsonl"
CHANGELOG = ROOT / "CHANGELOG.md"
README = ROOT / "README.md"
INSTALAR = ROOT / "INSTALAR.md"

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
SKILL_NAME = re.compile(r"^[a-z0-9-]{1,64}$")
# Claude rechaza al subir una Skill cualquier clave fuera de esta lista.
FRONTMATTER_KEYS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
# Nombres entre comillas invertidas que la Skill usa y que no son herramientas ni
# argumentos: campos de respuesta y códigos de error del servidor.
RESPONSE_NAMES = {
    "agent_context_conflict",
    "agent_not_selected",
    "aviso_del_modelo",
    "next_cursor",
    "next_offset",
    "operating_as",
    "partial_write",
    "rate_limited",
    "retry_after",
    "sello_posterior",
}
# La Skill arranca la sesión y carga el cerebro; el oficio lo trae el agente. Si nombra
# más herramientas que éstas, volvió a ser un catálogo.
MAX_TOOLS_IN_SKILL = 10

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


def check_manifest() -> tuple[str, str]:
    manifest = load_json(MANIFEST)
    marketplace = load_json(MARKETPLACE)
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
    # Claude (web y escritorio) se niega a instalar un plugin con bin/ en la raíz.
    if (ROOT / "bin").exists():
        fail("hay una carpeta bin/ en la raíz: impide instalar el plugin en Claude")
    return str(name), str(version)


def check_server() -> str:
    servers = load_json(MCP).get("mcpServers", {})
    if list(servers) != ["datalum"]:
        fail(".mcp.json: tiene que declarar un solo servidor, 'datalum'")
        return ""
    server = servers["datalum"]
    url = server.get("url", "")
    if server.get("type") != "http" or not url.startswith("https://"):
        fail(".mcp.json: el servidor tiene que ser type http con una dirección https://")
    return url


def check_skill(name: str, version: str, url: str, summary: dict, requirements: dict) -> None:
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
    if versioning.VERSION_LINE.format(version=version) not in body:
        fail(f"SKILL.md: falta la línea «{versioning.VERSION_LINE.format(version=version)}»")
    if not summary:
        return

    # Lo que la Skill nombra tiene que existir en el contrato, y las herramientas que
    # nombra tienen que estar declaradas en los requisitos: así cada despliegue las
    # vuelve a comprobar. No se exige nombrar el catálogo: el asistente lo descubre en
    # el conector y el oficio lo trae el cerebro del agente.
    tools = contract.by_name(summary)
    arguments = {arg for entry in summary["herramientas"] for arg in entry["p"]}
    # Con guion bajo se distingue un nombre del contrato de una palabra suelta.
    named = set(re.findall(r"`([a-z]+(?:_[a-z]+)+)`", body))
    named_tools = sorted(named & set(tools))
    stray = sorted(named - set(tools) - arguments - RESPONSE_NAMES)
    if stray:
        fail(
            "SKILL.md: nombra algo que el contrato de producción no trae (si es un campo "
            f"de respuesta, agrégalo a RESPONSE_NAMES en scripts/check.py): {stray}"
        )
    undeclared = sorted(set(named_tools) - set(requirements.get("herramientas", {})))
    if undeclared:
        fail(f"SKILL.md: nombra herramientas que compat/requisitos.json no declara: {undeclared}")
    if len(named_tools) > MAX_TOOLS_IN_SKILL:
        fail(
            f"SKILL.md: nombra {len(named_tools)} herramientas; con más de {MAX_TOOLS_IN_SKILL} "
            "vuelve a ser un catálogo que se queda atrás del servidor"
        )


def check_contract() -> tuple[dict, dict]:
    requirements = load_json(REQUIREMENTS)
    summary = load_json(CURRENT)
    if not requirements or not summary:
        return {}, requirements
    try:
        contract.validate(summary)
    except contract.ContractError as e:
        fail(f"compat/contrato-produccion.json: {e}")
        return {}, requirements
    facts = load_json(FACTS)
    comparison = contract.compare(summary, requirements, previous=summary, current_facts=facts)
    for reason in comparison["incompatible"]:
        fail(f"compat/requisitos.json contra el contrato de producción: {reason}")
    for reason in comparison["revision"]:
        fail(f"compat/requisitos.json contra el contrato de producción: {reason}")
    if comparison["derivados_cambian"]:
        fail("client/contract-facts.json no es el que se deriva del contrato de producción")
    stored = ROOT / "compat" / "instrucciones" / f"{summary['instrucciones_sha256'][:12]}.txt"
    if not stored.is_file():
        fail("compat/instrucciones/ no guarda el texto de las instrucciones del contrato vigente")
    elif contract.sha256_text(stored.read_text(encoding="utf-8")) != summary["instrucciones_sha256"]:
        fail(f"{stored.relative_to(ROOT)}: el texto no corresponde a su huella")
    try:
        ledger.read(LEDGER)
    except ValueError as e:
        fail(str(e))
    return summary, requirements


def check_hooks() -> None:
    hooks = load_json(HOOKS).get("hooks", {})
    if not hooks:
        fail("hooks/hooks.json: no declara ningún hook")
    for event, groups in hooks.items():
        for group in groups:
            for hook in group.get("hooks", []):
                if hook.get("type") != "command" or hook.get("command") != "node":
                    fail(f"hooks.json: {event} tiene que correr `node` con `args`, sin shell")
                for arg in hook.get("args", []):
                    target = ROOT / arg.replace("${CLAUDE_PLUGIN_ROOT}/", "")
                    if "${CLAUDE_PLUGIN_ROOT}" in arg and not target.is_file():
                        fail(f"hooks.json: {event} apunta a {arg}, que no existe")
            matcher = group.get("matcher")
            if event != "SessionStart" and (not matcher or "mcp__" not in matcher):
                fail(f"hooks.json: {event} tiene que limitarse a herramientas MCP con un matcher")


def check_docs(version: str, url: str) -> None:
    openai = OPENAI.read_text(encoding="utf-8")
    if f'url: "{url}"' not in openai:
        fail("agents/openai.yaml: la dirección del servidor no coincide con .mcp.json")
    for icon in re.findall(r'icon_\w+:\s*"\./([^"]+)"', openai):
        if not (SKILL_DIR / icon).is_file():
            fail(f"agents/openai.yaml: el ícono {icon} no existe")
    for doc in (README, INSTALAR):
        if url and url not in doc.read_text(encoding="utf-8"):
            fail(f"{doc.name}: no nombra la dirección del servidor")
    headings = re.findall(r"^## \[(\d+\.\d+\.\d+)\]", CHANGELOG.read_text(encoding="utf-8"), re.M)
    if not headings or headings[0] != version:
        fail(f"CHANGELOG.md: la primera versión tiene que ser [{version}]")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag")
    parser.add_argument("--notes")
    args = parser.parse_args()

    if args.notes:
        section = versioning.changelog_section(ROOT, args.notes)
        if section is None:
            print(f"CHANGELOG.md no tiene la sección [{args.notes}]", file=sys.stderr)
            return 1
        print(section)
        return 0

    name, version = check_manifest()
    url = check_server()
    summary, requirements = check_contract()
    check_skill(name, version, url, summary, requirements)
    check_hooks()
    check_docs(version, url)

    if args.tag and args.tag != f"v{version}":
        fail(f"la etiqueta {args.tag} no coincide con la versión v{version}")

    if errors:
        print("El plugin no está listo:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    count = len(summary.get("herramientas", []))
    print(f"Plugin datalum {version}: estructura coherente con el contrato de producción ({count} herramientas).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
