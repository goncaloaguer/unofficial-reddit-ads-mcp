# Reddit Ads MCP (Unofficial + Read-Only)

**Read-only, analysis-first [MCP](https://modelcontextprotocol.io) server for the Reddit Ads API v3.**
Ask your AI assistant about your Reddit Ads performance — campaigns, subreddit-level
breakdowns, reports, targeting — with a server that *cannot* modify anything.

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

## Getting started — pick your path

### 🟢 Path A: "I've never installed an MCP server or used Google Cloud"

Follow **[docs/BEGINNER_GUIDE.md](docs/BEGINNER_GUIDE.md)** — a complete,
copy-paste walkthrough from zero to asking Claude about your ads (~40 min,
~$0/month). It assumes nothing and explains what you should see at every step.

### 🔵 Path B: Advanced (you know your way around a terminal)

1. **Reddit credentials** (~10 min): create a developer app in Reddit Ads
   Manager (**Developer Applications**, redirect URI
   `http://localhost:8912/callback`), authorize with `scope=adsread`
   + `duration=permanent`, exchange the code for a refresh token —
   condensed steps in [docs/AUTHENTICATION.md](docs/AUTHENTICATION.md).
   Grab your `a2_…` ad account ID from the Ads Manager account switcher.
2. **Deploy to your own Cloud Run** (~15 min): follow
   [docs/DEPLOY_GCP.md](docs/DEPLOY_GCP.md) — Secret Manager for the four
   secrets, dedicated least-privilege service account,
   `gcloud builds submit` + `gcloud run deploy` with the personal-use cost
   profile (scale-to-zero, max 1 instance), and a billing alert.
3. **Or run locally over stdio** (no cloud at all):

   ```bash
   pip install .
   ```

   Claude Code / Claude Desktop config:

   ```json
   "reddit-ads": {
     "type": "stdio",
     "command": "reddit-ads-mcp",
     "env": {
       "REDDIT_CLIENT_ID": "…",
       "REDDIT_CLIENT_SECRET": "…",
       "REDDIT_REFRESH_TOKEN": "…",
       "REDDIT_USER_AGENT": "desktop:unofficial-reddit-ads-mcp:0.2.1 (by /u/you)",
       "ALLOWED_ACCOUNT_IDS": "a2_youraccount"
     }
   }
   ```

4. **Connect**: claude.ai custom connector (secret-path mode URL) or any
   header-capable MCP client (bearer mode). Details below.

Before you rely on the numbers, read [docs/API_NOTES.md](docs/API_NOTES.md) —
the live API differs from its own spec in ways that matter (unit scaling,
keyword-report lookback, pagination semantics). This server compensates for
all of them, with formulas returned alongside every derived value.

## Remote authentication (pick exactly one)

| Mode | Use when | How |
|---|---|---|
| `bearer` (default) | Your MCP client can send headers (Claude Code, API) | `Authorization: Bearer <MCP_ACCESS_TOKEN>` on `/mcp` |
| `secret_path` | Client cannot send custom headers (claude.ai custom connectors) | Endpoint served at `/<MCP_PATH_SECRET>/mcp`; `/mcp` returns 404 |

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

## License

MIT — see [LICENSE](LICENSE).
