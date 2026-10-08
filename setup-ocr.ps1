param(
    # Tesseract language codes: vie (Vietnamese), eng (English), jpn, fra, ...
    [string[]]$Languages = @("vie", "eng"),
    # Only fetch the language files; do not install the Tesseract program.
    [switch]$SkipInstall
)

# Optional setup for reading scanned PDF pages and images (OCR).
#
# 1. Makes sure the Tesseract program is on the machine (installs it with
#    winget when it is not; Windows asks for permission).
# 2. Downloads the language files into <runtime>\tessdata, where the skill
#    looks first. Nothing is written into the Tesseract installation.

$ErrorActionPreference = "Stop"
$RuntimeRoot = if ($env:DOCUMENT_READER_HOME) { $env:DOCUMENT_READER_HOME } else { Join-Path $HOME ".document-reader" }
$TessData = Join-Path $RuntimeRoot "tessdata"
$DataSource = "https://github.com/tesseract-ocr/tessdata_fast/raw/main"

function Find-Tesseract {
    if ($env:DOCUMENT_READER_TESSERACT) {
        if (Test-Path $env:DOCUMENT_READER_TESSERACT) { return $env:DOCUMENT_READER_TESSERACT }
        return $null
    }
    $onPath = Get-Command tesseract -ErrorAction SilentlyContinue
    if ($onPath) { return $onPath.Source }
    foreach ($root in @($env:ProgramFiles, $env:LOCALAPPDATA)) {
        if (-not $root) { continue }
        foreach ($folder in @("Tesseract-OCR", "Programs\Tesseract-OCR")) {
            $candidate = Join-Path (Join-Path $root $folder) "tesseract.exe"
            if (Test-Path $candidate) { return $candidate }
        }
    }
    return $null
}

foreach ($language in $Languages) {
    if ($language -notmatch '^[A-Za-z0-9_]+$') { throw "Not a Tesseract language code: $language" }
}

$Tesseract = Find-Tesseract
if (-not $Tesseract -and -not $SkipInstall) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "Tesseract is not installed and winget is not available. Install it from https://github.com/UB-Mannheim/tesseract/wiki and run this script again."
    }
    Write-Host "Installing Tesseract with winget (Windows will ask for permission)..."
    winget install --id UB-Mannheim.TesseractOCR --exact --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { throw "winget could not install Tesseract (exit code $LASTEXITCODE)" }
    $Tesseract = Find-Tesseract
}
if (-not $Tesseract) {
    throw "Tesseract was not found. Install it, or set DOCUMENT_READER_TESSERACT to tesseract.exe, and run this script again."
}
Write-Host "Tesseract: $Tesseract"

New-Item -ItemType Directory -Force -Path $TessData | Out-Null
foreach ($language in $Languages) {
    $target = Join-Path $TessData "$language.traineddata"
    if (Test-Path $target) {
        Write-Host "Language file already there: $language"
        continue
    }
    Write-Host "Downloading language file: $language"
    # To a temporary name first, so an interrupted download never leaves a
    # half-written file that Tesseract would then fail to load.
    $partial = "$target.part"
    try {
        Invoke-WebRequest -Uri "$DataSource/$language.traineddata" -OutFile $partial -UseBasicParsing
    } catch {
        Remove-Item -Force -ErrorAction SilentlyContinue $partial
        throw "Could not download $language.traineddata (is '$language' a Tesseract language code?): $($_.Exception.Message)"
    }
    Move-Item -Force $partial $target
}

$listing = & $Tesseract --tessdata-dir $TessData --list-langs 2>&1 | Out-String
foreach ($language in $Languages) {
    if ($listing -notmatch "(?m)^$language\s*$") { throw "Tesseract does not list '$language' in $TessData" }
}
Write-Host "OCR is ready. Languages in $TessData`: $($Languages -join ', ')"
Write-Host "Try it: python scripts\read_pdf.py <scanned.pdf> --ocr"
