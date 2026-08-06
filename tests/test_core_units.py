"""Unit tests: config/auth modes, limits, HTTP policy, reporting builder."""
import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

from reddit_ads_mcp import reporting  # noqa: E402
from reddit_ads_mcp.auth.mcp_bearer import check_request, mcp_mount_path  # noqa: E402
from reddit_ads_mcp.auth.reddit_oauth import OAuthError, parse_token_response  # noqa: E402
from reddit_ads_mcp.config import ConfigError, load_settings  # noqa: E402
from reddit_ads_mcp.policy.accounts import AccountNotAllowed, resolve_account  # noqa: E402
from reddit_ads_mcp.policy.limits import (  # noqa: E402
    DuplicateSuppressor,
    LimitExceeded,
    RollingWindowLimiter,
    SubrequestBudget,
)
from reddit_ads_mcp.reddit import http_policy  # noqa: E402

TOKEN = "x" * 40
PATH_SECRET = "A" * 43
BASE_ENV = {
    "REDDIT_CLIENT_ID": "cid",
    "REDDIT_CLIENT_SECRET": "cs",
    "REDDIT_REFRESH_TOKEN": "rt",
    "REDDIT_USER_AGENT": "cloudrun:reddit-ads-insights-mcp:0.1.0 (by /u/example)",
    "ALLOWED_ACCOUNT_IDS": "a2_abc123",
}


def settings_with(**extra):
    return load_settings({**BASE_ENV, **extra})


class ConfigTests(unittest.TestCase):
    def test_minimal_stdio_config(self):
        s = settings_with()
        self.assertEqual(s.transport, "stdio")
        self.assertEqual(s.default_account_id, "a2_abc123")

    def test_bad_user_agent_rejected(self):
        with self.assertRaises(ConfigError):
            settings_with(REDDIT_USER_AGENT="Mozilla/5.0")

    def test_allowlist_required(self):
        with self.assertRaises(ConfigError):
            load_settings({**BASE_ENV, "ALLOWED_ACCOUNT_IDS": ""})

    def test_http_requires_credential(self):
        with self.assertRaises(ConfigError):
            settings_with(MCP_TRANSPORT="http")

    def test_http_bearer_ok(self):
        s = settings_with(MCP_TRANSPORT="http", MCP_ACCESS_TOKEN=TOKEN)
        self.assertEqual(s.mcp_auth_mode, "bearer")
        self.assertIsNone(s.mcp_path_secret)

    def test_modes_mutually_exclusive(self):
        with self.assertRaises(ConfigError):
            settings_with(
                MCP_TRANSPORT="http",
                MCP_ACCESS_TOKEN=TOKEN,
                MCP_PATH_SECRET=PATH_SECRET,
            )

    def test_secret_path_mode(self):
        s = settings_with(
            MCP_TRANSPORT="http",
            MCP_AUTH_MODE="secret_path",
            MCP_PATH_SECRET=PATH_SECRET,
        )
        self.assertEqual(s.mcp_auth_mode, "secret_path")
        self.assertIsNone(s.mcp_access_token)
        self.assertTrue(s.warnings)

    def test_weak_path_secret_rejected(self):
        with self.assertRaises(ConfigError):
            settings_with(
                MCP_TRANSPORT="http",
                MCP_AUTH_MODE="secret_path",
                MCP_PATH_SECRET="reddit",
            )


