#!/usr/bin/env bash
set -euo pipefail

# ── Configuration ────────────────────────────────────────────────────────
# Set these before running, or export them as environment variables.
PROJECT_ID="${GCP_PROJECT_ID:?Set GCP_PROJECT_ID}"
REGION="${GCP_REGION:-us-central1}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "=== Deploying SeisMonitor-Platform to GCP ==="
echo "Project: $PROJECT_ID"
echo "Region:  $REGION"
echo ""

# ── 1. Enable APIs ───────────────────────────────────────────────────────
echo "--- Enabling GCP APIs ---"
gcloud services enable \
    run.googleapis.com \
    cloudscheduler.googleapis.com \
    bigquery.googleapis.com \
    cloudbuild.googleapis.com \
    artifactregistry.googleapis.com \
    --project="$PROJECT_ID"

# ── 2. Create Artifact Registry repo ────────────────────────────────────
echo "--- Creating Artifact Registry repo ---"
gcloud artifacts repositories create quake-images \
    --repository-format=docker \
    --location="$REGION" \
    --project="$PROJECT_ID" 2>/dev/null || echo "Artifact Registry repo already exists"

# ── 3. Create BigQuery dataset + tables ──────────────────────────────────
echo "--- Creating BigQuery dataset ---"
bq mk --dataset --location=US --project_id="$PROJECT_ID" \
    "${PROJECT_ID}:quake_stream" 2>/dev/null || echo "Dataset already exists"

echo "--- Creating BigQuery tables ---"
bq query --use_legacy_sql=false --project_id="$PROJECT_ID" \
    < "$REPO_ROOT/gcp/bigquery/schema.sql"

# Run migrations (idempotent)
echo "--- Running BigQuery migrations ---"
for migration in "$REPO_ROOT"/gcp/bigquery/migrations/*.sql; do
    if [ -f "$migration" ]; then
        echo "  Applying $(basename "$migration")..."
        bq query --use_legacy_sql=false --project_id="$PROJECT_ID" < "$migration" || true
    fi
done

# ── 4. Build the ingester image (shared by all per-source services) ──────
echo "--- Building ingester image ---"
INGESTER_IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/quake-images/ingest-quakes:latest"

cd "$REPO_ROOT"
gcloud builds submit \
    --project="$PROJECT_ID" \
    --config=/dev/stdin \
    . <<EOF
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-t', '$INGESTER_IMAGE', '-f', 'gcp/ingester/Dockerfile', '.']
images: ['$INGESTER_IMAGE']
EOF

# ── 5. Create scheduler service account ──────────────────────────────────
echo "--- Setting up Cloud Scheduler ---"
SA_EMAIL="quake-scheduler@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud iam service-accounts create quake-scheduler \
    --display-name="Quake Pipeline Scheduler" \
    --project="$PROJECT_ID" 2>/dev/null || echo "Service account already exists"

# ── 6. Deploy per-source ingester services ───────────────────────────────
echo "--- Deploying per-source ingester services ---"

# Source: name, scheduler interval (cron), memory
declare -A SOURCE_SCHEDULE
SOURCE_SCHEDULE[usgs]="*/1 * * * *"     # every 1 minute
SOURCE_SCHEDULE[emsc]="*/2 * * * *"     # every 2 minutes
SOURCE_SCHEDULE[gfz]="*/3 * * * *"      # every 3 minutes
SOURCE_SCHEDULE[isc]="*/5 * * * *"      # every 5 minutes
SOURCE_SCHEDULE[ipgp]="*/3 * * * *"     # every 3 minutes

SOURCES=("usgs" "emsc" "gfz" "isc" "ipgp")

for SOURCE in "${SOURCES[@]}"; do
    SERVICE_NAME="ingest-${SOURCE}"
    SCHEDULE="${SOURCE_SCHEDULE[$SOURCE]}"

    echo ""
    echo "--- Deploying $SERVICE_NAME ---"

    # Set min-instances=1 for USGS (highest priority), 0 for others
    MIN_INSTANCES=0
    if [ "$SOURCE" = "usgs" ]; then
        MIN_INSTANCES=1
    fi

    gcloud run deploy "$SERVICE_NAME" \
        --image="$INGESTER_IMAGE" \
        --region="$REGION" \
        --memory=256Mi \
        --cpu=1 \
        --timeout=60 \
        --max-instances=1 \
        --min-instances="$MIN_INSTANCES" \
        --set-env-vars="GCP_PROJECT_ID=$PROJECT_ID,BQ_DATASET=quake_stream,SOURCE_NAME=$SOURCE" \
        --no-allow-unauthenticated \
        --project="$PROJECT_ID"

    SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" \
        --region="$REGION" --project="$PROJECT_ID" \
        --format='value(status.url)')
    echo "  $SERVICE_NAME URL: $SERVICE_URL"

    # Grant scheduler invoker role
    gcloud run services add-iam-policy-binding "$SERVICE_NAME" \
        --region="$REGION" \
        --member="serviceAccount:$SA_EMAIL" \
        --role="roles/run.invoker" \
        --project="$PROJECT_ID"

    # Delete old scheduler job if exists
    gcloud scheduler jobs delete "quake-ingest-${SOURCE}" \
        --location="$REGION" --project="$PROJECT_ID" --quiet 2>/dev/null || true

    # Create scheduler job
    gcloud scheduler jobs create http "quake-ingest-${SOURCE}" \
        --location="$REGION" \
        --schedule="$SCHEDULE" \
        --uri="${SERVICE_URL}/ingest" \
        --http-method=POST \
        --oidc-service-account-email="$SA_EMAIL" \
        --attempt-deadline=60s \
        --max-retry-attempts=3 \
        --min-backoff=10s \
        --max-backoff=30s \
        --project="$PROJECT_ID"
