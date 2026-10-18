param(
    [Parameter(Mandatory=$true)][string]$Python,
    [string]$SourceRoot = (Split-Path $PSScriptRoot -Parent),
    [string]$PackageRoot = '',
    [string]$Output = ''
)
$ErrorActionPreference = 'Stop'
$pythonPath = (Resolve-Path -LiteralPath $Python).Path
$sourcePath = (Resolve-Path -LiteralPath $SourceRoot).Path
$testArguments = @('-B', (Join-Path $PSScriptRoot 'run_tests.py'), '--source-root', $sourcePath)
if ($PackageRoot) { $testArguments += @('--package-root', (Resolve-Path -LiteralPath $PackageRoot).Path) }
if ($Output) { $testArguments += @('--output', [IO.Path]::GetFullPath($Output)) }
& $pythonPath @testArguments
if ($LASTEXITCODE -ne 0) { throw 'CPU-only regression tests failed. No GPU validation was performed.' }
