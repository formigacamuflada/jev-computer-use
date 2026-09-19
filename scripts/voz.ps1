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
    [switch]$Whisper,      # faster-whisper local, em vez do motor do Windows
    [switch]$Jev,          # decide com o Jev de verdade em vez do mock
    [int]$Mic = -1,        # indice do microfone; veja -ListarMics
    [string]$Modelo = "small",   # tiny NAO serve para pt-BR
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
# Com ErrorActionPreference = Stop, um executavel que escreve em stderr vira
# erro fatal no PowerShell 5.1. O `status` escreve "daemon is not running" em
# stderr, entao a propria verificacao matava o script antes de ele tentar subir
# o daemon. Por isso o bloco roda com a preferencia relaxada.
$prevEAP = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    & $bin status *>$null
    $rodando = ($LASTEXITCODE -eq 0)

    if (-not $rodando) {
        Write-Host "daemon parado; subindo..." -ForegroundColor Yellow
        # `autostart kick` roda a tarefa agendada, que so existe se o autostart
        # estiver registrado. Com ele desativado, o kick falha com "o sistema
        # nao pode encontrar o arquivo especificado". Subir com `serve` direto
        # funciona nos dois casos.
        Start-Process -FilePath $bin -ArgumentList "serve" -WindowStyle Hidden
        foreach ($tentativa in 1..12) {
            Start-Sleep -Milliseconds 700
            & $bin status *>$null
            if ($LASTEXITCODE -eq 0) { $rodando = $true; break }
        }
    }
}
finally { $ErrorActionPreference = $prevEAP }

if (-not $rodando) {
    Write-Host "nao consegui subir o Cua Driver." -ForegroundColor Red
    Write-Host "Tente manualmente:  cua-driver autostart kick"
    Write-Host "Se persistir:       cua-driver doctor"
    exit 1
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
if ($Jev) { $argumentos += @("--decide", "live") }
if ($Modelo -eq "tiny") {
    Write-Host "aviso: o modelo tiny erra quase tudo em portugues (medido: 0 de 5)." -ForegroundColor Yellow
}
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
$cerebro = if ($Jev) { "Jev ao vivo" } else { "mock" }
Write-Host ("alvo: {0} | voz: {1} | decisao: {2}" -f $App, $modo, $cerebro)
Write-Host ""

Push-Location $raiz
try { & $py @argumentos } finally { Pop-Location }
