#Requires -Version 5.1
<# Compares two builds of the setup helper and fails when they differ.

   Why not a SHA256 match: the compiler this project uses
   (%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe) predates
   /deterministic, so two builds of the same sources are never byte-identical.
   Measured on 34,816 bytes: 17 bytes move, and always in the same two places -
   the 4-byte PE timestamp (at e_lfanew + 8) and the 16-byte module GUID (MVID).

   So the rule is: the files must be the same length, and every byte that
   differs outside the PE timestamp must fit inside one run of 16 bytes. One
   changed line of C# moves far more than that, which is what this check is for.

   Both files must have been built under the same output name
   (NH FUTURES API Setup.exe): the assembly name comes from the /out file name, so
   building to a different name moves the metadata wholesale and nothing matches.

   Messages stay ASCII: CI writes inline scripts as a BOM-less .ps1 and Windows
   PowerShell 5.1 reads those as the system ANSI code page. #>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Reference,
    [Parameter(Mandatory = $true)][string]$Candidate,
    [string]$Fix = 'Rebuild with scripts\build-setup.ps1 -SkipZip, copy the result to the repository root, and commit it.'
)
$ErrorActionPreference = 'Stop'

# .NET resolves relative paths against the process directory, which is not
# always where PowerShell thinks it is. Resolve before reading.
$left = [IO.File]::ReadAllBytes((Resolve-Path -LiteralPath $Reference).ProviderPath)
$right = [IO.File]::ReadAllBytes((Resolve-Path -LiteralPath $Candidate).ProviderPath)

if ($left.Length -ne $right.Length) {
    throw "Setup executables differ in size: $($left.Length) vs $($right.Length). $Fix"
}

$stamp = [BitConverter]::ToInt32($left, 0x3C) + 8
$moved = New-Object 'System.Collections.Generic.List[int]'
for ($i = 0; $i -lt $left.Length; $i++) {
    if ($left[$i] -ne $right[$i]) { $moved.Add($i) }
}
$rest = @($moved | Where-Object { $_ -lt $stamp -or $_ -ge ($stamp + 4) })
if ($rest.Count -eq 0) {
    Write-Output 'Setup executables match: only the build timestamp differs.'
    return
}

$span = $rest[$rest.Count - 1] - $rest[0] + 1
if ($span -gt 16) {
    throw "Setup executables differ: $($rest.Count) bytes across $span bytes, more than the module GUID. $Fix"
}
Write-Output 'Setup executables match: only the build timestamp and the module GUID differ.'
