[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$testRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('doccheck-v32-ollama-test-' + [guid]::NewGuid().ToString('N'))
$tempBase = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath()).TrimEnd('\') + '\'
$resolvedRoot = [System.IO.Path]::GetFullPath($testRoot)
if (-not $resolvedRoot.StartsWith($tempBase, [System.StringComparison]::OrdinalIgnoreCase) -or
    -not [System.IO.Path]::GetFileName($resolvedRoot).StartsWith('doccheck-v32-ollama-test-')) {
    throw 'Некорректный временный каталог теста.'
}

$csc = Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
if (-not (Test-Path -LiteralPath $csc -PathType Leaf)) {
    $csc = Join-Path $env:WINDIR 'Microsoft.NET/Framework/v4.0.30319/csc.exe'
}
if (-not (Test-Path -LiteralPath $csc -PathType Leaf)) {
    throw 'Для теста нужен компилятор C# из .NET Framework.'
}

$names = @('TEMP', 'PATH', 'OLLAMA_HOST', 'OLLAMA_NO_CLOUD', 'OLLAMA_NOPRUNE', 'OLLAMA_MODELS',
    'DOCCHECK_FAKE_OLLAMA_TRACE', 'DOCCHECK_FAKE_OLLAMA_EXIT')
$previous = @{}
foreach ($name in $names) {
    $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

try {
    $isolatedTemp = Join-Path $resolvedRoot 'temp'
    $pathDir = Join-Path $resolvedRoot 'path bin'
    $explicitDir = Join-Path $resolvedRoot 'explicit bundle'
    $preparedDir = Join-Path $isolatedTemp 'doccheck-v32-ollama-04016'
    New-Item -ItemType Directory -Path $isolatedTemp, $pathDir, $explicitDir, $preparedDir -Force | Out-Null

    $source = Join-Path $resolvedRoot 'FakeOllama.cs'
    @'
using System;
using System.IO;
using System.Reflection;
public static class FakeOllama {
    public static int Main(string[] args) {
        Func<string, string> env = name => Environment.GetEnvironmentVariable(name) ?? "<unset>";
        File.WriteAllLines(env("DOCCHECK_FAKE_OLLAMA_TRACE"), new[] {
            Assembly.GetExecutingAssembly().Location,
            string.Join("|", args),
            env("OLLAMA_HOST"), env("OLLAMA_NO_CLOUD"), env("OLLAMA_NOPRUNE"), env("OLLAMA_MODELS")
        });
        int exitCode;
        return int.TryParse(env("DOCCHECK_FAKE_OLLAMA_EXIT"), out exitCode) ? exitCode : 0;
    }
}
'@ | Set-Content -LiteralPath $source -Encoding UTF8
    $pathExe = Join-Path $pathDir 'ollama.exe'
    & $csc /nologo "/out:$pathExe" $source
    Assert-True ($LASTEXITCODE -eq 0) 'Не удалось собрать тестовый исполняемый файл.'

    $scriptPath = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../run-v32-local.ps1')).Path
    $pwsh = Join-Path $PSHOME 'pwsh.exe'
    $trace = Join-Path $resolvedRoot 'trace.txt'
    $env:TEMP = $isolatedTemp
    $env:PATH = $pathDir
    $env:DOCCHECK_FAKE_OLLAMA_TRACE = $trace
    $env:OLLAMA_HOST = '0.0.0.0:11434'
    $env:OLLAMA_NO_CLOUD = '0'
    $env:OLLAMA_NOPRUNE = '0'
    Remove-Item Env:DOCCHECK_FAKE_OLLAMA_EXIT -ErrorAction SilentlyContinue

    function Invoke-Scenario {
        param([string[]]$Arguments = @(), [bool]$ExpectSuccess = $true)
        if (Test-Path -LiteralPath $trace) { Remove-Item -LiteralPath $trace -Force }
        $output = (& $pwsh -NoProfile -File $scriptPath -Component ollama @Arguments 2>&1 | Out-String)
        $code = $LASTEXITCODE
        Assert-True (($code -eq 0) -eq $ExpectSuccess) "Неожиданный код $code. Вывод: $output"
        return $output
    }

    function Assert-Trace {
        param([string]$Executable, [string]$Models)
        Assert-True (Test-Path -LiteralPath $trace -PathType Leaf) 'Тестовый процесс не запускался.'
        $lines = @(Get-Content -LiteralPath $trace -Encoding UTF8)
        Assert-True ($lines.Count -eq 6) 'Неполный журнал тестового процесса.'
        Assert-True ($lines[0] -ieq $Executable) "Выбран неверный исполняемый файл: $($lines[0])."
        Assert-True ($lines[1] -eq 'serve') 'Передана неверная команда.'
        Assert-True ($lines[2] -eq '127.0.0.1:11438') 'Изменился адрес Ollama.'
        Assert-True ($lines[3] -eq '1') 'Не установлен OLLAMA_NO_CLOUD.'
        Assert-True ($lines[4] -eq '1') 'Не установлен OLLAMA_NOPRUNE.'
        Assert-True ($lines[5] -eq $Models) "Изменилось хранилище моделей: [$($lines[5])], ожидалось [$Models]."
    }

    $customModels = Join-Path $resolvedRoot 'custom models'
    $env:OLLAMA_MODELS = $customModels
    $null = Invoke-Scenario
    Assert-Trace $pathExe $customModels

    Remove-Item Env:OLLAMA_MODELS
    $null = Invoke-Scenario
    Assert-Trace $pathExe '<unset>'

    $preparedExe = Join-Path $preparedDir 'ollama.exe'
    Copy-Item -LiteralPath $pathExe -Destination $preparedExe
    $null = Invoke-Scenario
    Assert-Trace $preparedExe (Join-Path $preparedDir 'models')

    $explicitExe = Join-Path $explicitDir 'ollama.exe'
    Copy-Item -LiteralPath $pathExe -Destination $explicitExe
    $null = Invoke-Scenario -Arguments @('-OllamaDirectory', $explicitDir)
    Assert-Trace $explicitExe (Join-Path $explicitDir 'models')

    $missingDir = Join-Path $resolvedRoot 'missing explicit bundle'
    $message = Invoke-Scenario -Arguments @('-OllamaDirectory', $missingDir) -ExpectSuccess $false
    Assert-True ($message -match 'указанном каталоге') 'Нет понятной ошибки для неверного явного пути.'
    Assert-True (-not (Test-Path -LiteralPath $trace)) 'При неверном явном пути запущен другой процесс.'

    $env:DOCCHECK_FAKE_OLLAMA_EXIT = '7'
    $message = Invoke-Scenario -Arguments @('-OllamaDirectory', $explicitDir) -ExpectSuccess $false
    Assert-True ($message -match 'кодом 7') 'Ошибка исполняемого файла потеряна.'
    Assert-Trace $explicitExe (Join-Path $explicitDir 'models')
    Remove-Item Env:DOCCHECK_FAKE_OLLAMA_EXIT

    Remove-Item -LiteralPath $preparedExe -Force
    $emptyPath = Join-Path $resolvedRoot 'empty path'
    New-Item -ItemType Directory -Path $emptyPath | Out-Null
    $env:PATH = $emptyPath
    $message = Invoke-Scenario -ExpectSuccess $false
    Assert-True ($message -match 'Ollama не найдена') 'Нет понятной ошибки при отсутствии Ollama.'
    Assert-True (-not (Test-Path -LiteralPath $trace)) 'При отсутствии Ollama запущен процесс.'

    Write-Output 'Проверены выбор Ollama, переменные, приоритет каталогов и обработка ошибок.'
} finally {
    foreach ($name in $names) {
        if ($null -eq $previous[$name]) {
            Remove-Item -Path "Env:$name" -ErrorAction SilentlyContinue
        } else {
            [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process')
        }
    }
    if (Test-Path -LiteralPath $resolvedRoot -PathType Container) {
        Remove-Item -LiteralPath $resolvedRoot -Recurse -Force
    }
}