done

# Remove old monolithic scheduler job if it exists
gcloud scheduler jobs delete quake-ingest-every-minute \
    --location="$REGION" --project="$PROJECT_ID" --quiet 2>/dev/null || true

# ── 7. Build and deploy the dedup service ─────────────────────────────────
echo ""
echo "--- Building dedup service ---"
DEDUP_IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/quake-images/quake-dedup:latest"

cd "$REPO_ROOT"
gcloud builds submit \
    --project="$PROJECT_ID" \
    --config=/dev/stdin \
    . <<EOF
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-t', '$DEDUP_IMAGE', '-f', 'gcp/dedup/Dockerfile', '.']
images: ['$DEDUP_IMAGE']
EOF

echo "--- Deploying dedup service ---"
gcloud run deploy quake-dedup \
    --image="$DEDUP_IMAGE" \
    --region="$REGION" \
    --memory=512Mi \
    --cpu=1 \
    --timeout=120 \
    --max-instances=1 \
    --min-instances=0 \
    --set-env-vars="GCP_PROJECT_ID=$PROJECT_ID,BQ_DATASET=quake_stream" \
    --no-allow-unauthenticated \
    --project="$PROJECT_ID"

DEDUP_URL=$(gcloud run services describe quake-dedup \
    --region="$REGION" --project="$PROJECT_ID" \
    --format='value(status.url)')

gcloud run services add-iam-policy-binding quake-dedup \
    --region="$REGION" \
    --member="serviceAccount:$SA_EMAIL" \
    --role="roles/run.invoker" \
    --project="$PROJECT_ID"

gcloud scheduler jobs delete quake-dedup-every-5min \
    --location="$REGION" --project="$PROJECT_ID" --quiet 2>/dev/null || true

gcloud scheduler jobs create http quake-dedup-every-5min \
    --location="$REGION" \
    --schedule="*/5 * * * *" \
    --uri="${DEDUP_URL}/deduplicate" \
    --http-method=POST \
    --oidc-service-account-email="$SA_EMAIL" \
    --attempt-deadline=120s \
    --max-retry-attempts=2 \
    --min-backoff=15s \
    --max-backoff=60s \
    --project="$PROJECT_ID"

# ── 8. Deploy the Streamlit dashboard ────────────────────────────────────
echo ""
echo "--- Building dashboard image ---"
DASHBOARD_IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/quake-images/quake-dashboard:latest"

cd "$REPO_ROOT"
gcloud builds submit \
    --project="$PROJECT_ID" \
    --config=/dev/stdin \
    . <<EOF
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-t', '$DASHBOARD_IMAGE', '-f', 'gcp/dashboard/Dockerfile', '.']
images: ['$DASHBOARD_IMAGE']
EOF

echo "--- Deploying dashboard to Cloud Run ---"
gcloud run deploy quake-dashboard \
    --image="$DASHBOARD_IMAGE" \
    --region="$REGION" \
    --memory=512Mi \
    --cpu=1 \
    --timeout=300 \
    --max-instances=2 \
    --min-instances=0 \
    --set-env-vars="GCP_PROJECT_ID=$PROJECT_ID,BQ_DATASET=quake_stream" \
    --allow-unauthenticated \
    --session-affinity \
    --project="$PROJECT_ID"

DASHBOARD_URL=$(gcloud run services describe quake-dashboard \
    --region="$REGION" --project="$PROJECT_ID" \
    --format='value(status.url)')

# ── 9. Test the pipeline ─────────────────────────────────────────────────
echo ""
echo "--- Testing pipeline (manual trigger — USGS) ---"
gcloud scheduler jobs run quake-ingest-usgs \
    --location="$REGION" --project="$PROJECT_ID" || \
    echo "Manual trigger sent (check Cloud Run logs for result)"

# ── Done ─────────────────────────────────────────────────────────────────
echo ""
echo "=========================================="
echo "  Deployment complete!"
echo "=========================================="
echo ""
echo "  Dashboard:  $DASHBOARD_URL"
echo "  Dedup:      $DEDUP_URL"
echo ""
echo "  Per-source ingesters:"
for SOURCE in "${SOURCES[@]}"; do
    echo "    ingest-${SOURCE}"
done
echo ""
echo "  Scheduler jobs:"
echo "    usgs:  every 1 min"
echo "    emsc:  every 2 min"
echo "    gfz:   every 3 min"
echo "    isc:   every 5 min"
echo "    ipgp:  every 3 min"
echo "    dedup: every 5 min"
echo ""
echo "  Monitor: https://console.cloud.google.com/run?project=$PROJECT_ID"
echo "  Logs:    https://console.cloud.google.com/logs?project=$PROJECT_ID"
echo ""
