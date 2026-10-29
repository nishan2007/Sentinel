param(
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$controllerDirectory = Join-Path $PSScriptRoot 'sentinel-controller'
$pythonPath = Join-Path $controllerDirectory '.venv\Scripts\python.exe'
$dashboardUrl = 'http://localhost:8088/dashboard'
$logPath = Join-Path $controllerDirectory 'data\sentinel-startup.log'

function Write-StartupLog([string]$Message) {
    $line = '{0} {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
}

function Test-Sentinel {
    try {
        $health = Invoke-RestMethod 'http://127.0.0.1:8088/health' -TimeoutSec 2
        return $health.status -eq 'ok'
    } catch { return $false }
}

try {
    if (-not (Test-Sentinel)) {
        if (-not (Test-Path -LiteralPath $pythonPath)) {
            throw 'Sentinel Python environment is missing. Run the Windows setup first.'
        }
        Start-Process -FilePath $pythonPath -ArgumentList '-m', 'app.server', '--host', '0.0.0.0', '--port', '8088' -WorkingDirectory $controllerDirectory -WindowStyle Hidden
        $ready = $false
        for ($attempt = 0; $attempt -lt 30; $attempt++) {
            if (Test-Sentinel) { $ready = $true; break }
            Start-Sleep -Seconds 1
        }
        if (-not $ready) { throw 'Sentinel did not start within 30 seconds.' }
        Write-StartupLog 'Sentinel started successfully.'
    } else {
        Write-StartupLog 'Sentinel was already running.'
    }
    if (-not $NoBrowser) {
        Start-Process $dashboardUrl
    }
} catch {
    Write-StartupLog ('Sentinel failed to start: {0}' -f $_.Exception.Message)
    if (-not $NoBrowser) {
        Add-Type -AssemblyName System.Windows.Forms
        [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'Sentinel startup') | Out-Null
    }
    exit 1
}
