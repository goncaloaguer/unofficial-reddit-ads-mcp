"""Phase 3 diagnostics: tracking health, delivery, audiences, catalogs.

Composite tools return partial results with warnings when a subordinate
lookup fails (PLAN.md §6.3) — one broken endpoint never hides the rest.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from reddit_ads_mcp.context import AppContext
from reddit_ads_mcp.envelope import build_envelope
from reddit_ads_mcp.policy.accounts import resolve_account
from reddit_ads_mcp.tools.analysis_tools import UNTRUSTED_NOTE
from reddit_ads_mcp.tools.reporting_tools import get_report


def _age_hours(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        then = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    now = datetime.now(timezone.utc)
    return round((now - then).total_seconds() / 3600, 1)


async def get_tracking_health(
    ctx: AppContext,
    account_id: str | None = None,
) -> dict[str, Any]:
    """Is conversion tracking alive? Pixels + last-fired recency."""
    account = resolve_account(ctx.settings, account_id)
    budget = ctx.guard("get_tracking_health", {"account": account})
    warnings: list[str] = []
    pixels, _ = await ctx.client.paginate(
        "GET", f"/ad_accounts/{account}/pixels", budget=budget
    )
    out = []
    for pixel in pixels:
        pixel_id = pixel.get("id")
        entry: dict[str, Any] = {
            "pixel_id": pixel_id,
            "name": pixel.get("name"),
        }
        try:
            fired = await ctx.client.request(
                "GET", f"/pixels/{pixel_id}/last_fired_at", budget=budget
            )
            data = fired.get("data") or {}
            # Live API: the response is a per-event map (add_to_cart,
            # purchase, page_visit, ... -> datetime) plus a `breakdown` of
            # custom events — not a single last_fired_at field.
            events: dict[str, str] = {
                k: v for k, v in data.items()
                if isinstance(v, str) and k != "breakdown"
            }
            for k, v in (data.get("breakdown") or {}).items():
                if isinstance(v, str):
                    events[f"custom:{k}"] = v
            entry["events"] = {
                k: {"last_fired_at": v, "hours_ago": _age_hours(v)}
                for k, v in sorted(events.items())
            }
            latest = max(events.values()) if events else None
            entry["last_fired_at"] = latest
            age = _age_hours(latest)
            entry["hours_since_last_fire"] = age
            entry["status"] = (
                "healthy" if age is not None and age <= 24
                else "stale" if age is not None
                else "never_fired_or_unknown"
            )
        except Exception:  # noqa: BLE001 - partial results by design
            entry["status"] = "lookup_failed"
            warnings.append(f"last_fired_at lookup failed for pixel {pixel_id}")
        out.append(entry)
    if not out:
        warnings.append(
            "No pixels configured on this account — CONVERSIONS campaigns "
            "cannot attribute results without one, and from July 13, 2026 "
            "Reddit requires a conversion_pixel_id on new ad groups."
        )
    healthy = sum(1 for e in out if e.get("status") == "healthy")
    return build_envelope(
        data=out,
        meta={"rows_returned": len(out), "truncated": False},
        account_id=account,
        summary={"pixels": len(out), "healthy_last_24h": healthy,
                 "health_rule": "healthy = fired within 24h"},
        warnings=warnings,
    )


_DELIVERY_HINTS = {
    "CAMPAIGN_PAUSED": "the parent campaign is paused",
    "PAUSED": "this entity is paused",
    "NO_ACTIVE_CHILDREN": "no active child entities to serve",
    "PENDING_REVIEW": "creative is awaiting Reddit review",
    "REJECTED": "creative was rejected — see rejection_reason",
    "PENDING_BILLING": "billing/funding instrument issue",
    "ENDED": "schedule end time has passed",
    "SCHEDULED": "start time is in the future",
    "ARCHIVED": "entity is archived",
}


async def diagnose_delivery(
    ctx: AppContext,
    account_id: str | None = None,
    lookback_days: int = 3,
) -> dict[str, Any]:
    """Why isn't (or wasn't) the account serving? Status + spend evidence."""
    account = resolve_account(ctx.settings, account_id)
    budget = ctx.guard("diagnose_delivery", {"account": account,
                                             "d": lookback_days})
    warnings: list[str] = [UNTRUSTED_NOTE]
    campaigns, _ = await ctx.client.paginate(
        "GET", f"/ad_accounts/{account}/campaigns", budget=budget
    )
    ads, _ = await ctx.client.paginate(
        "GET", f"/ad_accounts/{account}/ads", budget=budget
    )
    findings = []
    for campaign in campaigns:
        if campaign.get("effective_status") == "ARCHIVED":
            continue
        statuses = campaign.get("delivery_status") or []
        blocking = [s for s in statuses if s in _DELIVERY_HINTS]
        findings.append(
            {
                "entity_type": "CAMPAIGN",
                "id": campaign.get("id"),
                "name": campaign.get("name"),
                "configured_status": campaign.get("configured_status"),
                "effective_status": campaign.get("effective_status"),
                "delivery_status": statuses,
                "explanations": [_DELIVERY_HINTS[s] for s in blocking],
                "conversion_pixel_id": campaign.get("conversion_pixel_id") or None,
            }
        )
    rejected = [
        {
            "entity_type": "AD",
            "id": ad.get("id"),
            "name": ad.get("name"),
            "effective_status": ad.get("effective_status"),
            "rejection_reason": ad.get("rejection_reason"),
        }
        for ad in ads
        if ad.get("rejection_reason")
    ]
    spend_evidence: dict[str, Any] = {}
    try:
        from reddit_ads_mcp import reporting

        starts, ends = reporting.default_date_range(lookback_days)
        rep = await get_report(
            ctx, starts_at=starts, ends_at=ends, account_id=account,
            fields=["IMPRESSIONS", "CLICKS", "SPEND"], breakdowns=["DATE"],
        )
        total_spend = sum(
            r.get("spend") or 0 for r in rep["data"]
        )
        spend_evidence = {
            "lookback_days": lookback_days,
            "spend": round(total_spend, 2),
            "delivering": total_spend > 0,
        }
    except Exception:  # noqa: BLE001
        warnings.append("recent-spend check failed; findings are status-only")
    serving = [f for f in findings if not f["explanations"]
               and f["effective_status"] == "ACTIVE"]
    missing_pixel = [
        f["name"] for f in findings
        if not f["conversion_pixel_id"]
        and f["configured_status"] != "ARCHIVED"
    ]
    if missing_pixel:
        warnings.append(
            "Campaigns without a conversion_pixel_id (required for new ad "
            "groups/CBO campaigns since 2026-07-13): "
            + ", ".join(missing_pixel[:10])
        )
    return build_envelope(
        data={"campaigns": findings, "rejected_ads": rejected,
              "recent_delivery": spend_evidence},
        meta={"rows_returned": len(findings), "truncated": False},
        account_id=account,
        summary={
            "campaigns_reviewed": len(findings),
            "actively_serving": len(serving),
            "rejected_ads": len(rejected),
        },
        warnings=warnings,
    )


async def list_custom_audiences(
    ctx: AppContext,
    account_id: str | None = None,
) -> dict[str, Any]:
    """Audience metadata only — never members (write/ingest is out of scope)."""
    account = resolve_account(ctx.settings, account_id)
    budget = ctx.guard("list_custom_audiences", {"account": account})
    rows, meta = await ctx.client.paginate(
        "GET", f"/ad_accounts/{account}/custom_audiences", budget=budget
    )
    slim = [
        {
            "id": r.get("id"),
            "name": r.get("name"),
            "type": r.get("type"),
            "status": r.get("status") or r.get("effective_status"),
            "size_range_lower": r.get("size_range_lower"),
            "size_range_upper": r.get("size_range_upper"),
            "created_at": r.get("created_at"),
            "modified_at": r.get("modified_at"),
        }
        for r in rows
    ]
    return build_envelope(
        data=slim,
        meta=meta,
        account_id=account,
        summary={"audiences": len(slim)},
        warnings=["Audience members are never accessible through this server; "
                  "sizes are Reddit-provided approximate ranges."],
    )


async def get_catalog_health(
    ctx: AppContext,
    business_id: str | None = None,
    account_id: str | None = None,
) -> dict[str, Any]:
    """Commerce catalog inventory and import status (if the business uses
    catalog sales). business_id is resolved from the ad account when omitted."""
    account = resolve_account(ctx.settings, account_id)
    budget = ctx.guard("get_catalog_health", {"account": account,
                                              "b": business_id})
    warnings: list[str] = []
    if not business_id:
        acct = await ctx.client.request(
            "GET", f"/ad_accounts/{account}", budget=budget
        )
        business_id = (acct.get("data") or {}).get("business_id")
    if not business_id:
        return build_envelope(
            data=[], meta={"rows_returned": 0, "truncated": False},
            account_id=account,
            summary={"catalogs": 0},
            warnings=["Could not resolve a business_id for this account; "
                      "pass business_id explicitly."],
        )
    catalogs, meta = await ctx.client.paginate(
        "GET", f"/businesses/{business_id}/product_catalogs", budget=budget
    )
    out = []
    for catalog in catalogs:
        cid = catalog.get("id")
        entry: dict[str, Any] = {
            "catalog_id": cid,
            "name": catalog.get("name"),
            "summary": catalog.get("summary"),
        }
        try:
            imports, _ = await ctx.client.paginate(
                "GET", f"/product_catalogs/{cid}/catalog_imports",
                budget=budget, max_rows=5, max_pages=1,
            )
            entry["recent_imports"] = [
                {"id": i.get("id"), "status": i.get("status"),
                 "created_at": i.get("created_at")}
                for i in imports[:5]
            ]
        except Exception:  # noqa: BLE001
            entry["recent_imports"] = None
            warnings.append(f"import lookup failed for catalog {cid}")
        out.append(entry)
    if not out:
        warnings.append("No product catalogs — expected unless you run "
                        "catalog-sales campaigns.")
    return build_envelope(
        data=out, meta=meta, account_id=account,
        summary={"business_id": business_id, "catalogs": len(out)},
        warnings=warnings or [UNTRUSTED_NOTE],
    )
