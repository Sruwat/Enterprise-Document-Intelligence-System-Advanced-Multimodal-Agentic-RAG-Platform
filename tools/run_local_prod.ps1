param(
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 3000,
    [switch]$SkipInstall,
    [switch]$NoFrontend
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }

function Test-PortFree([int]$Port) {
    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($listener) {
        throw "Port $Port is already in use. Stop the existing process or pass a different port."
    }
}

function Start-HiddenProcess($FilePath, $Arguments, $Name) {
    Write-Host "[Aiwana] starting $Name"
    Start-Process -FilePath $FilePath -ArgumentList $Arguments -WorkingDirectory $Root -WindowStyle Hidden | Out-Null
}

Test-PortFree $BackendPort
if (-not $NoFrontend) { Test-PortFree $FrontendPort }

$env:Path = (($env:Path -split ';' | Where-Object { $_ } | Select-Object -Unique) -join ';')
$env:PYTHONPATH = "$Root"
$env:APP_ENV = "production"
$env:REQUIRE_AUTH = "true"
$env:ENABLE_LOCAL_USER_FALLBACK = "false"
$env:EMAIL_PROVIDER = "memory"
$env:DATABASE_BACKEND = "postgres"
$env:DATABASE_URL = "postgresql+psycopg://aiwana:aiwana@localhost:5432/aiwana"
$env:ENABLE_REDIS = "true"
$env:REDIS_URL = "redis://localhost:6379/0"
$env:QDRANT_URL = "http://localhost:6333"
$env:NEXT_PUBLIC_API_BASE_URL = "http://localhost:$BackendPort"

if (-not $SkipInstall) {
    Write-Host "[Aiwana] installing backend requirements"
    & $Python -m pip install -r requirements-backend.txt
}

Write-Host "[Aiwana] starting Postgres, Redis, and Qdrant"
docker compose up -d postgres redis qdrant

Write-Host "[Aiwana] waiting for dependencies"
docker compose ps
Start-Sleep -Seconds 8

Write-Host "[Aiwana] running migrations"
& $Python -m alembic upgrade head

Start-HiddenProcess $Python "-m uvicorn app.api.main:app --host 0.0.0.0 --port $BackendPort" "backend"
Start-HiddenProcess $Python "-m tools.worker" "worker"

if (-not $NoFrontend) {
    Write-Host "[Aiwana] installing/building frontend dependencies if needed"
    Push-Location frontend
    if (-not (Test-Path node_modules)) { npm install }
    Start-Process -FilePath "npm.cmd" -ArgumentList "run dev -- -p $FrontendPort" -WorkingDirectory (Get-Location) -WindowStyle Hidden | Out-Null
    Pop-Location
}

Write-Host "[Aiwana] backend:  http://localhost:$BackendPort"
Write-Host "[Aiwana] frontend: http://localhost:$FrontendPort"
Write-Host "[Aiwana] run: `$env:AIWANA_SMOKE_STRICT='true'; `$env:AIWANA_SMOKE_BOOTSTRAP='true'; `$env:AIWANA_SMOKE_EMAIL='smoke@aiwana.local'; `$env:AIWANA_SMOKE_PASSWORD='aiwana-smoke-password'; python tools\smoke_prod.py"
