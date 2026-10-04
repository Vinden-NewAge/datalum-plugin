"""Pruebas de código de la actualización automática.

Cada prueba recorre el camino entero que sigue el flujo de GitHub (evaluar, empaquetar,
cerrar) sobre un repositorio con remoto local. El servidor desplegado y las versiones
de GitHub son de mentira; git es el real. Ninguna toca la red.
"""

from __future__ import annotations

import json
import unittest

from . import support
from .support import SHA_A, SHA_B, SHA_C, FakeProduction, Repo, base_tools, git, summary_of, tool

from compatlib import contract, finalize, ledger, pipeline, versioning  # noqa: E402

NOW = "2026-10-04T00:00:00Z"


def event(sha, summary=None, *, origin="aviso", environment="prod", release="v9.0.0"):
    return {
        "entorno": environment, "origen": origin, "sha": sha, "release": release,
        "corrida": "https://github.com/Vinden-NewAge/vinden-mcp-data-layer/actions/runs/1",
        "actor": "despliegue", "contrato": summary,
    }


def tools_with_change() -> list:
    """Un catálogo donde `run_metric` deja de llevar el contexto de la conversación:
    cambia un archivo derivado que sí llega a las instalaciones."""
    tools = base_tools()
    tools[3] = tool("run_metric", ["metric"], ["metric"])
    return tools


def tools_with_extra() -> list:
    """Un catálogo con una herramienta nueva que el plugin no usa."""
    return base_tools() + [tool("nueva_lectura", ["selection_context"])]


