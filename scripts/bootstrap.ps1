#Requires -Version 5.1
<#
.SYNOPSIS
    NH선물 Open API 프로그램을 설치하고 실행 파일을 만듭니다.

.DESCRIPTION
    도구는 요구 버전을 확인해 재사용하고, 의존성 설치와 선택한 빌드는 다시 수행합니다.

      1. 필요한 도구 설치      Node.js, uv, just
      2. 프로젝트 의존성 설치
      3. 프로그램 만들기       실행 파일(.exe) 생성

    APP Key 등 인증 정보는 프로그램 안 설정 화면에서 입력합니다. 처음 켤 때 자동으로 열립니다.

    Python은 따로 설치하지 않아도 됩니다. uv가 필요한 버전을 직접 준비합니다.

    이 파일은 한글 메시지를 포함하므로 반드시 UTF-8 BOM으로 저장해야 합니다.
    Windows PowerShell 5.1은 BOM이 없으면 스크립트를 ANSI로 읽어 구문 오류가 발생합니다.

.PARAMETER DevOnly
    개발용. 도구와 의존성만 설치하고 프로그램 만들기는 건너뜁니다.

.PARAMETER SkipSetup
    프로젝트 의존성 설치를 건너뜁니다.

.PARAMETER SkipBuild
    프로그램 만들기를 건너뜁니다.

.PARAMETER NonInteractive
    설치 도우미용. 콘솔 질문 없이 전달된 옵션으로 진행하고 단계 이벤트를 출력합니다.

.PARAMETER NoShortcut
    실행 파일을 만들더라도 바탕화면 바로가기는 만들지 않습니다.

.PARAMETER DryRun
    프로젝트 파일과 선택된 단계를 확인할 뿐 도구 실행·다운로드·빌드는 하지 않습니다.

.PARAMETER CheckOnly
    설치된 도구의 버전만 조회합니다. 다운로드·의존성 설치·빌드는 하지 않습니다.

.PARAMETER CancellationFile
    설치 UI가 만드는 취소 요청 파일입니다. 현재 명령이 끝난 뒤 다음 작업 전에 중단합니다.

.EXAMPLE
    .\scripts\bootstrap.ps1

.EXAMPLE
    .\scripts\bootstrap.ps1 -DevOnly
