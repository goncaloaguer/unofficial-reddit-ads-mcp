"""Typed, policy-enforcing Reddit Ads API client.

Every request passes through the read-operation registry, the account guard
(in tools), the subrequest budget, and pagination/rate-limit policy.
"""
from __future__ import annotations

import asyncio
from typing import Any

from reddit_ads_mcp.config import Settings
from reddit_ads_mcp.policy import registry
from reddit_ads_mcp.policy.limits import SubrequestBudget
from reddit_ads_mcp.reddit import http_policy
from reddit_ads_mcp.auth.reddit_oauth import TokenManager


class RedditApiError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


class RedditClient:
    def __init__(self, settings: Settings, tokens: TokenManager) -> None:
        self._settings = settings
        self._tokens = tokens
        self._client: Any = None
        self._lock = asyncio.Lock()

    async def _http(self):
        import httpx

        async with self._lock:
            if self._client is None:
                self._client = httpx.AsyncClient(
                    base_url=self._settings.api_base_url,
                    timeout=30,
                    follow_redirects=False,
                    headers={"User-Agent": self._settings.reddit_user_agent},
                )
        return self._client

    async def request(
        self,
        method: str,
        path: str,
        *,
        budget: SubrequestBudget,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        absolute_url: str | None = None,
    ) -> dict[str, Any]:
        """One policy-checked upstream request with retries."""
        op = registry.authorize(method, path)
        budget.spend()
        client = await self._http()

        attempt = 0
        while True:
            attempt += 1
            token = await self._tokens.get_token()
            headers = {"Authorization": f"Bearer {token}"}
            resp = await client.request(
                method,
                absolute_url or path,
                params=params if not absolute_url else None,
                json=json_body,
                headers=headers,
            )
            if resp.status_code == 200:
                try:
                    return resp.json()
                except ValueError as exc:
                    raise RedditApiError(200, "non-JSON response body") from exc
            if resp.status_code == 401 and attempt == 1:
                self._tokens.invalidate()
                continue
            if http_policy.should_retry(resp.status_code, attempt):
                state = http_policy.parse_rate_limit(dict(resp.headers))
                delay = (
                    min(30, state.reset_seconds)
                    if resp.status_code == 429 and state.reset_seconds
                    else http_policy.backoff_delay(attempt)
                )
                await asyncio.sleep(delay)
                continue
            detail = http_policy.summarize_error_body(resp.text or "")
            message = (
                f"Reddit Ads API returned HTTP {resp.status_code} for "
                f"{method} {op.path_template}"
            )
            if detail:
                message += f" — {detail}"
            raise RedditApiError(resp.status_code, message)

    async def paginate(
        self,
        method: str,
        path: str,
        *,
        budget: SubrequestBudget,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        max_pages: int | None = None,
        max_rows: int | None = None,
    ) -> tuple[list[dict], dict[str, Any]]:
        """Follow Reddit's pagination.next_url with validation and caps.

        Returns (rows, meta) where meta records pages fetched and truncation.
        """
        settings = self._settings
        max_pages = max_pages or settings.max_pages
        max_rows = max_rows or settings.max_report_rows

        rows: list[dict] = []
        seen_urls: set[str] = set()
        pages = 0
        truncated = False
        next_available = False
        url: str | None = None

        while True:
            payload = await self.request(
                method,
                path,
                budget=budget,
                params=params if url is None else None,
                # POST endpoints (reports, history) require the request body
                # on EVERY page; next_url only carries the cursor (live API,
                # verified: page-2 POST without body -> 400 "body required").
                json_body=json_body,
                absolute_url=url,
            )
            pages += 1
            data = payload.get("data")
            if isinstance(data, list):
                rows.extend(data)
            elif isinstance(data, dict):
                rows.append(data)

            next_url = (payload.get("pagination") or {}).get("next_url")
            next_available = bool(next_url)
            if not next_url:
                break
            if len(rows) >= max_rows or pages >= max_pages:
                truncated = True
                break
            if next_url in seen_urls:
                break  # defensive: pagination loop
            seen_urls.add(next_url)
            url = http_policy.validate_next_url(next_url, path)

        if len(rows) > max_rows:
            rows = rows[:max_rows]
            truncated = True

        meta = {
            "pages_fetched": pages,
            "rows_returned": len(rows),
            "truncated": truncated,
            "next_page_available": next_available and truncated,
            "source": "Reddit Ads API v3",
        }
        return rows, meta

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
