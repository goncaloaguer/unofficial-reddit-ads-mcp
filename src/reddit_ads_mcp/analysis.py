"""Deterministic analysis: aggregation, comparison, ranking, trends, pacing.

Pure stdlib functions. Every derived value's formula is returned alongside it
(PLAN.md §2.5); zero denominators yield None, never infinity.
"""
from __future__ import annotations

from statistics import mean, pstdev
from typing import Any

SUMMABLE = frozenset(
    {"impressions", "clicks", "spend", "engaged_click", "video_started",
     "key_conversion_total_count"}
)
NON_SUMMABLE = frozenset({"reach", "frequency"})


def safe_div(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or not denominator:
        return None
    return numerator / denominator


def aggregate(rows: list[dict], keys: list[str] | None = None) -> dict[str, float]:
    """Sum summable metrics across rows (conversion counts included)."""
    totals: dict[str, float] = {}
    for row in rows:
        for key, value in row.items():
            if not isinstance(value, (int, float)) or key.endswith(
                ("_micros", "_cents")
            ):
                continue
            summable = (
                key in SUMMABLE
                or (keys is not None and key in keys)
                or (
                    key.startswith("conversion_")
                    and key.endswith(("_clicks", "_views", "_total_value",
                                      "_total_items"))
                )
            )
            if summable and key not in NON_SUMMABLE:
                totals[key] = round(totals.get(key, 0) + value, 4)
    return totals


def derive_rates(totals: dict[str, float]) -> tuple[dict[str, float], list[dict]]:
    """Compute standard rates from aggregated totals with provenance."""
    derived: dict[str, float] = {}
    provenance: list[dict] = []

    def put(name: str, value: float | None, formula: str, digits: int = 4) -> None:
        if value is not None:
            derived[name] = round(value, digits)
            provenance.append({name: formula})

    spend = totals.get("spend")
    clicks = totals.get("clicks")
    impressions = totals.get("impressions")
    conversions = totals.get("key_conversion_total_count")
    put("ctr", safe_div(clicks, impressions), "sum(clicks)/sum(impressions)", 6)
    put("cpc", safe_div(spend, clicks), "sum(spend)/sum(clicks)")
    put("ecpm", safe_div((spend or 0) * 1000 if spend is not None else None,
                         impressions), "sum(spend)*1000/sum(impressions)")
    put("key_conversion_ecpa", safe_div(spend, conversions),
        "sum(spend)/sum(key_conversion_total_count)")
    put("key_conversion_rate", safe_div(conversions, impressions),
        "sum(key_conversion_total_count)/sum(impressions)", 6)
    return derived, provenance


def compare(
    period_a: dict[str, float], period_b: dict[str, float]
) -> list[dict[str, Any]]:
    """Compare metric dicts: absolute and percentage deltas (b relative to a)."""
    out: list[dict[str, Any]] = []
    for key in sorted(set(period_a) | set(period_b)):
        a, b = period_a.get(key), period_b.get(key)
        entry: dict[str, Any] = {"metric": key, "period_a": a, "period_b": b}
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            entry["delta"] = round(b - a, 4)
            entry["pct_change"] = (
                round((b - a) / abs(a), 4) if a else None
            )
        out.append(entry)
    return out


def rank(
    rows: list[dict],
    metric: str,
    *,
    descending: bool = True,
    top_n: int = 20,
    min_spend: float = 0.0,
) -> list[dict]:
    eligible = [
        r
        for r in rows
        if isinstance(r.get(metric), (int, float))
        and (r.get("spend") or 0) >= min_spend
    ]
    return sorted(eligible, key=lambda r: r[metric], reverse=descending)[:top_n]


def trend_series(
    rows: list[dict], metric: str, time_key: str = "date", window: int = 7
) -> dict[str, Any]:
    """Ordered series + moving average + simple anomaly flags.

    Anomaly rule: |value - moving_avg| > 2 * stdev of the prior window
    (requires >= window prior points; flagged points list the rule used).
    """
    ordered = sorted(
        (r for r in rows if isinstance(r.get(metric), (int, float))),
        key=lambda r: str(r.get(time_key, "")),
    )
    values = [float(r[metric]) for r in ordered]
    series, anomalies = [], []
    for i, row in enumerate(ordered):
        point: dict[str, Any] = {time_key: row.get(time_key), metric: values[i]}
        prior = values[max(0, i - window) : i]
        if len(prior) >= window:
            avg = mean(prior)
            sd = pstdev(prior)
            point[f"moving_avg_{window}"] = round(avg, 4)
            if sd > 0 and abs(values[i] - avg) > 2 * sd:
                point["anomaly"] = True
                anomalies.append(
                    {
                        time_key: row.get(time_key),
                        "value": values[i],
                        "expected": round(avg, 4),
                        "rule": f"|value - {window}-period mean| > 2 * stdev",
                    }
                )
        series.append(point)
    return {"series": series, "anomalies": anomalies}


def pacing(
    *,
    spend: float,
    budget_value: float | None,
    budget_type: str | None,
    start: str | None,
    end: str | None,
    now_iso: str,
) -> dict[str, Any]:
    """Spend vs elapsed schedule. All inputs already in currency units."""
    from datetime import datetime

    def parse(v: str | None):
        if not v:
            return None
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return None

    now = parse(now_iso)
    s, e = parse(start), parse(end)
    out: dict[str, Any] = {
        "spend": spend,
        "budget_value": budget_value,
        "budget_type": budget_type,
    }
    if budget_value:
        out["budget_utilization"] = round(spend / budget_value, 4)
        out["_formula"] = "spend / budget_value"
    if s and e and now and e > s:
        elapsed = max(0.0, min(1.0, (now - s).total_seconds() / (e - s).total_seconds()))
        out["schedule_elapsed"] = round(elapsed, 4)
        if budget_value and elapsed > 0:
            out["pace_index"] = round((spend / budget_value) / elapsed, 4)
            out["_pace_formula"] = (
                "(spend/budget_value)/schedule_elapsed; 1.0 = on pace"
            )
    return out
