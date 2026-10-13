$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Get-Command conda -ErrorAction SilentlyContinue)) { throw '未找到 Conda；请先运行 setup.ps1' }
conda --version | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Conda 命令无法执行；请检查 Conda 安装。' }
$env:QT_QPA_PLATFORM = 'offscreen'
conda run --no-capture-output -n mower-annotator python -m pytest -q --basetemp=.pytest_tmp
exit $LASTEXITCODE
