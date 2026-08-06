"""Pure HTTP-policy helpers: pagination URL validation, rate-limit parsing,
backoff. Stdlib-only so they are fully unit-testable without network deps.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

ALLOWED_HOST = "ads-api.reddit.com"
ALLOWED_PATH_PREFIX = "/api/v3/"


class UnsafeUrl(ValueError):
    pass


def validate_next_url(next_url: str, current_path_family: str) -> str:
    """Validate a Reddit-returned pagination URL before following it.

    Rules (PLAN.md §10.1): HTTPS only; exact Reddit Ads host; no credentials,
    fragments, or unexpected ports; path must stay within the API prefix and
    the same path family as the operation being paginated.
    """
    parts = urlsplit(next_url)
    if parts.scheme != "https":
        raise UnsafeUrl(f"pagination URL must be https: {next_url!r}")
    if parts.username or parts.password:
        raise UnsafeUrl("pagination URL must not embed credentials")
    if parts.fragment:
        raise UnsafeUrl("pagination URL must not contain a fragment")
    if parts.hostname != ALLOWED_HOST:
        raise UnsafeUrl(f"pagination URL host not allowed: {parts.hostname!r}")
    if parts.port not in (None, 443):
        raise UnsafeUrl(f"pagination URL port not allowed: {parts.port}")
    if not parts.path.startswith(ALLOWED_PATH_PREFIX):
        raise UnsafeUrl(f"pagination URL outside API prefix: {parts.path!r}")
    api_path = parts.path[len(ALLOWED_PATH_PREFIX) - 1 :]  # keep leading '/'
    family = current_path_family.rstrip("/")
    if api_path.rstrip("/") != family:
        raise UnsafeUrl(
            f"pagination URL path {api_path!r} left the current operation "
            f"family {family!r}"
        )
    return next_url


@dataclass(frozen=True)
class RateLimitState:
    """Parsed from RateLimit / RateLimit-Policy headers (IETF draft format)."""

    policy: str | None
    remaining: int | None
    reset_seconds: int | None


_RATELIMIT_ITEM = re.compile(r"(?:^|[;,]\s*)(limit|remaining|reset|r|t)\s*=\s*(\d+)")


def parse_rate_limit(headers: dict[str, str]) -> RateLimitState:
    """Parse rate-limit headers case-insensitively; tolerate absent headers."""
    lowered = {k.lower(): v for k, v in headers.items()}
    value = lowered.get("ratelimit") or lowered.get("x-ratelimit-remaining") or ""
    policy = lowered.get("ratelimit-policy")

    remaining = reset = None
    if value:
        fields = dict(_RATELIMIT_ITEM.findall(value))
        remaining = int(fields.get("remaining", fields.get("r", -1)))
        remaining = None if remaining < 0 else remaining
        reset = int(fields.get("reset", fields.get("t", -1)))
        reset = None if reset < 0 else reset
        if remaining is None and value.strip().isdigit():
            remaining = int(value.strip())
    reset_header = lowered.get("x-ratelimit-reset")
    if reset is None and reset_header and reset_header.isdigit():
        reset = int(reset_header)
    return RateLimitState(policy=policy, remaining=remaining, reset_seconds=reset)


def backoff_delay(attempt: int, base: float = 0.5, cap: float = 30.0) -> float:
    """Capped exponential backoff with full jitter. attempt starts at 1."""
    return random.uniform(0, min(cap, base * (2 ** (attempt - 1))))


def summarize_error_body(body_text: str, max_len: int = 400) -> str | None:
    """Extract Reddit's structured validation detail from an error body.

    Returns only field-level validation messages (e.g. "starts_at: must be a
    valid datetime...") — never row data, tokens, or free-form payloads.
    Rationale: opaque 400s made live debugging require manual curl
    reproduction (learned 2026-08-06); Reddit's `error.fields` messages are
    safe, actionable metadata.
    """
    import json as _json

    try:
        payload = _json.loads(body_text)
    except (ValueError, TypeError):
        return None
    error = payload.get("error")
    if not isinstance(error, dict):
        return None
    parts: list[str] = []
    message = error.get("message")
    if isinstance(message, str) and message and message != "Bad Request":
        parts.append(message)
    for field in error.get("fields") or []:
        if isinstance(field, dict):
            name = field.get("field", "?")
            msg = field.get("message", "")
            if isinstance(msg, str):
                parts.append(f"{name}: {msg}")
    if not parts:
        return None
    return "; ".join(parts)[:max_len]


RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
NO_RETRY_STATUS = frozenset({400, 401, 403, 404})


def should_retry(status: int, attempt: int, max_attempts: int = 4) -> bool:
    return status in RETRYABLE_STATUS and attempt < max_attempts
