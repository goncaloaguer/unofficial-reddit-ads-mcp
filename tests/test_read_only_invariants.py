"""Read-only invariant tests (PLAN.md §14.2). These must never be weakened."""
import json
import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

from reddit_ads_mcp.policy import registry  # noqa: E402

REGISTRY_PATH = SRC / "reddit_ads_mcp" / "policy" / "read_operations.json"

FORBIDDEN_PATH_FRAGMENTS = [
    "conversion_events",
    "data_deletion_jobs",
    "custom_audiences/{audience_id}/users",
    "batch_upsert",
    "batch_delete",
    "structured_posts/jobs",
]


class ReadOnlyInvariants(unittest.TestCase):
    def setUp(self):
        self.raw = json.loads(REGISTRY_PATH.read_text())
        self.enabled = [
            e for e in self.raw["operations"] if e["classification"] == "enabled"
        ]

    def test_no_enabled_write_methods(self):
        for e in self.enabled:
            self.assertIn(e["method"], ("GET", "POST"), e)

    def test_every_spec_write_method_is_denied(self):
        for e in self.raw["operations"]:
            if e["method"] in ("PATCH", "PUT", "DELETE"):
                self.assertEqual(e["classification"], "denied", e)

    def test_forbidden_paths_never_enabled(self):
        for e in self.enabled:
            for fragment in FORBIDDEN_PATH_FRAGMENTS:
                if fragment in e["path"]:
                    self.fail(f"forbidden operation enabled: {e}")

    def test_enabled_posts_are_the_reviewed_readlike_set(self):
        posts = sorted(
            e["path"] for e in self.enabled if e["method"] == "POST"
        )
        self.assertEqual(
            posts,
            sorted(
                [
                    "/ad_accounts/{ad_account_id}/reports",
                    "/ad_accounts/{ad_account_id}/history",
                    "/forecasting/bid_suggestions",
                    "/targeting/keyword_suggestions",
                    "/targeting/keyword_validations",
                    "/targeting/geolocations_validations",
                    "/businesses/{business_id}/ad_accounts/query",
                    "/businesses/{business_id}/funding_instruments/query",
                ]
            ),
        )

    def test_registry_loader_rejects_writes(self):
        for method in ("PATCH", "DELETE", "PUT"):
            with self.assertRaises(registry.OperationDenied):
                registry.authorize(method, "/campaigns/c_1")

    def test_denied_operation_raises(self):
        with self.assertRaises(registry.OperationDenied):
            registry.authorize("POST", "/pixels/px_1/conversion_events")
        with self.assertRaises(registry.OperationDenied):
            registry.authorize("POST", "/ad_accounts/a2_x/campaigns")

    def test_enabled_operation_matches(self):
        op = registry.authorize("GET", "/ad_accounts/a2_abc123/campaigns")
        self.assertEqual(op.method, "GET")
        op = registry.authorize("POST", "/ad_accounts/a2_abc123/reports")
        self.assertEqual(op.rate_group, "reporting")

    def test_path_traversal_rejected(self):
        for bad in ("/ad_accounts/../pixels", "//ad_accounts", "campaigns"):
            with self.assertRaises(registry.OperationDenied):
                registry.authorize("GET", bad)

    def test_oauth_scope_constant_is_adsread_only(self):
        from reddit_ads_mcp.config import REQUIRED_REDDIT_SCOPE

        self.assertEqual(REQUIRED_REDDIT_SCOPE, "adsread")

    def test_source_contains_no_write_scope_requests(self):
        for path in (SRC / "reddit_ads_mcp").rglob("*.py"):
            text = path.read_text()
            for scope in ("adsedit", "adsconversions", "adsdatadeletion"):
                # Scopes may be named only to *refuse* them (oauth guard).
                if scope in text and path.name != "reddit_oauth.py":
                    self.fail(f"{path} references write scope {scope}")


if __name__ == "__main__":
    unittest.main()
