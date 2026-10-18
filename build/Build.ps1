[CmdletBinding()]
param(
    [string]$Go = 'go',
    [string]$Python = 'python',
    [string]$PythonHome,
    [string]$SourceRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$OutputDirectory,
    [string]$GoModCache,
    [string]$GoCache,
    [switch]$Offline,
    [switch]$DownloadRuntime,
    [switch]$SkipTests
)
$ErrorActionPreference = 'Stop'
$buildRoot = [IO.Path]::GetFullPath($SourceRoot)
if ($Offline -and $DownloadRuntime) { throw 'Offline builds cannot download the Python runtime.' }
if ($DownloadRuntime -and -not $PythonHome) {
    $runtimePin = Get-Content -LiteralPath (Join-Path $buildRoot 'runtime\python-runtime.json') -Raw | ConvertFrom-Json
    if (-not $runtimePin.url.StartsWith('https://www.python.org/ftp/python/')) { throw 'Runtime URL must be the pinned official Python host.' }
    $downloadRoot = Join-Path $buildRoot 'build\work\downloads'
    New-Item -ItemType Directory -Force -Path $downloadRoot | Out-Null
    $runtimeArchive = Join-Path $downloadRoot ('python-' + $runtimePin.version + '-embed-amd64.zip')
    if (-not (Test-Path -LiteralPath $runtimeArchive)) {
        $partialArchive = $runtimeArchive + '.partial'
        Invoke-WebRequest -Uri $runtimePin.url -OutFile $partialArchive -UseBasicParsing
        if ((Get-FileHash -LiteralPath $partialArchive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $runtimePin.sha256) { throw 'Downloaded runtime checksum mismatch.' }
        Move-Item -LiteralPath $partialArchive -Destination $runtimeArchive
    }
    if ((Get-FileHash -LiteralPath $runtimeArchive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $runtimePin.sha256) { throw 'Cached runtime checksum mismatch.' }
    $PythonHome = Join-Path $downloadRoot ('python-' + $runtimePin.version)
    New-Item -ItemType Directory -Force -Path $PythonHome | Out-Null
    Expand-Archive -LiteralPath $runtimeArchive -DestinationPath $PythonHome -Force
}
if (-not $PSBoundParameters.ContainsKey('Python')) {
    if ($PythonHome) { $Python = Join-Path $PythonHome 'python.exe' }
    elseif (Test-Path -LiteralPath (Join-Path $buildRoot 'runtime\python\python.exe')) { $Python = Join-Path $buildRoot 'runtime\python\python.exe' }
}
$buildArgs = @('-X','utf8',(Join-Path $PSScriptRoot 'build.py'),'--source-root',$buildRoot,'--go',$Go)
if ($PythonHome) { $buildArgs += @('--python-home',[IO.Path]::GetFullPath($PythonHome)) }
if ($OutputDirectory) { $buildArgs += @('--output',[IO.Path]::GetFullPath($OutputDirectory)) }
if ($GoModCache) { $buildArgs += @('--go-mod-cache',[IO.Path]::GetFullPath($GoModCache)) }
if ($GoCache) { $buildArgs += @('--go-cache',[IO.Path]::GetFullPath($GoCache)) }
if ($Offline) { $buildArgs += '--offline' }
if ($DownloadRuntime) { $buildArgs += '--download-runtime' }
if ($SkipTests) { $buildArgs += '--skip-tests' }
& $Python @buildArgs
exit $LASTEXITCODE
