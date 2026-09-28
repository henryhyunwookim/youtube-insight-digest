<#
.SYNOPSIS
    Syncs local channels.json to Google Cloud Storage without redeploying Cloud Run.

.DESCRIPTION
    Uploads channels.json directly to gs://$BUCKET_NAME/$SERVICE_NAME/channels.json.
    Cloud Run reads this configuration dynamically on every scheduled run, enabling instant channel
    updates in seconds without rebuilding Docker containers.

.EXAMPLE
    .\deployment\sync_channels.ps1
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$ProjectId,

    [Parameter(Mandatory = $false)]
    [string]$BucketName
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\")).Path
$envPath = Join-Path $repoRoot ".env"
if (Test-Path $envPath) {
    Get-Content $envPath | ForEach-Object {
        if ($_ -match '^\s*([^#][^=]*)\s*=\s*(.*)$') {
            $name = $matches[1].Trim()
            $value = $matches[2].Trim()
            Set-Variable -Name "ENV_$name" -Value $value -Scope Script
        }
    }
}

$PROJECT_ID = if ($ProjectId) { $ProjectId } elseif ($ENV_GCP_PROJECT_ID) { $ENV_GCP_PROJECT_ID } else { (gcloud config get-value project 2>$null).Trim() }
$SERVICE_NAME = if ($ENV_SERVICE_NAME) { $ENV_SERVICE_NAME } else { "youtube-insight-digest" }
$BUCKET_NAME = if ($BucketName) { $BucketName } elseif ($ENV_GCS_BUCKET_NAME) { $ENV_GCS_BUCKET_NAME } else { "$PROJECT_ID-monitor-data" }

$channelsFile = Join-Path $repoRoot "channels.json"
if (-not (Test-Path $channelsFile)) {
    Write-Error "channels.json not found at $channelsFile"
    exit 1
}

Write-Host "===========================================================================" -ForegroundColor Green
Write-Host " Syncing channels.json to Google Cloud Storage..." -ForegroundColor Green
Write-Host "  Project:     $PROJECT_ID"
Write-Host "  Destination: gs://$BUCKET_NAME/$SERVICE_NAME/channels.json"
Write-Host "===========================================================================" -ForegroundColor Green

gcloud storage cp $channelsFile "gs://$BUCKET_NAME/$SERVICE_NAME/channels.json"

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "Channels synced successfully to Google Cloud Storage!" -ForegroundColor Green
    Write-Host "The scheduled Cloud Run pipeline will use this updated channel list on its next trigger." -ForegroundColor Green
} else {
    Write-Error "Failed to upload channels.json to Cloud Storage."
    exit 1
}
