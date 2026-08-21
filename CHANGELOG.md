# Changelog

## 0.2.2 (unreleased)

- Docs: platform-agnostic client guide (`docs/CONNECT.md`) covering Claude,
  ChatGPT, Cursor, VS Code, Gemini CLI, and generic MCP clients; README and
  deploy guide updated to note the server runs on any container host and
  works with any MCP client. No code changes.

## 0.2.1

- Pagination fix: POST endpoints re-send the request body on every page
  (fixes get_account_history; see API note 12).
- analyze_pacing: budgets converted from micros; daily-budget semantics
  (avg daily spend vs daily cap).
- analyze_creatives: creative format joined from post objects (ads return
  type=null).
- compare_periods: account-level report no longer requests AD_ACCOUNT_ID as
  a field (breakdown-only enum value).

## 0.2.0

- **Phase 2 analysis suite (9 new tools, 15 total)**: `compare_periods`,
  `rank_performance`, `analyze_trends` (moving average + statistical anomaly
  flags), `analyze_pacing` (spend vs budget/schedule), `analyze_conversions`
  (funnel + click/view attribution mix), `analyze_video` (watch funnel),
  `get_creative_context`, `analyze_creatives` (performance × format), and
  `get_account_history` (audit log, emails/full names redacted). All
  server-side arithmetic is deterministic with formulas returned; entity
  names are joined via single list calls; creative text is flagged as
  untrusted content.
- Surface Reddit's field-level validation messages in API errors (no payload
  data is ever echoed) — opaque HTTP 400s previously required manual
  reproduction to debug.
- Targeted error hint for the KEYWORD-breakdown lookback limit; limit
  documented in the `get_report` tool and `docs/API_NOTES.md`.
- Explicit warning on empty report results (no delivery vs. failure).
- Anonymized repository metadata for public release; added `docs/API_NOTES.md`.

## 0.1.x (internal, first working deployment)

- 0.1.5 — conversion values converted from cents (verified against Ads
  Manager); health endpoint moved to `/health` (Cloud Run's front end
  intercepts `/healthz`).
- 0.1.4 — cost metrics (CPC/eCPM/eCPA/…) converted from micros with raw-value
  provenance; value-scale and non-summable-reach warnings.
- 0.1.3 — report rows flattened from Reddit's nested `data[].metrics` shape;
  spend converted from micros; `metrics_updated_at` surfaced.
- 0.1.2 — report datetimes switched to the `Z` suffix form the live API
  requires.
- 0.1.1 — MCP SDK pinned to `>=1.9,<2` (SDK 2.0 is API-incompatible).
- 0.1.0 — initial build: read-only operation registry (99 operations
  classified), mutually exclusive bearer / secret-path auth, account
  allowlist, rate/loop safeguards, six tools, stdio + streamable-HTTP
  transports, Cloud Run deployment docs.
