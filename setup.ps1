$ErrorActionPreference = 'Stop'
$name = 'mower-annotator'
if (-not (Get-Command conda -ErrorAction SilentlyContinue)) { throw '未找到 Conda。请先安装 Miniconda 或 Anaconda，并在 Conda PowerShell Prompt 中运行。' }
conda --version | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Conda 命令存在但无法执行；请修复 Conda 安装或改用可工作的 Conda PowerShell Prompt。' }
$envs = conda env list --json | ConvertFrom-Json
$existing = @($envs.envs | Where-Object { (Split-Path $_ -Leaf) -eq $name })
if ($existing.Count -eq 0) { conda create -y -n $name python=3.11 }
conda run -n $name python -m pip install -r (Join-Path $PSScriptRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw '依赖安装失败' }
