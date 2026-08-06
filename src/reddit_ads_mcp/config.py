"""Startup configuration. Fails fast on invalid or unsafe settings.

All secrets arrive via environment variables (locally from the shell; on
Cloud Run from Secret Manager references). Nothing here can enable write
access to Reddit.

Remote MCP authentication uses exactly one mode (PLAN.md §9.2):
- MCP_AUTH_MODE=bearer (default): static bearer token on /mcp.
- MCP_AUTH_MODE=secret_path: high-entropy path credential /<secret>/mcp for
  MCP clients that cannot attach headers. /mcp returns 404 in this mode.
Startup fails if the selected mode lacks its credential or if both
credentials are active.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

_ACCOUNT_ID_RE = re.compile(r"^a2_[a-z0-9]+$")
_UA_RE = re.compile(r"^[\w.\-]+:[\w.\-]+:[\w.\-]+ \(by /u/[\w\-]+\)$")
_PATH_SECRET_RE = re.compile(r"^[A-Za-z0-9_\-]{43,}$")  # >=32 random bytes, urlsafe b64

REQUIRED_REDDIT_SCOPE = "adsread"


class ConfigError(ValueError):
    """Raised when configuration is missing or unsafe."""


@dataclass(frozen=True)
class Settings:
    # Reddit OAuth (secrets)
    reddit_client_id: str
    reddit_client_secret: str
    reddit_refresh_token: str
    # Reddit compliance
    reddit_user_agent: str
    # Account isolation
    allowed_account_ids: frozenset[str]
    default_account_id: str | None
    # MCP remote auth — exactly one active mode
    mcp_auth_mode: str  # "bearer" | "secret_path" (http transport only)
    mcp_access_token: str | None
    mcp_path_secret: str | None
    transport: str  # "stdio" | "http"
    host: str = "0.0.0.0"
    port: int = 8080
    # Safety ceilings (PLAN.md §7.4) — operator may lower, not raise via MCP
    max_tool_calls_per_hour: int = 60
    max_subrequests_per_call: int = 20
    max_concurrent_subrequests: int = 4
    tool_deadline_seconds: int = 90
    max_report_rows: int = 1000
    max_pages: int = 10
    max_report_days: int = 90
    max_entity_ids: int = 100
    max_response_bytes: int = 2 * 1024 * 1024
    api_base_url: str = "https://ads-api.reddit.com/api/v3"
    warnings: tuple[str, ...] = field(default_factory=tuple)


def _get(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name, default)
    return value.strip() if isinstance(value, str) else value


def load_settings(env: dict[str, str] | None = None) -> Settings:
    if env is not None:
        saved = dict(os.environ)
        os.environ.clear()
        os.environ.update(env)
        try:
            return load_settings(None)
        finally:
            os.environ.clear()
            os.environ.update(saved)

    problems: list[str] = []
    warnings: list[str] = []

    client_id = _get("REDDIT_CLIENT_ID")
    client_secret = _get("REDDIT_CLIENT_SECRET")
    refresh_token = _get("REDDIT_REFRESH_TOKEN")
    for name, value in (
        ("REDDIT_CLIENT_ID", client_id),
        ("REDDIT_CLIENT_SECRET", client_secret),
        ("REDDIT_REFRESH_TOKEN", refresh_token),
    ):
        if not value:
            problems.append(f"{name} is required")

    user_agent = _get("REDDIT_USER_AGENT")
    if not user_agent:
        problems.append(
            "REDDIT_USER_AGENT is required, format: "
            "'platform:app-id:version (by /u/username)'"
        )
    elif not _UA_RE.match(user_agent):
        problems.append(
            "REDDIT_USER_AGENT must follow Reddit's documented format "
            "'platform:app-id:version (by /u/username)'; generic or browser "
            "user agents are forbidden"
        )

    raw_allowed = _get("ALLOWED_ACCOUNT_IDS") or ""
    allowed = frozenset(a.strip() for a in raw_allowed.split(",") if a.strip())
    if not allowed:
        problems.append(
            "ALLOWED_ACCOUNT_IDS is required (comma-separated a2_* ad account "
            "IDs); account discovery never grants access implicitly"
        )
    else:
        bad = [a for a in sorted(allowed) if not _ACCOUNT_ID_RE.match(a)]
        if bad:
            problems.append(f"ALLOWED_ACCOUNT_IDS entries not in a2_* form: {bad}")

    default_account = _get("DEFAULT_ACCOUNT_ID")
    if default_account and default_account not in allowed:
        problems.append("DEFAULT_ACCOUNT_ID must be present in ALLOWED_ACCOUNT_IDS")
    if not default_account and len(allowed) == 1:
        default_account = next(iter(allowed))

    transport = (_get("MCP_TRANSPORT") or "stdio").lower()
    if transport not in ("stdio", "http"):
        problems.append("MCP_TRANSPORT must be 'stdio' or 'http'")

    auth_mode = (_get("MCP_AUTH_MODE") or "bearer").lower()
    access_token = _get("MCP_ACCESS_TOKEN")
    path_secret = _get("MCP_PATH_SECRET")

    if transport == "http":
        if auth_mode not in ("bearer", "secret_path"):
            problems.append("MCP_AUTH_MODE must be 'bearer' or 'secret_path'")
        elif access_token and path_secret:
            problems.append(
                "MCP_ACCESS_TOKEN and MCP_PATH_SECRET are both set; the auth "
                "modes are mutually exclusive — configure exactly one credential"
            )
        elif auth_mode == "bearer":
            if not access_token:
                problems.append("bearer mode requires MCP_ACCESS_TOKEN")
            elif len(access_token) < 32:
                problems.append("MCP_ACCESS_TOKEN must be at least 32 characters")
            path_secret = None
        elif auth_mode == "secret_path":
            if not path_secret:
                problems.append("secret_path mode requires MCP_PATH_SECRET")
            elif not _PATH_SECRET_RE.match(path_secret):
                problems.append(
                    "MCP_PATH_SECRET must be a URL-safe value of at least 32 "
                    "random bytes (e.g. `python3 -c \"import secrets; "
                    "print(secrets.token_urlsafe(32))\"`); do not choose a "
                    "memorable path"
                )
            access_token = None
            warnings.append(
                "secret_path compatibility mode active: the URL itself is the "
                "credential. It can appear in MCP client settings, browser "
                "history, and infrastructure request logs. Rotate it "
                "periodically and prefer bearer mode where your client "
                "supports headers."
            )
    else:
        access_token = None
        path_secret = None

    if problems:
        raise ConfigError("; ".join(problems))

    return Settings(
        reddit_client_id=client_id or "",
        reddit_client_secret=client_secret or "",
        reddit_refresh_token=refresh_token or "",
        reddit_user_agent=user_agent or "",
        allowed_account_ids=allowed,
        default_account_id=default_account,
        mcp_auth_mode=auth_mode,
        mcp_access_token=access_token,
        mcp_path_secret=path_secret,
        transport=transport,
        port=int(_get("PORT") or "8080"),
        warnings=tuple(warnings),
    )
