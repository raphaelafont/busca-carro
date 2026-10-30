"""Painel no navegador: carro buscado, botão de rodar e acompanhamento ao vivo.

Abre um servidor só no próprio computador (127.0.0.1) e o navegador padrão.
O servidor se encerra sozinho 10 minutos depois que a página do painel é fechada.
"""
import json
import logging
import os
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

from . import __version__, agenda, atualizador, historico, progresso
from .configuracao import (RAIZ, SITES_ESCOLHA, ErroConfig, definir_busca, excluir_busca, ler_config, ler_lista,
                           normalizar_busca)
from .fipe import Fipe

DADOS = RAIZ / 'dados'
RESULTADOS = RAIZ / 'resultados'
ARQ_PROGRESSO = DADOS / 'progresso.jsonl'
ARQ_PAINEL = DADOS / 'painel.json'
SAIDA_FILHO = DADOS / 'painel_ultima_saida.txt'
PEDIDO_PARADA = DADOS / 'parar.pedido'  # lido pela busca em andamento (principal.parada_pedida)
PAGINA = Path(__file__).parent / 'modelos' / 'painel.html'
OCIOSO_S = 600
log = logging.getLogger('buscacarros.painel')

MARCAS = ['Audi', 'BMW', 'BYD', 'Caoa Chery', 'Chevrolet', 'Citroën', 'Fiat', 'Ford', 'GWM', 'Honda', 'Hyundai',
          'Jac', 'Jaguar', 'Jeep', 'Kia', 'Land Rover', 'Lexus', 'Mercedes-Benz', 'Mini', 'Mitsubishi', 'Nissan',
          'Peugeot', 'Porsche', 'RAM', 'Renault', 'Subaru', 'Suzuki', 'Toyota', 'Volkswagen', 'Volvo']


class Estado:
    def __init__(self):
        self.ultimo_acesso = time.time()
        self.filho = None
        self.filho_inicio = 0
        self.lock_fipe = threading.Lock()
        self._fipe = None

    def fipe(self):
        if self._fipe is None:
            try:
                token = ler_config()['fipe']['token']
            except ErroConfig:
                token = ''
            self._fipe = Fipe(DADOS, token, nome_cache='fipe_painel.json')
            self._fipe.timeout, self._fipe.tentativas = 6, 1  # o painel não pode ficar esperando
        return self._fipe


ESTADO = Estado()


# --------------------------------------------------------------------------- rodada
def rodada_atual():
    info = agenda.rodada_em_andamento(DADOS)
    if info:
        return info
    f = ESTADO.filho
    if f and f.poll() is None:  # acabou de ser iniciada e ainda não criou a trava
        return {'pid': f.pid, 'inicio': ESTADO.filho_inicio, 'origem': 'painel'}
    return None


def iniciar_rodada():
    if rodada_atual():
        return False, 'Já existe uma busca em andamento.'
    exe = Path(sys.executable)
    # usa o python "sem janela" quando existe (Windows)
    sem_janela = exe.with_name('pythonw.exe')
    exe = sem_janela if sem_janela.exists() else exe
    opcoes = {}
    if sys.platform == 'win32':
        opcoes['creationflags'] = 0x08000000  # CREATE_NO_WINDOW
    else:
        opcoes['start_new_session'] = True
    iniciador = RAIZ / 'iniciar.py'
    if iniciador.is_file():  # instalação com versões: a busca usa a versão ativa (que pode ser mais nova)
        cmd = [str(exe), str(iniciador), 'busca']
    else:
        cmd = [str(exe), '-m', 'buscacarros']
    # o painel já procurou atualização ao abrir; a busca não precisa procurar de novo
    env = dict(os.environ, BUSCACARRO_RAIZ=str(RAIZ), BUSCACARRO_SEM_ATUALIZAR='1')
    with open(SAIDA_FILHO, 'w', encoding='utf-8') as saida:  # o processo filho herda a própria cópia
        ESTADO.filho = subprocess.Popen(cmd + ['--forcar', '--origem', 'painel'],
                                        cwd=str(RAIZ), stdout=saida, stderr=subprocess.STDOUT,
                                        stdin=subprocess.DEVNULL, env=env, **opcoes)
    ESTADO.filho_inicio = time.time()
    return True, 'Busca iniciada.'


