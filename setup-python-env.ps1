param(
    [string]$PythonVersion = "3.12",
    [string]$VenvPath = ""
)

$ErrorActionPreference = "Stop"
$RuntimeRoot = if ($env:DOCUMENT_READER_HOME) { $env:DOCUMENT_READER_HOME } else { Join-Path $HOME ".document-reader" }
$BinDir = Join-Path $RuntimeRoot "bin"
if (-not $VenvPath) { $VenvPath = Join-Path $RuntimeRoot "venv" }

New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
$Uv = Join-Path $BinDir "uv.exe"

if (-not (Test-Path $Uv)) {
    Write-Host "Installing uv from the official Astral installer..."
    $env:UV_INSTALL_DIR = $BinDir
    $env:UV_NO_MODIFY_PATH = "1"
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
}

if (-not (Test-Path $Uv)) { throw "uv installation failed: $Uv was not created" }

Write-Host "Installing managed Python $PythonVersion..."
& $Uv python install $PythonVersion
if ($LASTEXITCODE -ne 0) { throw "uv could not install Python $PythonVersion" }

Write-Host "Creating virtual environment at $VenvPath..."
& $Uv venv --python $PythonVersion $VenvPath
if ($LASTEXITCODE -ne 0) { throw "uv could not create the virtual environment" }

$Python = Join-Path $VenvPath "Scripts\python.exe"
Write-Host "Installing document-reader dependencies..."
& $Uv pip install --python $Python openpyxl
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed" }

& $Python -c "import openpyxl, sys; print(sys.version); print('openpyxl', openpyxl.__version__)"
if ($LASTEXITCODE -ne 0) { throw "Environment verification failed" }

Write-Host "Document Reader Python environment is ready: $Python"
