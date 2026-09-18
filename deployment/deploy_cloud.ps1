<#
.SYNOPSIS
    Deploys YouTube Insight Digest to Google Cloud Run and configures Cloud Scheduler.

.DESCRIPTION
    Containerizes the Flask service, deploys it to Google Cloud Run, configures
    a dedicated IAM Service Account with invocation rights, and schedules a Cloud Scheduler
    job to trigger the pipeline daily at 12:00 PM in the Asia/Tokyo timezone.

.PARAMETER ProjectId
    GCP Project ID. Defaults to .env configuration or active gcloud project.

.PARAMETER Region
    Deployment region. Defaults to 'us-central1'.

.PARAMETER ServiceName
    Cloud Run service name. Defaults to 'youtube-insight-digest'.

.PARAMETER JobName
    Cloud Scheduler job name. Defaults to 'youtube-insight-daily-trigger'.

.PARAMETER Schedule
    Cron expression. Defaults to '0 12 * * *' (daily at 12:00 PM).

.PARAMETER TimeZone
    Schedule timezone. Defaults to 'Asia/Tokyo'.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$ProjectId,

    [Parameter(Mandatory = $false)]
    [string]$Region,

    [Parameter(Mandatory = $false)]
    [string]$ServiceName,

    [Parameter(Mandatory = $false)]
    [string]$JobName,

    [Parameter(Mandatory = $false)]
    [string]$Schedule,

    [Parameter(Mandatory = $false)]
    [string]$TimeZone
)

$ErrorActionPreference = "Stop"

# Load local .env if available
$envPath = Join-Path $PSScriptRoot "..\" | Join-Path -ChildPath ".env"
if (Test-Path $envPath) {
    Write-Host "Loading configuration from: $envPath" -ForegroundColor DarkGray
    Get-Content $envPath | ForEach-Object {
        if ($_ -match '^\s*([^#][^=]*)\s*=\s*(.*)$') {
            $name = $matches[1].Trim()
            $value = $matches[2].Trim()
            Set-Variable -Name "ENV_$name" -Value $value -Scope Script
        }
    }
}

$PROJECT_ID = if ($ProjectId) { $ProjectId } elseif ($ENV_GCP_PROJECT_ID) { $ENV_GCP_PROJECT_ID } else { "gen-lang-client-0480639565" }
$REGION = if ($Region) { $Region } elseif ($ENV_GCP_REGION) { $ENV_GCP_REGION } else { "us-central1" }
$SERVICE_NAME = if ($ServiceName) { $ServiceName } elseif ($ENV_SERVICE_NAME) { $ENV_SERVICE_NAME } else { "youtube-insight-digest" }
$JOB_NAME = if ($JobName) { $JobName } elseif ($ENV_JOB_NAME) { $ENV_JOB_NAME } else { "youtube-insight-daily-trigger" }
$SCHEDULE = if ($Schedule) { $Schedule } elseif ($ENV_SCHEDULE) { $ENV_SCHEDULE } else { "0 12 * * *" }
$TIMEZONE = if ($TimeZone) { $TimeZone } elseif ($ENV_TIMEZONE) { $ENV_TIMEZONE } else { "Asia/Tokyo" }

Write-Host "===========================================================================" -ForegroundColor Green
Write-Host " Deploying YouTube Insight Digest to Google Cloud..." -ForegroundColor Green
Write-Host "  Project:  $PROJECT_ID"
Write-Host "  Region:   $REGION"
Write-Host "  Service:  $SERVICE_NAME"
Write-Host "  Job:      $JOB_NAME"
Write-Host "  Schedule: $SCHEDULE ($TIMEZONE)"
Write-Host "===========================================================================" -ForegroundColor Green
Write-Host ""

if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) {
    Write-Error "Google Cloud SDK (gcloud) is not found in PATH."
    exit 1
}

# Step 1: Set active project and default region
Write-Host "[Step 1/5] Setting active project to $PROJECT_ID and region to $REGION..." -ForegroundColor Cyan
gcloud config set project $PROJECT_ID
gcloud config set run/region $REGION

