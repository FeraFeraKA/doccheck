[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateSet('database', 'api', 'worker', 'site', 'ollama', 'stop-database')]
    [string]$Component,
    [string]$PostgresBin = (Join-Path $env:ProgramFiles 'PostgreSQL/18/bin'),
    [string]$OllamaDirectory = (Join-Path $env:TEMP 'doccheck-v32-ollama-04016'),
    [ValidateRange(1024, 65535)]
    [int]$DatabasePort = 15432,
    [ValidateRange(1024, 65535)]
    [int]$ApiPort = 8000,
    [ValidateRange(1024, 65535)]
    [int]$SitePort = 8080
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$runtime = Join-Path $root "data/v32-local-$DatabasePort"
$cluster = Join-Path $runtime 'postgres'
$passwordFile = Join-Path $runtime 'postgres-password'

function Invoke-Checked {
    param([string]$Executable, [string[]]$CommandArguments)
    & $Executable @CommandArguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Executable завершился с кодом $LASTEXITCODE."
    }
}

Push-Location $root
try {
    switch ($Component) {
        'database' {
            New-Item -ItemType Directory -Force -Path $runtime | Out-Null
            if (-not (Test-Path -LiteralPath (Join-Path $cluster 'PG_VERSION'))) {
                $password = [guid]::NewGuid().ToString('N')
                Set-Content -LiteralPath $passwordFile -Value $password -Encoding ascii
                Invoke-Checked (Join-Path $PostgresBin 'initdb.exe') @(
                    '-D', $cluster, '-U', 'doccheck', '-A', 'scram-sha-256',
                    '--encoding=UTF8', '--locale=C', '--pwfile', $passwordFile, '--no-instructions'
                )
            }
            if (-not (Test-Path -LiteralPath $passwordFile)) {
                throw "Отсутствует файл пароля локального кластера $passwordFile."
            }
            Invoke-Checked (Join-Path $PostgresBin 'pg_ctl.exe') @(
                '-D', $cluster, '-l', (Join-Path $runtime 'postgres.log'),
                '-o', "-p $DatabasePort -h 127.0.0.1", '-w', 'start'
            )
        }
        'stop-database' {
            Invoke-Checked (Join-Path $PostgresBin 'pg_ctl.exe') @(
                '-D', $cluster, '-m', 'fast', '-w', 'stop'
            )
        }
        'ollama' {
            $env:OLLAMA_HOST = '127.0.0.1:11438'
            $env:OLLAMA_NO_CLOUD = '1'
            $env:OLLAMA_MODELS = Join-Path $OllamaDirectory 'models'
            Invoke-Checked (Join-Path $OllamaDirectory 'ollama.exe') @('serve')
        }
        'site' {
            $env:DOCCHECK_API_TARGET = "http://127.0.0.1:$ApiPort"
            $env:VITE_DOCCHECK_PUBLIC_DEMO = '0'
            $frontend = Get-Content -LiteralPath 'frontend/package.json' -Raw | ConvertFrom-Json
            $pnpm = @('exec', '--yes', "--package=$($frontend.packageManager)", '--', 'pnpm')
            Invoke-Checked 'npm.cmd' ($pnpm + @('--dir', 'frontend', 'install', '--frozen-lockfile'))
            Invoke-Checked 'npm.cmd' ($pnpm + @(
                '--dir', 'frontend', 'dev', '--host', '127.0.0.1', '--port', "$SitePort", '--strictPort'
            ))
        }
        { $_ -in @('api', 'worker') } {
            if (-not (Test-Path -LiteralPath $passwordFile)) {
                throw 'Сначала запустите компонент database.'
            }
            $password = (Get-Content -LiteralPath $passwordFile -Raw).Trim()
            $env:DATABASE_URL = "postgresql+psycopg://doccheck:${password}@127.0.0.1:$DatabasePort/postgres"
            $env:DOCCHECK_UPLOAD_ROOT = Join-Path $runtime 'runs'
            $env:DOCCHECK_PUBLIC_DEMO = '0'
            $uvArguments = @('run', '--project', 'backend', '--locked', '--no-dev')
            if ($Component -eq 'api') {
                Invoke-Checked 'uv' ($uvArguments + @('alembic', '-c', 'backend/alembic.ini', 'upgrade', 'head'))
                Invoke-Checked 'uv' ($uvArguments + @(
                    'uvicorn', 'doccheck_backend.api:app', '--host', '127.0.0.1', '--port', "$ApiPort"
                ))
            } else {
                Invoke-Checked 'uv' ($uvArguments + @(
                    '--with-requirements', 'bench/e2e_v32_20261114/requirements.txt',
                    'python', '-m', 'doccheck_backend.run_worker',
                    '--processor', 'doccheck_backend.v32_adapter:process'
                ))
            }
        }
    }
} finally {
    Pop-Location
}
