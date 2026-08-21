# Connecting your AI tool

This server speaks standard [MCP](https://modelcontextprotocol.io) (streamable
HTTP for hosted deployments, stdio for local), so it works with **any MCP
client**: Claude, ChatGPT, Cursor, VS Code, Windsurf, Gemini CLI, and others.

You need two things from your deployment (see `DEPLOY_GCP.md`):

- **Your server URL** — `https://<your-service-url>`
- **One credential**, depending on the auth mode you deployed with:
  - `secret_path` mode → your endpoint is `https://<service>/<PATH_SECRET>/mcp`
    (the URL itself is the credential — treat it like a password)
  - `bearer` mode → your endpoint is `https://<service>/mcp` plus an
    `Authorization: Bearer <token>` header

**Which mode do I need?** If your client lets you set custom HTTP headers, use
`bearer`. If it only accepts a URL (most chat apps), use `secret_path`.

| Client | Header support | Use mode |
|---|---|---|
| Claude (web/desktop custom connector) | no | `secret_path` |
| ChatGPT (custom connector) | no | `secret_path` |
| Claude Code | yes | `bearer` (or `secret_path`) |
| Cursor | yes | `bearer` (or `secret_path`) |
| VS Code (Copilot MCP) | yes | `bearer` (or `secret_path`) |
| Gemini CLI | yes | `bearer` (or `secret_path`) |
| Local stdio (any desktop client) | n/a | none (runs on your machine) |

---

## Claude (claude.ai web / desktop)

1. Settings → **Connectors** → **Add custom connector**
2. Name it (e.g. `Reddit Ads`), paste your `secret_path` URL
   (`https://<service>/<PATH_SECRET>/mcp`), click **Add**
3. Requires a paid Claude plan. Try: *"List my ad accounts and show daily
   performance for the last 7 days."*

## ChatGPT

1. Enable **Developer mode**: Settings → **Apps** → Advanced settings (label
   and location vary by account; Business/Enterprise admins may need to allow
   connected data first)
2. **Add custom connector** → paste your `secret_path` URL
3. Enable the connector in a chat. Requires Plus/Pro/Business/Enterprise/Edu;
   ChatGPT only supports **hosted** servers (no local stdio).

## Claude Code

```bash
claude mcp add --transport http reddit-ads "https://<service>/mcp" \
  --header "Authorization: Bearer <MCP_ACCESS_TOKEN>"
```

## Cursor

Settings → MCP → Add server, or `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "reddit-ads": {
      "url": "https://<service>/mcp",
      "headers": { "Authorization": "Bearer <MCP_ACCESS_TOKEN>" }
    }
  }
}
```

## VS Code (GitHub Copilot agent mode)

`.vscode/mcp.json`:

```json
{
  "servers": {
    "reddit-ads": {
      "type": "http",
      "url": "https://<service>/mcp",
      "headers": { "Authorization": "Bearer <MCP_ACCESS_TOKEN>" }
    }
  }
}
```

## Gemini CLI

`~/.gemini/settings.json`:

```json
{
  "mcpServers": {
    "reddit-ads": {
      "httpUrl": "https://<service>/mcp",
      "headers": { "Authorization": "Bearer <MCP_ACCESS_TOKEN>" }
    }
  }
}
```

## Any other MCP client

Generic recipe: transport = **streamable HTTP**; URL = your endpoint; auth =
bearer header if supported, otherwise deploy in `secret_path` mode and use the
credentialed URL. If the client only supports **stdio**, run the server
locally instead:

```json
{
  "command": "reddit-ads-mcp",
  "env": {
    "REDDIT_CLIENT_ID": "…",
    "REDDIT_CLIENT_SECRET": "…",
    "REDDIT_REFRESH_TOKEN": "…",
    "REDDIT_USER_AGENT": "desktop:reddit-ads-insights-mcp:0.2.1 (by /u/you)",
    "ALLOWED_ACCOUNT_IDS": "a2_youraccount"
  }
}
```

---

**Data note (all clients):** whatever AI tool you connect will receive your
advertising metrics as conversation context. Review that provider's data
handling before connecting a production account, and don't share one
deployment across unrelated advertisers.

**Smoke test** for any hosted deployment:
`curl https://<service>/health` → `{"status":"ok"}`.
Client can't see the tools? Verify the exact endpoint path, then check
`docs/TROUBLESHOOTING` notes in `API_NOTES.md` (e.g. clients cache tool
lists — reconnect the connector after server upgrades).