def parar_e_gerar():
    """Pede para a busca em andamento parar no ponto em que está e gerar o relatório com o que já leu."""
    if not rodada_atual():
        return False, 'Nenhuma busca em andamento.'
    PEDIDO_PARADA.write_text(str(time.time()), encoding='utf-8')
    return True, 'Parando: a busca termina o que está lendo e gera o relatório.'


def parar_rodada():
    info = rodada_atual()
    if not info:
        return False, 'Nenhuma busca em andamento.'
    agenda.encerrar_processo(info['pid'])
    try:
        PEDIDO_PARADA.unlink()
    except FileNotFoundError:
        pass
    try:
        (DADOS / 'execucao.lock').unlink()
    except FileNotFoundError:
        pass
    _, _, rodada = progresso.ler(ARQ_PROGRESSO, 0)
    if rodada:
        with open(ARQ_PROGRESSO, 'a', encoding='utf-8') as f:
            f.write(json.dumps({'tipo': 'fim', 'status': 'interrompida', 'rodada': rodada, 'ts': round(time.time(), 2),
                                'msg': 'Busca interrompida pelo painel.'}, ensure_ascii=False) + '\n')
    return True, 'Busca interrompida.'


def erro_de_inicio():
    """Se a rodada iniciada pelo painel terminou sem começar (ex.: lista vazia), devolve a mensagem."""
    f = ESTADO.filho
    if not f or f.poll() is None or f.returncode == 0:
        return None
    eventos, _, _ = progresso.ler(ARQ_PROGRESSO, 0)
    if eventos and eventos[0].get('ts', 0) >= ESTADO.filho_inicio - 1:
        return None
    try:
        linhas = [l for l in SAIDA_FILHO.read_text(encoding='utf-8').splitlines() if l.strip()]
    except OSError:
        linhas = []
    return linhas[-1].split(' ', 2)[-1] if linhas else 'A busca não conseguiu começar.'


def estado_geral():
    try:
        cfg = ler_config()
    except ErroConfig:
        cfg = None
    ultima = agenda.ultima_execucao(DADOS)
    proxima = None
    if cfg:
        _, prox = agenda.deve_rodar(DADOS, cfg['execucao']['intervalo_dias'])
        proxima = prox.strftime('%d/%m/%Y') if prox else None
    return {
        'buscas': ler_lista(),
        'rodando': rodada_atual(),
        'parando': PEDIDO_PARADA.exists(),
        'sites_disponiveis': [{'chave': k, 'nome': n} for k, n in SITES_ESCOLHA.items()],
        'ultima': ultima,
        'proxima': proxima,
        'intervalo_dias': cfg['execucao']['intervalo_dias'] if cfg else 2,
        'tem_relatorio': (RESULTADOS / 'ultimo_relatorio.html').exists(),
        'erro_inicio': erro_de_inicio(),
        'versao': __version__,
        'atualizacao': atualizador.estado(),
        'agora': time.time(),
    }


# --------------------------------------------------------------------------- FIPE (sugestões e conferência)
def sugestoes_modelos(marca):
    with ESTADO.lock_fipe:
        f = ESTADO.fipe()
        f.indisponivel = False
        cod = f.marca(marca)
        if not cod:
            return []
        lista = f.cache['modelos'].get(str(cod)) or (f._get(f'/brands/{cod}/models') or [])
        if lista:
            f.cache['modelos'][str(cod)] = lista
            f.salvar()
    nomes = {}
    for m in lista:
        primeira = m['name'].split()[0]
        nomes.setdefault(primeira.lower(), primeira)
    return sorted(nomes.values(), key=str.lower)


