"""Unit tests for the deterministic analysis module."""
import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

from reddit_ads_mcp import analysis  # noqa: E402


class AggregateTests(unittest.TestCase):
    def test_sums_summable_skips_raw_and_reach(self):
        rows = [
            {"impressions": 100, "clicks": 5, "spend": 10.5, "reach": 90,
             "spend_micros": 10500000, "conversion_lead_clicks": 2},
            {"impressions": 200, "clicks": 10, "spend": 20.0, "reach": 150,
             "conversion_lead_clicks": 1},
        ]
        totals = analysis.aggregate(rows)
        self.assertEqual(totals["impressions"], 300)
        self.assertEqual(totals["spend"], 30.5)
        self.assertEqual(totals["conversion_lead_clicks"], 3)
        self.assertNotIn("reach", totals)
        self.assertNotIn("spend_micros", totals)

    def test_derive_rates_with_provenance_and_zero_denominators(self):
        rates, prov = analysis.derive_rates(
            {"spend": 100.0, "clicks": 50, "impressions": 5000,
             "key_conversion_total_count": 4}
        )
        self.assertEqual(rates["cpc"], 2.0)
        self.assertEqual(rates["ctr"], 0.01)
        self.assertEqual(rates["key_conversion_ecpa"], 25.0)
        self.assertTrue(any("cpc" in p for p in prov))
        empty, _ = analysis.derive_rates({"spend": 10.0, "clicks": 0,
                                          "impressions": 0})
        self.assertNotIn("cpc", empty)  # zero denominator -> omitted, not inf


class CompareTests(unittest.TestCase):
    def test_deltas_and_pct(self):
        result = analysis.compare({"spend": 100.0, "clicks": 50},
                                  {"spend": 150.0, "clicks": 25})
        by_metric = {r["metric"]: r for r in result}
        self.assertEqual(by_metric["spend"]["delta"], 50.0)
        self.assertEqual(by_metric["spend"]["pct_change"], 0.5)
        self.assertEqual(by_metric["clicks"]["pct_change"], -0.5)

    def test_zero_base_pct_is_none(self):
        result = analysis.compare({"spend": 0}, {"spend": 10})
        self.assertIsNone(result[0]["pct_change"])
        self.assertEqual(result[0]["delta"], 10)


class RankTests(unittest.TestCase):
    ROWS = [
        {"name": "a", "ecpa": 10.0, "spend": 100.0},
        {"name": "b", "ecpa": 5.0, "spend": 2.0},
        {"name": "c", "ecpa": 20.0, "spend": 500.0},
    ]

    def test_rank_descending_and_min_spend(self):
        top = analysis.rank(self.ROWS, "ecpa", top_n=2)
        self.assertEqual([r["name"] for r in top], ["c", "a"])
        filtered = analysis.rank(self.ROWS, "ecpa", descending=False,
                                 min_spend=50.0)
        self.assertEqual([r["name"] for r in filtered], ["a", "c"])


class TrendTests(unittest.TestCase):
    def test_anomaly_flagging(self):
        rows = [{"date": f"2026-07-{d:02d}", "spend": 100.0} for d in range(1, 11)]
        rows.append({"date": "2026-07-11", "spend": 100.5})
        rows.append({"date": "2026-07-12", "spend": 500.0})  # spike
        result = analysis.trend_series(rows, "spend", window=7)
        anomaly_dates = [a["date"] for a in result["anomalies"]]
        self.assertIn("2026-07-12", anomaly_dates)
        self.assertNotIn("2026-07-11", anomaly_dates)

    def test_short_series_no_anomalies(self):
        rows = [{"date": "2026-07-01", "spend": 1}, {"date": "2026-07-02",
                                                     "spend": 100}]
        self.assertEqual(analysis.trend_series(rows, "spend")["anomalies"], [])


class PacingTests(unittest.TestCase):
    def test_on_pace(self):
        out = analysis.pacing(
            spend=50.0, budget_value=100.0, budget_type="LIFETIME_BUDGET",
            start="2026-07-01T00:00:00Z", end="2026-07-11T00:00:00Z",
            now_iso="2026-07-06T00:00:00+00:00",
        )
        self.assertEqual(out["schedule_elapsed"], 0.5)
        self.assertEqual(out["pace_index"], 1.0)

    def test_missing_schedule_or_budget(self):
        out = analysis.pacing(spend=50.0, budget_value=None, budget_type=None,
                              start=None, end=None,
                              now_iso="2026-07-06T00:00:00+00:00")
        self.assertNotIn("pace_index", out)
        self.assertNotIn("budget_utilization", out)


if __name__ == "__main__":
    unittest.main()