class AuthModeTests(unittest.TestCase):
    def test_bearer_accepts_correct_token_on_mcp(self):
        s = settings_with(MCP_TRANSPORT="http", MCP_ACCESS_TOKEN=TOKEN)
        self.assertTrue(check_request(s, "/mcp", f"Bearer {TOKEN}").allowed)

    def test_bearer_rejects_wrong_or_missing(self):
        s = settings_with(MCP_TRANSPORT="http", MCP_ACCESS_TOKEN=TOKEN)
        self.assertEqual(check_request(s, "/mcp", "Bearer nope").status, 401)
        self.assertEqual(check_request(s, "/mcp", None).status, 401)

    def test_bearer_mode_never_serves_secret_paths(self):
        s = settings_with(MCP_TRANSPORT="http", MCP_ACCESS_TOKEN=TOKEN)
        self.assertEqual(
            check_request(s, f"/{PATH_SECRET}/mcp", f"Bearer {TOKEN}").status, 404
        )

    def test_secret_path_exact_match_only(self):
        s = settings_with(
            MCP_TRANSPORT="http",
            MCP_AUTH_MODE="secret_path",
            MCP_PATH_SECRET=PATH_SECRET,
        )
        self.assertEqual(mcp_mount_path(s), f"/{PATH_SECRET}/mcp")
        self.assertTrue(check_request(s, f"/{PATH_SECRET}/mcp", None).allowed)
        for path in ("/mcp", f"/{PATH_SECRET}", f"/{PATH_SECRET[:-1]}/mcp",
                     f"/{PATH_SECRET}/mcp/extra"):
            decision = check_request(s, path, None)
            self.assertFalse(decision.allowed, path)
            self.assertEqual(decision.status, 404, path)


class AccountTests(unittest.TestCase):
    def test_allowlist_enforced(self):
        s = settings_with()
        self.assertEqual(resolve_account(s, None), "a2_abc123")
        self.assertEqual(resolve_account(s, "a2_abc123"), "a2_abc123")
        with self.assertRaises(AccountNotAllowed):
            resolve_account(s, "a2_other")


class LimitTests(unittest.TestCase):
    def test_rolling_window(self):
        limiter = RollingWindowLimiter(2, window_seconds=3600)
        limiter.acquire(now=0)
        limiter.acquire(now=1)
        with self.assertRaises(LimitExceeded):
            limiter.acquire(now=2)
        limiter.acquire(now=3700)  # window rolled

    def test_subrequest_budget(self):
        budget = SubrequestBudget(2)
        budget.spend()
        budget.spend()
        with self.assertRaises(LimitExceeded):
            budget.spend()

    def test_duplicate_suppressor(self):
        sup = DuplicateSuppressor(window_seconds=2)
        key = DuplicateSuppressor.key("tool", {"a": 1})
        self.assertFalse(sup.is_rapid_duplicate(key, now=0))
        self.assertTrue(sup.is_rapid_duplicate(key, now=1))
        self.assertFalse(sup.is_rapid_duplicate(key, now=10))


class HttpPolicyTests(unittest.TestCase):
    FAMILY = "/ad_accounts/a2_x/campaigns"

    def test_valid_next_url(self):
        url = f"https://ads-api.reddit.com/api/v3{self.FAMILY}?page.token=abc"
        self.assertEqual(http_policy.validate_next_url(url, self.FAMILY), url)

    def test_rejects_http_and_foreign_hosts(self):
        for bad in (
            f"http://ads-api.reddit.com/api/v3{self.FAMILY}",
            f"https://evil.example/api/v3{self.FAMILY}",
            f"https://user:pw@ads-api.reddit.com/api/v3{self.FAMILY}",
            f"https://ads-api.reddit.com:8443/api/v3{self.FAMILY}",
            "https://ads-api.reddit.com/api/v3/pixels/px_1",
            f"https://ads-api.reddit.com/api/v3{self.FAMILY}#frag",
        ):
            with self.assertRaises(http_policy.UnsafeUrl):
                http_policy.validate_next_url(bad, self.FAMILY)

    def test_rate_limit_parsing(self):
        state = http_policy.parse_rate_limit(
            {"RateLimit": "limit=60, remaining=12, reset=31",
             "RateLimit-Policy": "burst;q=60;w=60"}
        )
        self.assertEqual(state.remaining, 12)
        self.assertEqual(state.reset_seconds, 31)
        empty = http_policy.parse_rate_limit({})
        self.assertIsNone(empty.remaining)

    def test_error_body_summary(self):
        body = ('{"error":{"code":400,"message":"Bad Request","fields":'
                '[{"field":"starts_at","message":"starts_at must be a valid '
                'datetime. Format: YYYY-MM-DDTHH:MM:SSZ"}]}}')
        summary = http_policy.summarize_error_body(body)
        self.assertIn("starts_at", summary)
        self.assertIn("YYYY-MM-DDTHH:MM:SSZ", summary)
        # Non-JSON, generic, and empty bodies yield nothing (no payload echo)
        self.assertIsNone(http_policy.summarize_error_body("<html>oops</html>"))
        self.assertIsNone(
            http_policy.summarize_error_body('{"error":{"message":"Bad Request"}}')
        )
        self.assertIsNone(http_policy.summarize_error_body('{"data":[1,2,3]}'))

    def test_retry_policy(self):
        self.assertTrue(http_policy.should_retry(429, 1))
        self.assertTrue(http_policy.should_retry(503, 2))
        self.assertFalse(http_policy.should_retry(400, 1))
        self.assertFalse(http_policy.should_retry(429, 4))


