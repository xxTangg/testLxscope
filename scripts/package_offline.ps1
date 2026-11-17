param(
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ComposeFile = Join-Path $ProjectRoot "docker-compose.yml"
$BackendImage = "testlxscope-intranet:latest"
$WebUiImage = "testlxscope-web-ui:latest"
$SandboxImage = "testlxscope-sandbox:latest"
$EgressImage = "testlxscope-egress:latest"
$RedisImage = "redis:7-alpine"
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$OutputDir = Join-Path $ProjectRoot "dist\agentscope-offline-$Stamp"
$TarFile = Join-Path $OutputDir "agentscope-images.tar"

function Invoke-Docker {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    & docker @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Docker command failed with exit code ${LASTEXITCODE}: docker $($Arguments -join ' ')"
    }
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker is not installed or is not available in PATH."
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

if (-not $SkipBuild) {
    Invoke-Docker @("compose", "-f", $ComposeFile, "--profile", "build", "build", "agentscope", "web-ui", "user-sandbox", "egress")
}
try {
    Invoke-Docker @("image", "inspect", $RedisImage) | Out-Null
}
catch {
    Invoke-Docker @("pull", $RedisImage)
}
Invoke-Docker @(
    "save"
    "--output"
    $TarFile
    $BackendImage
    $WebUiImage
    $SandboxImage
    $EgressImage
    $RedisImage
)

$Platforms = @(
    $BackendImage
    $WebUiImage
    $SandboxImage
    $EgressImage
    $RedisImage
) | ForEach-Object {
    (Invoke-Docker @("image", "inspect", "--format", "{{.Os}}/{{.Architecture}}", $_)).Trim()
}
$UniquePlatforms = @($Platforms | Select-Object -Unique)
if ($UniquePlatforms.Count -ne 1) {
    throw "All images in an offline package must use the same platform. Found: $($UniquePlatforms -join ', ')"
}
$Platform = $UniquePlatforms[0]

Copy-Item $ComposeFile (Join-Path $OutputDir "docker-compose.yml")
Copy-Item (Join-Path $ProjectRoot ".env.example") (Join-Path $OutputDir ".env.example")
Copy-Item (Join-Path $ProjectRoot "OPS_DEPLOYMENT.md") (Join-Path $OutputDir "OPS_DEPLOYMENT.md")
$DocsDir = Join-Path $OutputDir "docs"
New-Item -ItemType Directory -Force -Path $DocsDir | Out-Null
Copy-Item (Join-Path $ProjectRoot "docs\user-file-space.md") (Join-Path $DocsDir "user-file-space.md")

$Hash = (Get-FileHash -Algorithm SHA256 $TarFile).Hash
@{
    generated_at = (Get-Date).ToString("o")
    images = @(
        $BackendImage
        $WebUiImage
        $SandboxImage
        $EgressImage
        $RedisImage
    )
    platform = $Platform
    image_archive = "agentscope-images.tar"
    sha256 = $Hash
} | ConvertTo-Json | Set-Content (Join-Path $OutputDir "manifest.json") -Encoding UTF8

Write-Host "Offline package created: $OutputDir"
Write-Host "Image archive SHA256: $Hash"
