param([Parameter(Mandatory=$true)][string]$InputFile,[Parameter(Mandatory=$true)][string]$ReceiptFile)
$ErrorActionPreference='Stop'
try {
    $payload=Get-Content -LiteralPath $InputFile -Raw -Encoding UTF8 | ConvertFrom-Json
    [Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime] | Out-Null
    [Windows.Data.Xml.Dom.XmlDocument,Windows.Data.Xml.Dom.XmlDocument,ContentType=WindowsRuntime] | Out-Null
    $xml=New-Object Windows.Data.Xml.Dom.XmlDocument
    $title=[System.Security.SecurityElement]::Escape($payload.title)
    $body=[System.Security.SecurityElement]::Escape($payload.body)
    $xml.LoadXml("<toast><visual><binding template='ToastGeneric'><text>$title</text><text>$body</text></binding></visual></toast>")
    $notification=[Windows.UI.Notifications.ToastNotification]::new($xml)
    $notifier=[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Microsoft.Windows.PowerShell')
    $notifier.Show($notification)
    @{submitted=$true;method='Windows.UI.Notifications.ToastNotificationManager.Show';setting=[string]$notifier.Setting;pixel_verified=$false;utc=[DateTime]::UtcNow.ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath $ReceiptFile -Encoding UTF8
} catch {
    @{submitted=$false;error=$_.Exception.Message} | ConvertTo-Json | Set-Content -LiteralPath $ReceiptFile -Encoding UTF8
    exit 1
}