class OAuthTests(unittest.TestCase):
    def test_valid_response(self):
        token, ttl, scopes = parse_token_response(
            {"access_token": "t", "expires_in": 3600, "scope": "adsread"}
        )
        self.assertEqual((token, ttl), ("t", 3600.0))

    def test_missing_scope_rejected(self):
        with self.assertRaises(OAuthError):
            parse_token_response(
                {"access_token": "t", "expires_in": 3600, "scope": "read"}
            )

    def test_write_scope_grant_refused(self):
        with self.assertRaises(OAuthError):
            parse_token_response(
                {"access_token": "t", "expires_in": 3600,
                 "scope": "adsread adsedit"}
            )


class ReportingTests(unittest.TestCase):
    def test_metric_groups_are_valid_spec_fields(self):
        valid = reporting.valid_fields()
        for group, fields in reporting.METRIC_GROUPS.items():
            for f in fields:
                self.assertIn(f, valid, f"{group}:{f}")

    def test_breakdown_rules(self):
        reporting.validate_breakdowns(["CAMPAIGN_ID", "DATE", "COMMUNITY"])
        reporting.validate_breakdowns(["CAMPAIGN_ID", "DATE", "COUNTRY", "REGION"])
        with self.assertRaises(reporting.ReportValidationError):
            reporting.validate_breakdowns(["CAMPAIGN_ID", "DATE", "HOUR", "GENDER"])
        with self.assertRaises(reporting.ReportValidationError):
            reporting.validate_breakdowns(["SUBREDDIT"])

    def test_build_request(self):
        body = reporting.build_report_request(
            starts_at="2026-07-01",
            ends_at="2026-07-14",
            metric_groups=["core"],
            breakdowns=["DATE", "COMMUNITY"],
        )
        # Reddit's live API requires the Z-suffix datetime form (verified
        # against production 2026-08-06; a 400 names this format explicitly).
        self.assertEqual(body["data"]["starts_at"], "2026-07-01T00:00:00Z")
        self.assertIn("IMPRESSIONS", body["data"]["fields"])

    def test_range_ceiling(self):
        with self.assertRaises(reporting.ReportValidationError):
            reporting.build_report_request(
                starts_at="2026-01-01", ends_at="2026-07-01", max_report_days=90
            )

    def test_micro_field_conversion(self):
        rows = [
            {"cpc": 2224250.66, "ecpm": 20027680.7, "spend_micros": 1,
             "conversion_lead_ecpa": 266111524.0, "clicks": 136,
             "conversion_lead_total_value": 89988}
        ]
        converted = reporting.convert_micro_fields(rows)
        self.assertEqual(converted, ["conversion_lead_ecpa", "cpc", "ecpm"])
        self.assertAlmostEqual(rows[0]["cpc"], 2.2243, places=4)
        self.assertAlmostEqual(rows[0]["conversion_lead_ecpa"], 266.1115, places=4)
        self.assertEqual(rows[0]["cpc_micros"], 2224250.66)
        # untouched: counts, raw *_micros, and value fields pending scale check
        self.assertEqual(rows[0]["clicks"], 136)
        self.assertEqual(rows[0]["spend_micros"], 1)
        self.assertEqual(rows[0]["conversion_lead_total_value"], 89988)

    def test_unknown_field_rejected(self):
        with self.assertRaises(reporting.ReportValidationError):
            reporting.build_report_request(
                starts_at="2026-07-01", ends_at="2026-07-02", fields=["UPVOTES"]
            )


if __name__ == "__main__":
    unittest.main()
