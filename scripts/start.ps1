param([Parameter(Mandatory=$true)][string]$Config,[string]$Python,[switch]$Show)
$ErrorActionPreference='Stop'
$app=Split-Path -Parent $PSScriptRoot
if (-not $Python) { $Python=Join-Path $app '.venv/Scripts/python.exe' }
$settings=Get-Content -LiteralPath $Config -Raw -Encoding UTF8 | ConvertFrom-Json
if ($Show) { New-Item -ItemType File -Path (Join-Path $settings.runtime 'show.request') -Force | Out-Null; exit }
$pythonWindowless=Join-Path (Split-Path -Parent $Python) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonWindowless)) { $pythonWindowless=$Python }
Start-Process -FilePath $pythonWindowless -WorkingDirectory $app -ArgumentList @('-B','-m','chat_monitor','--config',('"'+$Config+'"')) -WindowStyle Hidden
