# Run explicitly from an elevated application. No restart is performed.
$ErrorActionPreference = 'Stop'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run the application as administrator or SYSTEM and try again.'
}
$path = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System'
Set-ItemProperty -Path $path -Name 'EnableLUA' -Value 0 -Type DWord
if ((Get-ItemPropertyValue -Path $path -Name 'EnableLUA') -ne 0) {
    throw 'EnableLUA verification failed. Check the policy before retrying.'
}
Write-Output 'UAC disabled in the registry (EnableLUA=0). Restart the VDI manually to apply the change.'
