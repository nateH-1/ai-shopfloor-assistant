param(
    [switch]$InstallDeps,
    [switch]$NoBackend,
    [switch]$NoFrontend
)

$ErrorActionPreference = "Stop"

$rootPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendRun = Join-Path $rootPath "backend\run.py"
$backendReq = Join-Path $rootPath "backend\requirements.txt"
$frontendPath = Join-Path $rootPath "frontend"
$venvPython = Join-Path $rootPath "backend\venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    $venvPython = Join-Path $rootPath "venv\Scripts\python.exe"
}
$dotenvPath = Join-Path $rootPath ".env"

if (-not (Test-Path $venvPython)) {
    throw "Python venv executable not found. Expected at 'backend\venv\Scripts\python.exe' or 'venv\Scripts\python.exe'."
}

if (-not (Test-Path $backendRun)) {
    throw "Backend launcher not found at $backendRun"
}

if (-not (Test-Path $frontendPath)) {
    throw "Frontend folder not found at $frontendPath"
}

function Get-DotEnvValue {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$Key
    )

    if (-not (Test-Path $Path)) {
        return $null
    }

    $line = Get-Content -Path $Path |
        Where-Object { $_ -match "^\s*$Key\s*=\s*" } |
        Select-Object -First 1

    if (-not $line) {
        return $null
    }

    $value = ($line -split "=", 2)[1].Trim()
    if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
        $value = $value.Substring(1, $value.Length - 2)
    }
    return $value
}

# Load OPENAI_API_KEY from root .env if not already present in current shell.
if ([string]::IsNullOrWhiteSpace($env:OPENAI_API_KEY)) {
    $dotenvApiKey = Get-DotEnvValue -Path $dotenvPath -Key "OPENAI_API_KEY"
    if (-not [string]::IsNullOrWhiteSpace($dotenvApiKey)) {
        $env:OPENAI_API_KEY = $dotenvApiKey
    }
}

if ([string]::IsNullOrWhiteSpace($env:FLASK_URL)) {
    $env:FLASK_URL = "http://localhost:5000"
}

if ([string]::IsNullOrWhiteSpace($env:OPENAI_API_KEY)) {
    Write-Warning "OPENAI_API_KEY is not set. Chat and document embeddings may fail. Local speech transcription does not require this key."
}

$backendInstallCmd = ""
$frontendInstallCmd = ""
if ($InstallDeps) {
    $backendInstallCmd = "pip install -r '$backendReq'; "
    $frontendInstallCmd = "Set-Location '$frontendPath'; npm install; "
}

$condaNoPluginsCmd = "`$env:CONDA_NO_PLUGINS='true'; "

$pidsFile = Join-Path $rootPath ".dev-pids"
$spawnedPids = @()

if (-not $NoBackend) {
    $backendCommand = "${condaNoPluginsCmd}Set-Location '$rootPath'; ${backendInstallCmd}& '$venvPython' '$backendRun'"
    $proc = Start-Process powershell -WorkingDirectory $rootPath -ArgumentList @(
        "-NoProfile",
        "-NoExit",
        "-ExecutionPolicy", "Bypass",
        "-Command", $backendCommand
    ) -PassThru
    $spawnedPids += $proc.Id
    Write-Host "Backend terminal started (PID $($proc.Id))."
}

if (-not $NoFrontend) {
    $frontendCommand = "${condaNoPluginsCmd}${frontendInstallCmd}Set-Location '$frontendPath'; npm run dev"
    $proc = Start-Process powershell -WorkingDirectory $frontendPath -ArgumentList @(
        "-NoProfile",
        "-NoExit",
        "-ExecutionPolicy", "Bypass",
        "-Command", $frontendCommand
    ) -PassThru
    $spawnedPids += $proc.Id
    Write-Host "Frontend terminal started (PID $($proc.Id))."
}

if ($spawnedPids.Count -gt 0) {
    $spawnedPids -join "`n" | Set-Content -Path $pidsFile
}

Write-Host "Done. Open http://localhost:3000 once both servers are ready."
Write-Host "Run .\stop-dev.ps1 to shut everything down cleanly."
