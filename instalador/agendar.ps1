# Checagem diária às 12h (para quem usa suspensão em vez de desligar o PC).
# A busca em si só roda se já tiverem passado 2 dias desde a última. Se o PC estiver desligado às 12h,
# roda assim que ele voltar. A busca também é conferida a cada login, pelo atalho da pasta Inicializar.
$ErrorActionPreference = 'Stop'
$pasta = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonw = Join-Path $pasta 'python\pythonw.exe'
$iniciar = Join-Path $pasta 'iniciar.py'

# remove a tarefa da versão antiga (instalação manual), se existir
try { Unregister-ScheduledTask -TaskName 'Busca de carros' -Confirm:$false -ErrorAction SilentlyContinue } catch { }

try {
    $acao = New-ScheduledTaskAction -Execute $pythonw -Argument ('"' + $iniciar + '" busca') -WorkingDirectory $pasta
    $gatilho = New-ScheduledTaskTrigger -Daily -At '12:00'
    $conf = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit (New-TimeSpan -Hours 2)
    Register-ScheduledTask -TaskName 'Busca Carro' -Action $acao -Trigger $gatilho -Settings $conf `
        -Description 'Confere se já é dia de buscar carros (a busca roda a cada 2 dias).' -Force | Out-Null
} catch {
    # sem a tarefa, a busca automática continua acontecendo ao entrar no Windows
}
exit 0
