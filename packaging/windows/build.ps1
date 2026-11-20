param(
    [Parameter(Mandatory = $true)][string]$Iscc,
    [Parameter(Mandatory = $true)][string]$OutputDir,
    [string]$Python = 'python'
)
$ErrorActionPreference = 'Stop'
function Invoke-Checked($Program, [string[]]$Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program exited with code $LASTEXITCODE" }
}
if (!(Split-Path -IsAbsolute $Iscc) -or !(Split-Path -IsAbsolute $OutputDir)) {
    throw 'Iscc and OutputDir must be absolute paths.'
}
Push-Location (Join-Path $PSScriptRoot '../..')
try {
    $version = Invoke-Checked $Python @('-c', 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')
    $bundle = Join-Path $OutputDir 'bundle/OffLook'
    $release = Join-Path $OutputDir 'release'
    New-Item -ItemType Directory -Path $release -Force | Out-Null
    Invoke-Checked $Python @('-m', 'PyInstaller', '--noconfirm', '--clean', '--workpath', (Join-Path $OutputDir 'work'), '--distpath', (Join-Path $OutputDir 'bundle'), 'packaging/windows/offlook.spec')
    Invoke-Checked $Python @('-m', 'qa.windows_smoke', '--cli', (Join-Path $bundle 'ol.exe'))
    Invoke-Checked $Python @('packaging/windows/collect_licenses.py', $bundle)
    Invoke-Checked $Iscc @('/Qp', "/DAppVersion=$version", "/DAppSourceDir=$bundle", "/DAppOutputDir=$release", (Join-Path $PSScriptRoot 'OffLook.iss'))
    $name = "OffLook-$version-windows-x64-setup.exe"
    $file = Join-Path $release $name
    $hash = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()
    Set-Content -LiteralPath "$file.sha256" -Encoding ascii -Value "$hash  $name"
} finally {
    Pop-Location
}
