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

    # Las herramientas de gráficas que servía Datalum cuando la 4.0.0 levantó la pausa, y
    # las cinco de artefactos que desde v2.301.0 listan los tableros en lugar de sus ocho
    # nombres de antes. Un despliegue posterior puede sumar otras de las mismas familias.
    GRAFICAS_Y_ARTEFACTOS = (
        "export_chart_csv", "get_chart", "render_chart", "save_chart_edit",
        "set_chart_options", "test_chart", "upsert_chart",
        "get_artifact", "run_artifact", "save_artifact_edit", "test_artifact", "upsert_artifact",
    )

    def test_produccion_sirve_las_graficas_y_los_artefactos_y_el_plugin_no_los_tiene_en_pausa(self):
        """La 4.0.0 levanta la pausa de la 2.0.4: el contrato de producción sirve las siete
        herramientas de gráficas de entonces y las cinco de artefactos, sin importar cuántas
        sume después, y ni los requisitos ni los hechos del cliente las niegan."""
        root = Path(__file__).resolve().parents[2]
        facts = json.loads((root / "client/contract-facts.json").read_text(encoding="utf-8"))
        requirements = json.loads((root / "compat/requisitos.json").read_text(encoding="utf-8"))
        names = {t["n"] for t in json.loads((root / "compat/contrato-produccion.json").read_text(encoding="utf-8"))["herramientas"]}
        self.assertEqual(len(self.GRAFICAS_Y_ARTEFACTOS), 12)
        self.assertEqual(sorted(set(self.GRAFICAS_Y_ARTEFACTOS) - names), [], "producción dejó de servirlas")
        self.assertNotIn("en_pausa", requirements)
        self.assertNotIn("en_pausa", facts)


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
        named |= set(facts.get("en_pausa", {}).get("herramientas", []))
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


class ElModeloDeR22(unittest.TestCase):
    """Datalum R22 añade a `use_agent` el modelo y el proveedor del asistente, opcionales.
    La Skill los manda sólo si el esquema los declara, así que lo que el plugin pide vale
    con R12 y con R22, como pide la transición de MANTENER.md."""

    ROOT = Path(__file__).resolve().parents[2]

    def load(self, relative: str) -> dict:
        return json.loads((self.ROOT / relative).read_text(encoding="utf-8"))

    def test_lo_que_el_plugin_pide_vale_con_r12_y_con_r22(self):
        requirements = self.load("compat/requisitos.json")
        for stored in ("compat/contratos/fe05777db569.json", "compat/contratos/7d298c8bef6f.json"):
            summary = contract.validate(self.load(stored))
            self.assertEqual(contract.compare(summary, requirements)["incompatible"], [], stored)

    def test_el_modelo_es_opcional_en_r22_y_no_existe_en_r12(self):
        r12 = contract.by_name(self.load("compat/contratos/fe05777db569.json"))["use_agent"]
        r22 = contract.by_name(self.load("compat/contratos/7d298c8bef6f.json"))["use_agent"]
        self.assertTrue({"model", "provider"} <= set(r22["p"]))
        self.assertEqual(r22["r"], r12["r"])
        self.assertFalse({"model", "provider"} & set(r12["p"]))

    def test_los_textos_de_r22_siguen_revisados(self):
        comparison = contract.compare(self.load("compat/contratos/7d298c8bef6f.json"), self.load("compat/requisitos.json"))
        self.assertEqual(comparison["revision"], [])


