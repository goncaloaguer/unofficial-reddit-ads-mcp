"""Account-structure tools: accounts, campaigns, ad groups, ads.

Plain async functions (SDK-free, unit-testable); app.py registers them as
MCP tools.
"""
from __future__ import annotations

from typing import Any

from reddit_ads_mcp.context import AppContext
from reddit_ads_mcp.envelope import build_envelope
from reddit_ads_mcp.policy.accounts import filter_allowed, resolve_account
from reddit_ads_mcp.policy.limits import check_entity_ids


def _status_filter(rows: list[dict], status: str | None) -> list[dict]:
    if not status:
        return rows
    wanted = status.upper()
    return [
        r
        for r in rows
        if wanted in (str(r.get("effective_status", "")).upper(),
                      str(r.get("configured_status", "")).upper())
    ]


async def list_ad_accounts(ctx: AppContext) -> dict[str, Any]:
    """List the ad accounts this deployment is allowed to analyze."""
    budget = ctx.guard("list_ad_accounts", {})
    rows: list[dict] = []
    meta: dict[str, Any] = {}
    for account_id in sorted(ctx.settings.allowed_account_ids):
        payload = await ctx.client.request(
            "GET", f"/ad_accounts/{account_id}", budget=budget
        )
        if isinstance(payload.get("data"), dict):
            rows.append(payload["data"])
    meta.update({"rows_returned": len(rows), "truncated": False})
    return build_envelope(
        data=filter_allowed(ctx.settings, rows),
        meta=meta,
        summary={"allowed_accounts": len(rows)},
        warnings=list(ctx.settings.warnings),
    )


async def list_campaigns(
    ctx: AppContext,
    account_id: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """List campaigns with objective, budget, schedule, and status."""
    account = resolve_account(ctx.settings, account_id)
    budget = ctx.guard("list_campaigns", {"account_id": account, "status": status})
    rows, meta = await ctx.client.paginate(
        "GET", f"/ad_accounts/{account}/campaigns", budget=budget
    )
    rows = _status_filter(rows, status)
    meta["rows_returned"] = len(rows)
    return build_envelope(
        data=rows,
        meta=meta,
        account_id=account,
        summary={"campaigns": len(rows)},
        max_response_bytes=ctx.settings.max_response_bytes,
    )


async def list_ad_groups(
    ctx: AppContext,
    account_id: str | None = None,
    campaign_ids: list[str] | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """List ad groups incl. full targeting, bid, budget, schedule config."""
    account = resolve_account(ctx.settings, account_id)
    check_entity_ids(campaign_ids, ctx.settings.max_entity_ids)
    budget = ctx.guard(
        "list_ad_groups",
        {"account_id": account, "campaign_ids": campaign_ids, "status": status},
    )
    rows, meta = await ctx.client.paginate(
        "GET", f"/ad_accounts/{account}/ad_groups", budget=budget
    )
    if campaign_ids:
        wanted = set(campaign_ids)
        rows = [r for r in rows if r.get("campaign_id") in wanted]
    rows = _status_filter(rows, status)
    meta["rows_returned"] = len(rows)
    return build_envelope(
        data=rows,
        meta=meta,
        account_id=account,
        summary={"ad_groups": len(rows)},
        max_response_bytes=ctx.settings.max_response_bytes,
    )


async def list_ads(
    ctx: AppContext,
    account_id: str | None = None,
    ad_group_ids: list[str] | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """List ads with creative refs, review status, and rejection reasons."""
    account = resolve_account(ctx.settings, account_id)
    check_entity_ids(ad_group_ids, ctx.settings.max_entity_ids)
    budget = ctx.guard(
        "list_ads",
        {"account_id": account, "ad_group_ids": ad_group_ids, "status": status},
    )
    rows, meta = await ctx.client.paginate(
        "GET", f"/ad_accounts/{account}/ads", budget=budget
    )
    if ad_group_ids:
        wanted = set(ad_group_ids)
        rows = [r for r in rows if r.get("ad_group_id") in wanted]
    rows = _status_filter(rows, status)
    meta["rows_returned"] = len(rows)
    rejected = [r for r in rows if r.get("rejection_reason")]
    return build_envelope(
        data=rows,
        meta=meta,
        account_id=account,
        summary={"ads": len(rows), "with_rejection_reason": len(rejected)},
        max_response_bytes=ctx.settings.max_response_bytes,
    )
