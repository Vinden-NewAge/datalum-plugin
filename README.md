# Datalum plugin

Connects AI assistants to [Datalum](https://datalum.ai), a governed data layer. The
assistant works through an agent that the company's administrator granted to the
person, and that agent decides which data and which actions are available. The
assistant reads and runs what is published right away. Changes to the governed catalog
need the person's approval, and many start as previews, drafts or proposals. Activating
a dataset happens only in the Datalum panel.

One repository serves every supported product:

| Product | What it uses |
|---|---|
| Grok Build | The plugin: `.claude-plugin/plugin.json`, `.mcp.json` and `skills/datalum/` |
| Claude Code | The same plugin, through `.claude-plugin/marketplace.json` |
| Claude (web and desktop) | The skill as a zip, plus the Datalum custom connector |
| ChatGPT | The skill as a zip (with `agents/openai.yaml`), plus the Datalum connector |

The plugin has no hooks, no commands, no local executables and no dependencies. The
`scripts/` folder only checks and packages this repository.

Installation steps for customers, in Spanish: [INSTALAR.md](INSTALAR.md).

## Components

- `.mcp.json`: the hosted Datalum MCP server (streamable HTTP).
- `skills/datalum/SKILL.md`: when and how to call the Datalum tools. The same skill for
  every product.
- `skills/datalum/agents/openai.yaml`: display name, icon and connector dependency for
  ChatGPT.

## Install

Grok Build: once Datalum is listed in the Grok Build marketplace, open `/marketplace`,
search for **Datalum**, and install. To try it from a local checkout:

```bash
grok --plugin-dir /absolute/path/to/datalum-plugin
```

Claude Code:

```
/plugin marketplace add Vinden-NewAge/datalum-plugin
/plugin install datalum@datalum
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
- At least one agent granted to that account by the company's administrator. With no
  agent granted, the tools answer that access has to be requested.
- The token only reaches what the chosen agent allows. Catalog changes need the person's
  confirmation, and some of them (activating a dataset, confirming a relation) only happen
  in the Datalum panel.

## Versions

Every release is listed in [CHANGELOG.md](CHANGELOG.md) (in Spanish) and published under
[Releases](https://github.com/Vinden-NewAge/datalum-plugin/releases) with the skill zip.
How releases are made: [MANTENER.md](MANTENER.md).

## License

Proprietary. Use of the hosted service is governed by Datalum's
[terms](https://datalum.ai/terminos) and [privacy notice](https://datalum.ai/privacidad).
