# Reddit Ads API v3 — live behavior notes

Realities of the production API that differ from (or are absent in) the
downloadable OpenAPI specification and third-party documentation. All were
verified against the live API in August 2026 and are encoded in this
codebase and its tests.

| # | Observation | Consequence in this code |
|---|---|---|
| 1 | Report `starts_at`/`ends_at` require the **`YYYY-MM-DDTHH:MM:SSZ`** form. `+00:00` offsets are rejected with HTTP 400, despite some third-party docs claiming the opposite. | `reporting.build_report_request` emits `Z`-suffixed datetimes; locked by unit test. |
| 2 | Report responses nest rows one level deeper than entity endpoints: `data → [{metrics: [...], metrics_updated_at}]`. | The report tool flattens `metrics` and surfaces `metrics_updated_at` in `meta`. |
| 3 | **Spend and cost metrics are micros** of the account currency (`SPEND`, `CPC`, `ECPM`, `CPV`, `COST_PER_*`, all `*_ECPA`). Verified to the cent against derived values. | Converted with provenance; raw values preserved as `*_micros`. |
| 4 | **Conversion values are cents** (`*_TOTAL_VALUE`, `*_AVG_VALUE`), verified against Ads Manager. `*_REVENUE` fields remain unverified. | Converted with provenance (`*_cents` preserved); revenue fields left raw with a warning. |
| 5 | **`KEYWORD` breakdowns only work for a recent lookback window** (~10 days observed). Older ranges return HTTP 400; keyword-level history is effectively unretrievable after the fact. | Documented in the tool; a targeted error hint explains the limit. Operational advice: pull keyword reports promptly (e.g. weekly) while campaigns deliver. |
| 6 | Reddit's 400 responses carry structured, safe validation detail in `error.fields`. | `summarize_error_body` surfaces field-level messages in MCP errors (never payload data). |
| 7 | The spec annotates `PATCH /saved_audiences/{id}` with the `adsread` scope — a write operation with a read scope annotation. | The read-only registry classifies by HTTP method, never by declared scope. |
| 8 | Google Cloud Run's front end **reserves the exact path `/healthz`** on `run.app` domains and answers 404 before the container sees the request. | Health endpoint is `/health`. |
| 9 | `gcloud run services describe --format='value(status.url)'` may return the legacy `*-<hash>-<region>.a.run.app` URL form; the deterministic `*-<project-number>.<region>.run.app` form is printed at deploy time. Both eventually route. | Deployment docs use the deploy-time URL. |
| 10 | MCP Python SDK 2.0 introduced breaking changes vs the 1.x FastMCP API. | Dependency pinned `mcp>=1.9,<2` until migration. |
| 11 | Empty report ranges return an empty `metrics` array (HTTP 200), indistinguishable from parsing errors without care. | Empty results produce an explicit warning distinguishing "no delivery" from failure. |
| 12 | Paginated POST endpoints (reports, account history) require the request body on **every page** — `pagination.next_url` carries only the cursor. A follow-up POST without the body returns 400 "request body is required". | The client re-sends the JSON body on every pagination request. |
| 13 | Ad-group `goal_value` (budget) is micros of the account currency, like spend. | Converted in pacing analysis with provenance. |
| 14 | Ad objects return `type: null`; the creative format (`VIDEO`/`IMAGE`/…) lives on the promoted post object. | Creative analysis joins format via one profile-posts list call per profile. |
| 15 | Account history responses include member emails and full names. | Redacted by policy before returning; actors identified by member_id/username. |

Additional operating facts encoded in tool documentation: metrics stabilize in
up to ~6 hours; delivery data spans 24 months; reach/frequency begin June 2024;
daily reach values are not summable into period reach; up to 3 report
breakdowns per request (4 for COUNTRY+REGION).
