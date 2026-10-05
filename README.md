# Datalum plugin

Connects AI assistants to [Datalum](https://datalum.ai), a governed data layer. A person
connects their Datalum account, chooses the agent their company's administrator granted
them and asks for the work. The assistant loads that agent's brain from Datalum each
time and follows it: its procedures, its limits, its output formats and its rules for
memory.

The plugin connects the person, prepares the session, recovers context and sends each
request to the agent's procedure. Business rules and the tool catalog stay with Datalum,
which validates every call it receives.

One repository serves every supported product:

| Product | What it uses |
|---|---|
| Claude Code | The plugin: `.claude-plugin/`, `.mcp.json`, `skills/datalum/`, `hooks/` and `client/` |
| Grok Build | The same plugin, read from `.claude-plugin/plugin.json` |
| Claude (web and desktop) | The skill as a zip, plus the Datalum custom connector |
| ChatGPT | The skill as a zip (with `agents/openai.yaml`), plus the Datalum connector |

Installation steps for customers, in Spanish: [INSTALAR.md](INSTALAR.md).

## Components

- `.mcp.json`: the hosted Datalum MCP server (streamable HTTP).
- `skills/datalum/SKILL.md`: how to connect, choose the agent, load its brain, keep the
  conversation on it and use memory by the agent's own rules. The same skill for every
  product.
- `skills/datalum/agents/openai.yaml`: display name, icon and connector dependency for
  ChatGPT.
- `hooks/hooks.json` and `client/`: checks that run on the person's machine in products
  that load plugin hooks. They only act on Datalum tools. They need Node 18 or later; if
  Node is missing the plugin works without them. What each check does and where it
  runs: [CONTROLES.md](CONTROLES.md) (Spanish).

The checks use no network and install nothing. `scripts/`, `tests/`, `evals/` and
`compat/` are for maintaining this repository and are not part of the skill package.

The plugin brings the connection and the generic skill. It does not install an agent's
delivery resources, such as `datalum-entregables` or the Builder's output format: the
agent's brain names them and says how to get them.

## Install

Claude Code:

```
/plugin marketplace add Vinden-NewAge/datalum-plugin
/plugin install datalum@datalum
```

Grok Build: once Datalum is listed in the Grok Build marketplace, open `/marketplace`,
search for **Datalum**, and install. To try it from a local checkout:

```bash
grok --plugin-dir /absolute/path/to/datalum-plugin
```

Claude (web and desktop) and ChatGPT: download
[datalum-skill.zip](https://github.com/Vinden-NewAge/datalum-plugin/releases/latest/download/datalum-skill.zip),
upload it as a skill, and add `https://mcp.datahub.vinden.cc/mcp` as a custom connector.

## Authentication

On first use the assistant opens the Datalum sign-in page in the browser. Sign in with a
Datalum account and approve the connection. Do not paste an API key or a token into the
chat.

Authentication is OAuth 2.1 with dynamic client registration and PKCE (S256). The client
is public (no secret).

## Network endpoints

| Endpoint | Purpose |
|---|---|
| `https://mcp.datahub.vinden.cc/mcp` | Hosted MCP server (streamable HTTP) |
| `https://mcp.datahub.vinden.cc/.well-known/oauth-protected-resource` | OAuth protected resource metadata (RFC 9728) |
| `https://api.datahub.vinden.cc/admin-api/oauth/register` | Dynamic client registration |
| `https://api.datahub.vinden.cc/admin-api/oauth/authorize` | Authorization |
| `https://api.datahub.vinden.cc/admin-api/oauth/token` | Token exchange and refresh |
| `https://datahub.vinden.cc` | Datalum panel: sign-in, consent, and approval of proposals |

The plugin calls no other host.

## Credentials and permissions

- A Datalum account in a company that uses Datalum.
- At least one active agent granted to that account by the company's administrator.
  Installing the plugin creates no accounts, companies or grants.
- The token only reaches what the chosen agent allows. Activating anything, approving a
  pending change and saving a version of an agent happen in the Datalum panel, by a
  person.

## Versions and updates

Every release is listed in [CHANGELOG.md](CHANGELOG.md) (in Spanish) and published under
[Releases](https://github.com/Vinden-NewAge/datalum-plugin/releases) with the skill zip.

After each Datalum deployment to production, a workflow in this repository checks the
plugin against the contract that deployment serves, publishes a patch version when a
compatible change needs one, and records the result in `compat/registro.jsonl`. How it
works, what it needs and how to recover from a failure: [MANTENER.md](MANTENER.md). How
each product receives a new version: [ACTUALIZAR.md](ACTUALIZAR.md). What has been
checked against what: [COMPATIBILIDAD.md](COMPATIBILIDAD.md).

## License

Proprietary. Use of the hosted service is governed by Datalum's
[terms](https://datalum.ai/terminos) and [privacy notice](https://datalum.ai/privacidad).
