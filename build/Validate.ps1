[CmdletBinding()]
param(
    [string]$SourceRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$PackageRoot,
    [string]$Python,
    [string]$Device = 'auto',
    [Parameter(Mandatory=$true)][string]$ProtocolExe,
    [string]$Output
)
$ErrorActionPreference = 'Stop'
$buildRoot = [IO.Path]::GetFullPath($SourceRoot)
if (-not $PackageRoot) {
    $sourceLock = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'source-lock.json') -Raw | ConvertFrom-Json
    $PackageRoot = Join-Path $buildRoot ('out\' + $sourceLock.version)
}
$PackageRoot = [IO.Path]::GetFullPath($PackageRoot)
if (-not $Python) { $Python = Join-Path $PackageRoot 'tools\python\python.exe' }
if (-not $Output) { $Output = Join-Path $PackageRoot 'validation-report.json' }
Write-Host 'Explicit validation will run brief work on the selected GPU and an official local protocol test.'
Write-Host 'It does not create a wallet or mine on the public network.'
$validationArgs = @('-B','-X','utf8',(Join-Path $buildRoot 'tests\validate_build.py'),'--package-root',$PackageRoot,'--source-root',$buildRoot,'--device',$Device,'--protocol-exe',[IO.Path]::GetFullPath($ProtocolExe),'--output',[IO.Path]::GetFullPath($Output))
& $Python @validationArgs
exit $LASTEXITCODE
