param([switch]$SkipOnedir)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$candidates = New-Object 'System.Collections.Generic.List[string]'
if ($env:CONDA_PREFIX -and (Split-Path $env:CONDA_PREFIX -Leaf) -eq 'mower-annotator') {
    $candidates.Add((Join-Path $env:CONDA_PREFIX 'python.exe'))
}
if ($env:CONDA_ENVS_PATH) {
    foreach ($base in ($env:CONDA_ENVS_PATH -split ';')) {
        if ($base) { $candidates.Add((Join-Path $base 'mower-annotator\python.exe')) }
    }
}
$condaCommand = Get-Command conda -ErrorAction SilentlyContinue
if ($condaCommand) {
    $condaRoot = Split-Path (Split-Path (Split-Path $condaCommand.Source -Parent) -Parent) -Parent
    $candidates.Add((Join-Path $condaRoot 'envs\mower-annotator\python.exe'))
}
if ($env:USERPROFILE) {
    $candidates.Add((Join-Path $env:USERPROFILE '.conda\envs\mower-annotator\python.exe'))
}
$python = $null
foreach ($candidate in $candidates) {
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { $python = $candidate; break }
}
if (-not $python) { throw 'mower-annotator environment not found. Activate it or set CONDA_ENVS_PATH.' }

$version = & $python -c "import sys; print('.'.join(map(str, sys.version_info[:2])))"
if ($LASTEXITCODE -ne 0 -or $version.Trim() -ne '3.11') { throw 'Build requires Python 3.11 in mower-annotator.' }
& $python -c 'import PySide6, PIL, yaml; from app.utils.core import class_hash; print(class_hash())'
if ($LASTEXITCODE -ne 0) { throw 'Runtime dependencies or classes.yaml are missing in mower-annotator.' }
& $python -m PyInstaller --version | Out-Null
if ($LASTEXITCODE -ne 0) {
    & $python -m pip install 'pyinstaller>=6,<7' --disable-pip-version-check
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller installation failed.' }
}

$env:PYINSTALLER_CONFIG_DIR = Join-Path $PSScriptRoot '.pyinstaller-cache'
$tempDir = Join-Path $PSScriptRoot '.packaging-tmp'
New-Item -ItemType Directory -Force -Path $env:PYINSTALLER_CONFIG_DIR, $tempDir | Out-Null
$originalTemp = $env:TEMP
$originalTmp = $env:TMP
$originalQt = $env:QT_QPA_PLATFORM
try {
    $env:TEMP = $tempDir
    $env:TMP = $tempDir
    $env:QT_QPA_PLATFORM = 'offscreen'
    if (-not $SkipOnedir) {
        & $python -m PyInstaller --noconfirm --clean MowerAnnotatorProbe.spec
        if ($LASTEXITCODE -ne 0) { throw 'Onedir build failed.' }
        $probe = Join-Path $PSScriptRoot 'dist\MowerAnnotatorProbe\MowerAnnotatorProbe.exe'
        if (-not (Test-Path -LiteralPath $probe -PathType Leaf)) { throw 'Onedir EXE is missing.' }
        $probeReport = Join-Path $PSScriptRoot 'docs\EXE_ONEDIR_TEST_REPORT.json'
        $probeProcess = Start-Process -FilePath $probe -ArgumentList ('--self-test "' + $probeReport + '"') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -Wait -PassThru
        if ($probeProcess.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $probeReport)) { throw 'Onedir packaged smoke test failed.' }
        if ((Get-Content -Raw -LiteralPath $probeReport | ConvertFrom-Json).status -ne 'passed') { throw 'Onedir packaged report is not passed.' }
    }

    & $python -m PyInstaller --noconfirm --clean MowerAnnotator.spec
    if ($LASTEXITCODE -ne 0) { throw 'Onefile build failed.' }
    $exe = Join-Path $PSScriptRoot 'dist\MowerAnnotator.exe'
    if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { throw 'Final EXE is missing.' }
    $report = Join-Path $PSScriptRoot 'docs\EXE_BUILD_TEST_REPORT.json'
    $exeProcess = Start-Process -FilePath $exe -ArgumentList ('--self-test "' + $report + '"') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -Wait -PassThru
    if ($exeProcess.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $report)) { throw 'Onefile packaged smoke test failed.' }
    if ((Get-Content -Raw -LiteralPath $report | ConvertFrom-Json).status -ne 'passed') { throw 'Onefile packaged report is not passed.' }
    $item = Get-Item -LiteralPath $exe
    Write-Host ('EXE: ' + $item.FullName)
    Write-Host ('SIZE_BYTES: ' + $item.Length)
    Write-Host ('TEST_REPORT: ' + $report)
}
finally {
    $env:TEMP = $originalTemp
    $env:TMP = $originalTmp
    $env:QT_QPA_PLATFORM = $originalQt
}
