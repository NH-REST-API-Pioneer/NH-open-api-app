#Requires -Version 5.1
[CmdletBinding()]
param([string]$Screenshot)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$output = Join-Path $repo ('desktop\setup-dist\tests-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $output | Out-Null
$exe = Join-Path $output 'SetupTests.exe'
foreach ($script in @('bootstrap.ps1', 'build-setup.ps1', 'compare-setup.ps1', 'test-setup.ps1')) {
    $path = Join-Path $PSScriptRoot $script
    $bytes = [IO.File]::ReadAllBytes($path)
    if ($bytes.Length -lt 3 -or $bytes[0] -ne 239 -or $bytes[1] -ne 187 -or $bytes[2] -ne 191) { throw "UTF-8 BOM missing: $script" }
    $tokens = $null; $parseErrors = $null
    [Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$parseErrors) | Out-Null
    if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
    Write-Output "PASS: PowerShell syntax and BOM: $script"
}
& $compiler /nologo /target:exe /main:NHSetup.SetupTests /codepage:65001 `
    /reference:System.dll /reference:System.Core.dll /reference:System.Drawing.dll /reference:System.Windows.Forms.dll `
    "/out:$exe" (Join-Path $PSScriptRoot 'setup\SetupCore.cs') (Join-Path $PSScriptRoot 'setup\SetupForm.cs') (Join-Path $PSScriptRoot 'setup\SetupTests.cs')
if ($LASTEXITCODE -ne 0) { throw 'Test compilation failed.' }
$launchDir = Join-Path $output 'launch-fixture\desktop\dist'
New-Item -ItemType Directory -Path $launchDir | Out-Null
& $compiler /nologo /target:winexe /codepage:65001 "/out:$launchDir\NH FUTURES API.exe" (Join-Path $PSScriptRoot 'setup\LaunchFixture.cs')
if ($LASTEXITCODE -ne 0) { throw 'Launch fixture compilation failed.' }
if ($Screenshot) { & $exe $repo $Screenshot } else { & $exe $repo }
if ($LASTEXITCODE -ne 0) { throw 'Setup tests failed.' }

# The repository keeps the setup helper at its root, so a source change that is
# not rebuilt would ship an executable that does not match its own sources. The
# comparison that guards that is scripts\compare-setup.ps1; these checks prove it
# accepts a rebuild of the same sources and rejects a build of changed sources.
$compare = Join-Path $PSScriptRoot 'compare-setup.ps1'
$root = Join-Path $repo 'NH FUTURES API Setup.exe'
if (-not (Test-Path -LiteralPath $root)) { throw 'Setup executable is missing from the repository root.' }

# The assembly name comes from /out:, so the file must carry the same name
# as the committed one or the metadata alone would make them differ.
$sameDir = Join-Path $output 'same'
New-Item -ItemType Directory -Path $sameDir | Out-Null
$same = Join-Path $sameDir 'NH FUTURES API Setup.exe'
& $compiler /nologo /target:winexe /platform:anycpu /optimize+ /codepage:65001 `
    /reference:System.dll /reference:System.Core.dll /reference:System.Drawing.dll /reference:System.Windows.Forms.dll `
    "/out:$same" (Join-Path $PSScriptRoot 'setup\SetupCore.cs') (Join-Path $PSScriptRoot 'setup\SetupForm.cs')
if ($LASTEXITCODE -ne 0) { throw 'Rebuild of the unchanged sources failed.' }
& $compare -Reference $root -Candidate $same | Out-Null
Write-Output 'PASS: a rebuild of the same sources matches the committed executable'

# One changed line is enough. The copy keeps the original sources untouched.
$changed = Join-Path $output 'changed'
New-Item -ItemType Directory -Path $changed | Out-Null
$core = Join-Path $changed 'SetupCore.cs'
$form = Join-Path $changed 'SetupForm.cs'
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'setup\SetupCore.cs') -Destination $core
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'setup\SetupForm.cs') -Destination $form
$text = [IO.File]::ReadAllText($core)
[IO.File]::WriteAllText($core, $text + [Environment]::NewLine + 'internal static class SetupBuildProbe { internal const int Value = 7; }' + [Environment]::NewLine)
$other = Join-Path $changed 'NH FUTURES API Setup.exe'
& $compiler /nologo /target:winexe /platform:anycpu /optimize+ /codepage:65001 `
    /reference:System.dll /reference:System.Core.dll /reference:System.Drawing.dll /reference:System.Windows.Forms.dll `
    "/out:$other" $core $form
if ($LASTEXITCODE -ne 0) { throw 'Build of the changed sources failed.' }
$caught = $null
try { & $compare -Reference $root -Candidate $other | Out-Null } catch { $caught = $_ }
if (-not $caught) { throw 'The comparison accepted a build of changed sources.' }
Write-Output 'PASS: a build of changed sources is rejected'
