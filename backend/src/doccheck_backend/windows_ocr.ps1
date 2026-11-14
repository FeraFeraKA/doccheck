# Decode a local PNG and emit raw WinRT OCR word boxes in source pixel space.
param([Parameter(Mandatory = $true)][string]$ImagePath)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$fileType = [Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime]
$streamType = [Windows.Storage.Streams.IRandomAccessStream, Windows.Storage.Streams, ContentType=WindowsRuntime]
$decoderType = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType=WindowsRuntime]
$bitmapType = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics.Imaging, ContentType=WindowsRuntime]
$engineType = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime]
$resultType = [Windows.Media.Ocr.OcrResult, Windows.Foundation, ContentType=WindowsRuntime]
$languageType = [Windows.Globalization.Language, Windows.Globalization, ContentType=WindowsRuntime]
$asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.IsGenericMethodDefinition -and
    $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
} | Select-Object -First 1

function Wait-Result($Operation, [type]$ResultType) {
    $task = $asTask.MakeGenericMethod($ResultType).Invoke($null, @($Operation))
    $task.GetAwaiter().GetResult()
}

$language = $engineType::AvailableRecognizerLanguages |
    Where-Object { $_.LanguageTag -eq 'ru' -or $_.LanguageTag.StartsWith('ru-') } |
    Select-Object -First 1
if ($null -eq $language) { throw 'Russian Windows OCR language is unavailable.' }
$engine = $engineType::TryCreateFromLanguage($language)
if ($null -eq $engine) { throw 'Could not initialize Windows OCR.' }

$ImagePath = [IO.Path]::GetFullPath($ImagePath)
$file = Wait-Result ([Windows.Storage.StorageFile]::GetFileFromPathAsync($ImagePath)) ([Windows.Storage.StorageFile])
$stream = Wait-Result ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) $streamType
try {
    $decoder = Wait-Result ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) $decoderType
    $bitmap = Wait-Result ($decoder.GetSoftwareBitmapAsync()) $bitmapType
    try {
        $ocr = Wait-Result ($engine.RecognizeAsync($bitmap)) $resultType
        $lines = @(
            foreach ($line in $ocr.Lines) {
                [ordered]@{ words = @(
                    foreach ($word in $line.Words) {
                        $box = $word.BoundingRect
                        [ordered]@{
                            text = $word.Text
                            box = @($box.X, $box.Y, ($box.X + $box.Width), ($box.Y + $box.Height))
                        }
                    }
                ) }
            }
        )
        [ordered]@{
            width = $decoder.PixelWidth
            height = $decoder.PixelHeight
            rotation = $ocr.TextAngle
            language = $language.LanguageTag
            lines = $lines
        } | ConvertTo-Json -Depth 6 -Compress
    }
    finally { $bitmap.Dispose() }
}
finally { $stream.Dispose() }
