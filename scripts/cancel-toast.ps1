param([string]$Tag,[string]$ReceiptFile)
$ErrorActionPreference='Stop'
try {
    [Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime] | Out-Null
    [Windows.UI.Notifications.ToastNotificationManager]::History.Remove($Tag,'CodexChatMonitor','Microsoft.Windows.PowerShell')
    @{removal_submitted=$true;tag=$Tag;actual_display_verified=$false} | ConvertTo-Json | Set-Content -LiteralPath $ReceiptFile -Encoding UTF8
} catch {
    @{removal_submitted=$false;error=$_.Exception.Message} | ConvertTo-Json | Set-Content -LiteralPath $ReceiptFile -Encoding UTF8
    exit 1
}
