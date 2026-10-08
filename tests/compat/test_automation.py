"""Pruebas de código de la actualización automática.

Cada prueba recorre el camino entero que sigue el flujo de GitHub (evaluar, empaquetar,
cerrar) sobre un repositorio con remoto local. El servidor desplegado y las versiones
de GitHub son de mentira; git es el real. Ninguna toca la red.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from . import support
from .support import SHA_A, SHA_B, SHA_C, FakeProduction, Repo, base_tools, git, summary_of, tool

from compatlib import contract, finalize, ledger, pipeline, publish, versioning  # noqa: E402

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

    def test_paquete_publicado_distinto_vuelve_a_borrador(self):
        tools = tools_with_change()
        self.repo.forge.corrupt = {"published"}
        _, entry = self.run_flow(event(SHA_B, summary_of(tools)), FakeProduction(SHA_B, tools))
        self.assertEqual(entry["resultado"], "paquete_no_coincide")
        self.assertIn("unpublish", self.repo.forge.calls)
        release = self.repo.forge.releases["v1.0.1"]
        self.assertTrue(release["draft"], "no queda a la vista")
        self.assertFalse(release["latest"])
        self.assertEqual(self.remote_version(), "1.0.0")

    # Defecto de la 2.0.1: la retirada de una publicación incorrecta no se comprobaba.
    def test_una_retirada_fallida_se_detecta_y_el_reintento_la_recupera(self):
        tools = tools_with_change()
        ev, prod = event(SHA_B, summary_of(tools)), FakeProduction(SHA_B, tools)
        self.repo.forge.corrupt = {"published"}
        self.repo.forge.fail_on = {"unpublish"}
        _, entry = self.run_flow(ev, prod)
        self.assertEqual(entry["resultado"], "retirada_fallida", "la retirada no se dio por hecha")
        self.assertFalse(self.repo.forge.releases["v1.0.1"]["draft"], "la versión sigue a la vista")

        # Lo publicado ya no está corrupto, pero sigue con los archivos equivocados.
        self.repo.forge.corrupt = set()
        bad = {name: "0" * 64 for name in self.repo.forge.releases["v1.0.1"]["assets"]}
        self.repo.forge.releases["v1.0.1"]["assets"] = bad
        _, retry = self.run_flow(ev, prod)
        self.assertEqual(retry["resultado"], "actualizado")
        release = self.repo.forge.releases["v1.0.1"]
        self.assertFalse(release["draft"])
        self.assertNotEqual(release["assets"], bad, "se publicaron los archivos probados")
        self.assertEqual(self.remote_version(), "1.0.1")

    def test_una_retirada_incierta_se_distingue_y_el_reintento_la_recupera(self):
        tools = tools_with_change()
        ev, prod = event(SHA_B, summary_of(tools)), FakeProduction(SHA_B, tools)
        self.repo.forge.corrupt = {"published"}
        # GitHub acepta la orden, pero después no se puede leer en qué estado quedó.
        self.repo.forge.fail_on = {"state_after_unpublish"}
        _, entry = self.run_flow(ev, prod)
        self.assertEqual(entry["resultado"], "retirada_incierta")
        self.repo.forge.corrupt = set()
        _, retry = self.run_flow(ev, prod)
        self.assertEqual(retry["resultado"], "actualizado")
        self.assertFalse(self.repo.forge.releases["v1.0.1"]["draft"])
        self.assertEqual(self.remote_version(), "1.0.1")

    def test_una_retirada_rechazada_y_sin_estado_se_recupera_en_el_reintento(self):
        tools = tools_with_change()
        ev, prod = event(SHA_B, summary_of(tools)), FakeProduction(SHA_B, tools)
        self.repo.forge.corrupt = {"published"}
        # GitHub rechaza la orden y además no contesta cómo quedó: sigue a la vista.
        self.repo.forge.fail_on = {"unpublish", "state_after_unpublish"}
        _, entry = self.run_flow(ev, prod)
        self.assertEqual(entry["resultado"], "retirada_incierta")
        self.assertFalse(self.repo.forge.releases["v1.0.1"]["draft"])
        self.repo.forge.corrupt = set()
        bad = {name: "0" * 64 for name in self.repo.forge.releases["v1.0.1"]["assets"]}
        self.repo.forge.releases["v1.0.1"]["assets"] = bad
        _, retry = self.run_flow(ev, prod)
        self.assertEqual(retry["resultado"], "actualizado")
        self.assertNotEqual(self.repo.forge.releases["v1.0.1"]["assets"], bad, "se publicaron los archivos probados")

    def test_una_descarga_fallida_no_retira_una_version_correcta(self):
        tools = tools_with_change()
        ev, prod = event(SHA_B, summary_of(tools)), FakeProduction(SHA_B, tools)
        # Falla la descarga de después de publicar: no se sabe qué quedó, no que esté mal.
        original = self.repo.forge.publish

        def publish_then_lose_download(tag):
            original(tag)
            self.repo.forge.fail_on.add("download")

        self.repo.forge.publish = publish_then_lose_download
        _, entry = self.run_flow(ev, prod)
        self.assertEqual(entry["resultado"], "publicacion_fallida")
        self.assertNotIn("unpublish", self.repo.forge.calls)
        self.assertFalse(self.repo.forge.releases["v1.0.1"]["draft"], "la versión correcta sigue publicada")
        self.repo.forge.publish = original
        _, retry = self.run_flow(ev, prod)
        self.assertEqual(retry["resultado"], "actualizado")
        self.assertEqual(retry["publicacion"]["estado"], "ya_publicada")

    def test_sin_un_intento_propio_anterior_no_se_toca_una_version_publicada(self):
        tools = tools_with_change()
        ev, prod = event(SHA_B, summary_of(tools)), FakeProduction(SHA_B, tools)
        # Una versión v1.0.1 ya publicada con otros archivos, sin intento previo de este
        # despliegue en el registro: no se retira ni se cambia.
        self.run_flow(event(SHA_A, summary_of(base_tools())), FakeProduction(SHA_A, base_tools()))
        self.repo.forge.corrupt = {"published"}
        self.repo.forge.fail_on = {"unpublish"}
        self.run_flow(ev, prod)  # deja v1.0.1 publicada con archivos malos: retirada_fallida
        self.repo.forge.corrupt = set()
        bad = {name: "0" * 64 for name in self.repo.forge.releases["v1.0.1"]["assets"]}
        self.repo.forge.releases["v1.0.1"]["assets"] = bad
        from compatlib import publish as pub
        assets = self.repo.package()
        with self.assertRaises(pub.Immutable):
            pub.publish(self.repo.forge, tag="v1.0.1", commit="HEAD", digest=self.repo.forge.tag_digest("v1.0.1"),
                        title="t", notes="n", assets=assets, recover=False)
        self.assertEqual(self.repo.forge.releases["v1.0.1"]["assets"], bad)

    def test_tras_volver_a_borrador_el_reintento_publica_lo_probado(self):
        tools = tools_with_change()
        ev, prod = event(SHA_B, summary_of(tools)), FakeProduction(SHA_B, tools)
        self.repo.forge.corrupt = {"published"}
        self.run_flow(ev, prod)
        self.repo.forge.corrupt = set()
        _, retry = self.run_flow(ev, prod)
        self.assertEqual(retry["resultado"], "actualizado")
        self.assertFalse(self.repo.forge.releases["v1.0.1"]["draft"])
        self.assertEqual(self.repo.remote_tags(), ["v1.0.1"])
        self.assertEqual(self.remote_version(), "1.0.1")

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


class GhForgeAgainstGh(unittest.TestCase):
    """La forja real contra un `gh` de mentira: lo que contesta la CLI de GitHub."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.bin = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.forge = publish.GhForge(self.bin)
        path = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{self.bin}{os.pathsep}{path}"
        self.addCleanup(os.environ.__setitem__, "PATH", path)

    def gh(self, script: str) -> None:
        target = self.bin / "gh"
        target.write_text("#!/bin/sh\n" + script, encoding="utf-8")
        target.chmod(0o755)

    def test_una_retirada_que_github_rechaza_se_informa(self):
        self.gh('echo "HTTP 403: Resource not accessible by integration" >&2; exit 1\n')
        self.assertIs(self.forge.unpublish("v1.0.1"), False)

    def test_una_retirada_aceptada_se_informa(self):
        self.gh("exit 0\n")
        self.assertIs(self.forge.unpublish("v1.0.1"), True)

    def test_una_version_que_no_existe_no_es_un_estado_desconocido(self):
        self.gh('echo "release not found" >&2; exit 1\n')
        self.assertIsNone(self.forge.release_state("v1.0.1"))

    def test_un_estado_que_no_se_puede_leer_no_se_da_por_inexistente(self):
        self.gh('echo "error connecting to api.github.com" >&2; exit 1\n')
        with self.assertRaises(publish.StateUnknown):
            self.forge.release_state("v1.0.1")


