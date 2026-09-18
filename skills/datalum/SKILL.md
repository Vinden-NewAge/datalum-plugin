---
name: datalum
description: >-
  Company data in Datalum through the agent the user was granted: metrics,
  datasets, charts, dashboards and the model. Use whenever the user mentions
  Datalum, or asks for data that lives there while the `datalum` MCP server is
  connected: indicadores, conjuntos de datos, gráficas, tableros, an agent's
  brain (cerebro) or memory, or drafting a new metric, chart, dashboard or
  agent. Covers the start sequence (list_agents, the user picks, use_agent,
  selection_context on every call), the preview-then-confirm rule for changes,
  and which Datalum tool answers each request.
compatibility: >-
  Needs the Datalum connector (remote MCP server at
  https://mcp.datahub.vinden.cc/mcp) and a Datalum account with at least one
  agent granted by the company's administrator.
metadata:
  author: Vinden
  short-description: AI CONTEXT PILL
  version: "1.0.0"
---

# Datalum

Datalum is a governed data layer. Every connection works through one **agent** that the
company's administrator granted to the person. The agent decides which data sources
(connectors) and which actions are available; the Datalum tools refuse anything outside
it. Reads run right away. Changes start as previews, drafts or proposals, and nothing
goes live until the person says yes.

Tool descriptions and responses are in Spanish. Reply to the person in their own
language and in business terms.

## Datalum's rules govern

For anything about Datalum, Datalum itself decides, in this order:

1. The instructions the Datalum server sends when the connection opens.
2. The context of the agent chosen with `use_agent`: its mission, rules, superpowers
   and documents.
3. The description and input schema of each tool.

This skill only helps you apply them. If it disagrees with any of them, follow Datalum
and tell the person about the difference. They also come before general knowledge:

- Business figures come only from Datalum results. Do not estimate, complete or
  recalculate a figure and present it as Datalum's. If the person asks for a
  calculation Datalum did not return, say that it is your own.
- When you give a figure, name the metric, chart or dataset and the period, as Datalum
  returned them.
- Definitions come from the published model and the agent's brain: what a metric
  means, which data it uses, how a period is cut. Do not replace them with general
  definitions.
- A refusal from Datalum stands. Do not look for another tool or route to the same
  result.
- The agent version chosen at the start of the conversation is the one that counts
  until the person asks to switch agents or to reload it.

The person decides what to do. Datalum decides how its data is read and changed.

## If the Datalum tools are missing

If no Datalum tool is available in this conversation, the connector is missing or
turned off. Tell the person to add or enable the Datalum connector with the address
`https://mcp.datahub.vinden.cc/mcp` and to sign in with their Datalum account. The
installation guide for each product is at
https://github.com/Vinden-NewAge/datalum-plugin/blob/main/INSTALAR.md. Do not answer
Datalum questions from any other source in the meantime.

## Start of every conversation

No Datalum tool returns content until an agent is chosen. Do these steps in order,
one at a time:

1. Call `list_agents`. It returns the person's keyring (*llavero*): the agents they
   can use.
   - Several agents: show them and ask which one to use. Do not choose for the person.
   - Exactly one: say which one it is and use it.
   - None: tell the person to ask their Datalum administrator for access, and stop.
2. Call `use_agent` with `agent` set to the chosen agent and `user_choice_quote` set to
   the person's own words choosing it, copied exactly. Never write that quote yourself.
3. Tell the person which agent is active, as the response gives it:
   "operando como <agent> v<N>".
4. Keep the `selection_context` from the response. Send it, under that same name, in
   every later Datalum call. All tools accept it except `list_agents` and
   `brain_import`. It keeps this conversation tied to its agent even when the
   connection does not carry a session header between calls.
5. Read the rest of the `use_agent` response before doing anything else:
   - `mission` and `index`: what the agent is for, its superpowers (*superpoderes*)
     and its documents. Open any of them with `brain_read`, copying `concept_id`
     exactly as it appears.
   - `connectors`: the data sources this agent reaches. Each one carries the `tenant`
     value that most tools require. Take `tenant` from here; do not guess it.
   - `expires_at`: when the choice expires from inactivity.
   - `news` and `memory`: recent changes to the agent and what it remembers about
     this person.

Later in the conversation:

- To use a different agent, call `release_agent`, then `use_agent` with the new one.
  `use_agent` on another agent while one is active is rejected.
- To pick up the latest version of the same agent, call `use_agent` again with it.
  The response comes back with `resealed: true`.
- If a tool answers "elige agente primero" (choose an agent first), the choice expired
  or `selection_context` was missing. Go back to step 1.

## How to call the tools

- **Copy argument names from each tool's input schema.** The catalog mixes
  `snake_case` and `camelCase`, sometimes between neighbouring tools: `propose_agent`
  takes `proposals_enabled`, `edit_draft_agent` takes `proposalsEnabled`, and
  `use_agent` takes `agent`, not `agentId`. The server ignores unknown arguments
  without an error, so a misspelled name silently changes what the call does.
- **Many descriptions say whether the tool reads or writes.** They start with `[Lee]`
  (read) or `[Escribe]` (write). The tables below cover the tools without that label.
- **Never invent tables, columns, metrics or dimensions.** Look them up first with
  `get_model`, `search_model` or `brain_search`.
- **Send writes one at a time, never in parallel.** On `rate_limited`, HTTP 429 or
  "temporarily limiting", the write was not applied: wait for `retry_after`, then retry
  with backoff (2 s, 4 s, 8 s). On `partial_write`, repeat the same call (it completes
  what is missing) and check the result with the matching `get_*` tool.
- **"No existe ese recurso"** (not found) means the object is outside this agent's
  reach. Tell the person. Do not try other tools to get around it.

## Changes need the person's yes

Most tools that change the catalog take a `confirm` argument.

1. Call the tool without `confirm`. It returns a preview and changes nothing.
2. Show the person what would change, in plain words.
3. Call again with `confirm: true` only after the person agrees in this conversation.
   One yes covers one call.

Some steps never happen from here:

- Activating a dataset happens only in the Datalum panel. `request_dataset_activation`
  files the request; it does not activate.
- A relation cannot be marked as confirmed from here.
- New metrics and dimensions are born as proposals, and agents are born as drafts.
  People review them in the panel.

Tools that delete or cut off other people need the person's explicit request, and some
take the person's words verbatim:

| Tool | Effect | Required |
|---|---|---|
| `delete_my_memories` | Permanently erases all of this person's memories with the agent | `confirm: true` and `user_request_quote` with the person's exact words |
| `workspace_purge` | Permanently empties the workspace trash | `frase` with the person's exact order |
| `start_agent_edit` | Takes a live agent out of service and disconnects whoever is using it | Preview without `confirm` first; show who gets disconnected |
| `apply_update` | Applies a new solution version; can disconnect agents | Preview without `confirm` first |
| `workspace_restore` | Returns the workspace schema and data to a restore point | The person asked for that restore point |

## Which tool for which request

The agent's family limits what it can do. **Creative** agents (*creativos*) can read the
physical schema and author catalog objects. **Institutional** agents (*institucionales*)
consume what is published and can file proposals. A tool outside the family answers
"not found".

### Reading the published model

| The person wants | Tool |
|---|---|
| An overview of the model: what exists and the rules | `get_model` |
| To find a metric, dimension or chart by meaning | `search_model` (returns names), then `brain_read` |
| To browse or open the agent's brain documents | `brain_index`, `brain_read`, `brain_search`, `brain_manifest` |
| The whole model as markdown | `export_brain` |
| One chart or dashboard definition | `get_chart`, `get_dashboard` |
| Saved filter sets (creative agents) | `list_filter_sets`, `get_filter_set` |
| A snapshot of connectors, tables, metrics and relations | `get_catalog_state` |

### Getting numbers

| The person wants | Tool |
|---|---|
| A metric value, by period or broken down | `run_metric` (one metric or several with the same cut; the server writes the SQL) |
| Detail rows from a governed dataset | `run_dataset` |
| The values a dimension can take, e.g. before filtering | `list_dimension_values` |
| A chart | `render_chart` (image plus a JSON summary; if images do not display, report the figures from the summary) |
| A chart's rows as a file | `export_chart_csv` (signed link that expires) |
| A whole dashboard | `run_dashboard` |

Prefer `run_metric` over raw SQL whenever an official metric exists: it applies the
company's definition and the data masking rules.

### Physical data (creative agents)

| The person wants | Tool |
|---|---|
| The tables in a data source | `list_tables` (use `prefix`, `page_size` and `compact` on large catalogs) |
| A table's columns | `describe_table` |
| Per-column statistics | `profile_table` |
| A read-only query | `run_query` (`SELECT`, `WITH`, `SHOW`, `DESCRIBE`, `EXPLAIN` only) |
| The SQL behind an earlier result | `get_execution_sql` with its `execution_ref` |
| Their own recent failed calls or curations | `list_my_attempts`, `list_my_curations` |

### Authoring (creative agents, always preview first)

| The person wants to | Tools, in order |
|---|---|
| Document tables and columns | `curate_table` |
| Describe a connector or link two connectors | `describe_connector`, `set_connector_links` |
| Define joins | `set_relations` |
| Create or change a metric | `upsert_metric`, then `test_metric` |
| Create or change a dimension | `upsert_dimension`, then `test_dimension` |
| Create a dataset | `upsert_dataset`, `describe_dataset_fields`, then `request_dataset_activation` |
| Create or change a chart | `upsert_chart`, `set_chart_options`, `test_chart`; seal an edit with `save_chart_edit` |
| Create or change a dashboard | `upsert_dashboard`, `test_dashboard`; seal an edit with `save_dashboard_edit` |
| Create a filter set | `upsert_filter_set`, then `test_filter_set` |
| Build a coded (HTML) dashboard | `upsert_custom_dashboard`, then `test_custom_dashboard` |
| Apply several catalog changes together | `apply_batch` (all or nothing) |
| Put tested charts, a dashboard and metrics live | `publish_bundle` (preview lists anything blocked) |
| Use a template | `list_templates`, `compare_template`, then `propose_install` |

### Proposals and memory

| The person wants to | Tool |
|---|---|
| Report a need or problem to the agent's owners (institutional agents with proposals on) | `submit_proposal`; follow up with `list_my_proposals` |
| Have the agent remember something | `remember` (`scope: compartida` turns it into a proposal) |
| See or drop what the agent remembers | `list_memories`, `forget` |
| Save a memory or a draft agent through the knowledge-package path | `brain_write` |
| Check an external knowledge package before importing it | `brain_import` (validates only; creates nothing) |

### Agents and solutions (creative agents with the agent factory)

| The person wants to | Tools |
|---|---|
| See every agent in the company | `list_organization_agents` |
| Propose a new agent or copy a template | `propose_agent`, `clone_agent` (both create drafts) |
| Adjust a draft | `edit_draft_agent`, `attach_draft_document`, `detach_draft_document`, `reorder_draft_documents`, `port_draft_connector`, `unport_draft_connector` |
| Edit a live agent | `start_agent_edit`, then `list_agent_documents`, `read_library_document`, `write_agent_document`, `add_agent_document`, `attach_agent_document`, `detach_agent_document`, `reorder_agent_documents`, `toggle_agent_document`, `edit_agent_ficha`, and `finish_agent_edit` to put it back in service |
| Install or update a solution | `list_solutions`, `install_solution`, `apply_update` |

The agent in use cannot edit itself. A library document can belong to several agents:
`write_agent_document` changes it for all of them, so say so before calling it.

### The company's workspace (its own writable tables)

| The person wants to | Tool |
|---|---|
| See the tables | `workspace_schema` |
| Query them | `workspace_query` |
| Insert, update or delete rows | `workspace_write` (applies directly; confirm with the person first) |
| Change the structure | `workspace_migrate` (named change, recorded with its author) |
| Undo | `workspace_undo` to list restore points and trash, then `workspace_restore` or `workspace_undelete` |
| Empty the trash for good | `workspace_purge` |

What each person can do here depends on the level their agent grants: read, write or
administer. Changing the structure, restoring and emptying the trash also need a
creative agent.
