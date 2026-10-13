param([Parameter(ValueFromRemainingArguments = $true)][string[]]$GradleArgs)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$bootstrapDir = Join-Path $projectRoot '.gradle-bootstrap'
$gradleBat = Join-Path $bootstrapDir 'gradle-8.9\bin\gradle.bat'
if (-not (Test-Path -LiteralPath $gradleBat)) {
    New-Item -ItemType Directory -Force -Path $bootstrapDir | Out-Null
    $archive = Join-Path $bootstrapDir 'gradle-8.9-bin.zip'
    Write-Host 'Downloading Gradle 8.9 (first build only)...'
    Invoke-WebRequest -Uri 'https://services.gradle.org/distributions/gradle-8.9-bin.zip' -OutFile $archive
    Expand-Archive -LiteralPath $archive -DestinationPath $bootstrapDir -Force
    Remove-Item -LiteralPath $archive
}
& $gradleBat @GradleArgs
exit $LASTEXITCODE
