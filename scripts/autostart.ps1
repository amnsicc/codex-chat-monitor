param([ValidateSet('Preview','Install','Remove')][string]$Action='Preview',[string]$Config,[string]$TargetDirectory)
$ErrorActionPreference='Stop'
$startup=[Environment]::GetFolderPath('Startup')
if ($Action -eq 'Preview' -and -not $TargetDirectory) { $TargetDirectory=$startup }
if (-not $TargetDirectory) { throw 'Explicit isolated TargetDirectory required' }
$directory=[IO.Path]::GetFullPath($TargetDirectory)
$target=Join-Path $directory 'CodexChatMonitor.vbs'
if ($Action -eq 'Preview') { Write-Output "User startup entry: $target"; exit }
if ($directory.TrimEnd('\') -ieq $startup.TrimEnd('\')) { throw 'User login changes await formal integration' }
if ($Action -eq 'Install') {
    if (-not $Config -or -not (Test-Path -LiteralPath $Config)) { throw 'A concrete config file is required' }
    $script=Join-Path $PSScriptRoot 'start.ps1'
    if ($script.Contains('%') -or $Config.Contains('%')) { throw 'Percent signs are not supported in startup paths' }
    if (Test-Path -LiteralPath $target) { throw 'Existing entry must be reviewed before replacement' }
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
    $command='powershell.exe -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "'+$script+'" -Config "'+$Config+'"'
    $escaped=$command.Replace('"','""')
    $body="' CodexChatMonitor owned entry"+[Environment]::NewLine+'Set shell = CreateObject("WScript.Shell")'+[Environment]::NewLine+'shell.Run "'+$escaped+'", 0, False'+[Environment]::NewLine
    [IO.File]::WriteAllText($target,$body,[Text.Encoding]::Unicode)
    Write-Output "Installed $target"
} else {
    if (Test-Path -LiteralPath $target) {
        $body=Get-Content -LiteralPath $target -Raw -Encoding Unicode
        if (-not $body.Contains((Join-Path $PSScriptRoot 'start.ps1'))) { throw 'Entry is not owned by this installation' }
        Remove-Item -LiteralPath $target
    }
    Write-Output "Removed owned entry $target"
}
