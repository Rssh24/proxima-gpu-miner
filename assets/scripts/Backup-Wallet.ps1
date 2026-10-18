$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms

# This action is run explicitly by the user. It copies only the encrypted key.
# DPAPI unlock material and plaintext recovery passwords are never exported.
try {
    if ($env:PROXIMA_MINER_DATA) {
        $dataRoot = [IO.Path]::GetFullPath($env:PROXIMA_MINER_DATA)
    } elseif ($env:LOCALAPPDATA) {
        $dataRoot = Join-Path $env:LOCALAPPDATA 'ProximaGpuMinerBeta\take1'
    } else {
        throw 'Local data folder is unavailable.'
    }
    $encryptedKey = Join-Path $dataRoot 'wallet\proxima.key'
    if (-not (Test-Path -LiteralPath $encryptedKey -PathType Leaf)) {
        [System.Windows.Forms.MessageBox]::Show(
            'No encrypted wallet was found. Complete GPU and wallet setup first.',
            'Wallet backup', 'OK', 'Information') | Out-Null
        return
    }
    $picker = New-Object System.Windows.Forms.FolderBrowserDialog
    $picker.Description = 'Choose a local folder for the encrypted wallet backup. Save the recovery password separately.'
    $picker.ShowNewFolderButton = $true
    try {
        if ($picker.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { return }
        $parent = [IO.Path]::GetFullPath($picker.SelectedPath)
    } finally {
        $picker.Dispose()
    }
    # Use a new subfolder and never overwrite another backup or source wallet.
    $label = 'Proxima-Take1-Wallet-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0,6)
    $destination = Join-Path $parent $label
    New-Item -ItemType Directory -Path $destination | Out-Null
    $userSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    & icacls.exe $destination /inheritance:r /grant:r ('*' + $userSid + ':(OI)(CI)F') '*S-1-5-18:(OI)(CI)F' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not protect the backup directory.' }
    Copy-Item -LiteralPath $encryptedKey -Destination (Join-Path $destination 'proxima.key') -ErrorAction Stop
    $instructions = @'
PROXIMA TAKE 1 — ENCRYPTED WALLET BACKUP

proxima.key is your encrypted wallet file. This backup does not contain a
plaintext private key, a recovery password, or a Windows DPAPI unlock file.

To recover after reinstalling Windows or on another PC, you need this
encrypted key file AND the correct wallet recovery password. Save the
password separately using the application's local password display.

Keep a separate offline copy on an external drive. A backup on the same disk
does not protect against that disk failing. Do not upload this folder or
share it in chat. Keep the recovery password private and separate.
'@
    [IO.File]::WriteAllText((Join-Path $destination 'BACKUP-README.txt'), $instructions, (New-Object Text.UTF8Encoding($false)))
    [System.Windows.Forms.MessageBox]::Show(
        "Encrypted wallet backup saved to:`r`n$destination`r`n`r`nSave the recovery password separately through the application. The backup cannot be recovered without it. Keep an offline copy on a separate drive.",
        'Wallet backup complete', 'OK', 'Information') | Out-Null
} catch {
    [System.Windows.Forms.MessageBox]::Show(
        'The wallet backup could not be completed. Check the destination, write permissions, and available disk space. Your original wallet has not been changed.',
        'Wallet backup failed', 'OK', 'Error') | Out-Null
}
