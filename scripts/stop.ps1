param([Parameter(Mandatory=$true)][string]$Config)
$settings=Get-Content -LiteralPath $Config -Raw -Encoding UTF8 | ConvertFrom-Json
New-Item -ItemType File -Path (Join-Path $settings.runtime 'stop.request') -Force | Out-Null
