# OCR nativo do Windows (Windows.Media.Ocr) sobre um arquivo de imagem.
# Uso:  powershell -File scripts/ocr.ps1 -Path captura.png [-Language pt-BR]
# Saida: JSON com linhas e bounding boxes.
param(
    [Parameter(Mandatory = $true)][string]$Path,
    [string]$Language = "pt-BR"
)

$ErrorActionPreference = "Stop"
# PowerShell 5.1 escreve no codepage ANSI por padrao; o JSON precisa sair em UTF-8.
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
# PowerShell 5.1 ignora [Console]::OutputEncoding quando o stdout esta
# redirecionado, o que corrompe acentos. Escrever bytes UTF-8 direto no
# handle padrao contorna a camada de texto inteira.
function Write-Utf8Stdout([string]$text) {
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($text)
    $out = [Console]::OpenStandardOutput()
    $out.Write($bytes, 0, $bytes.Length)
    $out.Flush()
}

Add-Type -AssemblyName System.Runtime.WindowsRuntime

$null = [Windows.Media.Ocr.OcrEngine, Windows.Media, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime]
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime]

$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]

function Await($op, $type) {
    $task = $asTaskGeneric.MakeGenericMethod($type).Invoke($null, @($op))
    $task.Wait(-1) | Out-Null
    $task.Result
}

$full = (Resolve-Path $Path).Path
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($full)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])

$engine = $null
try {
    $lang = New-Object Windows.Globalization.Language $Language
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)
}
catch { $engine = $null }
if ($null -eq $engine) { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages() }
if ($null -eq $engine) { throw "nenhuma engine de OCR disponivel" }

$result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])

$lines = @()
foreach ($line in $result.Lines) {
    $words = @()
    foreach ($w in $line.Words) {
        $r = $w.BoundingRect
        $words += [ordered]@{
            text = $w.Text
            x = [int]$r.X; y = [int]$r.Y
            width = [int]$r.Width; height = [int]$r.Height
        }
    }
    $lines += [ordered]@{ text = $line.Text; words = $words }
}

[ordered]@{
    schema = "jevcu.ocr_v1"
    language = $Language
    width = [int]$decoder.PixelWidth
    height = [int]$decoder.PixelHeight
    lines = $lines
} | ConvertTo-Json -Depth 6 -Compress | ForEach-Object { Write-Utf8Stdout $_ }