def conferir_na_fipe(marca, modelo):
    """Aviso se marca/modelo não existem na FIPE (provável erro de digitação). None = ok ou sem como conferir."""
    with ESTADO.lock_fipe:
        f = ESTADO.fipe()
        f.indisponivel = False
        cod = f.marca(marca)
        if f.indisponivel:
            return None
        if not cod:
            return f'Não encontrei a marca "{marca}" na tabela FIPE. Confira a grafia.'
        mods = f.modelos(cod, modelo)
        if f.indisponivel:
            return None
        f.salvar()
        if not mods:
            return f'Não encontrei o modelo "{modelo}" da {marca} na tabela FIPE. Confira a grafia.'
    return None


# --------------------------------------------------------------------------- HTTP
class Manipulador(BaseHTTPRequestHandler):
    server_version = 'BuscaCarros'

    def log_message(self, *args):
        pass

    def _json(self, codigo, dados):
        corpo = json.dumps(dados, ensure_ascii=False).encode('utf-8')
        self.send_response(codigo)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def _arquivo(self, caminho: Path, tipo='text/html; charset=utf-8'):
        try:
            corpo = caminho.read_bytes()
        except OSError:
            return self._json(404, {'erro': 'Arquivo não encontrado.'})
        self.send_response(200)
        self.send_header('Content-Type', tipo)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def _corpo(self):
        n = int(self.headers.get('Content-Length') or 0)
        if not n:
            return {}
        return json.loads(self.rfile.read(n).decode('utf-8'))

    def _autorizado(self):
        # só a página do próprio painel envia este cabeçalho (sites externos não conseguem)
        return self.headers.get('X-Painel') == '1'

    def do_GET(self):
        ESTADO.ultimo_acesso = time.time()
        url = urlparse(self.path)
        q = parse_qs(url.query)
        try:
            if url.path == '/':
                return self._arquivo(PAGINA)
            if url.path == '/api/ping':
                return self._json(200, {'ok': True, 'app': 'buscacarros'})
            if url.path == '/api/estado':
                return self._json(200, estado_geral())
            if url.path == '/api/progresso':
                desde = int((q.get('desde') or ['0'])[0])
                eventos, novo, rodada = progresso.ler(ARQ_PROGRESSO, desde)
                return self._json(200, {'eventos': eventos, 'desde': novo, 'rodada': rodada})
            if url.path == '/api/modelos':
                marca = (q.get('marca') or [''])[0]
                return self._json(200, {'modelos': sugestoes_modelos(marca) if marca else []})
            if url.path == '/api/marcas':
                return self._json(200, {'marcas': MARCAS})
            if url.path == '/icone.ico':
                return self._arquivo(RAIZ / 'icone.ico', 'image/x-icon')
            if url.path == '/relatorio':
                return self._arquivo(RESULTADOS / 'ultimo_relatorio.html')
            if url.path == '/api/historico':
                return self._json(200, {'historico': historico.listar(RESULTADOS, DADOS)})
            if url.path.startswith('/relatorios/'):
                arq = historico.caminho_relatorio(RESULTADOS, url.path.rsplit('/', 1)[1])
                if arq:
                    return self._arquivo(arq)
                return self._json(404, {'erro': 'Relatório não encontrado (os 30 mais recentes ficam guardados).'})
            return self._json(404, {'erro': 'Página não encontrada.'})
        except ErroConfig as e:
            return self._json(400, {'erro': str(e)})
        except Exception as e:
            log.exception('Erro no painel')
            return self._json(500, {'erro': f'Erro interno: {e}'})

    def do_POST(self):
        ESTADO.ultimo_acesso = time.time()
        if not self._autorizado():
            return self._json(403, {'erro': 'Acesso negado.'})
        url = urlparse(self.path)
        try:
            if url.path == '/api/buscas':
                dados = self._corpo()
                if not dados.get('forcar'):
                    b = normalizar_busca(dados)
                    aviso = conferir_na_fipe(b['marca'], b['modelo'])
                    if aviso:
                        return self._json(409, {'aviso': aviso})
                nova, anterior = definir_busca(dados)
                return self._json(200, {'busca': nova, 'anterior': anterior and anterior['titulo'],
                                        'buscas': ler_lista()})
            if url.path == '/api/rodar':
                ok, msg = iniciar_rodada()
                return self._json(200 if ok else 409, {'ok': ok, 'msg': msg})
            if url.path == '/api/parar-e-gerar':
                ok, msg = parar_e_gerar()
                return self._json(200 if ok else 409, {'ok': ok, 'msg': msg})
            if url.path == '/api/parar':
                ok, msg = parar_rodada()
                return self._json(200 if ok else 409, {'ok': ok, 'msg': msg})
            return self._json(404, {'erro': 'Ação desconhecida.'})
        except ErroConfig as e:
            return self._json(400, {'erro': str(e)})
        except Exception as e:
            log.exception('Erro no painel')
            return self._json(500, {'erro': f'Erro interno: {e}'})

    def do_DELETE(self):
        ESTADO.ultimo_acesso = time.time()
        if not self._autorizado():
            return self._json(403, {'erro': 'Acesso negado.'})
        url = urlparse(self.path)
        try:
            if url.path.startswith('/api/buscas/'):
                excluir_busca(url.path.rsplit('/', 1)[1])
                return self._json(200, {'buscas': ler_lista()})
            return self._json(404, {'erro': 'Ação desconhecida.'})
        except ErroConfig as e:
            return self._json(400, {'erro': str(e)})


