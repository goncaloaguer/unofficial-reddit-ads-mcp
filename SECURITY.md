# Security policy

## Reporting a vulnerability

Open a GitHub Security Advisory ("Report a vulnerability" on the Security
tab) rather than a public issue. Please do not include real advertiser data,
tokens, or account identifiers in reports.

## Design guarantees this project makes

- Requests only the `adsread` Reddit OAuth scope and refuses to start with a
  write-capable grant.
- Every upstream call must match a version-controlled allowlist of read
  operations; write methods are unreachable by construction and CI fails if
  that changes.
- Mandatory ad-account allowlist; pagination URLs are validated (scheme,
  host, path family) before being followed; redirects are disabled.
- No database, no persistent cache, no payload logging. Report rows, entity
  names, and tokens never appear in logs. Member emails/full names in
  account-history responses are redacted.
- Rate/loop safeguards bound tool calls, upstream requests, pages, rows,
  response size, and runtime.

## Operator responsibilities

Secrets live in your environment (Secret Manager on Cloud Run). Rotate the
MCP credential and Reddit app secret if they may have leaked
(docs/BEGINNER_GUIDE.md has the commands). Do not share one deployment across
unrelated advertisers.