class LaOrdenDeLaPersona(unittest.TestCase):
    """Datalum v2.256.0 exige en toda escritura la orden de la persona, con sus palabras,
    en `user_request_quote`: también en `remember`, `forget` y `release_agent`, que el
    plugin usa. La Skill la manda donde el esquema la declara, así que lo que el plugin
    pide vale con v2.256.0 y con los contratos de antes, como pide la transición de
    MANTENER.md."""

    ROOT = Path(__file__).resolve().parents[2]
    V2_256_0 = "compat/contratos/cbdf86b096d1.json"
    ANTERIORES = (
        "compat/contratos/fe05777db569.json",  # v2.249.0, R12
        "compat/contratos/7d298c8bef6f.json",  # v2.251.0, R22
        "compat/contratos/a9f83f73ebda.json",  # v2.252.0
        "compat/contratos/320277a2cdf2.json",  # v2.253.0
        "compat/contratos/62a22ceb71be.json",  # v2.254.0
        "compat/contratos/32e4904ed6c4.json",  # v2.255.0
    )
    ESCRITURAS = ("forget", "release_agent", "remember")

    def load(self, relative: str) -> dict:
        return json.loads((self.ROOT / relative).read_text(encoding="utf-8"))

    def test_lo_que_el_plugin_pide_vale_con_v2_256_0_y_con_los_contratos_de_antes(self):
        requirements = self.load("compat/requisitos.json")
        for stored in self.ANTERIORES + (self.V2_256_0,):
            summary = contract.validate(self.load(stored))
            self.assertEqual(contract.compare(summary, requirements)["incompatible"], [], stored)

    def test_la_orden_es_obligatoria_en_v2_256_0_y_no_existe_en_v2_255_0(self):
        nuevo = contract.by_name(self.load(self.V2_256_0))
        anterior = contract.by_name(self.load("compat/contratos/32e4904ed6c4.json"))
        for name in self.ESCRITURAS:
            self.assertIn("user_request_quote", nuevo[name]["r"], name)
            self.assertNotIn("user_request_quote", anterior[name]["p"], name)

    def test_el_plugin_la_declara_obligatoria_y_no_la_manda_si_el_esquema_no_la_trae(self):
        need = self.load("compat/requisitos.json")["herramientas"]
        for name in self.ESCRITURAS:
            self.assertIn("user_request_quote", need[name]["obligatorios"], name)
            self.assertNotIn("user_request_quote", need[name]["usa"], name)

    def test_el_contrato_de_produccion_es_uno_de_los_guardados_y_sus_textos_estan_revisados(self):
        """Sea cual sea el despliegue que sirve producción, su contrato es uno de los
        guardados en compat/contratos/, y sus instrucciones y las definiciones de lo que
        el plugin usa están leídas contra la Skill."""
        summary = contract.validate(self.load("compat/contrato-produccion.json"))
        guardados = [
            path.name for path in sorted((self.ROOT / "compat/contratos").glob("*.json"))
            if self.load(f"compat/contratos/{path.name}") == summary
        ]
        self.assertNotEqual(guardados, [], f"el contrato {summary['huella'][:12]} de producción no está en compat/contratos/")
        comparison = contract.compare(summary, self.load("compat/requisitos.json"), current_facts=self.load("client/contract-facts.json"))
        self.assertEqual(comparison["incompatible"], [])
        self.assertEqual(comparison["revision"], [])
        self.assertFalse(comparison["derivados_cambian"])

    def test_un_rollback_a_v2_253_0_v2_254_0_o_v2_255_0_no_pide_revision(self):
        requirements = self.load("compat/requisitos.json")
        for stored in self.ANTERIORES[3:]:
            comparison = contract.compare(contract.validate(self.load(stored)), requirements)
            self.assertEqual(comparison["incompatible"] + comparison["revision"], [], stored)

    def test_la_orden_es_una_cita_y_nunca_el_destino_de_una_escritura(self):
        facts = self.load("client/contract-facts.json")
        for name in self.ESCRITURAS + ("workspace_purge", "delete_my_memories"):
            self.assertEqual(facts["citas_humanas"].get(name), "user_request_quote", name)
        self.assertNotIn("user_request_quote", facts["destinos"].values())
        self.assertNotIn("release_agent", facts["destinos"], "soltar el agente no tiene destino")
        self.assertEqual(facts["destinos"]["remember"], "body_md")
        self.assertEqual(facts["destinos"]["forget"], "memory")


