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
    [switch]$Texto
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

$env:PYTHONPATH = Join-Path $raiz "src"
$env:JEVCU_DRIVER_BIN = $bin

$argumentos = @("-m", "jevcu", "--driver", "cua", "--app", $App)
if ($Texto) { $argumentos += @("--stt", "text") } else { $argumentos += @("--stt", "winrt") }
if (-not $Executar) { $argumentos += "--dry-run" }

if ($Executar) {
    Write-Host "MODO REAL: os cliques vao acontecer de verdade." -ForegroundColor Red
} else {
    Write-Host "dry-run: decide e fala, mas nao clica. Use -Executar para valer." -ForegroundColor Cyan
}
Write-Host ("alvo: {0} | voz: {1}" -f $App, $(if ($Texto) { "texto" } else { "pt-BR" }))
Write-Host ""

Push-Location $raiz
try { & python @argumentos } finally { Pop-Location }