class PausedFamilies(unittest.TestCase):
    """Las herramientas que el plugin tiene en pausa salen del contrato, por familia."""

    REQUIREMENTS = {"en_pausa": {"familias": ["chart", "dashboard"], "aviso": "En pausa."}}

    def facts(self, names):
        summary = summary_of([tool(name, ["name"], ["name"]) for name in names])
        return contract.derive_facts(summary, self.REQUIREMENTS)

    def test_cada_herramienta_de_una_familia_queda_en_pausa(self):
        facts = self.facts(["render_chart", "upsert_custom_dashboard", "export_chart_csv", "run_metric", "list_agents"])
        self.assertEqual(facts["en_pausa"]["herramientas"], ["export_chart_csv", "render_chart", "upsert_custom_dashboard"])
        self.assertEqual(facts["en_pausa"]["aviso"], "En pausa.")

    def test_una_herramienta_nueva_de_la_familia_tambien(self):
        facts = self.facts(["list_dashboards", "chart_templates", "run_metric"])
        self.assertEqual(facts["en_pausa"]["herramientas"], ["chart_templates", "list_dashboards"])

    def test_un_nombre_que_sólo_contiene_la_palabra_no_cuenta(self):
        facts = self.facts(["describe_charter", "run_metric"])
        self.assertEqual(facts["en_pausa"]["herramientas"], [])

    def test_sin_familias_en_pausa_no_hay_pausa(self):
        summary = summary_of([tool("render_chart", ["name"], ["name"])])
        self.assertNotIn("en_pausa", contract.derive_facts(summary, {}))

    def test_el_plugin_tiene_en_pausa_las_graficas_y_tableros_del_contrato_vigente(self):
        root = Path(__file__).resolve().parents[2]
        facts = json.loads((root / "client/contract-facts.json").read_text(encoding="utf-8"))
        names = [t["n"] for t in json.loads((root / "compat/contrato-produccion.json").read_text(encoding="utf-8"))["herramientas"]]
        expected = sorted(n for n in names if "chart" in n.split("_") or "dashboard" in n.split("_"))
        self.assertEqual(len(expected), 14)
        self.assertEqual(facts["en_pausa"]["herramientas"], expected)


