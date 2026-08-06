"""Report request building and validation.

The full field enumeration (447 fields) lives in reporting_fields.json,
extracted from the pinned OpenAPI spec — not in tool schemas, to conserve
model context. Tools accept compact metric_groups; advanced callers may pass
explicit fields, validated here against the spec enum.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from functools import lru_cache
from importlib import resources

from reddit_ads_mcp.policy.limits import LimitExceeded, check_date_range


class ReportValidationError(ValueError):
    pass


@lru_cache(maxsize=1)
def _spec() -> dict:
    return json.loads(
        resources.files("reddit_ads_mcp").joinpath("reporting_fields.json").read_text()
    )


def valid_fields() -> frozenset[str]:
    return frozenset(_spec()["fields"])


def valid_breakdowns() -> frozenset[str]:
    return frozenset(_spec()["breakdowns"])


# Curated metric groups. Every name is validated against the spec enum by
# tests, so a spec update that renames a field fails CI instead of failing at
# runtime.
METRIC_GROUPS: dict[str, list[str]] = {
    "core": [
        "IMPRESSIONS", "CLICKS", "SPEND", "CTR", "CPC", "ECPM", "REACH",
        "FREQUENCY", "ENGAGED_CLICK", "CURRENCY",
    ],
    "video": [
        "VIDEO_STARTED", "VIDEO_VIEWABLE_IMPRESSIONS",
        "VIDEO_FULLY_VIEWABLE_IMPRESSIONS", "VIDEO_PLAYS_WITH_SOUND",
        "VIDEO_PLAYS_EXPANDED", "VIDEO_WATCHED_25_PERCENT",
        "VIDEO_WATCHED_50_PERCENT", "VIDEO_WATCHED_75_PERCENT",
        "VIDEO_WATCHED_95_PERCENT", "VIDEO_WATCHED_100_PERCENT",
        "VIDEO_WATCHED_3_SECONDS", "VIDEO_WATCHED_5_SECONDS",
        "VIDEO_WATCHED_10_SECONDS", "VIDEO_COMPLETION_RATE",
        "VIDEO_VIEW_RATE", "CPV", "COST_PER_3_SECOND_VIEW",
        "COST_PER_6_SECOND_VIEW", "COST_PER_15_SECOND_VIEW",
        "COST_PER_COMPLETED_VIEW",
    ],
    "conversions": [
        "CONVERSION_PURCHASE_CLICKS", "CONVERSION_PURCHASE_VIEWS",
        "CONVERSION_PURCHASE_ECPA", "CONVERSION_LEAD_CLICKS",
        "CONVERSION_LEAD_VIEWS", "CONVERSION_LEAD_ECPA",
        "CONVERSION_SIGN_UP_CLICKS", "CONVERSION_SIGN_UP_VIEWS",
        "CONVERSION_SIGN_UP_ECPA", "CONVERSION_ADD_TO_CART_CLICKS",
        "CONVERSION_ADD_TO_CART_VIEWS", "CONVERSION_ADD_TO_CART_ECPA",
        "CONVERSION_PAGE_VISIT_CLICKS", "CONVERSION_PAGE_VISIT_VIEWS",
        "CONVERSION_PAGE_VISIT_ECPA", "CONVERSION_VIEW_CONTENT_CLICKS",
        "CONVERSION_VIEW_CONTENT_VIEWS", "CONVERSION_SEARCH_CLICKS",
        "KEY_CONVERSION_TOTAL_COUNT", "KEY_CONVERSION_RATE",
        "KEY_CONVERSION_ECPA", "REDDIT_LEADS",
    ],
    "value": [
        "CONVERSION_PURCHASE_TOTAL_VALUE", "CONVERSION_PURCHASE_AVG_VALUE",
        "CONVERSION_PURCHASE_TOTAL_ITEMS", "CONVERSION_ADD_TO_CART_TOTAL_VALUE",
        "CONVERSION_ADD_TO_CART_AVG_VALUE", "CONVERSION_LEAD_TOTAL_VALUE",
        "CONVERSION_SIGNUP_TOTAL_VALUE", "CONVERSION_ROAS",
    ],
    "app": [
        "APP_INSTALL_INSTALL_COUNT", "APP_INSTALL_INSTALL_CVR",
        "APP_INSTALL_INSTALL_ECPA", "APP_INSTALL_PURCHASE_COUNT",
        "APP_INSTALL_PURCHASE_CVR", "APP_INSTALL_PURCHASE_ECPA",
        "APP_INSTALL_SIGN_UP_COUNT", "APP_INSTALL_REVENUE",
        "APP_INSTALL_ROAS_DOUBLE", "APP_INSTALL_TOTAL_CONVERSIONS",
    ],
}

DEFAULT_GROUPS = ["core"]

_ENTITY_BREAKDOWNS = {"AD_ACCOUNT_ID", "CAMPAIGN_ID", "AD_GROUP_ID", "AD_ID"}


def resolve_fields(
    metric_groups: list[str] | None,
    explicit_fields: list[str] | None,
) -> list[str]:
    fields: list[str] = []
    for group in metric_groups or ([] if explicit_fields else DEFAULT_GROUPS):
        if group not in METRIC_GROUPS:
            raise ReportValidationError(
                f"unknown metric group {group!r}; available: "
                f"{sorted(METRIC_GROUPS)}"
            )
        fields.extend(METRIC_GROUPS[group])
    for f in explicit_fields or []:
        if f not in valid_fields():
            raise ReportValidationError(
                f"unknown report field {f!r}; see the reddit-ads://report-fields "
                "resource for the full list"
            )
        fields.append(f)
    # de-dupe, stable order
    return list(dict.fromkeys(fields))


def validate_breakdowns(breakdowns: list[str] | None) -> list[str]:
    bd = list(dict.fromkeys(breakdowns or []))
    unknown = [b for b in bd if b not in valid_breakdowns()]
    if unknown:
        raise ReportValidationError(
            f"unknown breakdowns {unknown}; valid: {sorted(valid_breakdowns())}"
        )
    limit = 4 if {"COUNTRY", "REGION"} <= set(bd) else 3
    if len(bd) > limit:
        raise ReportValidationError(
            f"at most {limit} breakdowns per report (4 only for the "
            "COUNTRY+REGION combination)"
        )
    return bd


def _parse_when(value: str, name: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReportValidationError(
            f"{name} must be an ISO date or datetime, got {value!r}"
        ) from exc


def build_report_request(
    *,
    starts_at: str,
    ends_at: str,
    metric_groups: list[str] | None = None,
    fields: list[str] | None = None,
    breakdowns: list[str] | None = None,
    time_zone_id: str | None = None,
    custom_column_ids: list[str] | None = None,
    filter: str | None = None,
    max_report_days: int = 90,
) -> dict:
    start = _parse_when(starts_at, "starts_at")
    end = _parse_when(ends_at, "ends_at")
    try:
        check_date_range((end - start).total_seconds() / 86400, max_report_days)
    except LimitExceeded as exc:
        raise ReportValidationError(str(exc)) from exc

    data: dict = {
        # Reddit requires the Z-suffix form: YYYY-MM-DDTHH:MM:SSZ
        "starts_at": start.strftime("%Y-%m-%dT%H:%M:%SZ")
        if start.tzinfo
        else start.strftime("%Y-%m-%dT00:00:00Z"),
        "ends_at": end.strftime("%Y-%m-%dT%H:%M:%SZ")
        if end.tzinfo
        else end.strftime("%Y-%m-%dT00:00:00Z"),
        "fields": resolve_fields(metric_groups, fields),
    }
    bd = validate_breakdowns(breakdowns)
    if bd:
        data["breakdowns"] = bd
    if time_zone_id:
        data["time_zone_id"] = time_zone_id
    if custom_column_ids:
        data["custom_column_ids"] = custom_column_ids
    if filter:
        data["filter"] = filter
    return {"data": data}


# Report fields returned in micros of the account currency. Verified against
# the live API 2026-08-06: CPC/eCPM/eCPA values divided by 1e6 reconcile
# exactly with spend/clicks/conversions. Value fields (*_total_value,
# *_avg_value, *_revenue) are NOT converted pending scale verification.
_MICRO_FIELD_SUFFIXES = ("_ecpa",)
_MICRO_FIELD_NAMES = frozenset({"cpc", "ecpm", "cpv"})
_MICRO_FIELD_PREFIXES = ("cost_per_",)


def convert_micro_fields(rows: list[dict]) -> list[str]:
    """Convert micro-denominated cost fields in place.

    Raw values are preserved as <field>_micros. Returns the list of converted
    field names (for provenance).
    """
    converted: set[str] = set()
    for row in rows:
        for key in list(row.keys()):
            if key.endswith("_micros"):
                continue
            is_micro = (
                key in _MICRO_FIELD_NAMES
                or key.endswith(_MICRO_FIELD_SUFFIXES)
                or key.startswith(_MICRO_FIELD_PREFIXES)
            )
            if is_micro and isinstance(row[key], (int, float)):
                row[f"{key}_micros"] = row[key]
                row[key] = round(row[key] / 1_000_000, 4)
                converted.add(key)
    return sorted(converted)


def convert_value_fields(rows: list[dict]) -> list[str]:
    """Convert conversion-value fields from cents in place.

    Scale verified against Ads Manager 2026-08-06: API returned
    conversion_add_to_cart_total_value=8997 for a period Ads Manager shows as
    ~$90 → cents. Raw values preserved as <field>_cents. Revenue fields
    (*_revenue, app install) are NOT converted — unverified scale.
    """
    converted: set[str] = set()
    for row in rows:
        for key in list(row.keys()):
            if key.endswith("_cents") or not key.startswith("conversion_"):
                continue
            if key.endswith(("_total_value", "_avg_value")) and isinstance(
                row[key], (int, float)
            ):
                row[f"{key}_cents"] = row[key]
                row[key] = round(row[key] / 100, 2)
                converted.add(key)
    return sorted(converted)


def freshness_warning(ends_at: str) -> str | None:
    end = _parse_when(ends_at, "ends_at")
    now = datetime.now(tz=end.tzinfo) if end.tzinfo else datetime.now()
    if (now - end).total_seconds() < 6 * 3600:
        return (
            "Metrics can take up to 6 hours to stabilize; figures for the most "
            "recent hours may still change."
        )
    return None


def default_date_range(days: int) -> tuple[str, str]:
    today = date.today()
    start = today.fromordinal(today.toordinal() - days)
    return start.isoformat(), today.isoformat()
