#!/usr/bin/env python3
"""Comprueba el plugin contra lo que sirve un despliegue de Datalum y publica si toca.

Sin dependencias: sólo la biblioteca estándar de Python 3.9+. Lo usa el flujo
.github/workflows/compat.yml; cada paso se puede correr también a mano.

  aviso      arma el aviso de un despliegue a partir de sus datos y lo valida
  evaluar    confirma el despliegue, consigue su contrato y lo compara; deja en el
             árbol los archivos derivados y, si hace falta, la versión nueva
  huella     imprime la huella de lo que llega a una instalación
  cerrar     publica si toca, anota el resultado en el registro y mueve main
  propuesta  imprime el aviso para una persona cuando algo no se pudo resolver solo
  avisar     abre ese aviso en GitHub, o lo comenta si ya está abierto
  publicar   publica una etiqueta puesta a mano con las mismas comprobaciones
  resumir    arma un resumen de contrato a partir de un tools/list completo

Cómo se mantiene y cómo se recupera de un fallo: MANTENER.md.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from compatlib import contract, finalize, packaging, pipeline, production, publish, versioning  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


class DryForge:
    """Forja que no toca nada: dice qué haría. Para ensayar el cierre sin publicar."""

    def __init__(self) -> None:
        self.steps: list = []
        self._assets: dict = {}
        self._digest = None

    def remote_tag(self, tag):
        return None

    def push_tag(self, tag, commit):
        self.steps.append(f"etiquetaría {tag} en {commit[:12]}")
        self._digest = versioning.shipped_digest(ROOT)

    def tag_digest(self, tag):
        return self._digest

    def release_state(self, tag):
        return "draft" if self._assets else None

    def release_assets(self, tag):
        return dict(self._assets)

    def create_draft(self, tag, title, notes, assets):
        self.steps.append(f"crearía el borrador de {tag} con {sorted(assets)}")
        self._assets = {name: publish.file_sha256(path) for name, path in assets.items()}

    def delete_draft(self, tag):
        self._assets = {}

    def publish(self, tag):
        self.steps.append(f"publicaría {tag}")

    def unpublish(self, tag):
        self.steps.append(f"devolvería {tag} a borrador")
        return True

    def advance_main(self, commit, *, branch, title, body):
        self.steps.append(f"llevaría main a {commit[:12]}")
        return "simulado"


def now_utc() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def cmd_aviso(args: argparse.Namespace) -> int:
    event = {
        "entorno": args.entorno,
        "origen": args.origen,
        "sha": args.sha.strip().lower() or None,
        "release": args.release.strip() or None,
        "corrida": args.corrida.strip() or None,
        "actor": args.actor.strip() or None,
    }
    text = args.contrato.strip()
    if text:
        try:
            event["contrato"] = json.loads(text)
        except json.JSONDecodeError as e:
            print(f"El contrato del aviso no es JSON: {e}", file=sys.stderr)
            return 1
    allowed = [a.strip() for a in args.actores.split(",") if a.strip()]
    if event["origen"] == "aviso" and allowed and event["actor"] not in allowed:
        print(f"Aviso rechazado: «{event['actor']}» no está entre quienes pueden avisar de un despliegue.", file=sys.stderr)
        return 1
    try:
        pipeline.validate_event(event)
    except (pipeline.EventError, contract.ContractError) as e:
        print(f"Aviso rechazado: {e}", file=sys.stderr)
        return 1
    Path(args.salida).write_text(json.dumps(event, ensure_ascii=False), encoding="utf-8")
    return 0


def cmd_evaluar(args: argparse.Namespace) -> int:
    event = json.loads(Path(args.evento).read_text(encoding="utf-8"))
    try:
        url = pipeline.mcp_url(ROOT, event.get("entorno"))
        prod = production.Production(url, token=os.environ.get("DATALUM_COMPAT_TOKEN") or None)
        evaluation = pipeline.evaluate(ROOT, event, prod=prod, today=now_utc()[:10])
    except (pipeline.EventError, contract.ContractError, production.ProductionError) as e:
        print(f"No se pudo evaluar: {e}", file=sys.stderr)
        return 1
    Path(args.salida).write_text(json.dumps(evaluation, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{evaluation['accion']}: {evaluation['resultado'] or 'sin cambios'} · {evaluation['detalle']}")
    return 0


def cmd_huella(_: argparse.Namespace) -> int:
    print(versioning.shipped_digest(ROOT))
    return 0


def cmd_cerrar(args: argparse.Namespace) -> int:
    evaluation = json.loads(Path(args.evaluacion).read_text(encoding="utf-8"))
    if evaluation["accion"] == "nada":
        print("Nada que cerrar: el despliegue ya estaba procesado.")
        return 0
    assets = {}
    for name in ("datalum-skill.zip", "publicacion.json"):
        path = ROOT / "dist" / name
        if path.exists():
            assets[name] = path
    forge = DryForge() if args.simular else publish.GhForge(ROOT)
    entry = finalize.finalize(
        ROOT,
        evaluation,
        forge=forge,
        assets=assets,
        tested_digest=args.probado,
        now=now_utc(),
        tests_passed=args.pruebas == "ok",
    )
    if args.simular:
        entry["simulacion"] = forge.steps
    print(json.dumps(entry, ensure_ascii=False, indent=2))
    failed = entry["resultado"] in ("publicacion_fallida", "paquete_no_coincide", "retirada_fallida", "retirada_incierta", "pruebas_fallidas")
    if str(entry.get("main", "")).startswith("pendiente"):
        # El resultado no llegó a main: la corrida queda en rojo para que alguien lo vea.
        print(f"main no avanzó: {entry['main']}", file=sys.stderr)
        failed = True
    return 1 if failed else 0


def cmd_propuesta(args: argparse.Namespace) -> int:
    evaluation = json.loads(Path(args.evaluacion).read_text(encoding="utf-8"))
    if args.resultado:
        evaluation["resultado"] = args.resultado
        evaluation["detalle"] = args.detalle or evaluation["detalle"]
    print(json.dumps(pipeline.proposal(evaluation), ensure_ascii=False))
    return 0


def cmd_publicar(args: argparse.Namespace) -> int:
    """El camino manual: una persona fundió el PR y puso la etiqueta. Publica con las
    mismas comprobaciones que el camino automático."""
    version = versioning.read_version(ROOT)
    if args.tag != f"v{version}":
        print(f"La etiqueta {args.tag} no coincide con la versión v{version}", file=sys.stderr)
        return 1
    assets = packaging.build(ROOT)
    wrong = packaging.verify(assets["datalum-skill.zip"], version)
    if wrong:
        print(wrong[0], file=sys.stderr)
        return 1
    forge = DryForge() if args.simular else publish.GhForge(ROOT)
    head = finalize.Git(ROOT).head()
    try:
        outcome = publish.publish(
            forge, tag=args.tag, commit=head, digest=versioning.shipped_digest(ROOT),
            title=f"Datalum {version}", notes=finalize._notes(ROOT, version), assets=assets,
            recover=args.recuperar,
        )
    except (publish.Immutable, publish.PackageMismatch, publish.WithdrawFailed, publish.WithdrawUncertain, publish.DownloadFailed, publish.StateUnknown) as e:
        print(f"No se publicó: {e}", file=sys.stderr)
        return 1
    print(json.dumps(outcome, ensure_ascii=False, indent=2))
    return 0


def cmd_avisar(args: argparse.Namespace) -> int:
    """Abre el aviso para una persona, o añade un comentario si ya está abierto."""
    import subprocess

    evaluation = json.loads(Path(args.evaluacion).read_text(encoding="utf-8"))
    if args.resultado:
        evaluation["resultado"] = args.resultado
        evaluation["detalle"] = args.detalle or evaluation["detalle"]
    text = pipeline.proposal(evaluation)
    if args.simular:
        print(json.dumps(text, ensure_ascii=False, indent=2))
        return 0
    found = subprocess.run(
        ["gh", "issue", "list", "--state", "open", "--search", f'in:title "{text["titulo"]}"', "--json", "number,title"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    same = [i for i in json.loads(found.stdout) if i["title"] == text["titulo"]]
    if same:
        subprocess.run(["gh", "issue", "comment", str(same[0]["number"]), "--body", text["cuerpo"]], cwd=ROOT, check=True)
    else:
        subprocess.run(["gh", "issue", "create", "--title", text["titulo"], "--body", text["cuerpo"]], cwd=ROOT, check=True)
    return 0


def cmd_resumir(args: argparse.Namespace) -> int:
    data = json.loads(Path(args.tools).read_text(encoding="utf-8"))
    greeting = data["initialize"]
    summary = contract.summarize(
        data["tools"], protocol=greeting["protocolVersion"], instructions=greeting["instructions"]
    )
    Path(args.salida).write_text(contract.canonical(summary), encoding="utf-8")
    print(f"{len(summary['herramientas'])} herramientas · huella {summary['huella']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("aviso")
    p.add_argument("--entorno", required=True)
    p.add_argument("--origen", required=True)
    for name in ("sha", "release", "corrida", "actor", "contrato"):
        p.add_argument(f"--{name}", default="")
    p.add_argument("--actores", default="", help="quienes pueden avisar, separados por comas; vacío = cualquiera con permiso de disparar el flujo")
    p.add_argument("--salida", required=True)
    p.set_defaults(run=cmd_aviso)

    p = sub.add_parser("evaluar")
    p.add_argument("--evento", required=True)
    p.add_argument("--salida", required=True)
    p.set_defaults(run=cmd_evaluar)

    p = sub.add_parser("huella")
    p.set_defaults(run=cmd_huella)

    p = sub.add_parser("cerrar")
    p.add_argument("--evaluacion", required=True)
    p.add_argument("--probado", required=True)
    p.add_argument("--pruebas", choices=("ok", "fallaron"), default="ok")
    p.add_argument("--simular", action="store_true")
    p.set_defaults(run=cmd_cerrar)

    p = sub.add_parser("propuesta")
    p.add_argument("--evaluacion", required=True)
    p.add_argument("--resultado", default="")
    p.add_argument("--detalle", default="")
    p.set_defaults(run=cmd_propuesta)

    p = sub.add_parser("publicar")
    p.add_argument("--tag", required=True)
    p.add_argument("--recuperar", action="store_true", help="retirar y volver a publicar una versión de esta etiqueta que quedó con otros archivos")
    p.add_argument("--simular", action="store_true")
    p.set_defaults(run=cmd_publicar)

    p = sub.add_parser("avisar")
    p.add_argument("--evaluacion", required=True)
    p.add_argument("--resultado", default="")
    p.add_argument("--detalle", default="")
    p.add_argument("--simular", action="store_true")
    p.set_defaults(run=cmd_avisar)

    p = sub.add_parser("resumir")
    p.add_argument("--tools", required=True)
    p.add_argument("--salida", required=True)
    p.set_defaults(run=cmd_resumir)

    args = parser.parse_args()
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
