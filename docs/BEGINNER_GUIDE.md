# Beginner guide — from zero to asking Claude about your Reddit Ads

For people who have **never installed an MCP server and never used Google
Cloud**. No prior knowledge assumed. You'll copy-paste commands into your
computer's terminal one at a time; each step tells you what you should see.
Total time: ~40 minutes. Expected running cost: **~$0/month** for personal use.

What you get at the end: a private connector in [claude.ai](https://claude.ai)
that lets Claude answer questions like *"which subreddits converted cheapest
last month?"* from your own Reddit Ads account. It is **read-only** — it
cannot change, pause, or spend anything.

> **Rules of the road**: the values you collect below (App ID, Secret,
> refresh token, connector URL) are passwords. Never paste them into chats,
> documents, or screenshots. If one leaks, see "Rotating credentials" at the
> end.

---

## What you'll collect along the way

| Value | You get it in | Looks like |
|---|---|---|
| Google Cloud project ID | Part 1 | `my-project-123456` |
| Reddit App ID | Part 2 | short random string |
| Reddit App Secret | Part 2 | longer random string |
| Reddit refresh token | Part 3 | `numbers-Letters…` |
| Ad account ID | Part 3 | `a2_xxxxxxxxxxxx` |
| Connector URL | Part 5 | `https://…run.app/…/mcp` |

## Part 0 — Open a terminal

- **Mac**: press `Cmd+Space`, type `Terminal`, press Enter.
- **Windows**: install [WSL](https://learn.microsoft.com/windows/wsl/install)
  and open Ubuntu, or use [Google Cloud Shell](https://shell.cloud.google.com)
  in your browser (skip installing gcloud if you use Cloud Shell).
- **Linux**: you know where it is.

Paste each grey block below into the terminal and press Enter. Wait for each
to finish (the prompt returns) before pasting the next.

## Part 1 — Google Cloud setup (~10 min)

**1.1** Create a Google Cloud account at
[console.cloud.google.com](https://console.cloud.google.com) if you don't have
one (requires a payment card, but this deployment is designed to stay at ~$0;
you'll also set a $5 alert).

**1.2** Install the gcloud command-line tool —
[instructions](https://cloud.google.com/sdk/docs/install) (on a Mac with
Homebrew: `brew install --cask google-cloud-sdk`). Then log in:

```bash
gcloud auth login
```

**1.3** Create a dedicated project and switch the tool to it:

```bash
export PROJECT_ID=reddit-ads-mcp-$RANDOM
export REGION=europe-west1        # or us-central1, pick one close to you
gcloud projects create $PROJECT_ID
gcloud config set project $PROJECT_ID
echo "Your project ID is: $PROJECT_ID  <- note it down"
```

**1.4** Link billing (needed even for free-tier use). List your billing
accounts, copy the ID shown, and link it:

```bash
gcloud billing accounts list
gcloud billing projects link $PROJECT_ID --billing-account=PASTE_BILLING_ACCOUNT_ID
```

**1.5** Switch on the needed services:

```bash
gcloud services enable run.googleapis.com artifactregistry.googleapis.com \
  secretmanager.googleapis.com cloudbuild.googleapis.com
```

## Part 2 — Create your Reddit developer app (~5 min)

1. Sign in at [ads.reddit.com](https://ads.reddit.com) with the Reddit
   account that has access to your advertiser account.
2. In your business/account settings find **Developer Applications** (may be
   under **Settings → API Access**) → **Create a new app**.
3. Fill in: any name (e.g. `my-ads-insights`), any description, and
   **Redirect URI**: exactly `http://localhost:8912/callback`
4. Save the **App ID** and **Secret** it shows you, then set them here
   (replace the placeholders, keep the quotes):

```bash
export REDDIT_APP_ID="PASTE_APP_ID"
export REDDIT_APP_SECRET="PASTE_SECRET"
export REDDIT_USERNAME="PASTE_YOUR_REDDIT_USERNAME"
```

## Part 3 — Authorize it and get your refresh token (~5 min)

**3.1** Print your personal authorization link and open it in a browser:

```bash
echo "https://www.reddit.com/api/v1/authorize?client_id=$REDDIT_APP_ID&response_type=code&state=setup123&redirect_uri=http%3A%2F%2Flocalhost%3A8912%2Fcallback&duration=permanent&scope=adsread"
```

**3.2** Click **Allow**. Note the permission screen asks only to **read**
advertising data — that's the whole point of this project.

**3.3** The browser will land on a page that **fails to load. That is
normal.** Look at the address bar: it contains `code=SOMETHING`. Copy the
SOMETHING (stop at any `#` or `&`) — it expires in ~10 minutes:

```bash
export REDDIT_CODE="PASTE_THE_CODE"
```

**3.4** Trade the code for a permanent refresh token:

```bash
curl -s -X POST https://www.reddit.com/api/v1/access_token \
  -u "$REDDIT_APP_ID:$REDDIT_APP_SECRET" \
  -A "script:unofficial-reddit-ads-mcp:0.2.1 (by /u/$REDDIT_USERNAME)" \
  -d "grant_type=authorization_code&code=$REDDIT_CODE&redirect_uri=http://localhost:8912/callback"
```

In the response, find `"refresh_token": "…"` (check it also says
`"scope": "adsread"`), then:

```bash
export REDDIT_REFRESH_TOKEN="PASTE_REFRESH_TOKEN"
```

**3.5** Your ad account ID: at [ads.reddit.com](https://ads.reddit.com), open
the account switcher (top-left); the ID under the account name starts with
`a2_`:

```bash
export AD_ACCOUNT_ID="a2_PASTE_YOURS"
```

## Part 4 — Store secrets and deploy (~15 min)

**4.1** Put the secrets in Google's vault:

```bash
printf '%s' "$REDDIT_APP_ID"        | gcloud secrets create reddit-client-id --data-file=-
printf '%s' "$REDDIT_APP_SECRET"    | gcloud secrets create reddit-client-secret --data-file=-
printf '%s' "$REDDIT_REFRESH_TOKEN" | gcloud secrets create reddit-refresh-token --data-file=-
python3 -c "import secrets; print(secrets.token_urlsafe(32))" | tr -d '\n' \
  | gcloud secrets create mcp-path-secret --data-file=-
```

(The last one generates the secret part of your future connector URL.)

**4.2** Create a locked-down identity that can read only these secrets:

```bash
gcloud iam service-accounts create reddit-ads-mcp-runtime
export SA="reddit-ads-mcp-runtime@$PROJECT_ID.iam.gserviceaccount.com"
for s in reddit-client-id reddit-client-secret reddit-refresh-token mcp-path-secret; do
  gcloud secrets add-iam-policy-binding $s \
    --member=serviceAccount:$SA --role=roles/secretmanager.secretAccessor
done
```

**4.3** Download this project and build it on Google's servers (2–4 min; must
end with `STATUS: SUCCESS`):

```bash
cd ~
git clone https://github.com/goncaloaguer/unofficial-reddit-ads-mcp.git
cd unofficial-reddit-ads-mcp
gcloud artifacts repositories create mcp --repository-format=docker --location=$REGION
gcloud builds submit --tag $REGION-docker.pkg.dev/$PROJECT_ID/mcp/reddit-ads-mcp:latest
```

**4.4** Deploy (one block, paste whole):

```bash
gcloud run deploy reddit-ads-mcp \
  --image $REGION-docker.pkg.dev/$PROJECT_ID/mcp/reddit-ads-mcp:latest \
  --region $REGION --service-account $SA --allow-unauthenticated \
  --min-instances 0 --max-instances 1 --concurrency 5 \
  --memory 512Mi --cpu 1 --timeout 120 \
  --labels application=reddit-ads-mcp,environment=personal \
  --set-env-vars "^@^MCP_TRANSPORT=http@MCP_AUTH_MODE=secret_path@ALLOWED_ACCOUNT_IDS=$AD_ACCOUNT_ID@REDDIT_USER_AGENT=cloudrun:unofficial-reddit-ads-mcp:0.2.1 (by /u/$REDDIT_USERNAME)" \
  --set-secrets "REDDIT_CLIENT_ID=reddit-client-id:latest,REDDIT_CLIENT_SECRET=reddit-client-secret:latest,REDDIT_REFRESH_TOKEN=reddit-refresh-token:latest,MCP_PATH_SECRET=mcp-path-secret:latest"
```

("--allow-unauthenticated" only opens Google's outer door; the app itself
rejects anyone without your secret URL.)

**4.5** Set a $5/month billing alert (notifications, not a hard cap):

```bash
gcloud billing budgets create --billing-account=PASTE_BILLING_ACCOUNT_ID \
  --display-name="reddit-ads-mcp" --budget-amount=5USD \
  --threshold-rule=percent=0.2 --threshold-rule=percent=1.0
```

## Part 5 — Get your URL and connect Claude (~3 min)

```bash
export URL="$(gcloud run services describe reddit-ads-mcp --region $REGION --format='value(status.url)')"
export PATHSECRET="$(gcloud secrets versions access latest --secret=mcp-path-secret)"
echo "" && echo "Connector URL (treat as a password):" && echo "$URL/$PATHSECRET/mcp" && echo ""
curl -s "$URL/health" && echo "  <- should say status ok"
curl -s -o /dev/null -w "  /mcp without secret -> %{http_code} (should be 404)\n" "$URL/mcp"
```

Then in [claude.ai → Settings → Connectors](https://claude.ai/settings/connectors):
**Add custom connector** → Name `Reddit Ads` → paste the full URL → Add.

## Part 6 — Try it

In a new Claude chat:

> Using the Reddit Ads connector, list my ad accounts and rank my subreddits
> by cost per conversion for the last 30 days.

If numbers match your Ads Manager: done. 🎉

---

## When things go wrong

| Symptom | Fix |
|---|---|
| `command not found: gcloud` | Step 1.2 didn't finish; reopen the terminal and retry |
| `PERMISSION_DENIED` | Wrong project or account: re-run `gcloud config set project $PROJECT_ID` |
| Build fails | Make sure you're inside the project folder (`cd ~/unofficial-reddit-ads-mcp`) |
| `invalid_grant` in Part 3.4 | The code expired — redo 3.1–3.4 quickly |
| Connector errors in Claude | Re-run the Part 5 checks; if `/health` fails, read logs: `gcloud run services logs read reddit-ads-mcp --region $REGION --limit 50` |
| Emergency off switch | `gcloud run services update reddit-ads-mcp --region $REGION --max-instances 0` |

## Rotating credentials (if something leaked)

- **Connector URL**: `python3 -c "import secrets; print(secrets.token_urlsafe(32))" | tr -d '\n' | gcloud secrets versions add mcp-path-secret --data-file=-`, then redeploy (Part 4.4) and update the URL in claude.ai.
- **Reddit app secret**: regenerate in the Reddit developer app settings, then `printf '%s' 'NEW' | gcloud secrets versions add reddit-client-secret --data-file=-` and redeploy. If reports then fail with an auth error, redo Part 3 for a fresh refresh token.
