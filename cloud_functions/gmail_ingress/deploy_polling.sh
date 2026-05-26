#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-pomeradriven}"
REGION="${REGION:-asia-northeast1}"
SCHEDULER_JOB="${SCHEDULER_JOB:-poll-gmail-every-minute}"
SCHEDULER_SERVICE_ACCOUNT="${SCHEDULER_SERVICE_ACCOUNT:-135607063731-compute@developer.gserviceaccount.com}"
ENV_FILE="${ENV_FILE:-.env.gmail.yaml}"

gcloud config set project "$PROJECT_ID"

gcloud services enable \
  cloudfunctions.googleapis.com \
  cloudbuild.googleapis.com \
  run.googleapis.com \
  cloudscheduler.googleapis.com

gcloud functions deploy poll-gmail \
  --gen2 \
  --region="$REGION" \
  --runtime=python312 \
  --source=cloud_functions/gmail_ingress \
  --entry-point=poll_gmail \
  --trigger-http \
  --no-allow-unauthenticated \
  --timeout=540s \
  --memory=512Mi \
  --max-instances=1 \
  --env-vars-file="$ENV_FILE" \
  --format="value(name,state,serviceConfig.uri)"

gcloud run services add-iam-policy-binding poll-gmail \
  --region="$REGION" \
  --member="serviceAccount:$SCHEDULER_SERVICE_ACCOUNT" \
  --role="roles/run.invoker" >/dev/null

POLL_URL="$(gcloud functions describe poll-gmail \
  --gen2 \
  --region="$REGION" \
  --format='value(serviceConfig.uri)')"

if gcloud scheduler jobs describe "$SCHEDULER_JOB" --location="$REGION" >/dev/null 2>&1; then
  gcloud scheduler jobs update http "$SCHEDULER_JOB" \
    --location="$REGION" \
    --schedule="* * * * *" \
    --time-zone="Asia/Tokyo" \
    --uri="$POLL_URL" \
    --http-method=POST \
    --attempt-deadline=540s \
    --oidc-service-account-email="$SCHEDULER_SERVICE_ACCOUNT"
else
  gcloud scheduler jobs create http "$SCHEDULER_JOB" \
    --location="$REGION" \
    --schedule="* * * * *" \
    --time-zone="Asia/Tokyo" \
    --uri="$POLL_URL" \
    --http-method=POST \
    --attempt-deadline=540s \
    --oidc-service-account-email="$SCHEDULER_SERVICE_ACCOUNT"
fi

echo "Deployed poll-gmail and every-minute Scheduler job."
