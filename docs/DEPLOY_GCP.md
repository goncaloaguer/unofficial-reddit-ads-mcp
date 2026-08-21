# Deploying to your own Google Cloud (Cloud Run)

This guide deploys a private, single-owner instance in **your** Google Cloud
project. Expected cost for personal use (a few sessions per week): **~$0/month**
(scale-to-zero, 1 max instance, well inside the free tier). Time: ~15 minutes
after you have your Reddit credentials (see `AUTHENTICATION.md`).

**Not a Google Cloud user?** The server is a plain container with an
env-var contract (see `.env.example`) — the same image runs on Fly.io,
Railway, Render, or any Docker host. This guide is simply the most
cost-guarded path we have tested end to end. Client connections are
documented separately in `CONNECT.md` and work identically wherever you host.

Never put secrets in Dockerfiles, git, build args, or shell commands that log
them. Secrets go into Secret Manager only.

## 0. Prerequisites

- [gcloud CLI](https://cloud.google.com/sdk/docs/install) authenticated:
  `gcloud auth login`
- Reddit credentials from `AUTHENTICATION.md`:
  client ID, client secret, refresh token, your `a2_…` account ID.

## 1. Create a dedicated project

```bash
export PROJECT_ID=reddit-ads-mcp-$RANDOM
gcloud projects create $PROJECT_ID
gcloud config set project $PROJECT_ID
# Link billing (needed even for free-tier usage):
gcloud billing accounts list
gcloud billing projects link $PROJECT_ID --billing-account=BILLING_ACCOUNT_ID

gcloud services enable run.googleapis.com artifactregistry.googleapis.com \
  secretmanager.googleapis.com cloudbuild.googleapis.com
```

## 2. Store secrets in Secret Manager

```bash
printf '%s' 'YOUR_CLIENT_ID'     | gcloud secrets create reddit-client-id --data-file=-
printf '%s' 'YOUR_CLIENT_SECRET' | gcloud secrets create reddit-client-secret --data-file=-
printf '%s' 'YOUR_REFRESH_TOKEN' | gcloud secrets create reddit-refresh-token --data-file=-

# MCP credential — pick ONE mode:
# bearer (recommended; Claude Code/API clients):
python3 -c "import secrets; print(secrets.token_urlsafe(32))" \
  | tr -d '\n' | gcloud secrets create mcp-access-token --data-file=-
# OR secret_path (claude.ai custom connectors):
# python3 -c "import secrets; print(secrets.token_urlsafe(32))" \
#   | tr -d '\n' | gcloud secrets create mcp-path-secret --data-file=-
```

Tip: `printf` (not `echo`) avoids trailing newlines corrupting the secret.

## 3. Dedicated least-privilege service account

```bash
gcloud iam service-accounts create reddit-ads-mcp-runtime
export SA=reddit-ads-mcp-runtime@$PROJECT_ID.iam.gserviceaccount.com

for s in reddit-client-id reddit-client-secret reddit-refresh-token mcp-access-token; do
  gcloud secrets add-iam-policy-binding $s \
    --member=serviceAccount:$SA --role=roles/secretmanager.secretAccessor
done
```

## 4. Build the container

```bash
gcloud artifacts repositories create mcp --repository-format=docker \
  --location=europe-west1
gcloud builds submit \
  --tag europe-west1-docker.pkg.dev/$PROJECT_ID/mcp/reddit-ads-mcp:0.1.0
```

## 5. Deploy (personal-use cost profile)

```bash
gcloud run deploy reddit-ads-mcp \
  --image europe-west1-docker.pkg.dev/$PROJECT_ID/mcp/reddit-ads-mcp:0.1.0 \
  --region europe-west1 \
  --service-account $SA \
  --allow-unauthenticated \
  --min-instances 0 --max-instances 1 --concurrency 5 \
  --memory 512Mi --cpu 1 --timeout 120 \
  --set-env-vars "MCP_TRANSPORT=http,MCP_AUTH_MODE=bearer,\
ALLOWED_ACCOUNT_IDS=a2_YOURACCOUNT,\
REDDIT_USER_AGENT=cloudrun:reddit-ads-insights-mcp:0.1.0 (by /u/YOUR_USERNAME)" \
  --set-secrets "REDDIT_CLIENT_ID=reddit-client-id:latest,\
REDDIT_CLIENT_SECRET=reddit-client-secret:latest,\
REDDIT_REFRESH_TOKEN=reddit-refresh-token:latest,\
MCP_ACCESS_TOKEN=mcp-access-token:latest"
```

`--allow-unauthenticated` refers to Google's IAM layer only — the application
itself rejects every request without your MCP credential. (An IAM-only
alternative exists for clients that can send Google identity tokens.)

For **secret_path** mode instead, replace the last two lines' auth pieces:
`MCP_AUTH_MODE=secret_path` and `MCP_PATH_SECRET=mcp-path-secret:latest`.

## 6. Connect your MCP client

```bash
export URL=$(gcloud run services describe reddit-ads-mcp \
  --region europe-west1 --format='value(status.url)')
export TOKEN=$(gcloud secrets versions access latest --secret=mcp-access-token)
```

- **Claude Code** (bearer):

  ```bash
  claude mcp add --transport http reddit-ads "$URL/mcp" \
    --header "Authorization: Bearer $TOKEN"
  ```

- **claude.ai custom connector** (secret_path mode): add a custom connector
  with URL `https://<service>/<MCP_PATH_SECRET>/mcp`. Treat that URL as a
  password.

Smoke test: `curl -s $URL/health` → `{"status":"ok"}`; `curl -s -o /dev/null
-w '%{http_code}' $URL/mcp` → `401` (bearer mode) proves auth is on.

## 7. Billing guardrails (do this)

```bash
gcloud billing budgets create --billing-account=BILLING_ACCOUNT_ID \
  --display-name="reddit-ads-mcp" --budget-amount=5USD \
  --threshold-rule=percent=0.2 --threshold-rule=percent=0.5 \
  --threshold-rule=percent=0.9 --threshold-rule=percent=1.0
```

Budget alerts are notifications, not hard caps. Emergency shutoff:

```bash
gcloud run services update reddit-ads-mcp --region europe-west1 --max-instances 0
```

Monthly 2-minute check: Cloud Run billable time ≈ 0, Artifact Registry storage
(keep ≤3 images), active secret versions (≤6; destroy rotated-out versions),
no unexpected resources.

## 8. Rotation

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))" | tr -d '\n' \
  | gcloud secrets versions add mcp-access-token --data-file=-
gcloud run services update reddit-ads-mcp --region europe-west1  # new revision
gcloud secrets versions destroy 1 --secret=mcp-access-token      # after verifying
```

Same pattern for the path secret (also update your connector URL) and for the
Reddit refresh token if ever revoked.