class ElArranquePorPartes(unittest.TestCase):
    """Datalum v2.266.0 arranca el agente por partes y cambia el texto de `use_agent` y de
    las instrucciones, sin tocar sus argumentos. Antes, v2.265.0 retiró `open_agent_card`,
    añadió las herramientas de las propuestas de mejora y también cambió las
    instrucciones. Lo que el plugin pide vale con los dos, y sus textos están leídos."""

    ROOT = Path(__file__).resolve().parents[2]
    V2_266_0 = "compat/contratos/35bad1406854.json"
    V2_265_0 = "compat/contratos/5322933881ba.json"
    V2_259_4 = "compat/contratos/c30df6792c2d.json"
    USA = ("brain_index", "brain_read", "forget", "list_agents", "list_memories", "release_agent", "remember", "use_agent")

    def load(self, relative: str) -> dict:
        return json.loads((self.ROOT / relative).read_text(encoding="utf-8"))

    def test_un_rollback_a_v2_266_0_no_pide_revision(self):
        summary = contract.validate(self.load(self.V2_266_0))
        comparison = contract.compare(summary, self.load("compat/requisitos.json"))
        self.assertEqual(comparison["incompatible"] + comparison["revision"], [])

    def test_un_rollback_a_v2_265_0_o_a_v2_259_4_no_pide_revision(self):
        requirements = self.load("compat/requisitos.json")
        for stored in (self.V2_265_0, self.V2_259_4):
            comparison = contract.compare(contract.validate(self.load(stored)), requirements)
            self.assertEqual(comparison["incompatible"] + comparison["revision"], [], stored)

    def test_use_agent_cambia_de_texto_y_no_de_argumentos(self):
        nuevo = contract.by_name(self.load(self.V2_266_0))
        anterior = contract.by_name(self.load(self.V2_265_0))
        self.assertNotEqual(nuevo["use_agent"]["h"], anterior["use_agent"]["h"])
        for name in self.USA:
            self.assertEqual((nuevo[name]["p"], nuevo[name]["r"]), (anterior[name]["p"], anterior[name]["r"]), name)
            if name != "use_agent":
                self.assertEqual(nuevo[name]["h"], anterior[name]["h"], name)

    def test_las_instrucciones_de_v2_265_0_y_v2_266_0_estan_guardadas_y_revisadas(self):
        reviewed = self.load("compat/requisitos.json")["instrucciones_revisadas"]
        for stored in (self.V2_265_0, self.V2_266_0):
            digest = self.load(stored)["instrucciones_sha256"]
            self.assertIn(digest, reviewed, stored)
            text = (self.ROOT / "compat/instrucciones" / f"{digest[:12]}.txt").read_text(encoding="utf-8")
            self.assertEqual(contract.sha256_text(text), digest, stored)
        nuevas = (self.ROOT / "compat/instrucciones" / f"{self.load(self.V2_266_0)['instrucciones_sha256'][:12]}.txt").read_text(encoding="utf-8")
        self.assertIn("`leelo_antes_de_actuar`", nuevas)
        self.assertIn('unit:"arranque"', nuevas)

    def test_open_agent_card_salio_y_los_controles_ya_no_la_nombran(self):
        anterior = contract.by_name(self.load(self.V2_259_4))
        for stored in (self.V2_265_0, self.V2_266_0):
            names = set(contract.by_name(self.load(stored)))
            self.assertIn("open_agent_card", anterior)
            self.assertNotIn("open_agent_card", names, stored)
            self.assertTrue({"list_proposals", "set_proposal_state"} <= names, stored)
        facts = self.load("client/contract-facts.json")
        self.assertNotIn("open_agent_card", facts["destinos"])
        self.assertNotIn("open_agent_card", facts["sin_selection_context"])