class Flow(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Repo()
        self.addCleanup(self.repo.close)

    def run_flow(self, ev, prod, *, tests_passed=True, tamper=None):
        repo = self.repo
        git(repo.root, "fetch", "origin", "main")
        git(repo.root, "reset", "--hard", "FETCH_HEAD")
        evaluation = pipeline.evaluate(
            repo.root, ev, prod=prod, today="2026-10-04", attempts=2, wait=lambda _: None
        )
        if evaluation["accion"] == "nada":
            return evaluation, None
        assets = repo.package()
        tested = versioning.shipped_digest(repo.root)
        if tamper:
            tamper()
        entry = finalize.finalize(
            repo.root, evaluation, forge=repo.forge, assets=assets,
            tested_digest=tested, now=NOW, tests_passed=tests_passed,
        )
        return evaluation, entry

    def remote_ledger(self) -> list:
        text = self.repo.remote_file("compat/registro.jsonl")
        return [json.loads(line) for line in text.splitlines() if line]

    def remote_version(self) -> str:
        return json.loads(self.repo.remote_file(".claude-plugin/plugin.json"))["version"]

    # ── Despliegue exitoso con cambios ────────────────────────────────────────
    def test_despliegue_con_cambios_publica_una_version_y_la_verifica(self):
        tools = tools_with_change()
        evaluation, entry = self.run_flow(event(SHA_B, summary_of(tools)), FakeProduction(SHA_B, tools))
        self.assertEqual(evaluation["accion"], "publicar")
        self.assertEqual(entry["resultado"], "actualizado")
        self.assertEqual(entry["plugin"]["version"], "1.0.1")
        self.assertEqual(entry["main"], "ok")
        self.assertEqual(self.repo.remote_tags(), ["v1.0.1"])
        release = self.repo.forge.releases["v1.0.1"]
        self.assertFalse(release["draft"])
        self.assertTrue(release["latest"])
        self.assertEqual(release["assets"]["datalum-skill.zip"], entry["plugin"]["paquete"])
        self.assertEqual(self.remote_version(), "1.0.1")
        self.assertIn("## [1.0.1] - 2026-10-04", self.repo.remote_file("CHANGELOG.md"))
        self.assertIn("run_metric", json.loads(self.repo.remote_file("client/contract-facts.json"))["sin_selection_context"])
        line = self.remote_ledger()[-1]
        self.assertEqual(line["despliegue"]["sha"], SHA_B)
        self.assertEqual(line["contrato"]["huella"], summary_of(tools)["huella"])
        self.assertEqual(line["plugin"]["version"], "1.0.1")
        # La etiqueta publica exactamente el contenido que se probó.
        self.assertEqual(self.repo.forge.tag_digest("v1.0.1"), entry["plugin"]["contenido"])

    # ── Despliegue exitoso sin cambios ────────────────────────────────────────
    def test_despliegue_sin_cambios_conserva_la_version_y_registra(self):
        tools = base_tools()
        evaluation, entry = self.run_flow(event(SHA_B, summary_of(tools)), FakeProduction(SHA_B, tools))
        self.assertEqual(evaluation["clase"], "sin_cambios")
        self.assertEqual(entry["resultado"], "compatible_sin_cambios")
        self.assertEqual(entry["plugin"]["version"], "1.0.0")
        self.assertEqual(self.repo.remote_tags(), [])
        self.assertEqual(self.repo.forge.releases, {})
        self.assertEqual(self.remote_version(), "1.0.0")
        self.assertEqual(self.remote_ledger()[-1]["despliegue"]["sha"], SHA_B)

    def test_cambio_que_el_plugin_no_usa_no_genera_version(self):
        tools = tools_with_extra()
        evaluation, entry = self.run_flow(event(SHA_B, summary_of(tools)), FakeProduction(SHA_B, tools))
        self.assertEqual(evaluation["clase"], "compatible")
        self.assertEqual(entry["resultado"], "compatible_sin_cambios")
        self.assertEqual(self.repo.remote_tags(), [])
        self.assertEqual(self.remote_version(), "1.0.0")
        current = json.loads(self.repo.remote_file("compat/contrato-produccion.json"))
        self.assertEqual(current["huella"], summary_of(tools)["huella"])
        self.assertIn("herramientas nuevas: nueva_lectura", evaluation["notas"])

    # ── Despliegue fallido ────────────────────────────────────────────────────
    def test_despliegue_que_no_pasa_salud_no_cambia_nada(self):
        tools = tools_with_change()
        prod = FakeProduction(SHA_B, tools, ok=False)
        evaluation, entry = self.run_flow(event(SHA_B, summary_of(tools)), prod)
        self.assertEqual(entry["resultado"], "despliegue_no_confirmado")
        self.assertEqual(evaluation["accion"], "avisar")
        self.assertEqual(self.repo.remote_tags(), [])
        self.assertEqual(self.remote_version(), "1.0.0")

    def test_servidor_caido_no_cambia_nada(self):
        prod = FakeProduction(SHA_B, base_tools())
        prod.down = True
        _, entry = self.run_flow(event(SHA_B, summary_of(base_tools())), prod)
        self.assertEqual(entry["resultado"], "despliegue_no_confirmado")
        self.assertIn("salud", entry["detalle"])

    def test_servidor_caido_en_la_lectura_de_cada_hora_se_anota(self):
        prod = FakeProduction(SHA_B, base_tools())
        prod.down = True
        back = {"entorno": "prod", "origen": "reconciliacion", "sha": None}
        _, entry = self.run_flow(back, prod)
        self.assertEqual(entry["resultado"], "despliegue_no_confirmado")
        self.assertNotIn("sha", entry["despliegue"])
        self.assertEqual(entry["main"], "ok")
        self.assertEqual(self.remote_ledger()[-1]["resultado"], "despliegue_no_confirmado")

    def test_la_misma_caida_con_otro_texto_de_error_no_es_novedad(self):
        prod = FakeProduction(SHA_B, base_tools())
        prod.down = True
        back = {"entorno": "prod", "origen": "reconciliacion", "sha": None}
        self.run_flow(back, prod)
        lines = len(self.remote_ledger())
        prod.health = lambda: (_ for _ in ()).throw(support.production.ProductionError("connection reset"))
        evaluation, entry = self.run_flow(back, prod)
        self.assertEqual(evaluation["accion"], "nada")
        self.assertIsNone(entry)
        self.assertEqual(len(self.remote_ledger()), lines)

    def test_aviso_de_un_commit_que_el_servidor_no_sirve_no_cuenta(self):
        tools = tools_with_change()
        _, entry = self.run_flow(event(SHA_B, summary_of(tools)), FakeProduction(SHA_A, base_tools()))
        self.assertEqual(entry["resultado"], "despliegue_no_confirmado")
        self.assertEqual(self.repo.remote_tags(), [])

    # ── Cambio incompatible ───────────────────────────────────────────────────
    def test_cambio_incompatible_detiene_la_publicacion_y_propone(self):
        tools = tools_with_change()
        tools[1] = tool("use_agent", ["agent", "selection_context"], ["agent"])
        evaluation, entry = self.run_flow(event(SHA_B, summary_of(tools)), FakeProduction(SHA_B, tools))
        self.assertEqual(entry["resultado"], "incompatible")
        self.assertEqual(evaluation["accion"], "proponer")
        self.assertEqual(self.repo.remote_tags(), [])
        self.assertEqual(self.remote_version(), "1.0.0")
        self.assertNotIn("run_metric", json.loads(self.repo.remote_file("client/contract-facts.json"))["sin_selection_context"])
        text = pipeline.proposal(evaluation)
        self.assertIn("no es compatible", text["titulo"])
        self.assertIn("user_choice_quote", text["cuerpo"])
        self.assertIn("No se publicó ninguna versión", text["cuerpo"])

    def test_argumento_obligatorio_nuevo_es_incompatible(self):
        tools = base_tools()
        tools[2] = tool("remember", ["kind", "title", "body_md", "slug", "motivo"], ["kind", "title", "body_md", "motivo"])
        _, entry = self.run_flow(event(SHA_B, summary_of(tools)), FakeProduction(SHA_B, tools))
        self.assertEqual(entry["resultado"], "incompatible")
        self.assertIn("motivo", entry["detalle"])

    def test_texto_que_el_plugin_sigue_pide_revision_y_no_publica(self):
        tools = tools_with_change()
        new_text = "Instrucciones nuevas: elige tú el agente."
        prod = FakeProduction(SHA_B, tools, instructions=new_text)
        evaluation, entry = self.run_flow(event(SHA_B, summary_of(tools, new_text)), prod)
        self.assertEqual(entry["resultado"], "revision_requerida")
        self.assertEqual(self.repo.remote_tags(), [])
        saved = self.repo.remote_file(f"compat/instrucciones/{contract.sha256_text(new_text)[:12]}.txt")
        self.assertEqual(saved, new_text)
        self.assertIn("hace falta leerlo", pipeline.proposal(evaluation)["titulo"])

    def test_tras_la_revision_de_una_persona_el_despliegue_se_cierra(self):
        tools = tools_with_change()
        new_text = "Instrucciones nuevas, equivalentes a las anteriores."
        prod = FakeProduction(SHA_B, tools, instructions=new_text)
        ev = event(SHA_B, summary_of(tools, new_text))
        _, first = self.run_flow(ev, prod)
        self.assertEqual(first["resultado"], "revision_requerida")
        lines = len(self.remote_ledger())

        # La lectura de la hora siguiente no repite el aviso.
        again, entry = self.run_flow({"entorno": "prod", "origen": "reconciliacion", "sha": None}, prod)
        self.assertEqual(again["accion"], "nada")
        self.assertIsNone(entry)
        self.assertEqual(len(self.remote_ledger()), lines)

        # Una persona lee el texto y lo da por revisado, por el camino normal del repositorio.
        requirements = json.loads(self.repo.remote_file("compat/requisitos.json"))
        requirements["instrucciones_revisadas"].append(contract.sha256_text(new_text))
        self.repo.write_json("compat/requisitos.json", requirements)
        git(self.repo.root, "commit", "-am", "revisado")
        git(self.repo.root, "push", "origin", "HEAD:main")

        evaluation, closed = self.run_flow({"entorno": "prod", "origen": "reconciliacion", "sha": None}, prod)
        self.assertEqual(evaluation["despliegue"]["tipo"], "pendiente")
        self.assertEqual(closed["resultado"], "actualizado")
        self.assertEqual(self.remote_version(), "1.0.1")

    def test_la_lectura_de_cada_hora_no_repite_un_aviso_sin_novedad(self):
        back = {"entorno": "prod", "origen": "reconciliacion", "sha": None}
        prod = FakeProduction(SHA_B, tools_with_change())
        _, first = self.run_flow(back, prod)
        self.assertEqual(first["resultado"], "contrato_no_disponible")
        lines = len(self.remote_ledger())
        for _ in range(3):
            evaluation, entry = self.run_flow(back, prod)
            self.assertEqual(evaluation["accion"], "nada")
            self.assertIsNone(entry)
        self.assertEqual(len(self.remote_ledger()), lines)
        # Cuando llega el contrato, el mismo despliegue sí se procesa.
        _, entry = self.run_flow(event(SHA_B, summary_of(tools_with_change())), prod)
        self.assertEqual(entry["resultado"], "actualizado")

    # ── Publicación fallida, evento duplicado y reintento ─────────────────────
    def test_publicacion_fallida_no_mueve_main_y_el_reintento_no_duplica(self):
        tools = tools_with_change()
        ev, prod = event(SHA_B, summary_of(tools)), FakeProduction(SHA_B, tools)
        self.repo.forge.fail_on = {"publish"}
        _, entry = self.run_flow(ev, prod)
        self.assertEqual(entry["resultado"], "publicacion_fallida")
        self.assertEqual(self.remote_version(), "1.0.0")
        self.assertTrue(self.repo.forge.releases["v1.0.1"]["draft"])
        self.assertFalse(self.repo.forge.releases["v1.0.1"]["latest"])
        self.assertEqual(self.repo.remote_tags(), ["v1.0.1"])
        tagged = self.repo.forge.remote_tag("v1.0.1")

        _, retry = self.run_flow(ev, prod)
        self.assertEqual(retry["despliegue"]["tipo"], "reintento")
        self.assertEqual(retry["resultado"], "actualizado")
        self.assertEqual(self.repo.remote_tags(), ["v1.0.1"])
        self.assertEqual(self.repo.forge.remote_tag("v1.0.1"), tagged)
        self.assertEqual(self.repo.forge.calls.count("create"), 1)
        self.assertFalse(self.repo.forge.releases["v1.0.1"]["draft"])
        self.assertEqual(self.remote_version(), "1.0.1")
        self.assertEqual([l["resultado"] for l in self.remote_ledger()], ["publicacion_fallida", "actualizado"])

    def test_evento_duplicado_no_hace_nada(self):
        tools = tools_with_change()
        ev, prod = event(SHA_B, summary_of(tools)), FakeProduction(SHA_B, tools)
        self.run_flow(ev, prod)
        main_before, lines_before = self.repo.remote_main(), len(self.remote_ledger())
        evaluation, entry = self.run_flow(ev, prod)
        self.assertEqual(evaluation["accion"], "nada")
        self.assertIsNone(entry)
        self.assertEqual(self.repo.remote_main(), main_before)
        self.assertEqual(len(self.remote_ledger()), lines_before)
        self.assertEqual(self.repo.remote_tags(), ["v1.0.1"])

    def test_etiqueta_existente_con_otro_contenido_no_se_toca(self):
        git(self.repo.root, "tag", "v1.0.1")
        git(self.repo.root, "push", "origin", "refs/tags/v1.0.1")
        before = self.repo.forge.remote_tag("v1.0.1")
        tools = tools_with_change()
        _, entry = self.run_flow(event(SHA_B, summary_of(tools)), FakeProduction(SHA_B, tools))
        self.assertEqual(entry["resultado"], "publicacion_fallida")
        self.assertIn("ya existe con otro contenido", entry["detalle"])
        self.assertEqual(self.repo.forge.remote_tag("v1.0.1"), before)
        self.assertEqual(self.repo.forge.releases, {})

    # ── Despliegues concurrentes ──────────────────────────────────────────────
    def test_un_despliegue_antiguo_no_pisa_la_compatibilidad_del_mas_reciente(self):
        newer, older = tools_with_change(), tools_with_extra()
        prod = FakeProduction(SHA_C, newer)
        # Los dos avisos llegan en desorden: primero se procesa el más reciente.
        _, first = self.run_flow(event(SHA_C, summary_of(newer)), prod)
        self.assertEqual(first["resultado"], "actualizado")
        _, late = self.run_flow(event(SHA_B, summary_of(older)), prod)
        self.assertEqual(late["resultado"], "despliegue_no_confirmado")
        current = json.loads(self.repo.remote_file("compat/contrato-produccion.json"))
        self.assertEqual(current["huella"], summary_of(newer)["huella"])
        self.assertEqual(ledger.latest(self.remote_ledger(), "prod")["despliegue"]["sha"], SHA_C)
        self.assertEqual(self.remote_version(), "1.0.1")

    def test_aviso_antiguo_procesado_antes_no_estorba_al_reciente(self):
        newer = tools_with_change()
        prod = FakeProduction(SHA_C, newer)
        _, late = self.run_flow(event(SHA_B, summary_of(tools_with_extra())), prod)
        self.assertEqual(late["resultado"], "despliegue_no_confirmado")
        _, entry = self.run_flow(event(SHA_C, summary_of(newer)), prod)
        self.assertEqual(entry["resultado"], "actualizado")

    # ── Rollback ──────────────────────────────────────────────────────────────
    def test_rollback_se_comprueba_con_el_contrato_guardado(self):
        self.run_flow(event(SHA_A, summary_of(base_tools())), FakeProduction(SHA_A, base_tools()))
        changed = tools_with_change()
        self.run_flow(event(SHA_B, summary_of(changed)), FakeProduction(SHA_B, changed))
        self.assertEqual(self.remote_version(), "1.0.1")

        # Producción vuelve al commit anterior. No hay aviso: lo ve la lectura programada.
        back = {"entorno": "prod", "origen": "reconciliacion", "sha": None}
        evaluation, entry = self.run_flow(back, FakeProduction(SHA_A, base_tools()))
        self.assertEqual(entry["despliegue"]["tipo"], "rollback")
        self.assertEqual(evaluation["contrato"]["origen"], "registro")
        self.assertEqual(entry["resultado"], "actualizado")
        self.assertEqual(self.remote_version(), "1.0.2")
        facts = json.loads(self.repo.remote_file("client/contract-facts.json"))
        self.assertNotIn("run_metric", facts["sin_selection_context"])
        # Las versiones anteriores siguen publicadas y sin tocar.
        self.assertEqual(self.repo.remote_tags(), ["v1.0.1", "v1.0.2"])
        self.assertFalse(self.repo.forge.releases["v1.0.1"]["draft"])

    def test_rollback_sin_cambios_que_publicar_solo_se_registra(self):
        self.run_flow(event(SHA_A, summary_of(base_tools())), FakeProduction(SHA_A, base_tools()))
        extra = tools_with_extra()
        self.run_flow(event(SHA_B, summary_of(extra)), FakeProduction(SHA_B, extra))
        back = {"entorno": "prod", "origen": "reconciliacion", "sha": None}
        _, entry = self.run_flow(back, FakeProduction(SHA_A, base_tools()))
        self.assertEqual(entry["despliegue"]["tipo"], "rollback")
        self.assertEqual(entry["resultado"], "compatible_sin_cambios")
        self.assertEqual(self.repo.remote_tags(), [])

    # ── Paquete descargado distinto del probado ───────────────────────────────
    def test_borrador_distinto_del_probado_no_se_publica(self):
        tools = tools_with_change()
        self.repo.forge.corrupt = {"draft"}
        _, entry = self.run_flow(event(SHA_B, summary_of(tools)), FakeProduction(SHA_B, tools))
        self.assertEqual(entry["resultado"], "paquete_no_coincide")
        self.assertTrue(self.repo.forge.releases["v1.0.1"]["draft"])
        self.assertNotIn("publish", self.repo.forge.calls)
        self.assertEqual(self.remote_version(), "1.0.0")

    def test_paquete_publicado_distinto_se_retira_de_ultima_version(self):
        tools = tools_with_change()
        self.repo.forge.corrupt = {"published"}
        _, entry = self.run_flow(event(SHA_B, summary_of(tools)), FakeProduction(SHA_B, tools))
        self.assertEqual(entry["resultado"], "paquete_no_coincide")
        self.assertIn("demote", self.repo.forge.calls)
        self.assertFalse(self.repo.forge.releases["v1.0.1"]["latest"])
        self.assertEqual(self.remote_version(), "1.0.0")

    def test_contenido_cambiado_despues_de_probar_no_se_publica(self):
        tools = tools_with_change()

        def tamper():
            self.repo.write("hooks/hooks.json", '{"cambiado": true}\n')

        _, entry = self.run_flow(event(SHA_B, summary_of(tools)), FakeProduction(SHA_B, tools), tamper=tamper)
        self.assertEqual(entry["resultado"], "paquete_no_coincide")
        self.assertEqual(self.repo.remote_tags(), [])
        self.assertEqual(self.repo.remote_file("hooks/hooks.json"), "{}")

    # ── Contrato, pruebas y reglas del repositorio ────────────────────────────
    def test_pruebas_fallidas_no_publican(self):
        tools = tools_with_change()
        _, entry = self.run_flow(event(SHA_B, summary_of(tools)), FakeProduction(SHA_B, tools), tests_passed=False)
        self.assertEqual(entry["resultado"], "pruebas_fallidas")
        self.assertEqual(self.repo.remote_tags(), [])
        self.assertEqual(self.remote_version(), "1.0.0")

    def test_commit_desconocido_sin_contrato_se_avisa(self):
        back = {"entorno": "prod", "origen": "reconciliacion", "sha": None}
        evaluation, entry = self.run_flow(back, FakeProduction(SHA_B, tools_with_change()))
        self.assertEqual(entry["resultado"], "contrato_no_disponible")
        self.assertEqual(evaluation["accion"], "avisar")
        self.assertEqual(self.repo.remote_tags(), [])

    def test_con_credencial_de_lectura_el_contrato_sale_del_servidor(self):
        tools = tools_with_change()
        back = {"entorno": "prod", "origen": "reconciliacion", "sha": None}
        evaluation, entry = self.run_flow(back, FakeProduction(SHA_B, tools, token=True))
        self.assertEqual(evaluation["contrato"]["origen"], "servidor")
        self.assertEqual(entry["contrato"]["verificacion"], "completa")
        self.assertEqual(entry["resultado"], "actualizado")

    def test_contrato_del_aviso_que_no_es_el_servido_se_rechaza(self):
        sent = summary_of(tools_with_change(), "Otras instrucciones.")
        _, entry = self.run_flow(event(SHA_B, sent), FakeProduction(SHA_B, tools_with_change()))
        self.assertEqual(entry["resultado"], "contrato_no_coincide")
        self.assertEqual(self.repo.remote_tags(), [])

    def test_catalogo_completo_distinto_del_aviso_se_rechaza(self):
        prod = FakeProduction(SHA_B, tools_with_extra(), token=True)
        _, entry = self.run_flow(event(SHA_B, summary_of(tools_with_change())), prod)
        self.assertEqual(entry["resultado"], "contrato_no_coincide")

    def test_entorno_previo_prepara_y_prueba_la_candidata_sin_publicar(self):
        tools = tools_with_change()
        ev = event(SHA_B, summary_of(tools), environment="qa")
        evaluation, entry = self.run_flow(ev, FakeProduction(SHA_B, tools))
        self.assertEqual(entry["resultado"], "candidata_lista")
        self.assertEqual(evaluation["version_nueva"], "1.0.1")
        self.assertTrue(entry["plugin"]["candidata"])
        self.assertEqual(entry["plugin"]["version"], "1.0.1")
        # Nada de la candidata llega a main ni se publica.
        self.assertEqual(self.repo.remote_tags(), [])
        self.assertEqual(self.repo.forge.releases, {})
        self.assertEqual(self.remote_version(), "1.0.0")
        self.assertNotIn("run_metric", json.loads(self.repo.remote_file("client/contract-facts.json"))["sin_selection_context"])
        self.assertNotIn("[1.0.1]", self.repo.remote_file("CHANGELOG.md"))
        # El contrato queda guardado: cuando producción sirva ese commit ya se conoce.
        self.assertTrue(self.repo.remote_file(f"compat/contratos/{SHA_B[:12]}.json"))
        self.assertIsNone(ledger.latest(self.remote_ledger(), "prod"))

    def test_produccion_promueve_la_candidata_que_probo_el_entorno_previo(self):
        tools = tools_with_change()
        _, candidate = self.run_flow(event(SHA_B, summary_of(tools), environment="qa"), FakeProduction(SHA_B, tools))
        # Producción sirve el mismo commit y ya no hace falta mandar el contrato.
        ev = {"entorno": "prod", "origen": "aviso", "sha": SHA_B, "release": "v9.0.0"}
        evaluation, entry = self.run_flow(ev, FakeProduction(SHA_B, tools))
        self.assertEqual(evaluation["contrato"]["origen"], "registro")
        self.assertEqual(entry["resultado"], "actualizado")
        self.assertTrue(entry["candidata"]["promovida"])
        self.assertEqual(entry["plugin"]["contenido"], candidate["plugin"]["contenido"])
        self.assertEqual(self.remote_version(), "1.0.1")

    def test_un_cambio_incompatible_se_ve_en_el_entorno_previo(self):
        tools = base_tools()
        tools[1] = tool("use_agent", ["agent", "selection_context"], ["agent"])
        ev = event(SHA_B, summary_of(tools), environment="qa")
        evaluation, entry = self.run_flow(ev, FakeProduction(SHA_B, tools))
        self.assertEqual(entry["resultado"], "incompatible")
        self.assertEqual(entry["despliegue"]["entorno"], "qa")
        self.assertIsNone(ledger.latest(self.remote_ledger(), "prod"))
        self.assertEqual(self.remote_version(), "1.0.0")

    def test_candidata_que_no_pasa_las_pruebas_queda_anotada(self):
        tools = tools_with_change()
        ev = event(SHA_B, summary_of(tools), environment="qa")
        _, entry = self.run_flow(ev, FakeProduction(SHA_B, tools), tests_passed=False)
        self.assertEqual(entry["resultado"], "pruebas_fallidas")
        self.assertEqual(self.remote_version(), "1.0.0")
        self.assertEqual(self.repo.remote_tags(), [])

    def test_si_main_no_admite_el_empuje_queda_una_rama_pendiente(self):
        tools = tools_with_change()
        ev, prod = event(SHA_B, summary_of(tools)), FakeProduction(SHA_B, tools)
        repo = self.repo
        evaluation = pipeline.evaluate(repo.root, ev, prod=prod, today="2026-10-04", attempts=1, wait=lambda _: None)
        assets, tested = repo.package(), versioning.shipped_digest(repo.root)
        # Mientras tanto alguien más mueve main: el empuje directo deja de ser posible.
        git(repo.root, "stash", "-u")
        other = git(repo.root, "commit-tree", "HEAD^{tree}", "-p", "HEAD", "-m", "otro cambio")
        git(repo.root, "push", "origin", f"{other}:refs/heads/main")
        git(repo.root, "stash", "pop")
        entry = finalize.finalize(repo.root, evaluation, forge=repo.forge, assets=assets, tested_digest=tested, now=NOW)
        self.assertEqual(entry["resultado"], "actualizado")
        self.assertTrue(entry["main"].startswith("pendiente"))
        self.assertEqual(self.repo.remote_main(), other)


class Events(unittest.TestCase):
    def test_avisos_mal_formados_se_rechazan(self):
        good = event(SHA_A, summary_of(base_tools()))
        for change in (
            {"entorno": "staging"},
            {"origen": "push"},
            {"sha": "abc"},
            {"sha": None},
        ):
            with self.assertRaises(pipeline.EventError, msg=str(change)):
                pipeline.validate_event(dict(good, **change))

    def test_contrato_alterado_se_rechaza(self):
        summary = summary_of(base_tools())
        summary["herramientas"][0]["p"] = ["inyectado"]
        with self.assertRaises(contract.ContractError):
            pipeline.validate_event(event(SHA_A, summary))

    def test_contrato_con_nombres_raros_se_rechaza(self):
        summary = summary_of(base_tools())
        summary["herramientas"][0]["n"] = "list_agents; rm -rf"
        summary["huella"] = contract.fingerprint(summary)
        with self.assertRaises(contract.ContractError):
            contract.validate(summary)

    def test_la_direccion_sale_del_repositorio_no_del_aviso(self):
        repo = Repo()
        self.addCleanup(repo.close)
        self.assertEqual(pipeline.mcp_url(repo.root, "prod"), "https://mcp.example.invalid/mcp")
        self.assertEqual(pipeline.mcp_url(repo.root, "qa"), "https://qa.example.invalid/mcp")
        clean = pipeline.validate_event(dict(event(SHA_A), url="https://atacante.invalid/mcp"))
        self.assertNotIn("url", clean)


class LedgerRules(unittest.TestCase):
    def line(self, sha, result, environment="prod"):
        return {"despliegue": {"entorno": environment, "sha": sha}, "resultado": result}

    def test_clasifica_el_commit_servido(self):
        entries = [self.line(SHA_A, "compatible_sin_cambios"), self.line(SHA_B, "actualizado")]
        self.assertEqual(ledger.classify_event(entries, "prod", SHA_B), "duplicado")
        self.assertEqual(ledger.classify_event(entries, "prod", SHA_A), "rollback")
        self.assertEqual(ledger.classify_event(entries, "prod", SHA_C), "nuevo")
        entries.append(self.line(SHA_C, "publicacion_fallida"))
        self.assertEqual(ledger.classify_event(entries, "prod", SHA_C), "reintento")
        entries.append(self.line(SHA_C, "revision_requerida"))
        self.assertEqual(ledger.classify_event(entries, "prod", SHA_C), "pendiente")

    def test_un_despliegue_no_confirmado_no_cuenta_como_ultimo(self):
        entries = [self.line(SHA_A, "actualizado"), self.line(SHA_B, "despliegue_no_confirmado")]
        self.assertEqual(ledger.latest(entries, "prod")["despliegue"]["sha"], SHA_A)

    def test_los_entornos_no_se_mezclan(self):
        entries = [self.line(SHA_A, "candidata_lista", "qa")]
        self.assertEqual(ledger.classify_event(entries, "prod", SHA_A), "nuevo")


if __name__ == "__main__":
    unittest.main()
