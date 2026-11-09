param([ValidateSet('Preview','Install','Remove')][string]$Action='Preview',[string]$Config,[string]$TargetDirectory)
$ErrorActionPreference='Stop'
$startup=[Environment]::GetFolderPath('Startup')
if (-not $TargetDirectory) { $TargetDirectory=$startup }
$target=[IO.Path]::GetFullPath((Join-Path $TargetDirectory 'CodexChatMonitor.cmd'))
if ($Action -eq 'Preview') { Write-Output "User startup entry: $target"; exit }
if ($Action -eq 'Install') {
    if (-not $Config -or -not (Test-Path -LiteralPath $Config)) { throw 'A concrete config file is required' }
    $script=Join-Path $PSScriptRoot 'start.ps1'
    if ($script.Contains('%') -or $Config.Contains('%')) { throw 'Percent signs are not supported in startup paths' }
    if (Test-Path -LiteralPath $target) { throw 'Existing entry must be reviewed before replacement' }
    $body="@echo off`r`npowershell.exe -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$script`" -Config `"$Config`"`r`n"
    [IO.File]::WriteAllText($target,$body,[Text.Encoding]::Default)
    Write-Output "Installed $target"
} else {
    if (Test-Path -LiteralPath $target) {
        $body=Get-Content -LiteralPath $target -Raw
        if (-not $body.Contains((Join-Path $PSScriptRoot 'start.ps1'))) { throw 'Entry is not owned by this installation' }
        Remove-Item -LiteralPath $target
    }
    Write-Output "Removed owned entry $target"
}