class LaEntregaDespues(unittest.TestCase):
    """Producción pasó de v2.266.0 a v2.292.2 por 25 versiones sin contrato. Ninguna quita
    algo que el plugin usa: cambian las instrucciones y el texto de las ocho herramientas,
    y desde v2.289.0 todas aceptan `run_id`, opcional. v2.292.2 suma la descarga del
    conjunto. Lo que el plugin pide vale con v2.292.2 y con un rollback a v2.292.1 o
    v2.292.0, y los textos están leídos."""

    ROOT = Path(__file__).resolve().parents[2]
    V2_292_2 = "compat/contratos/6f24d473aef7.json"
    V2_292_1 = "compat/contratos/b6c40a9617a6.json"
    V2_292_0 = "compat/contratos/b8918c5e61dc.json"
    V2_266_0 = "compat/contratos/35bad1406854.json"
    USA = ElArranquePorPartes.USA

    def load(self, relative: str) -> dict:
        return json.loads((self.ROOT / relative).read_text(encoding="utf-8"))

    def test_un_rollback_a_v2_292_2_no_pide_revision(self):
        """Desde v2.301.0 un rollback a una versión con los ocho nombres de los tableros
        cambia la lista derivada: el flujo la regenera y publica un parche."""
        summary = contract.validate(self.load(self.V2_292_2))
        comparison = contract.compare(summary, self.load("compat/requisitos.json"), current_facts=self.load("client/contract-facts.json"))
        self.assertEqual(comparison["incompatible"] + comparison["revision"], [])

    def test_un_rollback_a_v2_292_1_o_a_v2_292_0_no_pide_revision(self):
        requirements = self.load("compat/requisitos.json")
        for stored in (self.V2_292_1, self.V2_292_0):
            comparison = contract.compare(contract.validate(self.load(stored)), requirements)
            self.assertEqual(comparison["incompatible"] + comparison["revision"], [], stored)

    def test_las_herramientas_que_usa_solo_suman_run_id(self):
        nuevo = contract.by_name(self.load(self.V2_292_2))
        anterior = contract.by_name(self.load(self.V2_266_0))
        for name in self.USA:
            self.assertEqual(sorted(set(nuevo[name]["p"]) - set(anterior[name]["p"])), ["run_id"], name)
            self.assertEqual(set(anterior[name]["p"]) - set(nuevo[name]["p"]), set(), name)
            self.assertEqual(nuevo[name]["r"], anterior[name]["r"], name)

    def test_las_instrucciones_nuevas_estan_guardadas_y_revisadas(self):
        reviewed = self.load("compat/requisitos.json")["instrucciones_revisadas"]
        for prefix in ("1106dd42f780", "f02ab59763ef", "6a3181a6053b"):
            text = (self.ROOT / "compat/instrucciones" / f"{prefix}.txt").read_text(encoding="utf-8")
            digest = contract.sha256_text(text)
            self.assertTrue(digest.startswith(prefix), prefix)
            self.assertIn(digest, reviewed, prefix)
        self.assertEqual(self.load(self.V2_292_2)["instrucciones_sha256"][:12], "6a3181a6053b")

    def test_la_descarga_entra_y_los_controles_la_nombran(self):
        names = set(contract.by_name(self.load(self.V2_292_2)))
        self.assertTrue({"export_dataset_csv", "complete_run", "cancel_run"} <= names)
        self.assertNotIn("export_dataset_csv", contract.by_name(self.load(self.V2_292_1)))
        facts = self.load("client/contract-facts.json")
        self.assertEqual(facts["destinos"]["export_dataset_csv"], "dataset")
        self.assertNotIn("render_chart", facts["destinos"])


