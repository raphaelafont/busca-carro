"""Instala (ou reinstala) o Busca Carro em %LOCALAPPDATA%\\BuscaCarro, só para o usuário atual.

Roda pelo Instalar.bat, com o Python embutido do próprio pacote (python.exe é assinado pela Python
Software Foundation). Não usa nenhum .exe próprio sem assinatura, que o Controle Inteligente de
Aplicativos do Windows 11 bloqueia.

Passos:
  1. encerra o painel ou uma busca em andamento;
  2. apaga tudo o que instalações anteriores deixaram, menos os arquivos da pessoa
     (config.ini, buscas.json, buscas.xlsx, dados, resultados, logs);
  3. copia o programa;
  4. traz o carro, as configurações, os dados e os relatórios da pasta antiga "Busca Carros"
     da área de trabalho (versão manual), se existir, e apaga essa pasta;
  5. cria os atalhos (área de trabalho, Menu Iniciar, Inicializar) e a checagem diária às 12h;
  6. registra em "Aplicativos instalados" (desinstalar pelo Windows).
"""
import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path

NOME = 'Busca Carro'
PASTA_NOME = 'BuscaCarro'
CHAVE_DESINST = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\BuscaCarro'
TAREFA = 'Busca Carro'
FICAM = {'config.ini', 'buscas.json', 'buscas.xlsx', 'dados', 'resultados', 'logs'}

AQUI = Path(__file__).resolve().parent          # ...\BuscaCarro-Instalador\programa
SEM_JANELA = 0x08000000                          # CREATE_NO_WINDOW


def destino_padrao():
    base = os.environ.get('LOCALAPPDATA') or str(Path.home() / 'AppData' / 'Local')
    return Path(base) / PASTA_NOME


def passo(texto):
    print(texto, flush=True)


# --------------------------------------------------------------------------- pastas do Windows
CSIDL_PROGRAMS, CSIDL_STARTUP, CSIDL_DESKTOPDIRECTORY = 0x02, 0x07, 0x10


def pasta_especial(csidl):
    buf = ctypes.create_unicode_buffer(260)
    if ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf) != 0:
        raise OSError(f'pasta especial {csidl} não encontrada')
    return Path(buf.value)


# --------------------------------------------------------------------------- processos
class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD), ('th32ProcessID', wintypes.DWORD),
                ('th32DefaultHeapID', ctypes.c_size_t), ('th32ModuleID', wintypes.DWORD),
                ('cntThreads', wintypes.DWORD), ('th32ParentProcessID', wintypes.DWORD),
                ('pcPriClassBase', ctypes.c_long), ('dwFlags', wintypes.DWORD),
                ('szExeFile', ctypes.c_wchar * 260)]


def encerrar_processos(pasta):
    """Encerra processos cujo executável está dentro de `pasta` (painel, busca, driver do navegador)."""
    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.OpenProcess.restype = wintypes.HANDLE
    alvo = str(pasta).rstrip('\\').lower() + '\\'
    eu = os.getpid()
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    if not snap or snap == wintypes.HANDLE(-1).value:
        return 0
    encerrados = 0
    try:
        e = PROCESSENTRY32W()
        e.dwSize = ctypes.sizeof(e)
        ok = k32.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            pid = e.th32ProcessID
            if pid not in (0, eu):
                h = k32.OpenProcess(0x1000 | 0x0001, False, pid)  # QUERY_LIMITED_INFORMATION | TERMINATE
                if h:
                    try:
                        buf = ctypes.create_unicode_buffer(1024)
                        n = wintypes.DWORD(len(buf))
                        if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
                            if buf.value.lower().startswith(alvo) and k32.TerminateProcess(h, 1):
                                encerrados += 1
                    finally:
                        k32.CloseHandle(h)
            ok = k32.Process32NextW(snap, ctypes.byref(e))
    finally:
        k32.CloseHandle(snap)
    if encerrados:
        time.sleep(1)
    return encerrados


# --------------------------------------------------------------------------- arquivos
def _apagar(p):
    def liberar(func, caminho, _exc):  # arquivo somente leitura
        try:
            os.chmod(caminho, 0o666)
            func(caminho)
        except OSError:
            pass
    if p.is_dir() and not p.is_symlink():
        shutil.rmtree(p, onerror=liberar)
    else:
        try:
            p.unlink()
        except OSError:
            liberar(os.unlink, str(p), None)


def limpar_instalacao_anterior(destino):
    """Apaga tudo em `destino`, menos os arquivos da pessoa. Só age numa pasta chamada BuscaCarro."""
    if destino.name.lower() != PASTA_NOME.lower() or not destino.is_dir():
        return []
    sobras = []
    for p in destino.iterdir():
        if p.name.lower() in FICAM:
            continue
        _apagar(p)
        if p.exists():
            sobras.append(p.name)
    return sobras


