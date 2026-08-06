# Contributing

Thanks for your interest! Ground rules:

- **Read-only is non-negotiable.** PRs adding write operations (create,
  update, delete, pause, budget, audience upload, conversion ingestion) will
  be declined regardless of quality; see PLAN.md §2.1. A management server
  belongs in a separate project.
- **Never include real advertiser data** in issues, PRs, fixtures, or test
  cases — synthetic data only.
- Run `python -m unittest discover tests` and
  `python scripts/check_openapi_drift.py` before submitting.
- Spec updates: replace `openapi/reddit-ads-v3.json`, update
  `openapi/SHA256SUMS`, classify any new/changed operations in
  `scripts/generate_registry.py`, regenerate the registry, and update
  `docs/API_NOTES.md` if live behavior differs — all in one PR.
- New live-API discoveries (unit scaling, limits, response quirks) belong in
  `docs/API_NOTES.md` with how you verified them.