class LaVersion297(unittest.TestCase):
    """Producción pasó de v2.292.2 a v2.297.0 por ocho versiones sin contrato. Ninguna
    cambia las instrucciones ni los argumentos de lo que el plugin usa. v2.293.0 suma
    `run_workflow`; v2.293.1 dice el tamaño de lo entregado en el texto de las lecturas
    de conjuntos; v2.295.0 cambia la definición de `use_agent`, que cuenta los objetos de
    cada conector, y v2.297.0 la de los tableros. Desde v2.296.1 el servidor pide la
    credencial antes del saludo, y el contrato con sesión no cambia por eso."""

    ROOT = Path(__file__).resolve().parents[2]
    VERSIONES = (
        ("v2.293.0", "f325234b96cf"),
        ("v2.293.1", "12e67bb95093"),
        ("v2.293.2", "5df1953f092a"),
        ("v2.294.0", "c5f7957224d0"),
        ("v2.295.0", "b252076b9e36"),
        ("v2.296.0", "31e5506cd27d"),
        ("v2.296.1", "cd6982d20052"),
        ("v2.297.0", "6cfe471036cc"),
    )
    USA = ElArranquePorPartes.USA

    def load(self, relative: str) -> dict:
        return json.loads((self.ROOT / relative).read_text(encoding="utf-8"))

    def stored(self, commit: str) -> dict:
        return contract.validate(self.load(f"compat/contratos/{commit}.json"))

    def test_v2_297_0_y_sus_textos_estan_revisados(self):
        summary = self.stored("6cfe471036cc")
        comparison = contract.compare(summary, self.load("compat/requisitos.json"))
        self.assertEqual(comparison["incompatible"] + comparison["revision"], [])

    def test_un_rollback_a_cualquiera_de_las_ocho_no_pide_revision(self):
        """Desde v2.301.0 el rollback a una de las ocho cambia la lista derivada, porque
        vuelven los ocho nombres de los tableros: el flujo publica un parche."""
        requirements = self.load("compat/requisitos.json")
        facts = self.load("client/contract-facts.json")
        for version, commit in self.VERSIONES:
            comparison = contract.compare(self.stored(commit), requirements, current_facts=facts)
            self.assertEqual(comparison["incompatible"] + comparison["revision"], [], version)

    def test_sin_la_lectura_de_use_agent_v2_295_0_pide_revision(self):
        """Sin la huella leída de `use_agent`, el flujo para en v2.295.0 y las siguientes."""
        old = self.load("compat/requisitos.json")
        old["definiciones_revisadas"] = {
            name: hashes[:-1] if name == "use_agent" else hashes
            for name, hashes in old["definiciones_revisadas"].items()
        }
        self.assertEqual(
            contract.compare(self.stored("b252076b9e36"), old)["revision"],
            ["la definición de `use_agent` cambió y nadie la ha leído contra la Skill"],
        )

    def test_las_instrucciones_son_las_de_v2_281_0_en_las_ocho(self):
        for version, commit in self.VERSIONES:
            self.assertEqual(self.stored(commit)["instrucciones_sha256"][:12], "6a3181a6053b", version)

    def test_las_herramientas_que_usa_no_cambian_de_argumentos(self):
        anterior = contract.by_name(self.load("compat/contratos/6f24d473aef7.json"))
        for version, commit in self.VERSIONES:
            nuevo = contract.by_name(self.stored(commit))
            for name in self.USA:
                self.assertEqual(nuevo[name]["p"], anterior[name]["p"], f"{version} {name}")
                self.assertEqual(nuevo[name]["r"], anterior[name]["r"], f"{version} {name}")

    def test_use_agent_cambia_solo_en_v2_295_0(self):
        hashes = [contract.by_name(self.stored(commit))["use_agent"]["h"] for _, commit in self.VERSIONES]
        self.assertEqual(len(set(hashes[:4])), 1)
        self.assertEqual(len(set(hashes[4:])), 1)
        self.assertNotEqual(hashes[3], hashes[4])
        self.assertIn(hashes[4], self.load("compat/requisitos.json")["definiciones_revisadas"]["use_agent"])

    def test_run_workflow_entra_en_v2_293_0(self):
        self.assertNotIn("run_workflow", contract.by_name(self.load("compat/contratos/6f24d473aef7.json")))
        for version, commit in self.VERSIONES:
            names = contract.by_name(self.stored(commit))
            self.assertIn("run_workflow", names, version)
            self.assertEqual(len(names), 100, version)

    def test_v2_296_1_sirve_el_contrato_de_v2_296_0(self):
        self.assertEqual(self.stored("cd6982d20052")["huella"], self.stored("31e5506cd27d")["huella"])


