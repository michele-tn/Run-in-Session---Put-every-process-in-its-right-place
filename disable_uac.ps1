# Run explicitly from an elevated application. No restart is performed.
param(
    [ValidateSet('Enable', 'Disable')]
    [string]$Action = 'Disable'
)

$ErrorActionPreference = 'Stop'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run the application as administrator or SYSTEM and try again.'
}
$path = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System'
$value = if ($Action -eq 'Enable') { 1 } else { 0 }
Set-ItemProperty -Path $path -Name 'EnableLUA' -Value $value -Type DWord
if ((Get-ItemPropertyValue -Path $path -Name 'EnableLUA') -ne $value) {
    throw 'EnableLUA verification failed. Check the policy before retrying.'
}
Write-Output "UAC policy saved (EnableLUA=$value). Restart Windows manually to apply the change."
