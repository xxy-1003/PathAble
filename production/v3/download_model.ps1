$ErrorActionPreference = 'Stop'
$modelDir = Join-Path $PSScriptRoot 'models'
$modelPath = Join-Path $modelDir 'yolo11n-seg.onnx'
$expectedHash = '0bc32bc92e985b881141ef9bd2216e2a746f70519d0d24da9fc85decc4428cf4'

if (Test-Path -LiteralPath $modelPath) {
    $existingHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $modelPath).Hash.ToLowerInvariant()
    if ($existingHash -eq $expectedHash) {
        Write-Output "Verified model already present: $modelPath"
        return
    }
    throw "Existing model has a different SHA-256: $modelPath"
}

New-Item -ItemType Directory -Path $modelDir -Force | Out-Null
$temporaryPath = Join-Path $modelDir 'yolo11n-seg.onnx.download'
try {
    Invoke-WebRequest -Uri 'https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo11n-seg.onnx' -OutFile $temporaryPath
    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $temporaryPath).Hash.ToLowerInvariant()
    if ($hash -ne $expectedHash) {
        throw "Downloaded model SHA-256 mismatch: $hash"
    }
    Move-Item -LiteralPath $temporaryPath -Destination $modelPath
    Write-Output "Downloaded and verified: $modelPath"
} finally {
    if (Test-Path -LiteralPath $temporaryPath) {
        Remove-Item -LiteralPath $temporaryPath
    }
}
