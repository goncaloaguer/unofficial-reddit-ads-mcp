"""Reporting tools: get_report and get_daily_performance."""
from __future__ import annotations

from typing import Any

from reddit_ads_mcp import reporting
from reddit_ads_mcp.reddit.client import RedditApiError
from reddit_ads_mcp.context import AppContext
from reddit_ads_mcp.envelope import build_envelope
from reddit_ads_mcp.policy.accounts import resolve_account


async def get_report(
    ctx: AppContext,
    starts_at: str,
    ends_at: str,
    account_id: str | None = None,
    metric_groups: list[str] | None = None,
    fields: list[str] | None = None,
    breakdowns: list[str] | None = None,
    time_zone_id: str | None = None,
    custom_column_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Flexible performance report.

    metric_groups: core, video, conversions, value, app. Up to 3 breakdowns
    (4 with COUNTRY+REGION); see the reddit-ads://report-breakdowns resource.
    """
    account = resolve_account(ctx.settings, account_id)
    body = reporting.build_report_request(
        starts_at=starts_at,
        ends_at=ends_at,
        metric_groups=metric_groups,
        fields=fields,
        breakdowns=breakdowns,
        time_zone_id=time_zone_id,
        custom_column_ids=custom_column_ids,
        max_report_days=ctx.settings.max_report_days,
    )
    budget = ctx.guard(
        "get_report", {"account_id": account, **body["data"]}
    )
    try:
        raw_rows, meta = await ctx.client.paginate(
            "POST", f"/ad_accounts/{account}/reports", budget=budget, json_body=body
        )
    except RedditApiError as exc:
        if exc.status == 400 and "KEYWORD" in (body["data"].get("breakdowns") or []):
            raise RedditApiError(
                400,
                f"{exc} — note: Reddit only serves KEYWORD breakdowns for a "
                "recent lookback window (roughly the last 10 days, observed "
                "live). Narrow the date range to recent dates; older "
                "keyword-level data is not retrievable.",
            ) from exc
        raise
    # Reddit nests report rows: data -> [{metrics: [...], metrics_updated_at}]
    rows: list[dict] = []
    metrics_updated_at = None
    for wrapper in raw_rows:
        if isinstance(wrapper, dict) and "metrics" in wrapper:
            metrics_updated_at = wrapper.get("metrics_updated_at") or metrics_updated_at
            rows.extend(wrapper.get("metrics") or [])
        elif isinstance(wrapper, dict):
            rows.append(wrapper)
    meta["rows_returned"] = len(rows)
    if metrics_updated_at:
        meta["metrics_updated_at"] = metrics_updated_at

    # Spend arrives in micros of the account currency (verified live:
    # 302498090 micros == 302.50). Convert with provenance; keep the raw value.
    derived = []
    if any(isinstance(r.get("spend"), (int, float)) for r in rows):
        for row in rows:
            if isinstance(row.get("spend"), (int, float)):
                row["spend_micros"] = row.pop("spend")
                row["spend"] = round(row["spend_micros"] / 1_000_000, 2)
        derived.append(
            {"spend": "spend_micros / 1,000,000 (account currency units)"}
        )
    converted = reporting.convert_micro_fields(rows)
    for name in converted:
        derived.append({name: f"{name}_micros / 1,000,000 (account currency units)"})
    for name in reporting.convert_value_fields(rows):
        derived.append({name: f"{name}_cents / 100 (account currency units)"})
    warnings = []
    if any(k.endswith("_revenue") for r in rows for k in r):
        warnings.append(
            "Revenue fields (*_revenue) are returned unscaled — their unit is "
            "unverified. Check against Ads Manager before financial "
            "conclusions."
        )
    if any("reach" in r for r in rows) and "DATE" in (body["data"].get("breakdowns") or []):
        warnings.append(
            "Daily reach values count unique users per day and cannot be "
            "summed into a period total."
        )
    if not rows:
        warnings.append(
            "No rows returned: either no delivery in this range (check "
            "campaign effective_status and schedules with list_campaigns) or "
            "metrics for very recent hours have not stabilized yet."
        )
    if fw := reporting.freshness_warning(ends_at):
        warnings.append(fw)
    return build_envelope(
        data=rows,
        meta=meta,
        account_id=account,
        summary={
            "rows": len(rows),
            "fields": body["data"]["fields"],
            "breakdowns": body["data"].get("breakdowns", []),
        },
        warnings=warnings,
        derived_metrics=derived,
        max_response_bytes=ctx.settings.max_response_bytes,
    )


async def get_daily_performance(
    ctx: AppContext,
    days: int = 7,
    account_id: str | None = None,
) -> dict[str, Any]:
    """Standard KPIs by day for the last N days (default 7)."""
    days = max(1, min(days, ctx.settings.max_report_days))
    starts_at, ends_at = reporting.default_date_range(days)
    result = await get_report(
        ctx,
        starts_at=starts_at,
        ends_at=ends_at,
        account_id=account_id,
        metric_groups=["core"],
        breakdowns=["DATE"],
    )
    rows = result["data"]
    totals: dict[str, float] = {}
    for row in rows:
        for key in ("impressions", "clicks", "spend"):
            value = row.get(key)
            if isinstance(value, (int, float)):
                totals[key] = round(totals.get(key, 0) + value, 2)
    spend = totals.get("spend")
    clicks = totals.get("clicks")
    impressions = totals.get("impressions")
    derived = list(result.get("derived_metrics") or [])
    if spend is not None and clicks:
        totals["cpc_derived"] = round(spend / clicks, 4)
        derived.append(
            {"cpc_derived": "sum(spend)/sum(clicks) over the period, "
             "account currency"}
        )
    if clicks is not None and impressions:
        totals["ctr_derived"] = round(clicks / impressions, 6)
        derived.append({"ctr_derived": "sum(clicks)/sum(impressions) over the period"})
    result["summary"] = {"days": days, "totals": totals}
    result["derived_metrics"] = derived
    return result
