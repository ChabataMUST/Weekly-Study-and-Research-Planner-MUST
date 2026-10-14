$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
# Keep temporary installation files and package downloads beside the project.
$tempPath = Join-Path $projectRoot '.install-tmp'
$cachePath = Join-Path $projectRoot '.pip-cache'
New-Item -ItemType Directory -Force -Path $tempPath,$cachePath | Out-Null
$env:TEMP = $tempPath
$env:TMP = $tempPath
$env:PIP_CACHE_DIR = $cachePath
$env:PYTHONUTF8 = '1'
$venv = Join-Path $projectRoot '.venv'
$venvPython = Join-Path $venv 'Scripts\python.exe'

function Test-Environment {
    if (-not (Test-Path -LiteralPath $venvPython)) {return $false}
    try {
        & $venvPython -c "import sys, importlib.util; raise SystemExit(0 if sys.version_info >= (3, 11) and importlib.util.find_spec('pip') else 1)" 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}

if (-not (Test-Environment)) {
    if (Test-Path -LiteralPath $venv) {
        $backupName = '.venv-backup-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
        Rename-Item -LiteralPath $venv -NewName $backupName
        Write-Host "Incomplete environment preserved as $backupName"
    }
    $pythonFound = $false
    foreach ($name in @('python','py')) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if (-not $command) {continue}
        & $command.Source -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' 2>$null
        if ($LASTEXITCODE -ne 0) {continue}
        Write-Host 'Creating a local Python environment...'
        & $command.Source -m venv $venv
        if ($LASTEXITCODE -ne 0) {throw 'Could not create the environment. Check the Python installation.'}
        $pythonFound = $true
        break
    }
    if (-not $pythonFound) {throw 'Python 3.11 or newer is required. Install Python, then run setup.cmd again.'}
}
Write-Host 'Installing runtime dependencies...'
& $venvPython -m pip install -r (Join-Path $projectRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) {throw 'Package installation failed. Check the network or proxy and run setup.cmd again.'}
& $venvPython -c "import flask, reportlab; print('Runtime dependencies are ready.')"
if ($LASTEXITCODE -ne 0) {throw 'Dependency check failed.'}
Write-Host 'Ready. Start the application with start.cmd.'
