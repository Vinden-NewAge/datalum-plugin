"""Apoyo de las pruebas de la automatización: un plugin de mentira en un repositorio
git con remoto local, un servidor desplegado de mentira y una forja cuyas versiones
viven en memoria.

Los datos son inventados. git es el real: las etiquetas, los commits y el empuje a
`main` se ejercitan de verdad contra el remoto local.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from compatlib import contract, packaging, production, publish  # noqa: E402

INSTRUCTIONS = "Instrucciones sintéticas del servidor de pruebas."
SHA_A = "a" * 40
SHA_B = "b" * 40
SHA_C = "c" * 40


def tool(name: str, props: list, required: list = (), note: str = "") -> dict:
    return {
        "name": name,
        "description": f"Herramienta sintética {name}. {note}".strip(),
        "inputSchema": {
            "type": "object",
            "properties": {p: {"type": "string"} for p in props},
            "required": list(required),
        },
    }


def base_tools() -> list:
    return [
        tool("list_agents", []),
        tool("use_agent", ["agent", "user_choice_quote", "selection_context"], ["agent", "user_choice_quote"]),
        tool("remember", ["kind", "title", "body_md", "slug", "selection_context"], ["kind", "title", "body_md"]),
        tool("run_metric", ["metric", "selection_context"], ["metric"]),
        tool("brain_import", ["files"], ["files"]),
    ]


def summary_of(tools: list, instructions: str = INSTRUCTIONS) -> dict:
    return contract.summarize(tools, protocol="2025-06-18", instructions=instructions)


def requirements_for(summary: dict) -> dict:
    tools = contract.by_name(summary)
    need = {
        "list_agents": {"usa": [], "obligatorios": []},
        "use_agent": {
            "usa": ["agent", "user_choice_quote", "selection_context"],
            "obligatorios": ["agent", "user_choice_quote"],
        },
        "remember": {"usa": ["kind", "title", "body_md", "slug"], "obligatorios": ["kind", "title", "body_md"]},
    }
    return {
        "esquema": 1,
        "protocolos": ["2025-06-18"],
        "herramientas": need,
        "citas_humanas": {"use_agent": "user_choice_quote"},
        "instrucciones_revisadas": [summary["instrucciones_sha256"]],
        "definiciones_revisadas": {name: [tools[name]["h"]] for name in need},
    }


class FakeProduction:
    """Un despliegue de mentira: contesta salud, saludo y catálogo."""

    def __init__(self, sha: str, tools: list, *, release: str = "v9.0.0", ok: bool = True,
                 instructions: str = INSTRUCTIONS, token: bool = False) -> None:
        self.sha, self.tools_list, self.release, self.ok = sha, tools, release, ok
        self.instructions = instructions
        self.has_token = token
        self.down = False

    def health(self) -> dict:
        if self.down:
            raise production.ProductionError("sin respuesta")
        return {"ok": self.ok, "sha": self.sha, "release": self.release}

    def greeting(self) -> dict:
        return {
            "protocolo": "2025-06-18",
            "version": "9.0.0",
            "instrucciones": self.instructions,
            "instrucciones_sha256": contract.sha256_text(self.instructions),
        }

    def tools(self, *, auth: bool) -> list:
        return self.tools_list if auth else self.tools_list[:1]

    def full_contract(self) -> dict:
        return summary_of(self.tools_list, self.instructions)


class LocalForge(publish.GhForge):
    """git de verdad contra el remoto local; las versiones de GitHub, en memoria.
    `fail_on` nombra el paso que revienta una vez; `corrupt` altera lo que se descarga."""

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.releases: dict = {}
        self.fail_on: set = set()
        self.corrupt: set = set()
        self.calls: list = []

    def _maybe_fail(self, step: str) -> None:
        self.calls.append(step)
        if step in self.fail_on:
            self.fail_on.discard(step)
            raise subprocess.CalledProcessError(1, ["gh", "release", step], stderr="fallo inyectado")

    def release_state(self, tag):
        release = self.releases.get(tag)
        return None if release is None else ("draft" if release["draft"] else "published")

    def release_assets(self, tag):
        release = self.releases.get(tag)
        if release is None:
            return {}
        stage = "draft" if release["draft"] else "published"
        assets = dict(release["assets"])
        if stage in self.corrupt:
            assets = {name: "0" * 64 for name in assets}
        return assets

    def create_draft(self, tag, title, notes, assets):
        self._maybe_fail("create")
        self.releases[tag] = {
            "draft": True, "latest": False, "title": title, "notes": notes,
            "assets": {name: publish.file_sha256(path) for name, path in assets.items()},
        }

    def delete_draft(self, tag):
        self.calls.append("delete_draft")
        del self.releases[tag]

    def publish(self, tag):
        self._maybe_fail("publish")
        self.releases[tag].update(draft=False, latest=True)

    def unpublish(self, tag):
        self.calls.append("unpublish")
        self.releases[tag].update(draft=True, latest=False)

    def advance_main(self, commit, *, branch, title, body):
        pushed = self._run("git", "push", self.remote, f"{commit}:refs/heads/{self.main}", check=False)
        return "ok" if pushed.returncode == 0 else f"pendiente: rama {branch}"


def git(root: Path, *args: str) -> str:
    return subprocess.run(("git",) + args, cwd=root, capture_output=True, text=True, check=True).stdout.strip()


class Repo:
    """Un plugin mínimo en un repositorio con remoto local."""

    def __init__(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.remote = base / "origin.git"
        self.root = base / "plugin"
        git(base, "init", "--bare", "-b", "main", str(self.remote))
        self.root.mkdir()
        git(self.root, "init", "-b", "main")
        git(self.root, "config", "user.name", "prueba")
        git(self.root, "config", "user.email", "prueba@example.invalid")
        git(self.root, "remote", "add", "origin", str(self.remote))

        self.contract = summary_of(base_tools())
        self.requirements = requirements_for(self.contract)
        self.write(".gitignore", "dist/\n")
        self.write(".mcp.json", json.dumps({"mcpServers": {"datalum": {"type": "http", "url": "https://mcp.example.invalid/mcp"}}}))
        self.write(".claude-plugin/plugin.json", json.dumps({"name": "datalum", "version": "1.0.0"}, indent=2))
        self.write(
            "skills/datalum/SKILL.md",
            '---\nname: datalum\nmetadata:\n  version: "1.0.0"\n---\n\nThis is version 1.0.0 of the Datalum skill.\n',
        )
        self.write("CHANGELOG.md", "# Cambios\n\n## [1.0.0] - 2026-01-01\n\n- Primera.\n")
        self.write("hooks/hooks.json", "{}\n")
        self.write_json("compat/requisitos.json", self.requirements)
        self.write_json("compat/contrato-produccion.json", self.contract)
        self.write_json("compat/entornos.json", {"qa": {"mcp": "https://qa.example.invalid/mcp"}})
        self.write_json("client/contract-facts.json", contract.derive_facts(self.contract, self.requirements))
        git(self.root, "add", "-A")
        git(self.root, "commit", "-m", "base")
        git(self.root, "push", "origin", "main")
        self.forge = LocalForge(self.root)

    def close(self) -> None:
        self._tmp.cleanup()

    def write(self, relative: str, text: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def write_json(self, relative: str, data: dict) -> None:
        self.write(relative, json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n")

    def version(self) -> str:
        return json.loads((self.root / ".claude-plugin/plugin.json").read_text())["version"]

    def remote_main(self) -> str:
        return git(self.root, "ls-remote", "origin", "refs/heads/main").split()[0]

    def remote_file(self, relative: str) -> str:
        git(self.root, "fetch", "origin", "main")
        return git(self.root, "show", f"FETCH_HEAD:{relative}")

    def remote_tags(self) -> list:
        out = git(self.root, "ls-remote", "--tags", "origin")
        return sorted(line.split("refs/tags/")[1] for line in out.splitlines() if line)

    def package(self) -> dict:
        return packaging.build(self.root)
