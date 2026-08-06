"""Reddit OAuth token manager: refresh-token -> short-lived access tokens.

Requests and accepts only the `adsread` scope. Tokens live only in memory.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from reddit_ads_mcp.config import REQUIRED_REDDIT_SCOPE, Settings

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
_EXPIRY_MARGIN_SECONDS = 120


class OAuthError(RuntimeError):
    pass


@dataclass
class _Token:
    value: str
    expires_at: float


def parse_token_response(payload: dict) -> tuple[str, float, set[str]]:
    """Validate a token response. Returns (token, ttl_seconds, scopes).

    Raises OAuthError if the response is malformed or the scope grant is not
    exactly what this read-only server requires.
    """
    token = payload.get("access_token")
    if not token or not isinstance(token, str):
        raise OAuthError("token response missing access_token")
    ttl = payload.get("expires_in")
    if not isinstance(ttl, (int, float)) or ttl <= 0:
        raise OAuthError("token response missing valid expires_in")
    scopes = set(str(payload.get("scope", "")).replace(",", " ").split())
    if REQUIRED_REDDIT_SCOPE not in scopes:
        raise OAuthError(
            f"granted scopes {sorted(scopes)} do not include "
            f"'{REQUIRED_REDDIT_SCOPE}'"
        )
    extra = scopes - {REQUIRED_REDDIT_SCOPE}
    if extra & {"adsedit", "adsconversions", "adsdatadeletion"}:
        raise OAuthError(
            f"refresh token carries write scopes {sorted(extra)}; this "
            "read-only server refuses to run with a write-capable grant. "
            "Re-authorize the app requesting only 'adsread'."
        )
    return token, float(ttl), scopes


class TokenManager:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._token: _Token | None = None
        self._lock = asyncio.Lock()

    async def get_token(self) -> str:
        cached = self._token
        if cached and cached.expires_at - time.monotonic() > _EXPIRY_MARGIN_SECONDS:
            return cached.value
        async with self._lock:
            cached = self._token
            if cached and cached.expires_at - time.monotonic() > _EXPIRY_MARGIN_SECONDS:
                return cached.value
            payload = await self._refresh()
            token, ttl, _ = parse_token_response(payload)
            self._token = _Token(value=token, expires_at=time.monotonic() + ttl)
            return token

    def invalidate(self) -> None:
        self._token = None

    async def _refresh(self) -> dict:
        import httpx  # deferred so policy modules stay dependency-free

        auth = (self._settings.reddit_client_id, self._settings.reddit_client_secret)
        data = {
            "grant_type": "refresh_token",
            "refresh_token": self._settings.reddit_refresh_token,
        }
        headers = {"User-Agent": self._settings.reddit_user_agent}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(TOKEN_URL, auth=auth, data=data, headers=headers)
        if resp.status_code != 200:
            # Never echo the response body: it may contain sensitive detail.
            raise OAuthError(f"token refresh failed with HTTP {resp.status_code}")
        try:
            return resp.json()
        except ValueError as exc:
            raise OAuthError("token endpoint returned non-JSON response") from exc