class ElConectorDeR12(unittest.TestCase):
    """Datalum R12 nombra el conector `connector` en toda herramienta que lo pide y
    rechaza `tenant`. Lo que el plugin pide y lo que deriva del contrato siguen a R12."""

    ROOT = Path(__file__).resolve().parents[2]

    def load(self, relative: str) -> dict:
        return json.loads((self.ROOT / relative).read_text(encoding="utf-8"))

    def before_r12(self) -> dict:
        """El contrato guardado de v2.243.0, de antes de R12."""
        return self.load("compat/contratos/22a5a022caeb.json")

    def with_connector(self, summary: dict) -> dict:
        """El mismo contrato con el conector nombrado como en R12: `tenant` y `tenantSlug`
        pasan a `connector`."""
        def rename(args):
            return sorted({"connector" if a in ("tenant", "tenantSlug") else a for a in args})

        body = dict(summary, herramientas=[dict(e, p=rename(e["p"]), r=rename(e["r"])) for e in summary["herramientas"]])
        body["huella"] = contract.fingerprint(body)
        return contract.validate(body)

    def test_con_el_conector_de_r12_el_plugin_es_compatible_y_el_conector_no_es_destino(self):
        summary = self.with_connector(self.before_r12())
        requirements = self.load("compat/requisitos.json")
        self.assertEqual(contract.compare(summary, requirements)["incompatible"], [])
        destinos = contract.derive_facts(summary, requirements)["destinos"]
        self.assertNotIn("connector", destinos.values())
        self.assertNotIn("get_model", destinos, "sólo pide el conector: no tiene destino")
        self.assertEqual(destinos["apply_batch"], "operations")

    def test_los_hechos_del_cliente_nombran_las_herramientas_de_r12(self):
        """`client/contract-facts.json` se derivó de la lista de herramientas de R12: los
        ocho nombres nuevos tienen destino, y no queda ninguno de los anteriores ni de las
        herramientas que R12 retira."""
        facts = self.load("client/contract-facts.json")
        named = set(facts["destinos"]) | set(facts["citas_humanas"]) | set(facts["sin_selection_context"])
        named |= set(facts["en_pausa"]["herramientas"])
        self.assertEqual(
            {name: facts["destinos"].get(name) for name in (
                "propose_metric", "propose_dataset", "propose_dimension", "attach_draft_connector",
                "detach_draft_connector", "propose_solution_install", "apply_solution_update", "edit_agent_profile",
            )},
            {
                "propose_metric": "name", "propose_dataset": "name", "propose_dimension": "name",
                "attach_draft_connector": "agentId", "detach_draft_connector": "agentId",
                "propose_solution_install": "template_id", "apply_solution_update": "solution", "edit_agent_profile": "agentId",
            },
        )
        gone = {
            "upsert_metric", "upsert_dataset", "upsert_dimension", "port_draft_connector", "unport_draft_connector",
            "propose_install", "apply_update", "edit_agent_ficha", "start_agent_edit", "finish_agent_edit", "publish_bundle",
        }
        self.assertEqual(named & gone, set())
        self.assertEqual([n for n in named if n.endswith("_status") or n.startswith("deprecate_")], [])

    def test_contra_el_contrato_de_antes_de_r12_el_plugin_pide_connector(self):
        reasons = contract.compare(self.before_r12(), self.load("compat/requisitos.json"))["incompatible"]
        self.assertEqual(
            reasons,
            [
                "`brain_index` ya no acepta ['connector'], que el plugin manda",
                "`brain_read` ya no acepta ['connector'], que el plugin manda",
            ],
        )


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