class LaVersion301(unittest.TestCase):
    """Producción pasó de v2.297.0 a v2.301.0 por seis versiones sin contrato. v2.297.1
    cambia la definición de `remember`: dice la forma de un paso hecho y acepta la que ya
    usaba. v2.301.0 es la liberación del nombre: lista `get_artifact`, `upsert_artifact`,
    `test_artifact`, `run_artifact` y `save_artifact_edit` en lugar de los ocho nombres de
    los tableros, que siguen respondiendo sin listarse, y sus instrucciones dicen
    «artefacto» donde decían «tablero». Ninguna cambia los argumentos de lo que el plugin
    usa."""

    ROOT = Path(__file__).resolve().parents[2]
    VERSIONES = (
        ("v2.297.1", "d024448ef60c"),
        ("v2.298.0", "2c35343971d5"),
        ("v2.299.0", "21ec71ec3c50"),
        ("v2.300.0", "efefe90867b9"),
        ("v2.300.1", "3f7caf7080fe"),
        ("v2.301.0", "3126db756aba"),
    )
    ARTEFACTOS = ("get_artifact", "run_artifact", "save_artifact_edit", "test_artifact", "upsert_artifact")
    TABLEROS = (
        "get_custom_dashboard", "get_dashboard", "run_dashboard", "save_dashboard_edit",
        "test_custom_dashboard", "test_dashboard", "upsert_custom_dashboard", "upsert_dashboard",
    )
    USA = ElArranquePorPartes.USA

    def load(self, relative: str) -> dict:
        return json.loads((self.ROOT / relative).read_text(encoding="utf-8"))

    def stored(self, commit: str) -> dict:
        return contract.validate(self.load(f"compat/contratos/{commit}.json"))

    def test_produccion_es_v2_301_0_y_sus_textos_estan_revisados(self):
        summary = contract.validate(self.load("compat/contrato-produccion.json"))
        self.assertEqual(summary, self.stored("3126db756aba"))
        comparison = contract.compare(summary, self.load("compat/requisitos.json"), current_facts=self.load("client/contract-facts.json"))
        self.assertEqual(comparison["incompatible"] + comparison["revision"], [])
        self.assertFalse(comparison["derivados_cambian"])

    def test_un_rollback_a_cualquiera_de_las_seis_no_pide_revision(self):
        requirements = self.load("compat/requisitos.json")
        for version, commit in self.VERSIONES:
            comparison = contract.compare(self.stored(commit), requirements)
            self.assertEqual(comparison["incompatible"] + comparison["revision"], [], version)

    def test_la_lista_nombra_las_cinco_de_artefactos_y_no_las_ocho_de_antes(self):
        names = set(contract.by_name(self.stored("3126db756aba")))
        self.assertTrue(set(self.ARTEFACTOS) <= names)
        self.assertEqual(sorted(set(self.TABLEROS) & names), [])
        before = set(contract.by_name(self.stored("3f7caf7080fe")))
        self.assertTrue(set(self.TABLEROS) <= before)
        destinos = self.load("client/contract-facts.json")["destinos"]
        for name in self.ARTEFACTOS:
            self.assertIn(name, destinos)
        for name in self.TABLEROS:
            self.assertNotIn(name, destinos)

    def test_las_instrucciones_nuevas_estan_guardadas_y_revisadas(self):
        reviewed = self.load("compat/requisitos.json")["instrucciones_revisadas"]
        text = (self.ROOT / "compat/instrucciones/20fb1c516393.txt").read_text(encoding="utf-8")
        digest = contract.sha256_text(text)
        self.assertTrue(digest.startswith("20fb1c516393"))
        self.assertIn(digest, reviewed)
        self.assertEqual(self.stored("3126db756aba")["instrucciones_sha256"], digest)
        for version, commit in self.VERSIONES[:-1]:
            self.assertEqual(self.stored(commit)["instrucciones_sha256"][:12], "6a3181a6053b", version)

    def test_sin_la_lectura_de_remember_v2_297_1_pide_revision(self):
        """Sin la huella leída de `remember`, el flujo para en v2.297.1 y las siguientes."""
        old = self.load("compat/requisitos.json")
        old["definiciones_revisadas"] = {
            name: hashes[:-1] if name == "remember" else hashes
            for name, hashes in old["definiciones_revisadas"].items()
        }
        self.assertEqual(
            contract.compare(self.stored("d024448ef60c"), old)["revision"],
            ["la definición de `remember` cambió y nadie la ha leído contra la Skill"],
        )

    def test_las_herramientas_que_usa_no_cambian_de_argumentos(self):
        anterior = contract.by_name(self.stored("6cfe471036cc"))
        for version, commit in self.VERSIONES:
            nuevo = contract.by_name(self.stored(commit))
            for name in self.USA:
                self.assertEqual(nuevo[name]["p"], anterior[name]["p"], f"{version} {name}")
                self.assertEqual(nuevo[name]["r"], anterior[name]["r"], f"{version} {name}")


