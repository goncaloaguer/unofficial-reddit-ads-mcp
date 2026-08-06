#!/usr/bin/env python3
"""Generate the read-operation registry scaffold from the pinned OpenAPI spec.

Every operation in the spec is explicitly classified. The output registry
(src/reddit_ads_mcp/policy/read_operations.json) is the single source of truth
for which upstream Reddit Ads API operations this server may ever call.

Classification policy (see PLAN.md §4.1):
- All PATCH/PUT/DELETE operations are DENIED, always.
- POST operations are DENIED unless explicitly listed in READ_LIKE_POSTS
  (reporting, history, suggestions, validations, scoped queries).
- GET operations are ALLOWED unless listed in DENIED_GETS.
- The generated file is version-controlled; humans review every change.

Run: python3 scripts/generate_registry.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = ROOT / "openapi" / "reddit-ads-v3.json"
OUT_PATH = ROOT / "src" / "reddit_ads_mcp" / "policy" / "read_operations.json"

# POST operations that are semantically reads (no server-side state mutation).
# Each entry was manually reviewed against the spec. Anything not listed here
# that uses POST is denied.
READ_LIKE_POSTS: dict[str, str] = {
    "/ad_accounts/{ad_account_id}/reports": "Performance reporting query",
    "/ad_accounts/{ad_account_id}/history": "Account change-history query",
    "/forecasting/bid_suggestions": "Bid suggestion query",
    "/targeting/keyword_suggestions": "Keyword suggestion query",
    "/targeting/keyword_validations": "Keyword validation query",
    "/targeting/geolocations_validations": "Geolocation validation query",
    "/businesses/{business_id}/ad_accounts/query": "Scoped ad-account query",
    "/businesses/{business_id}/funding_instruments/query": "Scoped funding-instrument query",
}

# GET operations we deliberately do not enable in v1 (still read-only, but
# unnecessary for the tool surface, sensitive, or requiring a scope this
# server refuses to hold). classification: "disabled".
DISABLED_GETS: dict[str, str] = {
    "/data_deletion_jobs/{job_id}": (
        "Requires adsdatadeletion scope; data-deletion workflow is out of "
        "scope for this read-only server"
    ),
    "/structured_posts/jobs/{post_creation_job_id}": (
        "Creation-job status only exists for write workflows; unnecessary "
        "surface for a read-only server"
    ),
}

# Data-sensitivity classes used for output-shaping decisions downstream.
SENSITIVITY_OVERRIDES: dict[str, str] = {
    "/me": "identity",
    "/me/businesses": "identity",
    "/ad_accounts/{ad_account_id}/history": "audit",
    "/ad_accounts/{ad_account_id}/custom_audiences": "audience_metadata",
    "/custom_audiences/{audience_id}": "audience_metadata",
    "/ad_accounts/{ad_account_id}/lead_gen_forms": "legacy",
    "/lead_gen_forms/{lead_gen_form_id}": "legacy",
}

RATE_GROUPS: list[tuple[str, str]] = [
    ("/reports", "reporting"),
    ("/history", "reporting"),
    ("/forecasting", "forecasting"),
    ("/targeting", "taxonomy"),
    ("/channel_planning", "forecasting"),
    ("/time_zones", "taxonomy"),
    ("/industries", "taxonomy"),
    ("/feature_access", "taxonomy"),
]


def rate_group(path: str) -> str:
    for fragment, group in RATE_GROUPS:
        if fragment in path:
            return group
    return "entity"


def main() -> None:
    spec = json.loads(SPEC_PATH.read_text())
    spec_sha = hashlib.sha256(SPEC_PATH.read_bytes()).hexdigest()

    entries = []
    counts = {"enabled": 0, "denied": 0, "disabled": 0}

    for path, ops in sorted(spec["paths"].items()):
        for method, op in sorted(ops.items()):
            if method not in ("get", "post", "put", "patch", "delete"):
                continue
            op_id = op.get("operationId") or f"{method}_{path}"
            scopes = sorted(
                {
                    s
                    for sec in op.get("security", [])
                    for scheme_scopes in sec.values()
                    for s in scheme_scopes
                }
            )
            paginated = any(
                prm.get("name") in ("page.size", "page.token", "page.cursor")
                for prm in op.get("parameters", [])
                if isinstance(prm, dict)
            )

            if method in ("patch", "put", "delete"):
                classification, reason = "denied", "Mutating HTTP method"
            elif method == "post":
                if path in READ_LIKE_POSTS:
                    classification, reason = "enabled", READ_LIKE_POSTS[path]
                else:
                    classification, reason = "denied", "POST create/ingest operation"
            else:  # get
                if path in DISABLED_GETS:
                    classification, reason = "disabled", DISABLED_GETS[path]
                else:
                    classification, reason = "enabled", "Read operation"

            # Safety net: a spec bug must never enable a write (e.g. the
            # PATCH-with-adsread annotation known in the current spec).
            if classification == "enabled" and method not in ("get", "post"):
                raise AssertionError(f"refusing to enable {method} {path}")

            counts[classification] += 1
            entries.append(
                {
                    "operation_id": op_id,
                    "method": method.upper(),
                    "path": path,
                    "classification": classification,
                    "reason": reason,
                    "declared_scopes": scopes,
                    "rate_group": rate_group(path),
                    "paginated": paginated,
                    "sensitivity": SENSITIVITY_OVERRIDES.get(path, "standard"),
                }
            )

    registry = {
        "$comment": "Generated by scripts/generate_registry.py; human-reviewed. "
        "The server refuses any upstream call not matching an enabled entry.",
        "spec_sha256": spec_sha,
        "spec_version": spec.get("info", {}).get("version"),
        "counts": counts,
        "operations": entries,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(registry, indent=2) + "\n")

    print(f"spec sha256: {spec_sha}")
    print(f"classified {sum(counts.values())} operations: {counts}")
    enabled_posts = [
        e for e in entries if e["classification"] == "enabled" and e["method"] == "POST"
    ]
    print("\nenabled POST (read-like) operations:")
    for e in enabled_posts:
        print(f"  POST {e['path']}  — {e['reason']}")
    denied_reads_annotated = [
        e
        for e in entries
        if e["classification"] == "denied" and "adsread" in e["declared_scopes"]
    ]
    if denied_reads_annotated:
        print("\nDENIED despite adsread annotation (spec inconsistencies):")
        for e in denied_reads_annotated:
            print(f"  {e['method']} {e['path']}")
    return


if __name__ == "__main__":
    sys.exit(main())