def copiar_programa(destino):
    destino.mkdir(parents=True, exist_ok=True)
    for p in AQUI.iterdir():  # instalar.py vai junto: o desinstalar.py usa as funções dele
        alvo = destino / p.name
        if p.is_dir():
            shutil.copytree(p, alvo, dirs_exist_ok=True, copy_function=shutil.copyfile)
        else:
            shutil.copyfile(p, alvo)  # só o conteúdo: a marca de "baixado da internet" não vai junto


def migrar_pasta_manual(destino, desktop):
    """Leva o carro, as configurações, os dados e os relatórios da versão manual antiga e apaga a pasta."""
    antiga = desktop / 'Busca Carros'
    if not any((antiga / n).exists() for n in ('buscacarros', '.venv', 'buscas.json')):
        return False
    encerrar_processos(antiga)
    for nome in ('buscas.json', 'config.ini'):
        if (antiga / nome).is_file() and not (destino / nome).exists():
            shutil.copyfile(antiga / nome, destino / nome)
    for nome in ('dados', 'resultados'):
        if (antiga / nome).is_dir() and not any((destino / nome).glob('*')):
            shutil.copytree(antiga / nome, destino / nome, dirs_exist_ok=True, copy_function=shutil.copyfile)
    eu = Path(sys.argv[0]).resolve()
    for p in antiga.iterdir():
        if eu.is_relative_to(p):  # instalador extraído dentro da pasta antiga: não apaga a si mesmo
            continue
        _apagar(p)
    try:
        antiga.rmdir()
    except OSError:
        pass
    return True


# --------------------------------------------------------------------------- atalhos (IShellLinkW via ctypes)
class GUID(ctypes.Structure):
    _fields_ = [('d1', wintypes.DWORD), ('d2', wintypes.WORD), ('d3', wintypes.WORD), ('d4', ctypes.c_ubyte * 8)]

    def __init__(self, texto):
        super().__init__()
        ctypes.oledll.ole32.CLSIDFromString(texto, ctypes.byref(self))


def _metodo(obj, indice, *argtypes):
    vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    proto = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, *argtypes)
    f = proto(vtbl[indice])
    return lambda *a: f(obj, *a)


def criar_atalho(lnk, alvo, argumentos, pasta_trabalho, icone, descricao, mostrar=1):
    ole32 = ctypes.oledll.ole32
    ole32.CoInitialize(None)
    link = ctypes.c_void_p()
    ole32.CoCreateInstance(ctypes.byref(GUID('{00021401-0000-0000-C000-000000000046}')), None, 1,
                           ctypes.byref(GUID('{000214F9-0000-0000-C000-000000000046}')), ctypes.byref(link))
    persist = ctypes.c_void_p()
    try:
        _metodo(link, 20, wintypes.LPCWSTR)(str(alvo))                    # SetPath
        _metodo(link, 11, wintypes.LPCWSTR)(argumentos)                   # SetArguments
        _metodo(link, 9, wintypes.LPCWSTR)(str(pasta_trabalho))           # SetWorkingDirectory
        _metodo(link, 17, wintypes.LPCWSTR, ctypes.c_int)(str(icone), 0)  # SetIconLocation
        _metodo(link, 7, wintypes.LPCWSTR)(descricao)                     # SetDescription
        _metodo(link, 15, ctypes.c_int)(mostrar)                          # SetShowCmd
        _metodo(link, 0, ctypes.c_void_p, ctypes.c_void_p)(              # QueryInterface(IPersistFile)
            ctypes.byref(GUID('{0000010B-0000-0000-C000-000000000046}')), ctypes.byref(persist))
        Path(lnk).parent.mkdir(parents=True, exist_ok=True)
        _metodo(persist, 6, wintypes.LPCWSTR, wintypes.BOOL)(str(lnk), True)  # Save
    finally:
        if persist:
            _metodo(persist, 2)()
        _metodo(link, 2)()


def criar_atalhos(destino, desktop):
    pythonw = destino / 'python' / 'pythonw.exe'
    iniciar = f'"{destino / "iniciar.py"}"'
    icone = destino / 'icone.ico'
    menu, inicializar = pasta_especial(CSIDL_PROGRAMS), pasta_especial(CSIDL_STARTUP)
    criar_atalho(desktop / f'{NOME}.lnk', pythonw, f'{iniciar} painel', destino, icone, f'Painel do {NOME}')
    criar_atalho(menu / f'{NOME}.lnk', pythonw, f'{iniciar} painel', destino, icone, f'Painel do {NOME}')
    criar_atalho(inicializar / f'{NOME}.lnk', pythonw, f'{iniciar} busca', destino, icone,
                 f'Busca automática do {NOME} (a cada 2 dias)', mostrar=7)
    for pasta in (desktop, menu, inicializar):  # atalhos da versão manual antiga
        try:
            (pasta / 'Busca de carros.lnk').unlink()
        except OSError:
            pass


# --------------------------------------------------------------------------- checagem diária às 12h
def _xml(texto):
    return texto.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