class LaVersion304(unittest.TestCase):
    """Producción pasó de v2.301.0 a v2.304.0 por cuatro versiones sin contrato. v2.302.0
    pone tope al cuerpo de `remember` (4 000 caracteres con la cabecera). v2.303.1 suma
    `get_artifact_kit`, el contrato de la página de un Sites. v2.304.0 escribe un Sites en
    su borrador por tramos (`template_offset`) y por reemplazos (`edits`), los dos sin
    `confirm`, y lo guarda en una versión con `if_match`. Ninguna cambia los argumentos de
    lo que el plugin usa ni sus instrucciones."""

    ROOT = Path(__file__).resolve().parents[2]
    VERSIONES = (
        ("v2.302.0", "70300e3fd347"),
        ("v2.303.1", "f0ebf75fe62c"),
        ("v2.303.2", "737c8a45acbb"),
        ("v2.304.0", "dee23b3fe544"),
    )
    USA = ElArranquePorPartes.USA

    def load(self, relative: str) -> dict:
        return json.loads((self.ROOT / relative).read_text(encoding="utf-8"))

    def stored(self, commit: str) -> dict:
        return contract.validate(self.load(f"compat/contratos/{commit}.json"))

    def test_produccion_es_v2_304_0_y_sus_textos_estan_revisados(self):
        summary = contract.validate(self.load("compat/contrato-produccion.json"))
        self.assertEqual(summary, self.stored("dee23b3fe544"))
        comparison = contract.compare(summary, self.load("compat/requisitos.json"), current_facts=self.load("client/contract-facts.json"))
        self.assertEqual(comparison["incompatible"] + comparison["revision"], [])
        self.assertFalse(comparison["derivados_cambian"])

    def test_un_rollback_a_cualquiera_de_las_cuatro_no_pide_revision(self):
        requirements = self.load("compat/requisitos.json")
        for version, commit in self.VERSIONES:
            comparison = contract.compare(self.stored(commit), requirements)
            self.assertEqual(comparison["incompatible"] + comparison["revision"], [], version)

    def test_sin_la_lectura_de_remember_v2_302_0_pide_revision(self):
        """Sin la huella leída de `remember` de v2.302.0, el flujo para en las cuatro."""
        nueva = contract.by_name(self.stored("70300e3fd347"))["remember"]["h"]
        old = self.load("compat/requisitos.json")
        self.assertIn(nueva, old["definiciones_revisadas"]["remember"])
        old["definiciones_revisadas"]["remember"] = [h for h in old["definiciones_revisadas"]["remember"] if h != nueva]
        for version, commit in self.VERSIONES:
            self.assertEqual(
                contract.compare(self.stored(commit), old)["revision"],
                ["la definición de `remember` cambió y nadie la ha leído contra la Skill"],
                version,
            )

    def test_get_artifact_kit_entra_en_v2_303_1(self):
        self.assertNotIn("get_artifact_kit", contract.by_name(self.stored("70300e3fd347")))
        for version, commit in self.VERSIONES[1:]:
            names = contract.by_name(self.stored(commit))
            self.assertIn("get_artifact_kit", names, version)
            self.assertEqual(len(names), 98, version)

    def test_v2_304_0_escribe_el_sites_por_tramos_y_reemplazos(self):
        names = contract.by_name(self.stored("dee23b3fe544"))
        self.assertTrue({"template_offset", "edits", "if_match"} <= set(names["upsert_artifact"]["p"]))
        self.assertIn("if_match", names["save_artifact_edit"]["p"])
        antes = contract.by_name(self.stored("737c8a45acbb"))
        self.assertNotIn("edits", antes["upsert_artifact"]["p"])
        self.assertNotIn("if_match", antes["save_artifact_edit"]["p"])

    def test_las_instrucciones_son_las_de_v2_301_0_en_las_cuatro(self):
        for version, commit in self.VERSIONES:
            self.assertEqual(self.stored(commit)["instrucciones_sha256"][:12], "20fb1c516393", version)

    def test_las_herramientas_que_usa_no_cambian_de_argumentos(self):
        anterior = contract.by_name(self.stored("3126db756aba"))
        for version, commit in self.VERSIONES:
            nuevo = contract.by_name(self.stored(commit))
            for name in self.USA:
                self.assertEqual(nuevo[name]["p"], anterior[name]["p"], f"{version} {name}")
                self.assertEqual(nuevo[name]["r"], anterior[name]["r"], f"{version} {name}")


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
