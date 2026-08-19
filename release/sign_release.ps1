param(
    [string]$Executable = "",
    [string]$ReleaseRoot = "D:\VoiceGrid-Release",
    [string]$TimestampServer = "http://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$buildManifest = Get-Content -LiteralPath (Join-Path $repoRoot "build.json") -Raw -Encoding UTF8 | ConvertFrom-Json
$version = [string]$buildManifest.version
if (-not $version) {
    throw "build.json does not contain a version."
}
if (-not $Executable) {
    $candidates = @(Get-ChildItem -LiteralPath $repoRoot -Filter "VoiceGrid *.exe" -File)
    if ($candidates.Count -ne 1) {
        throw "Expected exactly one VoiceGrid launcher in the repository root."
    }
    $Executable = $candidates[0].FullName
}
$exe = [System.IO.Path]::GetFullPath($Executable)
$release = [System.IO.Path]::GetFullPath($ReleaseRoot)
if ($release -ne "D:\VoiceGrid-Release") {
    throw "ReleaseRoot must be D:\VoiceGrid-Release."
}
if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) {
    throw "Launcher not found: $exe"
}

$certificateDirectory = Join-Path $release "certificates"
$reportDirectory = Join-Path $release "reports"
[System.IO.Directory]::CreateDirectory($certificateDirectory) | Out-Null
[System.IO.Directory]::CreateDirectory($reportDirectory) | Out-Null
$certificate = $null
try {
    $certificateArguments = @{
        Type = "CodeSigningCert"
        Subject = "CN=VoiceGrid"
        CertStoreLocation = "Cert:\CurrentUser\My"
        KeyAlgorithm = "RSA"
        KeyLength = 3072
        HashAlgorithm = "SHA256"
        KeyExportPolicy = "NonExportable"
        NotAfter = (Get-Date).AddYears(5)
    }
    $certificate = New-SelfSignedCertificate @certificateArguments
    $signatureArguments = @{
        LiteralPath = $exe
        Certificate = $certificate
        HashAlgorithm = "SHA256"
        TimestampServer = $TimestampServer
    }
    $signature = Set-AuthenticodeSignature @signatureArguments
    if (-not $signature.SignerCertificate) {
        throw "Authenticode signature was not embedded."
    }

    $cerPath = Join-Path $certificateDirectory "VoiceGrid-$version-SelfSigned.cer"
    Export-Certificate -Cert $certificate -FilePath $cerPath -Force | Out-Null
    $hash = (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant()
    $info = @(
        "VoiceGrid $version self-signed release certificate",
        "Executable: $([System.IO.Path]::GetFileName($exe))",
        "SHA256: $hash",
        "Certificate subject: $($certificate.Subject)",
        "Certificate thumbprint: $($certificate.Thumbprint)",
        "Certificate valid from: $($certificate.NotBefore.ToString())",
        "Certificate valid until: $($certificate.NotAfter.ToString())",
        "Timestamp server: $TimestampServer",
        "Signature status on this machine: $($signature.Status)",
        "",
        "This certificate is self-signed. It verifies that the executable has not",
        "changed since signing, but it does not establish public publisher trust",
        "and does not prevent Windows SmartScreen warnings."
    ) -join [Environment]::NewLine
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText(
        (Join-Path $reportDirectory "SIGNING-INFO.txt"),
        $info + [Environment]::NewLine,
        $utf8
    )
    Write-Output $info
}
finally {
    if ($certificate) {
        $certificatePath = "Cert:\CurrentUser\My\$($certificate.Thumbprint)"
        if (Test-Path $certificatePath) {
            Remove-Item -LiteralPath $certificatePath -Force
        }
    }
}
