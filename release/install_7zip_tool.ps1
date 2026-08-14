param(
    [string]$ReleaseRoot = "D:\VoiceGrid-Release"
)

$ErrorActionPreference = "Stop"
$release = [System.IO.Path]::GetFullPath($ReleaseRoot)
if ($release -ne "D:\VoiceGrid-Release") {
    throw "ReleaseRoot must be D:\VoiceGrid-Release."
}
$toolDirectory = Join-Path $release "tools\7zip-26.02"
$installer = Join-Path $release "work\7z2602-x64.exe"
[System.IO.Directory]::CreateDirectory((Split-Path -Parent $installer)) | Out-Null
[System.IO.Directory]::CreateDirectory($toolDirectory) | Out-Null

$url = "https://www.7-zip.org/a/7z2602-x64.exe"
Invoke-WebRequest -Uri $url -OutFile $installer -UseBasicParsing
$download = Get-Item -LiteralPath $installer
if ($download.Length -lt 1000000) {
    throw "Downloaded 7-Zip installer is unexpectedly small."
}
$process = Start-Process -FilePath $installer -ArgumentList "/S", "/D=$toolDirectory" -WindowStyle Hidden -Wait -PassThru
if ($process.ExitCode -ne 0) {
    throw "7-Zip installer failed with exit code $($process.ExitCode)."
}
if (-not (Test-Path -LiteralPath (Join-Path $toolDirectory "7z.exe"))) {
    throw "7z.exe was not installed into the release tool directory."
}
Get-FileHash -LiteralPath $installer -Algorithm SHA256
