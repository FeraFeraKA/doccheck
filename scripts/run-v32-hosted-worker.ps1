[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [uri]$RenderOrigin,
    [switch]$Once
)

$ErrorActionPreference = 'Stop'
$origin = $RenderOrigin.GetLeftPart([System.UriPartial]::Authority)
$isRender = $RenderOrigin.Scheme -eq 'https' -and $RenderOrigin.IsDefaultPort -and
    $RenderOrigin.DnsSafeHost.EndsWith('.onrender.com', [StringComparison]::OrdinalIgnoreCase)
$isLocal = $RenderOrigin.Scheme -eq 'http' -and $RenderOrigin.Host -eq '127.0.0.1'
if ($RenderOrigin.OriginalString -cne $origin -or $RenderOrigin.UserInfo -or
    (-not $isRender -and -not $isLocal)) {
    throw 'Укажите HTTPS origin API Render или HTTP origin 127.0.0.1 для проверки. Без пути и завершающего слеша.'
}

$previousToken = $env:DOCCHECK_HOSTED_WORKER_TOKEN
Push-Location (Split-Path -Parent $PSScriptRoot)
try {
    $health = Invoke-RestMethod -Uri "$origin/health" -MaximumRedirection 0 -TimeoutSec 90
    if ($health.status -ne 'ok' -or $health.database -ne 'ok') {
        throw 'API не подтвердил готовность.'
    }

    $tags = Invoke-RestMethod -Uri 'http://127.0.0.1:11438/api/tags' -NoProxy -MaximumRedirection 0 -TimeoutSec 10
    $matchingModels = @($tags.models | Where-Object { $_.name -ceq 'qwen3.5:4b-q4_K_M' })
    if ($matchingModels.Count -ne 1 -or
        $matchingModels[0].digest -cne 'd8b0f5e9760cd1682034f292d7ef72ec46f432149be0df7574bf2d6e92e38c04') {
        throw 'Сначала подготовьте локальную Qwen по инструкции v3.2.'
    }

    if (-not $previousToken) {
        $env:DOCCHECK_HOSTED_WORKER_TOKEN = Read-Host -Prompt 'Секрет воркера DocCheck' -MaskInput
    }
    if ($env:DOCCHECK_HOSTED_WORKER_TOKEN -cnotmatch '^[\x00-\x7F]{32,256}\z') {
        throw 'Секрет воркера должен содержать от 32 до 256 ASCII-символов.'
    }
    $arguments = @(
        'run', '--project', 'backend', '--locked',
        '--with-requirements', 'bench/e2e_v32_20261114/requirements.txt',
        'python', '-m', 'doccheck_backend.hosted_worker', '--origin', $origin,
        '--processor', 'doccheck_backend.v32_adapter:process'
    )
    if ($Once) {
        $arguments += '--once'
    }
    & uv @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Воркер завершился с кодом $LASTEXITCODE."
    }
} finally {
    $env:DOCCHECK_HOSTED_WORKER_TOKEN = $previousToken
    Pop-Location
}
