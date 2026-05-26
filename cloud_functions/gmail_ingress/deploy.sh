#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-pomeradriven}"
REGION="${REGION:-asia-northeast1}"
TOPIC="${TOPIC:-gmail-push}"
SCHEDULER_JOB="${SCHEDULER_JOB:-refresh-gmail-watch-daily}"
SCHEDULER_SERVICE_ACCOUNT="${SCHEDULER_SERVICE_ACCOUNT:-}"
ENV_FILE="${ENV_FILE:-.env.gmail.yaml}"

if [[ -z "$SCHEDULER_SERVICE_ACCOUNT" ]]; then
  echo "SCHEDULER_SERVICE_ACCOUNT is required for the authenticated Scheduler call." >&2
  exit 1
fi

gcloud config set project "$PROJECT_ID"

gcloud services enable \
  gmail.googleapis.com \
  pubsub.googleapis.com \
  cloudfunctions.googleapis.com \
  cloudbuild.googleapis.com \
  run.googleapis.com \
  eventarc.googleapis.com \
  cloudscheduler.googleapis.com

gcloud pubsub topics describe "$TOPIC" >/dev/null 2>&1 || gcloud pubsub topics create "$TOPIC"
gcloud pubsub topics add-iam-policy-binding "$TOPIC" \
  --member="serviceAccount:gmail-api-push@system.gserviceaccount.com" \
  --role="roles/pubsub.publisher" >/dev/null

gcloud functions deploy gmail-ingress \
  --gen2 \
  --region="$REGION" \
  --runtime=python312 \
  --source=cloud_functions/gmail_ingress \
  --entry-point=gmail_ingress \
  --trigger-topic="$TOPIC" \
  --timeout=540s \
  --memory=512Mi \
  --env-vars-file="$ENV_FILE"

gcloud functions deploy refresh-gmail-watch \
  --gen2 \
  --region="$REGION" \
  --runtime=python312 \
  --source=cloud_functions/gmail_ingress \
  --entry-point=refresh_gmail_watch \
  --trigger-http \
  --no-allow-unauthenticated \
  --timeout=120s \
  --memory=256Mi \
  --env-vars-file="$ENV_FILE"

gcloud run services add-iam-policy-binding refresh-gmail-watch \
  --region="$REGION" \
  --member="serviceAccount:$SCHEDULER_SERVICE_ACCOUNT" \
  --role="roles/run.invoker" >/dev/null

WATCH_URL="$(gcloud functions describe refresh-gmail-watch \
  --gen2 \
  --region="$REGION" \
  --format='value(serviceConfig.uri)')"

if gcloud scheduler jobs describe "$SCHEDULER_JOB" --location="$REGION" >/dev/null 2>&1; then
  gcloud scheduler jobs update http "$SCHEDULER_JOB" \
    --location="$REGION" \
    --schedule="0 9 * * *" \
    --time-zone="Asia/Tokyo" \
    --uri="$WATCH_URL" \
    --http-method=POST \
    --oidc-service-account-email="$SCHEDULER_SERVICE_ACCOUNT"
else
  gcloud scheduler jobs create http "$SCHEDULER_JOB" \
    --location="$REGION" \
    --schedule="0 9 * * *" \
    --time-zone="Asia/Tokyo" \
    --uri="$WATCH_URL" \
    --http-method=POST \
    --oidc-service-account-email="$SCHEDULER_SERVICE_ACCOUNT"
fi

echo "Deployed Gmail Push ingress and daily watch renewal."
