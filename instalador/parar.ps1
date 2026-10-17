# Encerra processos do Busca Carro (painel, busca e o driver do navegador) antes de atualizar ou desinstalar.
param([string]$Pasta)
if (-not $Pasta) { exit 0 }
$alvo = $Pasta.TrimEnd('\') + '\'
Get-Process -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -and $_.Path.StartsWith($alvo, [System.StringComparison]::OrdinalIgnoreCase) } |
    ForEach-Object { try { Stop-Process -Id $_.Id -Force -ErrorAction Stop } catch { } }
Start-Sleep -Milliseconds 500
exit 0
