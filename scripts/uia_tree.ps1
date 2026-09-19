# Arvore de UI Automation de uma janela, em JSON.
#
#   powershell -File scripts/uia_tree.ps1 -Foreground
#   powershell -File scripts/uia_tree.ps1 -ProcessName explorer -MaxNodes 1500
#
# Emite a arvore inteira ate os limites; o esqueleto e o drill-down sao feitos
# em memoria no Python, sem uma segunda chamada.
param(
    [string]$ProcessName,
    [switch]$Foreground,
    [int]$MaxNodes = 1200,
    [int]$MaxDepth = 12
)

$ErrorActionPreference = "Stop"
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

Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

$AE = [System.Windows.Automation.AutomationElement]
$walker = [System.Windows.Automation.TreeWalker]::ControlViewWalker

function Get-TargetElement {
    if ($Foreground) {
        Add-Type -Namespace Win -Name Fg -MemberDefinition @'
[DllImport("user32.dll")] public static extern System.IntPtr GetForegroundWindow();
'@
        $hwnd = [Win.Fg]::GetForegroundWindow()
        if ($hwnd -eq [System.IntPtr]::Zero) { throw "nenhuma janela em primeiro plano" }
        return $AE::FromHandle($hwnd)
    }
    if ($ProcessName) {
        $proc = Get-Process -Name $ProcessName -ErrorAction SilentlyContinue |
                Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
        if (-not $proc) { throw "nenhuma janela visivel para o processo '$ProcessName'" }
        return $AE::FromHandle($proc.MainWindowHandle)
    }
    throw "informe -Foreground ou -ProcessName"
}

$script:count = 0
$script:truncated = $false

function Read-Node($element, [int]$depth) {
    if ($script:count -ge $MaxNodes) { $script:truncated = $true; return $null }
    $script:count++

    try {
        $info = $element.Current
        $role = $info.ControlType.ProgrammaticName -replace '^ControlType\.', ''
        $node = [ordered]@{
            ref     = "e$($script:count)"
            role    = $role
            name    = $info.Name
            enabled = [bool]$info.IsEnabled
        }
    }
    catch { return $null }   # elemento morreu entre o walk e a leitura

    if ($depth -lt $MaxDepth) {
        $kids = @()
        try { $child = $walker.GetFirstChild($element) } catch { $child = $null }
        while ($null -ne $child) {
            if ($script:count -ge $MaxNodes) { $script:truncated = $true; break }
            $sub = Read-Node $child ($depth + 1)
            if ($null -ne $sub) { $kids += $sub }
            try { $child = $walker.GetNextSibling($child) } catch { break }
        }
        if ($kids.Count -gt 0) { $node.children = $kids }
    }
    return $node
}

$target = Get-TargetElement
$started = Get-Date
$tree = Read-Node $target 0
$elapsed = [int]((Get-Date) - $started).TotalMilliseconds

[ordered]@{
    schema     = "jevcu.uia_tree_v1"
    app        = (Get-Process -Id $target.Current.ProcessId -ErrorAction SilentlyContinue).ProcessName
    window     = $target.Current.Name
    node_count = $script:count
    truncated  = $script:truncated
    elapsed_ms = $elapsed
    tree       = $tree
} | ConvertTo-Json -Depth 40 -Compress | ForEach-Object { Write-Utf8Stdout $_ }
