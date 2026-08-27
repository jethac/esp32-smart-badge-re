[CmdletBinding()]
param(
    [string]$Destination = (Join-Path $PSScriptRoot '..\app\libs')
)

$ErrorActionPreference = 'Stop'

$Repository = 'https://github.com/Jieli-Tech/Android-JL_OTA.git'
$Commit = '4bf054e1ae6e549b617e266cea733576c80c55d5'
$AarName = 'jl_bt_ota_V1.11.0_11015-release.aar'
$ExpectedSha256 = '6F8DEC58C53C33DC9B1189D6AA1ECC4A0FE6A43ECF44BB4C79BBEE723E0D2550'
$Destination = [System.IO.Path]::GetFullPath($Destination)
$DestinationAar = Join-Path $Destination $AarName

function Assert-ExpectedHash([string]$Path) {
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToUpperInvariant()
    if ($actual -ne $ExpectedSha256) {
        throw "SHA-256 mismatch for $Path. Expected $ExpectedSha256, got $actual."
    }
}

if (Test-Path -LiteralPath $DestinationAar) {
    Assert-ExpectedHash $DestinationAar
} else {
    $temporaryRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('jieli-ota-' + [Guid]::NewGuid())
    $checkout = Join-Path $temporaryRoot 'Android-JL_OTA'
    try {
        New-Item -ItemType Directory -Path $temporaryRoot | Out-Null
        git clone --no-checkout $Repository $checkout
        if ($LASTEXITCODE -ne 0) { throw 'Unable to clone the official JieLi OTA repository.' }
        git -C $checkout fetch --depth 1 origin $Commit
        if ($LASTEXITCODE -ne 0) { throw "Unable to fetch JieLi OTA commit $Commit." }
        git -C $checkout checkout --detach $Commit
        if ($LASTEXITCODE -ne 0) { throw "Unable to check out JieLi OTA commit $Commit." }
        if ((git -C $checkout rev-parse HEAD).Trim() -ne $Commit) {
            throw "Checked out an unexpected JieLi OTA revision."
        }

        $sourceAar = Join-Path $checkout (Join-Path 'libs' $AarName)
        if (-not (Test-Path -LiteralPath $sourceAar)) {
            throw "The pinned JieLi OTA checkout has no libs/$AarName."
        }
        $sourceLicense = Join-Path $checkout 'LICENSE'
        if (-not (Test-Path -LiteralPath $sourceLicense)) {
            throw 'The pinned JieLi OTA checkout has no root LICENSE file.'
        }

        Assert-ExpectedHash $sourceAar
        New-Item -ItemType Directory -Force -Path $Destination | Out-Null
        Copy-Item -LiteralPath $sourceAar -Destination $DestinationAar
        Copy-Item -LiteralPath $sourceLicense -Destination (Join-Path $Destination 'LICENSE') -Force
        Assert-ExpectedHash $DestinationAar
    } finally {
        if (Test-Path -LiteralPath $temporaryRoot) {
            Remove-Item -LiteralPath $temporaryRoot -Recurse -Force
        }
    }
}

Write-Output "Verified $DestinationAar at JieLi commit $Commit."
