#!/usr/bin/env python3
"""Detect drift between a Reddit Ads OpenAPI spec and the reviewed registry.

Usage:
    python3 scripts/check_openapi_drift.py [path-to-new-spec.json]

Without an argument, verifies the pinned spec against the registry (CI mode:
fails if the registry was not regenerated after a spec change, or if any spec
operation is unclassified).

With a newly downloaded spec, reports added/removed/changed operations that
require manual classification before the pinned spec may be updated.

Exit codes: 0 = no drift, 1 = drift or unclassified operations found.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PINNED = ROOT / "openapi" / "reddit-ads-v3.json"
REGISTRY = ROOT / "src" / "reddit_ads_mcp" / "policy" / "read_operations.json"


def spec_operations(spec: dict) -> dict[tuple[str, str], list[str]]:
    ops: dict[tuple[str, str], list[str]] = {}
    for path, path_ops in spec.get("paths", {}).items():
        for method, op in path_ops.items():
            if method not in ("get", "post", "put", "patch", "delete"):
                continue
            scopes = sorted(
                {
                    s
                    for sec in op.get("security", [])
                    for scheme_scopes in sec.values()
                    for s in scheme_scopes
                }
            )
            ops[(method.upper(), path)] = scopes
    return ops


def main() -> int:
    registry = json.loads(REGISTRY.read_text())
    reg_ops = {(e["method"], e["path"]): e for e in registry["operations"]}
    pinned_sha = hashlib.sha256(PINNED.read_bytes()).hexdigest()

    problems: list[str] = []

    if registry.get("spec_sha256") != pinned_sha:
        problems.append(
            "registry spec_sha256 does not match the pinned spec — "
            "rerun scripts/generate_registry.py and review the diff"
        )

    target = Path(sys.argv[1]) if len(sys.argv) > 1 else PINNED
    new_ops = spec_operations(json.loads(target.read_text()))

    added = sorted(set(new_ops) - set(reg_ops))
    removed = sorted(set(reg_ops) - set(new_ops))
    scope_changed = sorted(
        key
        for key in set(new_ops) & set(reg_ops)
        if new_ops[key] != reg_ops[key]["declared_scopes"]
    )

    for method, path in added:
        problems.append(f"NEW unclassified operation: {method} {path}")
    for method, path in removed:
        problems.append(f"REMOVED operation still in registry: {method} {path}")
    for method, path in scope_changed:
        problems.append(f"SCOPE change: {method} {path}")

    if problems:
        print(f"DRIFT DETECTED against {target.name}:")
        for p in problems:
            print(f"  - {p}")
        print(
            "\nEvery new or changed operation must be manually classified in "
            "scripts/generate_registry.py, then the registry regenerated and "
            "the pinned spec + SHA256SUMS updated in the same commit."
        )
        return 1

    print(f"no drift: {len(reg_ops)} operations match {target.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
