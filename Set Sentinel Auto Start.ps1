param(
    [ValidateSet('Install', 'Remove', 'Status')]
    [string]$Action = 'Install'
)

$ErrorActionPreference = 'Stop'
$shortcutName = 'Sentinel Auto Start.lnk'
$startupDirectory = [Environment]::GetFolderPath('Startup')
$shortcutPath = Join-Path $startupDirectory $shortcutName
$launcherPath = Join-Path $PSScriptRoot 'Start Sentinel Desktop.ps1'

function Test-AutoStart {
    Test-Path -LiteralPath $shortcutPath
}

switch ($Action) {
    'Install' {
        if (-not (Test-Path -LiteralPath $launcherPath)) {
            throw "Sentinel launcher was not found at $launcherPath"
        }

        $shell = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut($shortcutPath)
        $shortcut.TargetPath = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
        $shortcut.Arguments = "-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$launcherPath`" -NoBrowser"
        $shortcut.WorkingDirectory = $PSScriptRoot
        $shortcut.Description = 'Start the Sentinel controller silently when this user signs in.'
        $shortcut.Save()
        Write-Output "Sentinel auto-start installed for $env:USERNAME."
        Write-Output "Shortcut: $shortcutPath"
    }
    'Remove' {
        if (Test-AutoStart) {
            Remove-Item -LiteralPath $shortcutPath
            Write-Output 'Sentinel auto-start removed.'
        } else {
            Write-Output 'Sentinel auto-start was not installed.'
        }
    }
    'Status' {
        if (Test-AutoStart) {
            Write-Output "Sentinel auto-start is installed: $shortcutPath"
        } else {
            Write-Output 'Sentinel auto-start is not installed.'
            exit 1
        }
    }
}