# Step 2: Enable required GCP services
Write-Host "[Step 2/5] Enabling required APIs (Cloud Run, Cloud Build, Artifact Registry, Cloud Scheduler, Secret Manager, Cloud Storage)..." -ForegroundColor Cyan
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com cloudscheduler.googleapis.com secretmanager.googleapis.com storage.googleapis.com

# Step 3: Deploy container from source to Cloud Run
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\")).Path
Set-Location $repoRoot

Write-Host "[Step 3/5] Deploying container from source (.) to Cloud Run..." -ForegroundColor Cyan
gcloud run deploy $SERVICE_NAME `
    --source . `
    --region $REGION `
    --no-allow-unauthenticated `
    --timeout 300 `
    --memory 1Gi `
    --quiet

# Retrieve the assigned service URL
$SERVICE_URL = (& gcloud run services describe $SERVICE_NAME --region $REGION --format "value(status.url)").Trim()
if (-not $SERVICE_URL) {
    Write-Error "Failed to retrieve the deployed service URL for $SERVICE_NAME."
    exit 1
}
Write-Host "Service deployed successfully at: $SERVICE_URL" -ForegroundColor Green

# Step 4: Configure dedicated Service Account for Cloud Scheduler
$SA_NAME = "youtube-scheduler-sa"
$SA_EMAIL = "$SA_NAME@$PROJECT_ID.iam.gserviceaccount.com"

Write-Host "[Step 4/5] Setting up Service Account ($SA_EMAIL) for Cloud Scheduler..." -ForegroundColor Cyan
if (-not (gcloud iam service-accounts list --filter="email:$SA_EMAIL" --format="value(email)")) {
    Write-Host "Creating service account: $SA_NAME..."
    gcloud iam service-accounts create $SA_NAME --display-name "YouTube Insight Digest Scheduler Invoker"
} else {
    Write-Host "Service account $SA_NAME already exists."
}

# Grant run.invoker role on Cloud Run service to Service Account
Write-Host "Granting roles/run.invoker to $SA_EMAIL..."
$iamArgs = @(
    "run", "services", "add-iam-policy-binding", $SERVICE_NAME,
    "--region", $REGION,
    "--member=serviceAccount:$SA_EMAIL",
    "--role=roles/run.invoker",
    "--quiet"
)
& gcloud @iamArgs

# Step 5: Configure Cloud Scheduler recurring HTTP trigger
Write-Host "[Step 5/5] Configuring Cloud Scheduler recurring trigger at 12:00 PM JST..." -ForegroundColor Cyan
$audience = $SERVICE_URL.TrimEnd('/')

if (gcloud scheduler jobs list --location=$REGION --filter="name:projects/$PROJECT_ID/locations/$REGION/jobs/$JOB_NAME" --format="value(name)") {
    Write-Host "Updating existing Cloud Scheduler job ($JOB_NAME)..."
    $schedArgs = @(
        "scheduler", "jobs", "update", "http", $JOB_NAME,
        "--location", $REGION,
        "--schedule", $SCHEDULE,
        "--time-zone", $TIMEZONE,
        "--uri", $SERVICE_URL,
        "--http-method", "POST",
        "--oidc-service-account-email", $SA_EMAIL,
        "--oidc-token-audience", $audience
    )
    & gcloud @schedArgs
} else {
    Write-Host "Creating new Cloud Scheduler job ($JOB_NAME)..."
    $schedArgs = @(
        "scheduler", "jobs", "create", "http", $JOB_NAME,
        "--location", $REGION,
        "--schedule", $SCHEDULE,
        "--time-zone", $TIMEZONE,
        "--uri", $SERVICE_URL,
        "--http-method", "POST",
        "--oidc-service-account-email", $SA_EMAIL,
        "--oidc-token-audience", $audience
    )
    & gcloud @schedArgs
}

Write-Host ""
Write-Host "===========================================================================" -ForegroundColor Green
Write-Host " Cloud Deployment & Scheduler Setup Complete!" -ForegroundColor Green
Write-Host " Service URL: $SERVICE_URL" -ForegroundColor Green
Write-Host " Schedule:    $SCHEDULE ($TIMEZONE)" -ForegroundColor Green
Write-Host " Invoker SA:  $SA_EMAIL" -ForegroundColor Green
Write-Host "===========================================================================" -ForegroundColor Green