def agendar(destino):
    """Tarefa diária às 12h (para quem usa suspensão em vez de desligar). Se o PC estiver desligado,
    roda quando voltar. A busca só acontece se já passaram 2 dias; a checagem é rápida."""
    subprocess.run(['schtasks.exe', '/Delete', '/TN', 'Busca de carros', '/F'], capture_output=True,
                   creationflags=SEM_JANELA)  # tarefa da versão manual antiga
    xml = f'''<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Confere se já é dia de buscar carros (a busca roda a cada 2 dias).</Description></RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>2026-01-01T12:00:00</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Principals><Principal id="Author"><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <ExecutionTimeLimit>PT2H</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{_xml(str(destino / 'python' / 'pythonw.exe'))}</Command>
      <Arguments>{_xml(f'"{destino / "iniciar.py"}" busca')}</Arguments>
      <WorkingDirectory>{_xml(str(destino))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
'''
    arq = Path(tempfile.gettempdir()) / 'buscacarro_tarefa.xml'
    arq.write_text(xml, encoding='utf-16')
    try:
        r = subprocess.run(['schtasks.exe', '/Create', '/TN', TAREFA, '/XML', str(arq), '/F'],
                           capture_output=True, creationflags=SEM_JANELA)
        return r.returncode == 0
    finally:
        try:
            arq.unlink()
        except OSError:
            pass


# --------------------------------------------------------------------------- "Aplicativos instalados"
def registrar(destino, versao):
    import winreg
    pythonw = destino / 'python' / 'pythonw.exe'
    desinstalar = f'"{pythonw}" "{destino / "desinstalar.py"}"'
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, CHAVE_DESINST) as k:
        for nome, valor in (('DisplayName', NOME), ('DisplayVersion', versao), ('Publisher', NOME),
                            ('DisplayIcon', str(destino / 'icone.ico')), ('InstallLocation', str(destino)),
                            ('UninstallString', desinstalar), ('QuietUninstallString', desinstalar + ' /S')):
            winreg.SetValueEx(k, nome, 0, winreg.REG_SZ, valor)
        for nome in ('NoModify', 'NoRepair'):
            winreg.SetValueEx(k, nome, 0, winreg.REG_DWORD, 1)


# --------------------------------------------------------------------------- principal
def versao_do_pacote():
    try:
        return json.loads((AQUI / 'base.json').read_text(encoding='utf-8')).get('instalador') or '?'
    except (OSError, ValueError):
        return '?'


def instalar(destino=None, desktop=None, abrir=True):
    destino = Path(destino or destino_padrao())
    desktop = Path(desktop or pasta_especial(CSIDL_DESKTOPDIRECTORY))
    versao = versao_do_pacote()
    if AQUI == destino or destino in AQUI.parents:
        raise SystemExit(f'Extraia o instalador em outra pasta (por exemplo, Downloads), não em {destino}.')

    passo(f'Instalando o {NOME} {versao} em {destino}')
    passo('- encerrando o painel ou uma busca em andamento')
    encerrar_processos(destino)
    passo('- apagando arquivos de instalações anteriores (o carro, as configurações e os dados ficam)')
    sobras = limpar_instalacao_anterior(destino)
    if sobras:
        time.sleep(2)
        encerrar_processos(destino)
        sobras = limpar_instalacao_anterior(destino)
    if sobras:
        raise SystemExit('Não consegui apagar: ' + ', '.join(sobras) +
                         '. Feche o painel do Busca Carro (ou reinicie o computador) e rode o Instalar de novo.')
    passo('- copiando o programa')
    copiar_programa(destino)
    if migrar_pasta_manual(destino, desktop):
        passo('- pasta antiga "Busca Carros" da área de trabalho: carro e dados trazidos, pasta apagada')
    if not (destino / 'config.ini').exists():
        shutil.copyfile(destino / 'config.exemplo.ini', destino / 'config.ini')
    passo('- criando os atalhos')
    criar_atalhos(destino, desktop)
    passo('- agendando a checagem diária às 12h')
    if not agendar(destino):
        passo('  (não deu para agendar; a busca automática continua acontecendo ao entrar no Windows)')
    registrar(destino, versao)
    passo(f'\n{NOME} {versao} instalado. O ícone "{NOME}" está na área de trabalho.')
    if abrir:
        subprocess.Popen([str(destino / 'python' / 'pythonw.exe'), str(destino / 'iniciar.py'), 'painel'],
                         cwd=str(destino), close_fds=True, creationflags=0x00000008 | 0x00000200)  # DETACHED, NEW_GROUP
        passo('O painel está abrindo no navegador.')
    return destino


def main(argv):
    abrir = '--sem-abrir' not in argv
    try:
        instalar(abrir=abrir)
        codigo = 0
    except SystemExit as e:
        print(f'\nERRO: {e}', flush=True)
        codigo = 1
    except Exception as e:
        print(f'\nERRO inesperado: {type(e).__name__}: {e}', flush=True)
        codigo = 1
    if '/S' not in argv:
        try:
            input('\nPressione Enter para fechar.')
        except EOFError:
            pass
    return codigo


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
