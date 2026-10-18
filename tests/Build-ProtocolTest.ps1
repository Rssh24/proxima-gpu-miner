param(
    [Parameter(Mandatory=$true)][string]$Python,
    [Parameter(Mandatory=$true)][string]$Go,
    [string]$SourceRoot = (Split-Path $PSScriptRoot -Parent),
    [string]$OutputDirectory = '',
    [string]$GoModCache = ''
)
$ErrorActionPreference = 'Stop'
$arguments = @('-B', (Join-Path $PSScriptRoot 'build_protocol_test.py'), '--go', (Resolve-Path -LiteralPath $Go).Path, '--source-root', (Resolve-Path -LiteralPath $SourceRoot).Path)
if ($OutputDirectory) { $arguments += @('--output-directory', [IO.Path]::GetFullPath($OutputDirectory)) }
if ($GoModCache) { $arguments += @('--gomodcache', (Resolve-Path -LiteralPath $GoModCache).Path) }
& (Resolve-Path -LiteralPath $Python).Path @arguments
if ($LASTEXITCODE -ne 0) { throw 'Protocol test compilation failed. No GPU test was run.' }