# --------------------------------------------------------------------------- início
def instancia_existente():
    try:
        info = json.loads(ARQ_PAINEL.read_text(encoding='utf-8'))
        s = requests.Session()
        s.trust_env = False
        r = s.get(f"http://127.0.0.1:{info['porta']}/api/ping", timeout=2)
        if r.ok and r.json().get('app') == 'buscacarros':
            return info['porta']
    except Exception:
        pass
    return None


def servidor_livre():
    for porta in range(8765, 8800):
        try:
            return ThreadingHTTPServer(('127.0.0.1', porta), Manipulador), porta
        except OSError:
            continue
    raise RuntimeError('Nenhuma porta livre entre 8765 e 8799.')


def main(abrir_navegador=True):
    DADOS.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s', datefmt='%H:%M:%S',
                        stream=sys.stderr if sys.stderr else open(os.devnull, 'w'))
    porta = instancia_existente()
    if porta:
        if abrir_navegador:
            webbrowser.open(f'http://127.0.0.1:{porta}/')
        return 0
    try:
        ler_lista()  # cria/migra a lista na primeira vez
    except ErroConfig as e:
        log.error(str(e))
    srv, porta = servidor_livre()
    ARQ_PAINEL.write_text(json.dumps({'porta': porta, 'pid': os.getpid(), 'inicio': datetime.now().isoformat()}),
                          encoding='utf-8')

    def vigia():
        while True:
            time.sleep(30)
            if time.time() - ESTADO.ultimo_acesso > OCIOSO_S:
                srv.shutdown()
                return

    threading.Thread(target=vigia, daemon=True).start()
    log.info('Painel em http://127.0.0.1:%d/', porta)
    if abrir_navegador:
        threading.Timer(0.5, lambda: webbrowser.open(f'http://127.0.0.1:{porta}/')).start()
    try:
        srv.serve_forever()
    finally:
        srv.server_close()
        try:
            if json.loads(ARQ_PAINEL.read_text(encoding='utf-8')).get('pid') == os.getpid():
                ARQ_PAINEL.unlink()
        except Exception:
            pass
    return 0


if __name__ == '__main__':
    sys.exit(main('--sem-navegador' not in sys.argv))
