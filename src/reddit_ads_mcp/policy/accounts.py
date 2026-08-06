"""Ad-account isolation. Every tool resolves and validates its account here."""
from __future__ import annotations

from reddit_ads_mcp.config import Settings


class AccountNotAllowed(PermissionError):
    pass


def resolve_account(settings: Settings, account_id: str | None) -> str:
    """Resolve an explicit or default account and enforce the allowlist."""
    resolved = (account_id or settings.default_account_id or "").strip()
    if not resolved:
        raise AccountNotAllowed(
            "no account_id given and no DEFAULT_ACCOUNT_ID configured; "
            f"allowed accounts: {sorted(settings.allowed_account_ids)}"
        )
    if resolved not in settings.allowed_account_ids:
        raise AccountNotAllowed(
            f"account {resolved!r} is not in ALLOWED_ACCOUNT_IDS; this "
            "deployment is restricted to explicitly allowlisted accounts"
        )
    return resolved


def filter_allowed(settings: Settings, accounts: list[dict]) -> list[dict]:
    """Filter a discovery response down to allowlisted accounts only."""
    return [a for a in accounts if a.get("id") in settings.allowed_account_ids]
