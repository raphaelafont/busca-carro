"""Desinstala o Busca Carro (chamado por "Aplicativos instalados" do Windows ou por Desinstalar.bat).

Pergunta antes (a não ser com /S), encerra o painel e a busca, remove atalhos, a tarefa agendada e o
registro, e apaga a pasta do programa inteira (inclusive carro, configurações e relatórios).
"""
import ctypes
import os
import subprocess
import sys
import tempfile
from pathlib import Path

PASTA = Path(__file__).resolve().parent
sys.path.insert(0, str(PASTA))

NOME = 'Busca Carro'
CHAVE_DESINST = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\BuscaCarro'
SEM_JANELA = 0x08000000


def caixa(texto, botoes=0x40):
    return ctypes.windll.user32.MessageBoxW(None, texto, f'Desinstalar o {NOME}', botoes)


def main(argv):
    from instalar import CSIDL_DESKTOPDIRECTORY, CSIDL_PROGRAMS, CSIDL_STARTUP, encerrar_processos, pasta_especial
    silencioso = '/S' in argv
    if not silencioso and caixa(f'Remover o {NOME} deste computador?\n\nO carro buscado, as configurações e os '
                                'relatórios também serão apagados.', 0x4 | 0x20) != 6:  # MB_YESNO | ÍCONE ?; IDYES
        return 1
    if PASTA.name.lower() != 'buscacarro':
        caixa(f'Pasta inesperada ({PASTA}); nada foi apagado.', 0x10)
        return 1
    encerrar_processos(PASTA)
    subprocess.run(['schtasks.exe', '/Delete', '/TN', NOME, '/F'], capture_output=True, creationflags=SEM_JANELA)
    for csidl in (CSIDL_DESKTOPDIRECTORY, CSIDL_PROGRAMS, CSIDL_STARTUP):
        try:
            (pasta_especial(csidl) / f'{NOME}.lnk').unlink()
        except OSError:
            pass
    try:
        import winreg
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, CHAVE_DESINST)
    except OSError:
        pass
    # este processo roda o pythonw.exe de dentro da pasta: quem apaga a pasta é um cmd, depois que ele fechar
    subprocess.Popen(f'cmd.exe /d /c ping -n 4 127.0.0.1 >nul & rmdir /s /q "{PASTA}"',
                     cwd=tempfile.gettempdir(), close_fds=True, creationflags=SEM_JANELA | 0x00000008)
    if not silencioso:
        caixa(f'O {NOME} foi removido.')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
