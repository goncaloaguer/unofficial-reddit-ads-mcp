# Reddit authentication setup

Goal: a **client ID**, **client secret**, and a permanent **refresh token**
scoped to `adsread` only. One-time, ~10 minutes.

## 1. Create the developer application

1. Sign in at [ads.reddit.com](https://ads.reddit.com) with the Reddit account
   that has access to your advertiser account.
2. Business settings → **Developer Applications** → **Create a new app**.
3. Name it (e.g. `reddit-ads-insights-mcp`), description optional.
4. **Redirect URI** — first try `http://localhost:8912/callback`.
   - If the form accepts localhost, use it (preferred flow below).
   - If Reddit requires a public HTTPS URI, use any HTTPS URL **you control**
     that can show you the `code` query parameter (even a static page). Do not
     use third-party callback pages: the authorization code passes through
     whoever operates the page.
5. Save the **App ID** (client ID) and **Secret**.

## 2. Authorize (adsread only)

Open in a browser, replacing `YOUR_APP_ID` and the redirect URI with yours
(URL-encoded):

```
https://www.reddit.com/api/v1/authorize?client_id=YOUR_APP_ID&response_type=code&state=SOME_RANDOM_STRING&redirect_uri=YOUR_REDIRECT_URI&duration=permanent&scope=adsread
```

Click **Allow**. Verify the `state` in the redirected URL matches what you
sent, then copy the `code` parameter (it expires in minutes).

> Scope must be exactly `adsread`. The server refuses to start if the grant
> includes write scopes.

## 3. Exchange the code for a refresh token

```bash
curl -s -X POST https://www.reddit.com/api/v1/access_token \
  -u "YOUR_APP_ID:YOUR_SECRET" \
  -A "script:reddit-ads-insights-mcp:0.1.0 (by /u/YOUR_USERNAME)" \
  -d "grant_type=authorization_code&code=YOUR_CODE&redirect_uri=YOUR_REDIRECT_URI"
```

The JSON response contains `refresh_token` — store it directly in Secret
Manager (Cloud Run) or your local `.env`. It remains valid until revoked.
Check the `scope` field in the response is `adsread`.

If the code expired or the redirect URI mismatches, redo step 2 — the
`redirect_uri` must match the app configuration exactly.

## 4. Find your ad account ID

Ads Manager → account switcher (top-left) → the value under the account name,
e.g. `a2_xxxxxxxxxxxx`. This goes into `ALLOWED_ACCOUNT_IDS`.

## Revoking access

Remove the app at reddit.com → Settings → Security → third-party access, or
delete the developer application in Ads Manager. Then destroy the stored
secret versions.
