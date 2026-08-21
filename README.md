# Reddit Ads Insights MCP

**Read-only, analysis-first [MCP](https://modelcontextprotocol.io) server for the Reddit Ads API v3.**
Ask your AI assistant about your Reddit Ads performance — campaigns, subreddit-level
breakdowns, reports, targeting — with a server that *cannot* modify anything.

Works with **any MCP client**: Claude, ChatGPT, Cursor, VS Code, Windsurf,
Gemini CLI, and anything else that speaks MCP — see
[docs/CONNECT.md](docs/CONNECT.md). Host it anywhere a container runs; a
step-by-step free-tier Google Cloud Run guide is included.

> **Unofficial community project.** Not affiliated with, endorsed, certified, or
> supported by Reddit, Inc. "Reddit" is a trademark of Reddit, Inc. You are
> responsible for your own compliance with Reddit's
> [Ads API Terms](https://ads-api.reddit.com/docs/v3/) and Developer Terms.

## Why this exists

- **Permanently read-only.** Requests only the `adsread` OAuth scope, and every
  outgoing API call must match a version-controlled allowlist of read
  operations (all 99 spec operations are explicitly classified; CI fails if a
  write becomes reachable). There is no write mode to misconfigure.
- **Single advertiser per deployment.** You deploy it in *your own* Google
  Cloud project (or run it locally); your credentials never touch anyone
  else's infrastructure. A mandatory account allowlist blocks cross-account
  access.
- **Built for analysis.** Flexible reports across ~450 metrics with up to 3
  breakdown dimensions (COMMUNITY — i.e. subreddit — DATE, HOUR, COUNTRY,
  PLACEMENT, KEYWORD, and more), plus safety ceilings so an AI client loop
  can't burn your rate limits or your wallet.
- **Personal-use cost profile.** Scale-to-zero Cloud Run, max 1 instance;
  normal personal use lands at ~$0/month.

## Tools (15)

**Structure**: `list_ad_accounts` · `list_campaigns` · `list_ad_groups` ·
`list_ads`

**Reporting**: `get_report` · `get_daily_performance`

**Analysis**: `compare_periods` · `rank_performance` · `analyze_trends` ·
`analyze_pacing` · `analyze_conversions` · `analyze_video` ·
`analyze_creatives` · `get_creative_context` · `get_account_history`

Resources: `reddit-ads://report-fields`, `reddit-ads://capabilities`.
Phase 3 (diagnostics + targeting intelligence) is planned — see `PLAN.md`;
live-API quirks are documented in `docs/API_NOTES.md`.

## Setup overview

1. **Create a Reddit Ads developer application** — in
   [Reddit Ads Manager](https://ads.reddit.com), open your business settings →
   **Developer Applications** → create an app. Note the **client ID** and
   **secret**.
2. **Authorize with `adsread` only** and obtain a **refresh token** (see
   [docs/AUTHENTICATION.md](docs/AUTHENTICATION.md)). The server refuses to
   run with a write-capable grant.
3. **Find your ad account ID** (`a2_…`) in the Ads Manager account switcher.
4. **Run it** (either way):
   - **Locally (stdio)** for desktop MCP clients:

     ```bash
     pip install .
     cp .env.example .env   # fill in values, then source it
     reddit-ads-mcp
     ```

   - **Hosted** — any container platform works (the image is a plain
     Dockerfile). A complete free-tier walkthrough for **Google Cloud Run**
     is in [docs/DEPLOY_GCP.md](docs/DEPLOY_GCP.md) (~15 min); the same
     env-var contract applies on Fly.io, Railway, Render, or your own VPS.
     Hosted mode is required for chat apps like claude.ai and ChatGPT, which
     can't run local servers.

5. **Connect your AI tool** — per-client instructions for Claude, ChatGPT,
   Cursor, VS Code, Gemini CLI, and generic MCP clients:
   [docs/CONNECT.md](docs/CONNECT.md).

## Remote authentication (pick exactly one)

| Mode | Use when | How |
|---|---|---|
| `bearer` (default) | Your MCP client can send headers (Claude Code, Cursor, VS Code, Gemini CLI) | `Authorization: Bearer <MCP_ACCESS_TOKEN>` on `/mcp` |
| `secret_path` | Client only accepts a URL (claude.ai and ChatGPT custom connectors) | Endpoint served at `/<MCP_PATH_SECRET>/mcp`; `/mcp` returns 404 |

Secret-path mode treats the URL as the credential: it can appear in client
settings, browser history, and infrastructure logs. Generate it with
`python3 -c "import secrets; print(secrets.token_urlsafe(32))"`, rotate it
periodically, and prefer bearer mode when possible.

## Safety & privacy properties

- Only `adsread`; startup fails if the token grant includes write scopes.
- Exact-match operation allowlist; pagination URLs are validated (HTTPS, host,
  path family) before being followed.
- Mandatory `ALLOWED_ACCOUNT_IDS`; every tool call re-checks the account.
- Rate/loop safeguards: 60 tool calls per rolling hour, 20 upstream requests
  per call, duplicate-call suppression, 90-day report ceiling, bounded rows,
  pages, and response size.
- No database, no persistent cache, no payload logging. Report rows and
  entity names never appear in logs.

**Data disclosure note:** this server returns your advertising metrics to the
MCP client you connect — typically a hosted AI assistant. Review your AI
provider's data handling and your own obligations under Reddit's terms before
connecting a production account. Do not share one deployment across unrelated
advertisers, and do not use returned data to train models without the
necessary permissions.

## Development

```bash
pip install -e ".[dev]"
python3 -m unittest discover tests      # or: pytest
python3 scripts/check_openapi_drift.py  # spec/registry drift gate
```

The pinned OpenAPI spec lives in `openapi/` with its checksum. Any spec update
requires reclassifying changed operations and regenerating the registry in the
same commit — CI enforces this.

## Acknowledgments

No code was reused from other projects, but this server stands on prior art
worth crediting:

- [mkerchenski/RedditAdsMcp](https://github.com/mkerchenski/RedditAdsMcp)
  (C#, MIT) and [sbmeaper/reddit-ad-mcp](https://github.com/sbmeaper/reddit-ad-mcp)
  (Python) — the first open-source Reddit Ads MCP servers; their setup flows
  informed our authentication documentation.
- Public field references from Supermetrics and Adzviser helped map the
  reporting surface before the official OpenAPI spec settled every enum
  (the live API disagreed with third-party docs in places — see
  [docs/API_NOTES.md](docs/API_NOTES.md)).
- Built with the official
  [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk).

## Dependencies

Three direct runtime dependencies, declared in `pyproject.toml`:
`mcp` (pinned `>=1.9,<2`; SDK 2.0 is API-incompatible), `httpx`, and
`pydantic`. A committed `uv.lock` pins the full transitive tree for
reproducible builds; Dependabot proposes version updates weekly. The small
footprint is deliberate — this server handles ad-account credentials, so
every dependency is attack surface.

## License

MIT — see [LICENSE](LICENSE).
