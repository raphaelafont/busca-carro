"""Controle de quando rodar: a cada N dias, sem rodadas simultâneas."""
import json
import os
import socket
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path


def deve_rodar(pasta_dados: Path, intervalo_dias: int):
    try:
        ultima = date.fromisoformat(ultima_execucao(pasta_dados)['data'])
    except Exception:
        return True, None
    proxima = ultima + timedelta(days=intervalo_dias)
    return date.today() >= proxima, proxima


def ultima_execucao(pasta_dados: Path):
    try:
        return json.loads((pasta_dados / 'ultima_execucao.json').read_text(encoding='utf-8'))
    except Exception:
        return None


def registrar(pasta_dados: Path, resumo: dict):
    arq = pasta_dados / 'ultima_execucao.json'
    arq.write_text(json.dumps({'data': date.today().isoformat(), 'hora': datetime.now().strftime('%H:%M'), **resumo},
                              ensure_ascii=False, indent=1), encoding='utf-8')


def processo_vivo(pid):
    if not pid:
        return False
    if sys.platform == 'win32':
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.windll.kernel32
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        k32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        k32.CloseHandle.argtypes = (wintypes.HANDLE,)
        h = k32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        codigo = wintypes.DWORD()
        ok = k32.GetExitCodeProcess(h, ctypes.byref(codigo))
        k32.CloseHandle(h)
        return bool(ok) and codigo.value == 259  # STILL_ACTIVE
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False


def encerrar_processo(pid):
    """Encerra a rodada e o navegador que ela abriu."""
    if not processo_vivo(pid):
        return False
    if sys.platform == 'win32':
        import subprocess
        subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'], capture_output=True,
                       creationflags=0x08000000)
    else:
        import signal
        try:
            os.killpg(os.getpgid(int(pid)), signal.SIGTERM)
        except OSError:
            os.kill(int(pid), signal.SIGTERM)
    return True


def rodada_em_andamento(pasta_dados: Path, validade_horas=3):
    """Dados da trava se houver uma rodada viva; senão None."""
    arq = pasta_dados / 'execucao.lock'
    try:
        info = json.loads(arq.read_text(encoding='utf-8'))
    except Exception:
        return None
    if time.time() - info.get('inicio', 0) > validade_horas * 3600 or not processo_vivo(info.get('pid')):
        return None
    return info


class Trava:
    """Impede duas execuções ao mesmo tempo (ex.: painel + execução automática)."""

    def __init__(self, pasta_dados: Path, origem='manual'):
        self.arq = pasta_dados / 'execucao.lock'
        self.pasta = pasta_dados
        self.origem = origem

    def __enter__(self):
        outra = rodada_em_andamento(self.pasta)
        if outra and outra.get('pid') != os.getpid():
            inicio = datetime.fromtimestamp(outra['inicio']).strftime('%H:%M')
            raise RuntimeError(f"Já existe uma busca em andamento (iniciada às {inicio}).")
        self.arq.write_text(json.dumps({'pid': os.getpid(), 'inicio': time.time(), 'origem': self.origem}),
                            encoding='utf-8')
        return self

    def __exit__(self, *exc):
        try:
            self.arq.unlink()
        except FileNotFoundError:
            pass


def aguardar_internet(limite_s=240, avisar=None):
    """Logo após ligar o PC a rede pode demorar; espera até ela responder."""
    inicio = time.time()
    primeira = True
    while time.time() - inicio < limite_s:
        try:
            with socket.create_connection(('www.google.com', 443), timeout=5):
                return True
        except OSError:
            if primeira and avisar:
                avisar('Aguardando conexão com a internet…')
                primeira = False
            time.sleep(10)
    return False
