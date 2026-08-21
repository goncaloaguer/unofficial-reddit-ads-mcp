"""Phase 3 targeting intelligence and forecasting tools (all read-only)."""
from __future__ import annotations

from typing import Any

from reddit_ads_mcp.context import AppContext
from reddit_ads_mcp.envelope import build_envelope
from reddit_ads_mcp.policy.accounts import resolve_account
from reddit_ads_mcp.tools.analysis_tools import UNTRUSTED_NOTE

_TAXONOMY_PATHS = {
    "interests": "/targeting/interests",
    "geolocations": "/targeting/geolocations",
    "devices": "/targeting/devices",
    "carriers": "/targeting/carriers",
    "languages": "/targeting/languages",
    "third_party_audiences": "/targeting/third_party_audiences",
}


async def search_targeting(
    ctx: AppContext,
    kind: str,
    query: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Unified targeting lookup.

    kind: communities (searchable), interests, geolocations, devices,
    carriers, languages, third_party_audiences. `query` only applies to
    communities; taxonomies are returned as-is (filtered client-side when
    a query is given).
    """
    budget = ctx.guard("search_targeting", {"kind": kind, "q": query})
    warnings = [UNTRUSTED_NOTE]
    if kind == "communities":
        rows, meta = await ctx.client.paginate(
            "GET", "/targeting/communities/search", budget=budget,
            params={"query": query} if query else None,
            max_rows=limit, max_pages=2,
        )
        warnings.append(
            "Community search with bare keywords can return unrelated large "
            "subreddits; get_community_suggestions usually gives better "
            "expansion ideas. Targeting uses community NAMES, not t5_ IDs."
        )
    elif kind in _TAXONOMY_PATHS:
        rows, meta = await ctx.client.paginate(
            "GET", _TAXONOMY_PATHS[kind], budget=budget,
            max_rows=max(limit, 200), max_pages=3,
        )
        if query:
            q = query.lower()
            rows = [r for r in rows if q in str(r).lower()][:limit]
            meta["rows_returned"] = len(rows)
    else:
        raise ValueError(
            f"kind must be one of: communities, {', '.join(_TAXONOMY_PATHS)}"
        )
    return build_envelope(
        data=rows[:limit] if kind != "communities" else rows,
        meta=meta,
        summary={"kind": kind, "query": query, "rows": len(rows[:limit])},
        warnings=warnings,
        max_response_bytes=ctx.settings.max_response_bytes,
    )


async def get_community_suggestions(
    ctx: AppContext,
    seed_communities: list[str] | None = None,
    website_url: str | None = None,
) -> dict[str, Any]:
    """Reddit's own community-targeting suggestions from seed subreddit
    names and/or a website URL."""
    if not seed_communities and not website_url:
        raise ValueError("provide seed_communities and/or website_url")
    budget = ctx.guard(
        "get_community_suggestions",
        {"seeds": seed_communities, "url": website_url},
    )
    params: dict[str, Any] = {}
    if seed_communities:
        params["names"] = ",".join(
            c.removeprefix("r/") for c in seed_communities
        )
    if website_url:
        params["website_url"] = website_url
    rows, meta = await ctx.client.paginate(
        "GET", "/targeting/communities/suggestions", budget=budget,
        params=params, max_pages=2,
    )
    return build_envelope(
        data=rows, meta=meta,
        summary={"suggestions": len(rows)},
        warnings=[UNTRUSTED_NOTE],
        max_response_bytes=ctx.settings.max_response_bytes,
    )


async def get_reach_estimate(
    ctx: AppContext,
    geolocation: str,
    duration_days: int = 7,
    min_age: int | None = None,
    max_age: int | None = None,
    gender: str | None = None,
) -> dict[str, Any]:
    """Channel-planning reach/impressions estimate.

    API constraints (spec-enforced): duration_days must be 7 or 28;
    geolocation is a single country code; gender MALE/FEMALE/ALL.
    """
    if duration_days not in (7, 28):
        raise ValueError("duration_days must be 7 or 28 (API constraint)")
    budget = ctx.guard(
        "get_reach_estimate",
        {"geo": geolocation, "d": duration_days, "a": [min_age, max_age],
         "g": gender},
    )
    params: dict[str, Any] = {
        "geolocation": geolocation.upper(),
        "duration_days": duration_days,
    }
    if min_age is not None:
        params["min_age"] = min_age
    if max_age is not None:
        params["max_age"] = max_age
    if gender:
        params["gender"] = gender.upper()
    rows, meta = await ctx.client.paginate(
        "GET", "/channel_planning/reach", budget=budget, params=params,
        max_pages=2,
    )
    return build_envelope(
        data=rows, meta=meta,
        summary={"geolocation": params["geolocation"],
                 "duration_days": duration_days},
        warnings=["Estimates are Reddit's planning figures, not delivery "
                  "guarantees."],
    )


async def get_bid_suggestions(
    ctx: AppContext,
    bid_type: str,
    campaign_objective: str,
    account_id: str | None = None,
    targeting: dict[str, Any] | None = None,
    optimization_goal: str | None = None,
) -> dict[str, Any]:
    """Reddit's suggested bid for a scenario (bid_type: CPC/CPM/CPV/CPV6;
    objective e.g. CONVERSIONS, CLICKS, IMPRESSIONS)."""
    account = resolve_account(ctx.settings, account_id)
    budget = ctx.guard(
        "get_bid_suggestions",
        {"account": account, "bt": bid_type, "obj": campaign_objective,
         "t": targeting, "og": optimization_goal},
    )
    data: dict[str, Any] = {
        "ad_account_id": account,
        "bid_type": bid_type.upper(),
        "campaign_objective": campaign_objective.upper(),
    }
    if targeting:
        data["targeting"] = targeting
    if optimization_goal:
        data["optimization_goal"] = optimization_goal.upper()
    rows, meta = await ctx.client.paginate(
        "POST", "/forecasting/bid_suggestions", budget=budget,
        json_body={"data": data},
    )
    return build_envelope(
        data=rows, meta=meta, account_id=account,
        summary={"bid_type": data["bid_type"],
                 "campaign_objective": data["campaign_objective"]},
        warnings=["Suggested bids are Reddit forecasts; monetary values in "
                  "responses may be micro-denominated — reconcile against a "
                  "known bid before acting."],
    )


async def get_keyword_suggestions(
    ctx: AppContext,
    seed_keywords: list[str],
) -> dict[str, Any]:
    """Keyword-targeting expansion ideas from seed keywords."""
    if not seed_keywords:
        raise ValueError("seed_keywords must be non-empty")
    budget = ctx.guard("get_keyword_suggestions", {"seeds": seed_keywords})
    rows, meta = await ctx.client.paginate(
        "POST", "/targeting/keyword_suggestions", budget=budget,
        json_body={"data": {"seed_keywords": seed_keywords[:50]}},
    )
    return build_envelope(
        data=rows, meta=meta,
        summary={"seeds": len(seed_keywords[:50]), "suggestions": len(rows)},
        warnings=[UNTRUSTED_NOTE,
                  "Remember: keyword performance reporting is only available "
                  "for a ~10-day lookback — pull reports promptly."],
    )


async def get_feature_access(
    ctx: AppContext,
    account_id: str | None = None,
    business_id: str | None = None,
) -> dict[str, Any]:
    """Which gated features (catalogs, lead gen, …) are available."""
    account = resolve_account(ctx.settings, account_id)
    budget = ctx.guard("get_feature_access", {"account": account,
                                              "b": business_id})
    params: dict[str, Any] = {"ad_account_id": account}
    if business_id:
        params["business_id"] = business_id
    rows, meta = await ctx.client.paginate(
        "GET", "/feature_access", budget=budget, params=params
    )
    return build_envelope(
        data=rows, meta=meta, account_id=account,
        summary={"features": len(rows)},
        warnings=["An empty list means no explicitly gated features were "
                  "returned — not an authentication failure."],
    )


async def get_saved_audiences(
    ctx: AppContext,
    account_id: str | None = None,
) -> dict[str, Any]:
    """Reusable targeting templates configured on the account."""
    account = resolve_account(ctx.settings, account_id)
    budget = ctx.guard("get_saved_audiences", {"account": account})
    rows, meta = await ctx.client.paginate(
        "GET", f"/ad_accounts/{account}/saved_audiences", budget=budget
    )
    return build_envelope(
        data=rows, meta=meta, account_id=account,
        summary={"saved_audiences": len(rows)},
        warnings=[UNTRUSTED_NOTE],
        max_response_bytes=ctx.settings.max_response_bytes,
    )


async def list_lead_gen_forms(
    ctx: AppContext,
    account_id: str | None = None,
) -> dict[str, Any]:
    """Lead-gen form inventory (metadata only, never submitted leads).

    Legacy: Reddit sunsets the Lead Generation Forms API on 2026-09-21 and
    pauses onsite-form ads on 2026-09-30.
    """
    account = resolve_account(ctx.settings, account_id)
    budget = ctx.guard("list_lead_gen_forms", {"account": account})
    rows, meta = await ctx.client.paginate(
        "GET", f"/ad_accounts/{account}/lead_gen_forms", budget=budget
    )
    return build_envelope(
        data=rows, meta=meta, account_id=account,
        summary={"forms": len(rows)},
        warnings=[
            "Reddit sunsets the Lead Generation Forms API on 2026-09-21; "
            "onsite-form ads pause 2026-09-30. Plan migrations accordingly.",
            "Submitted lead data is never accessible through this server.",
        ],
    )
