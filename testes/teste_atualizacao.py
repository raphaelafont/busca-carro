"""Ciclo completo da atualização automática, com um "GitHub" falso na própria máquina.

Monta uma instalação de mentira (iniciar.py + versoes/<v>) numa pasta temporária e confere:
instala versão nova, não repete a procura em seguida, recusa pacote adulterado, não ativa versão que
não carrega, avisa quando precisa do instalador, recusa caminhos perigosos no zip, volta para a versão
anterior se a ativa não abrir, o painel abre na versão nova e a falta de internet não atrapalha.
"""
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PROJETO = Path(__file__).resolve().parents[1]
REPO = 'teste/busca-carro'
RELEASES = {}   # versão -> bytes do zip
MANIFESTO = {}  # o que /releases/latest/download/atualizacao.json devolve
PEDIDOS = []


def pacote(versao, alterar=None, extra=None):
    """Zip com o código do projeto, na versão pedida (alterar: {arquivo: função(texto)->texto})."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for p in sorted((PROJETO / 'buscacarros').rglob('*')):
            if not p.is_file() or '__pycache__' in p.parts:
                continue
            nome = p.relative_to(PROJETO).as_posix()
            dados = p.read_bytes()
            if nome == 'buscacarros/__init__.py':
                dados = re.sub(rb"__version__ = '[^']+'", f"__version__ = '{versao}'".encode(), dados)
            if nome == 'buscacarros/atualizador.py':
                dados = re.sub(rb"REPOSITORIO = '[^']+'", f"REPOSITORIO = '{REPO}'".encode(), dados)
            if alterar and nome in alterar:
                dados = alterar[nome](dados.decode('utf-8')).encode('utf-8')
            z.writestr(nome, dados)
        for nome, texto in (extra or {}).items():
            z.writestr(nome, texto)
    return buf.getvalue()


def publicar(versao, zip_bytes, sha=None, base_minima=1, notas='teste'):
    RELEASES[versao] = zip_bytes
    MANIFESTO.clear()
    MANIFESTO.update({'versao': versao, 'pacote': f'buscacarros-{versao}.zip',
                      'sha256': sha or hashlib.sha256(zip_bytes).hexdigest(), 'tamanho': len(zip_bytes),
                      'base_minima': base_minima, 'notas': notas})


class GitHubFalso(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        PEDIDOS.append(self.path)
        if self.path == f'/{REPO}/releases/latest/download/atualizacao.json':
            corpo = json.dumps(MANIFESTO).encode()
        else:
            m = re.fullmatch(rf'/{REPO}/releases/download/v([\d.]+)/buscacarros-([\d.]+)\.zip', self.path)
            if not m or m.group(1) not in RELEASES:
                self.send_response(404)
                self.end_headers()
                return
            corpo = RELEASES[m.group(1)]
        self.send_response(200)
        self.send_header('Content-Length', str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)


def montar_instalacao(pasta, versao):
    shutil.copyfile(PROJETO / 'iniciar.py', pasta / 'iniciar.py')
    (pasta / 'base.json').write_text('{"base": 1}', encoding='utf-8')
    alvo = pasta / 'versoes' / versao
    with zipfile.ZipFile(io.BytesIO(pacote(versao))) as z:
        z.extractall(alvo)
    (pasta / 'versoes' / 'ativa.json').write_text(json.dumps({'versao': versao, 'anterior': None}), encoding='utf-8')
    (pasta / 'buscas.json').write_text('{"buscas": []}', encoding='utf-8')
    shutil.copyfile(PROJETO / 'config.exemplo.ini', pasta / 'config.exemplo.ini')


def main():
    srv = ThreadingHTTPServer(('127.0.0.1', 0), GitHubFalso)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    porta = srv.server_address[1]
    inst = Path(tempfile.mkdtemp(prefix='bc_inst_'))
    env = {k: v for k, v in os.environ.items() if not k.startswith('BUSCACARRO_')}
    env.update(BUSCACARRO_URL_BASE=f'http://127.0.0.1:{porta}', NO_PROXY='127.0.0.1,localhost', no_proxy='127.0.0.1,localhost')

    def rodar(*args, extra_env=None, timeout=180):
        r = subprocess.run([sys.executable, str(inst / 'iniciar.py'), *args], cwd=str(inst), timeout=timeout,
                           env={**env, **(extra_env or {})}, capture_output=True, text=True)
        return r

    ativa = lambda: json.loads((inst / 'versoes' / 'ativa.json').read_text(encoding='utf-8'))
    situacao = lambda: json.loads((inst / 'dados' / 'atualizacao.json').read_text(encoding='utf-8'))
    try:
        montar_instalacao(inst, '9.0.0')

        # 1. versão nova publicada -> baixa, testa e ativa
        publicar('9.0.1', pacote('9.0.1'), notas='Melhorias no ritmo das buscas.')
        r = rodar('atualizar')
        assert r.returncode == 0, r.stderr
        a = ativa()
        assert a['versao'] == '9.0.1' and a['anterior'] == '9.0.0', a
        assert (inst / 'versoes' / '9.0.1' / 'buscacarros' / 'painel.py').exists()
        s = situacao()
        assert s['situacao'] == 'instalada' and s['notas_instalada'] == 'Melhorias no ritmo das buscas.', s
        print('1. versão nova baixada, testada e ativada: ok')

        # 2. procurar de novo logo em seguida não consulta a internet
        n = len(PEDIDOS)
        rodar('atualizar')
        assert len(PEDIDOS) == n, 'não devia consultar de novo em menos de 10 min'
        r = rodar('atualizar', '--forcar')
        assert situacao()['situacao'] == 'atual' and len(PEDIDOS) == n + 1
        print('2. sem nova consulta em seguida; com --forcar, "já está na mais recente": ok')

        # 3. pacote adulterado (SHA-256 não confere) -> não instala
        publicar('9.0.2', pacote('9.0.2'), sha='0' * 64)
        rodar('atualizar', '--forcar')
        assert ativa()['versao'] == '9.0.1' and not (inst / 'versoes' / '9.0.2').exists()
        assert situacao()['situacao'] == 'erro' and 'SHA-256' in situacao()['mensagem'], situacao()
        print('3. pacote adulterado recusado: ok')

        # 4. versão que não carrega -> não ativa e não tenta de novo
        quebrada = pacote('9.0.3', alterar={'buscacarros/principal.py': lambda t: t + '\ndef quebrado(:\n'})
        publicar('9.0.3', quebrada)
        rodar('atualizar', '--forcar')
        assert ativa()['versao'] == '9.0.1' and '9.0.3' in ativa().get('ruins', []), ativa()
        n = len(PEDIDOS)
        rodar('atualizar', '--forcar')
        assert situacao()['situacao'] == 'ignorada' and len(PEDIDOS) == n + 1, (situacao(), PEDIDOS[n:])
        print('4. versão que não carrega fica de fora (e não é baixada de novo): ok')

        # 5. versão que precisa de instalador novo -> só avisa
        publicar('9.1.0', pacote('9.1.0'), base_minima=2)
        rodar('atualizar', '--forcar')
        s = situacao()
        assert s['situacao'] == 'precisa_instalador' and ativa()['versao'] == '9.0.1', s
        print('5. versão que exige instalador novo só gera aviso: ok')

        # 6. zip com caminho perigoso -> recusado
        publicar('9.0.5', pacote('9.0.5', extra={'../fora.txt': 'x'}))
        rodar('atualizar', '--forcar')
        assert ativa()['versao'] == '9.0.1' and not (inst.parent / 'fora.txt').exists()
        assert 'caminho não permitido' in situacao()['mensagem'], situacao()
        print('6. zip com caminho perigoso recusado: ok')

        # 7. versão ativa que não abre -> volta sozinha para a anterior
        ruim = inst / 'versoes' / '9.0.9'
        with zipfile.ZipFile(io.BytesIO(pacote('9.0.9', alterar={
                'buscacarros/atualizador.py': lambda t: 'raise ImportError("defeito de teste")\n' + t}))) as z:
            z.extractall(ruim)
        (inst / 'versoes' / 'ativa.json').write_text(json.dumps({'versao': '9.0.9', 'anterior': '9.0.1'}), encoding='utf-8')
        r = rodar('atualizar')
        assert r.returncode == 0, r.stderr
        a = ativa()
        assert a['versao'] == '9.0.1' and '9.0.9' in a['ruins'] and a['voltou_de']['versao'] == '9.0.9', a
        print('7. versão ativa com defeito: volta para a anterior e segue: ok')

        # 8. painel abre pela versão ativa
        p = subprocess.Popen([sys.executable, str(inst / 'iniciar.py'), 'painel', '--sem-navegador'], cwd=str(inst),
                             env={**env, 'BUSCACARRO_SEM_ATUALIZAR': '1'}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(40):
                time.sleep(0.25)
                try:
                    info = json.loads((inst / 'dados' / 'painel.json').read_text(encoding='utf-8'))
                    break
                except (OSError, ValueError):
                    continue
            else:
                raise AssertionError('painel não abriu')
            req = urllib.request.Request(f"http://127.0.0.1:{info['porta']}/api/estado")
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            e = json.loads(opener.open(req, timeout=10).read())
            assert e['versao'] == '9.0.1' and e['atualizacao']['automatica'] is True, e
        finally:
            p.terminate()
            p.wait(10)
        print('8. painel abre na versão ativa e mostra a atualização automática: ok')

        # 9. sem internet -> segue com a versão instalada, rápido
        srv.shutdown()
        srv.server_close()
        t = time.time()
        r = rodar('atualizar', '--forcar')
        assert r.returncode == 0 and ativa()['versao'] == '9.0.1' and situacao()['situacao'] == 'erro'
        assert time.time() - t < 30
        print('9. sem internet: segue com a versão instalada: ok')
        print('TUDO OK')
    finally:
        try:
            srv.shutdown()
        except Exception:
            pass
        shutil.rmtree(inst, ignore_errors=True)


if __name__ == '__main__':
    main()