#>
[CmdletBinding()]
param(
    [switch]$DevOnly,
    [switch]$SkipSetup,
    [switch]$SkipBuild,
    [switch]$NonInteractive,
    [switch]$NoShortcut,
    [switch]$DryRun,
    [switch]$CheckOnly,
    [string]$CancellationFile
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
if ($NonInteractive) {
    [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
    $OutputEncoding = [Console]::OutputEncoding
}

function Assert-NotCancelled {
    if ($CancellationFile -and (Test-Path -LiteralPath $CancellationFile -PathType Leaf)) {
        throw [System.OperationCanceledException]::new('설치 취소 요청을 확인했습니다. 이미 설치된 항목은 유지됩니다.')
    }
}

function Send-Stage {
    param([string]$Stage, [string]$Message)
    # 'done' 은 일이 다 끝난 뒤의 알림이라 취소 지점이 아닙니다. 마지막 단계 도중 취소를
    # 눌렀더라도 그 단계가 끝났으면 설치는 끝난 것이고, 되돌릴 다음 단계가 없습니다.
    if ($Stage -ne 'done') { Assert-NotCancelled }
    if ($NonInteractive) { Write-Output "NHSETUP|$Stage|$Message" }
    else { Write-Host "`n==> $Message" -ForegroundColor Cyan }
}

if ($DevOnly) {
    $SkipBuild = $true
}

$RepoRoot = Split-Path -Parent $PSScriptRoot
$ExePath = Join-Path $RepoRoot 'desktop\dist\NH FUTURES API.exe'

# 선택지 번호 -> 설정할 대상. 3번은 둘 다 고르는 경우입니다.

function Write-Step { param([string]$Message) Write-Host "`n==> $Message" -ForegroundColor Cyan }
function Write-Ok { param([string]$Message) Write-Host "    $Message" -ForegroundColor Green }
function Write-Info { param([string]$Message) Write-Host "    $Message" -ForegroundColor Gray }

function Get-VersionFrom {
    <# 명령을 실행해 첫 번째 x.y.z 형태의 버전을 읽습니다. 명령이 없으면 $null. #>
    param([string]$Command, [string[]]$ArgumentList = @('--version'))

    if (-not (Get-Command $Command -ErrorAction SilentlyContinue)) { return $null }
    try {
        $raw = & $Command @ArgumentList 2>&1 | Out-String
    }
    catch {
        return $null
    }
    if ($raw -match '(\d+)\.(\d+)\.(\d+)') { return [version]$Matches[0] }
    return $null
}

# MinVersion 이 $null 이면 설치 여부만 확인합니다.
$Tools = @(
    @{ Name = 'Node.js'; Command = 'node'; MinVersion = [version]'22.15.0'; WingetId = 'OpenJS.NodeJS.LTS' }
    @{ Name = 'uv';      Command = 'uv';   MinVersion = $null;             WingetId = 'astral-sh.uv' }
    @{ Name = 'just';    Command = 'just'; MinVersion = $null;             WingetId = 'Casey.Just' }
)

function Update-SessionPath {
    <#
        winget은 PATH를 레지스트리에만 기록합니다. 실행 중인 셸은 물론 새로 연 터미널도
        explorer.exe 재시작 또는 로그아웃 전까지 이를 인식하지 못하므로, 방금 설치한
        도구를 이어서 사용하려면 레지스트리에서 직접 다시 읽어와야 합니다.
        기존 PATH를 덮어쓰지 않고 없는 항목만 덧붙입니다.
    #>
    $existing = $env:PATH -split ';' | Where-Object { $_ }
    $registry = @(
        [Environment]::GetEnvironmentVariable('Path', 'Machine')
        [Environment]::GetEnvironmentVariable('Path', 'User')
    ) | Where-Object { $_ } | ForEach-Object { $_ -split ';' } | Where-Object { $_ }

    $missing = $registry | Where-Object { $existing -notcontains $_ }
    if ($missing) {
        $env:PATH = (@($existing) + @($missing)) -join ';'
    }
}

function Install-Tool {
    param([hashtable]$Tool)
    Assert-NotCancelled

    Write-Info "winget으로 $($Tool.Name) 설치 중... (몇 분 걸릴 수 있습니다)"
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw 'winget이 없습니다. Microsoft Store의 앱 설치 관리자를 설치하거나 회사 관리자에게 문의해 주세요.'
    }
    $installArgs = @('install', '--id', $Tool.WingetId, '-e', '--source', 'winget',
        '--accept-source-agreements', '--accept-package-agreements')
    if ($NonInteractive) { $installArgs += @('--silent', '--disable-interactivity') }
    & winget @installArgs
    if ($LASTEXITCODE -ne 0) {
        throw "$($Tool.Name) 설치에 실패했습니다. (winget 종료 코드: $LASTEXITCODE)"
    }

    Update-SessionPath

    $version = Get-VersionFrom -Command $Tool.Command
    if ($null -eq $version) {
        throw @"
$($Tool.Name) 설치는 완료되었지만 '$($Tool.Command)' 명령을 찾을 수 없습니다.
터미널을 새로 열거나 로그아웃 후 다시 로그인한 뒤 이 스크립트를 다시 실행해 주세요.
"@
    }
    if ($Tool.MinVersion -and $version -lt $Tool.MinVersion) {
        throw @"
$($Tool.Name) 를 설치했지만 여전히 $version 이 사용됩니다. (필요 버전: $($Tool.MinVersion) 이상)
이전에 설치된 버전이 PATH에서 우선하고 있을 수 있습니다.
'where $($Tool.Command)' 로 확인한 뒤 PATH 순서를 조정하거나 이전 버전을 제거해 주세요.
"@
    }
    Write-Ok "$($Tool.Name) $version 설치 완료"
}

function Invoke-Just {
    <# 프로젝트 폴더에서 just 명령을 실행합니다. #>
    param([string]$Recipe, [string]$What)
    Assert-NotCancelled

    Push-Location -LiteralPath $RepoRoot
    try {
        just $Recipe
        if ($LASTEXITCODE -ne 0) {
            throw "$What 이(가) 실패했습니다. (종료 코드: $LASTEXITCODE)"
        }
    }
    finally {
        Pop-Location
    }
}

function Confirm-Yes {
    <# 예/아니오를 묻습니다. 기본값은 Enter 만 눌렀을 때 선택됩니다. #>
    param([string]$Prompt, [bool]$DefaultYes = $true)

    $hint = if ($DefaultYes) { '(Y/n)' } else { '(y/N)' }
    while ($true) {
        $answer = (Read-Host "$Prompt $hint").Trim().ToLower()
        if (-not $answer) { return $DefaultYes }
        if ($answer -in @('y', 'yes', '예')) { return $true }
        if ($answer -in @('n', 'no', '아니오')) { return $false }
        Write-Host "    y 또는 n 으로 입력해 주세요." -ForegroundColor Yellow
    }
}

function New-DesktopShortcut {
    param([string]$Target, [string]$Name)

    $desktop = [Environment]::GetFolderPath('Desktop')
    $linkPath = Join-Path $desktop "$Name.lnk"
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut($linkPath)
    $link.TargetPath = $Target
    $link.WorkingDirectory = Split-Path -Parent $Target
    $link.Description = 'NH FUTURES API — NH선물 Open API 기반 트레이딩 플랫폼'
    $link.Save()
    return $linkPath
}

# ---------------------------------------------------------------------------

Write-Host ""
Write-Host "NH FUTURES API 설치" -ForegroundColor White
Write-Host "프로젝트 경로: $RepoRoot" -ForegroundColor Gray

Send-Stage 'begin' '설치 작업 시작'
foreach ($required in @('justfile', 'pyproject.toml', 'frontend\package.json')) {
    if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot $required) -PathType Leaf)) {
        throw "프로젝트 파일이 없습니다: $required. ZIP의 압축을 모두 풀어 주세요."
    }
}

