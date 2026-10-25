param(
    [string]$ApiUrl = 'https://pqrtq5b8og.execute-api.ap-southeast-2.amazonaws.com',
    [string]$Python = 'python',
    [string]$Model = (Join-Path $PSScriptRoot 'models/yolo11s-seg.onnx'),
    [int]$Camera = 0,
    [string]$Outbox = (Join-Path $PSScriptRoot '../../.test-tmp/aws-camera-demo')
)
$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $Model -PathType Leaf)) {
    throw 'Supply -Model with the existing YOLO11s segmentation ONNX file. Detection must be available.'
}
if ([string]::IsNullOrWhiteSpace($env:PATHABLE_AUTH_TOKEN)) {
    throw 'Sign in as camera-demo, copy the camera token, and set PATHABLE_AUTH_TOKEN from the clipboard first.'
}
# Credentials are inherited through the environment, never command-line arguments.
& $Python (Join-Path $PSScriptRoot 'live_navigation.py') --camera $Camera --backend dshow `
    --start B --dest D --aws-workflow --api-url $ApiUrl --api-prefix /api/v2 `
    --camera-id camera-b-01 --model $Model --voice-mode tts --outbox-dir $Outbox `
    --poll-interval-s 4 --http-timeout-s 12 --max-submission-attempts 3
exit $LASTEXITCODE
