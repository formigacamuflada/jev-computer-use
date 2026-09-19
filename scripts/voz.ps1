# Lancador do modo de voz.
#
#   .\scripts\voz.ps1                      # qBittorrent, dry-run (nao clica)
#   .\scripts\voz.ps1 -App Discord
#   .\scripts\voz.ps1 -App chrome -Executar # SAI DO DRY-RUN: clica de verdade
#   .\scripts\voz.ps1 -Texto                # digitado em vez de falado
#
# Resolve o binario, sobe o daemon se preciso e ajusta o PYTHONPATH.
param(
    [string]$App = "qbittorrent",
    [switch]$Executar,
    [switch]$Texto,
    [switch]$Whisper,      # faster-whisper local na GPU, em vez do motor do Windows
    [int]$Mic = -1,        # indice do microfone; veja -ListarMics
    [string]$Modelo = "small",
    [switch]$ListarMics
)

$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $PSScriptRoot

# --- binario do Cua Driver ---
$bin = (Get-Command cua-driver -ErrorAction SilentlyContinue).Source
if (-not $bin) {
    $provavel = Join-Path $env:LOCALAPPDATA "Programs\Cua\cua-driver\bin\cua-driver.exe"
    if (Test-Path $provavel) { $bin = $provavel }
}
if (-not $bin) {
    Write-Host "cua-driver nao encontrado." -ForegroundColor Red
    Write-Host "Instale com:  irm https://cua.ai/driver/install.ps1 | iex"
    exit 1
}

# --- daemon ---
& $bin status *>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "subindo o daemon..." -ForegroundColor Yellow
    & $bin autostart kick *>$null
    Start-Sleep -Seconds 2
}

# --- interpretador ---
# Esta maquina tem mais de um Python no PATH, e qual deles responde por
# "python" muda conforme o shell. O venv do projeto remove a ambiguidade:
# as dependencias ficam onde o lancador sabe procurar.
$py = Join-Path $raiz ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "criando o venv do projeto (primeira vez)..." -ForegroundColor Yellow
    $base = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $base) { Write-Host "python nao encontrado no PATH." -ForegroundColor Red; exit 1 }
    & $base -m venv (Join-Path $raiz ".venv")
    & $py -m pip install --quiet --only-binary=:all: `
        winrt-runtime "winrt-Windows.Media.SpeechRecognition" `
        "winrt-Windows.Globalization" "winrt-Windows.Foundation" `
        "winrt-Windows.Foundation.Collections"
}

$env:PYTHONPATH = Join-Path $raiz "src"
$env:JEVCU_DRIVER_BIN = $bin

if ($ListarMics) {
    Push-Location $raiz
    try { & $py -m jevcu --list-mics } finally { Pop-Location }
    exit 0
}

$argumentos = @("-m", "jevcu", "--driver", "cua", "--app", $App)
if ($Texto)        { $argumentos += @("--stt", "text") }
elseif ($Whisper)  { $argumentos += @("--stt", "whisper", "--model", $Modelo) }
else               { $argumentos += @("--stt", "winrt") }
if ($Mic -ge 0)    { $argumentos += @("--mic", "$Mic") }
if (-not $Executar) { $argumentos += "--dry-run" }

if ($Executar) {
    Write-Host "MODO REAL: os cliques vao acontecer de verdade." -ForegroundColor Red
} else {
    Write-Host "dry-run: decide e fala, mas nao clica. Use -Executar para valer." -ForegroundColor Cyan
}
$modo = if ($Texto) { "texto" } elseif ($Whisper) { "whisper $Modelo" } else { "winrt pt-BR" }
Write-Host ("alvo: {0} | voz: {1}" -f $App, $modo)
Write-Host ""

Push-Location $raiz
try { & $py @argumentos } finally { Pop-Location }
