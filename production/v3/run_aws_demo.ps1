param(
    [string]$ApiUrl = 'https://pqrtq5b8og.execute-api.ap-southeast-2.amazonaws.com',
    [string]$Python = 'python',
    [string]$Model = (Join-Path $PSScriptRoot 'models/yolo11s-seg.onnx'),
    [int]$Camera = 1,
    [string]$Outbox = (Join-Path $PSScriptRoot '../../.test-tmp/aws-camera-demo'),
    [switch]$PromptForToken
)
$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $Model -PathType Leaf)) {
    throw 'Supply -Model with the existing YOLO11s segmentation ONNX file. Detection must be available.'
}
if ($PromptForToken -or [string]::IsNullOrWhiteSpace($env:PATHABLE_AUTH_TOKEN)) {
    Write-Host 'Open http://localhost:8003/ in a separate tab. Choose Camera / laptop sign-in and use camera-demo.'
    Write-Host 'Click Copy camera access token, then paste it at the hidden prompt below and press Enter.'
    Write-Host 'Copy the token AFTER starting this command so copying the command cannot replace it.'
    $cameraSecret = Read-Host 'Camera access token (hidden)' -AsSecureString
    $cameraPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($cameraSecret)
    try {
        $env:PATHABLE_AUTH_TOKEN = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($cameraPtr).Trim()
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($cameraPtr)
        $cameraSecret.Dispose()
    }
}
& $Python (Join-Path $PSScriptRoot 'aws_camera_preflight.py') --api-url $ApiUrl --outbox-dir $Outbox
if ($LASTEXITCODE -ne 0) { throw 'Camera connection check failed. Follow the message above; no camera upload was started.' }
# Credentials are inherited through the environment, never command-line arguments.
& $Python (Join-Path $PSScriptRoot 'live_navigation.py') --camera $Camera --backend dshow `
    --start B --dest D --aws-workflow --api-url $ApiUrl --api-prefix /api/v2 `
    --camera-id camera-b-01 --model $Model --voice-mode tts --outbox-dir $Outbox `
    --poll-interval-s 4 --http-timeout-s 12 --max-submission-attempts 3
exit $LASTEXITCODE
