#Requires -Version 5.1
<# Builds a Windows GUI bootstrapper and a source ZIP. No installation or NH calls.
   Only tracked repository files and the explicit setup files below enter the ZIP.
   Each build uses a fresh output directory; existing archives are never overwritten.
   The ZIP bundles the EXE with those sources: the EXE only runs beside the sources
   it installs, so it is never handed out on its own. -Version names the build inside
   the ZIP. The copy people normally download is the one committed at the repository
   root, which -SkipZip rebuilds. #>
[CmdletBinding()]
param([switch]$SkipZip, [string]$Version = '')
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $compiler)) { throw '.NET Framework 4.x C# compiler was not found. Build on Windows with .NET Framework installed.' }
$destination = Join-Path $repo ('desktop\setup-dist\' + [DateTime]::Now.ToString('yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N').Substring(0, 8))
$bundle = Join-Path $destination 'NHFutures'
New-Item -ItemType Directory -Path $bundle | Out-Null
$exe = Join-Path $bundle 'NH FUTURES API Setup.exe'
$sources = @((Join-Path $PSScriptRoot 'setup\SetupCore.cs'), (Join-Path $PSScriptRoot 'setup\SetupForm.cs'))
& $compiler /nologo /target:winexe /platform:anycpu /optimize+ /codepage:65001 `
    /reference:System.dll /reference:System.Core.dll /reference:System.Drawing.dll /reference:System.Windows.Forms.dll `
    "/out:$exe" @sources
if ($LASTEXITCODE -ne 0) { throw 'Setup compilation failed.' }
Write-Output "Built: $exe"
if ($SkipZip) { return }

Push-Location -LiteralPath $repo
try {
    # core.quotepath=false keeps Korean paths readable. Git is needed only by the ZIP producer.
    $tracked = @(git -c core.quotepath=false ls-files)
    if ($LASTEXITCODE -ne 0) { throw 'Cannot enumerate tracked source files. Build the distribution from a Git checkout.' }
    # Name the build so a downloaded ZIP can be traced back to the commit it came from.
    if (-not $Version) {
        $commit = (git rev-parse --short HEAD)
        $Version = if ($LASTEXITCODE -eq 0 -and $commit) { "local-$commit" } else { 'local' }
    }
} finally { Pop-Location }
$setupFiles = @('README.md', 'scripts/bootstrap.ps1', 'scripts/build-setup.ps1',
    'scripts/test-setup.ps1', 'scripts/setup/SetupCore.cs', 'scripts/setup/SetupForm.cs',
    'scripts/setup/SetupTests.cs', 'docs/windows-setup.md')
$paths = @($tracked + $setupFiles | Sort-Object -Unique)
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = Join-Path $destination 'NHFutures-Windows-Setup.zip'
$stream = [IO.File]::Open($zip, [IO.FileMode]::CreateNew)
$archive = New-Object IO.Compression.ZipArchive($stream, [IO.Compression.ZipArchiveMode]::Create, $false)
try {
    foreach ($relative in $paths) {
        # The launcher is added once from this build, below. A committed EXE would be
        # stale the moment the sources change, so one is never packaged from the tree.
        if ($relative -in @('NH FUTURES API Setup.exe', 'NH API Setup.exe')) { continue }
        # Never package repository metadata, generated output or private/local configuration.
        if ($relative -match '(^|/)(\.git|\.claude|\.codex|\.agents|\.venv|node_modules|nh_private|setup-dist)(/|$)' -or
            $relative -match '(^|/)(config\.yaml|\.env[^/]*|CLAUDE\.md|AGENTS\.md)$' -or
            $relative -match '\.(log|pem|key)$') { continue }
        $full = [IO.Path]::GetFullPath((Join-Path $repo $relative))
        if (-not $full.StartsWith($repo.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) { throw "Outside project: $relative" }
        if (-not (Test-Path -LiteralPath $full -PathType Leaf)) { throw "Missing source file: $relative" }
        [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive, $full, ('NHFutures/' + $relative.Replace('\', '/'))) | Out-Null
    }
    [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive, $exe, 'NHFutures/NH FUTURES API Setup.exe') | Out-Null
    # Which build this is: the -Version name, or the commit when none was given.
    $writer = New-Object IO.StreamWriter($archive.CreateEntry('NHFutures/VERSION').Open(), (New-Object Text.UTF8Encoding($false)))
    try { $writer.WriteLine($Version) } finally { $writer.Dispose() }
} finally { $archive.Dispose(); $stream.Dispose() }
# Lower case is what sha256sum and certutil print, so a reader can compare without
# converting. Get-FileHash returns upper case.
$hash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
# `sha256sum -c` reads this shape, and so does a person comparing by eye.
$sums = Join-Path $destination 'SHA256SUMS.txt'
[IO.File]::WriteAllText($sums, "$hash  $([IO.Path]::GetFileName($zip))`n", (New-Object Text.UTF8Encoding($false)))
Write-Output "Version: $Version"
Write-Output "ZIP: $zip"
Write-Output "SHA256: $hash"
Write-Output "Sums: $sums"
Write-Output 'Extract the entire ZIP before launching NH FUTURES API Setup.exe. This build is not code-signed.'