# 실제 설치 명령보다 앞에서 끝냅니다. 미리보기는 도구 실행·다운로드·바로가기 생성을 하지 않습니다.
if ($DryRun) {
    Send-Stage 'tools' '[미리보기] Node.js 22.15.0 이상 / uv / just 확인 및 필요한 도구 설치'
    if (-not $SkipSetup) { Send-Stage 'dependencies' '[미리보기] just setup' }
    if (-not $SkipBuild) {
        Send-Stage 'build' '[미리보기] just package (화면 빌드 포함)'
        if (-not $NoShortcut) { Send-Stage 'shortcut' '[미리보기] NH FUTURES API 바로가기 생성' }
    }
    Send-Stage 'done' '미리보기 완료 — 실제 설치는 하지 않았습니다'
    return
}

Update-SessionPath

if ($CheckOnly) {
    foreach ($tool in $Tools) {
        $version = Get-VersionFrom -Command $tool.Command
        $state = if ($null -eq $version) { '설치 필요' }
            elseif ($tool.MinVersion -and $version -lt $tool.MinVersion) { "$version → 업데이트 필요 ($($tool.MinVersion) 이상)" }
            else { "$version · 재사용" }
        Write-Output "NHSETUP|tool|$($tool.Name): $state"
    }
    Write-Output 'NHSETUP|tool|Python: 프로젝트 요구 버전을 uv가 준비합니다.'
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Write-Output 'NHSETUP|tool|winget 없음: 도구 추가 설치가 필요하면 앱 설치 관리자를 준비하세요.'
    }
    Send-Stage 'done' '도구 확인 완료 — 실제 설치는 하지 않았습니다'
    return
}

# --- 1. 필요한 도구 설치 ---------------------------------------------------

