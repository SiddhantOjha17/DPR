# DPR update script - run this on the server after pushing changes to git.
# Pulls the latest code, syncs dependencies, and restarts the Windows Service.
#
# Usage: right-click > Run with PowerShell, or from a PowerShell prompt:
#   cd C:\path\to\dpr
#   .\deploy\update.ps1
#
# The service name below must match whatever name was used when the service
# was registered with NSSM (see DEPLOYMENT.md step 5). Update it here if you
# registered it under a different name.

$ServiceName = "DPR"

Write-Host "Pulling latest changes..."
git pull
if ($LASTEXITCODE -ne 0) {
    Write-Host "git pull failed - aborting restart." -ForegroundColor Red
    exit 1
}

Write-Host "Syncing dependencies..."
uv sync
if ($LASTEXITCODE -ne 0) {
    Write-Host "uv sync failed - aborting restart." -ForegroundColor Red
    exit 1
}

Write-Host "Restarting the $ServiceName service..."
nssm restart $ServiceName

Write-Host "Done. Check status with: nssm status $ServiceName"