Send-Stage 'tools' '필요한 도구 확인 및 설치'
foreach ($tool in $Tools) {
    Assert-NotCancelled
    $version = Get-VersionFrom -Command $tool.Command

    if ($null -eq $version) {
        Write-Info "$($tool.Name): 설치되어 있지 않음"
        Install-Tool -Tool $tool
    }
    elseif ($tool.MinVersion -and $version -lt $tool.MinVersion) {
        Write-Info "$($tool.Name): $version (필요 버전 $($tool.MinVersion) 이상)"
        Install-Tool -Tool $tool
    }
    else {
        Write-Ok "$($tool.Name) $version"
    }
}
Write-Info "Python은 uv가 프로젝트에 맞는 버전을 자동으로 준비합니다."

# --- 2. 프로젝트 의존성 설치 -----------------------------------------------

if ($SkipSetup) {
    Write-Step "프로젝트 의존성 설치 (건너뜀)"
    Write-Info "필요할 때 'just setup' 을 실행하세요."
}
else {
    Send-Stage 'dependencies' '프로젝트 의존성 설치'
    Invoke-Just -Recipe 'setup' -What '프로젝트 의존성 설치'
}

# --- 3. 프로그램 만들기 -----------------------------------------------------

$built = $false

if ($SkipBuild) {
    Write-Step "프로그램 만들기 (건너뜀)"
    Write-Info "필요할 때 'just package' 를 실행하세요."
}
else {
    Send-Stage 'build' '화면 및 실행 파일 만들기'

    # 소스를 수정할 목적이라면 실행 파일이 당장 필요하지 않으므로 건너뛸 수 있게 합니다.
    Write-Info "실행 파일을 만드는 데 1~2분 정도 걸립니다."
    Write-Info "소스를 수정하실 예정이라면 나중에 만드셔도 됩니다."
    Write-Host ""

    if ($NonInteractive -or (Confirm-Yes "    지금 실행 파일을 만들까요?")) {
        Write-Info "실행 파일을 만드는 중입니다. 잠시 기다려 주세요..."
        Invoke-Just -Recipe 'package' -What '실행 파일 만들기'

        if (-not (Test-Path -LiteralPath $ExePath -PathType Leaf)) {
            throw "실행 파일이 만들어지지 않았습니다: $ExePath"
        }
        $built = $true
        Write-Ok "완성되었습니다: $ExePath"

        Write-Host ""
        if (-not $NoShortcut -and ($NonInteractive -or (Confirm-Yes "    바탕화면에 바로가기를 만들까요?"))) {
            Send-Stage 'shortcut' '바탕화면 바로가기 만들기'
            $link = New-DesktopShortcut -Target $ExePath -Name 'NH FUTURES API'
            Write-Ok "바탕화면에 'NH FUTURES API' 바로가기를 만들었습니다."
        }
    }
    else {
        Write-Info "건너뛰었습니다. 필요할 때 'just package' 를 실행하세요."
    }
}

# --- 마무리 -----------------------------------------------------------------

Write-Step "완료되었습니다"

if ($built) {
    Write-Info "바탕화면의 'NH FUTURES API' 아이콘을 더블클릭하면 프로그램이 실행됩니다."
    Write-Info "바로가기를 만들지 않았다면 아래 파일을 직접 실행하세요."
    Write-Info "  $ExePath"
    Write-Host ""
}

Write-Info "소스를 수정하실 때 쓰는 명령입니다."
Write-Info "  just dev       개발 모드로 실행 (http://localhost:5173)"
Write-Info "  just test      테스트"
Write-Info "  just build     화면 만들기"
Write-Info "  just package   실행 파일 만들기"

Write-Host ""

Send-Stage 'done' '선택한 설치 작업이 완료되었습니다'
Write-Host "이번에 새로 설치된 도구가 있다면, 다른 터미널에서는 새로 열거나" -ForegroundColor Yellow
Write-Host "로그아웃 후 다시 로그인해야 명령을 인식합니다." -ForegroundColor Yellow
Write-Host ""
