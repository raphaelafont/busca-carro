"""Atualização automática pela internet.

As versões são publicadas como "releases" do repositório do Busca Carro no GitHub. Cada uma traz:
  atualizacao.json          versão, nome do pacote, SHA-256, tamanho, base mínima e notas
  buscacarros-<versão>.zip  só o código do programa (o Python e o navegador ficam como estão)
  BuscaCarro-Instalador.zip instalador completo, para quem ainda não tem o programa

Passos: lê atualizacao.json da versão mais recente; se for mais nova que a instalada, baixa o pacote,
confere tamanho e SHA-256, extrai em versoes/<versão>, testa se o programa carrega num processo separado
e só então passa a usá-lo (versoes/ativa.json). A versão anterior fica guardada para voltar se precisar.
"""
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path

from . import __version__
from .configuracao import RAIZ

REPOSITORIO = 'raphaelafont/busca-carro'  # dono/repositório no GitHub (definido por publicar.py)
URL_BASE = os.environ.get('BUSCACARRO_URL_BASE', 'https://github.com').rstrip('/')
VERSOES = RAIZ / 'versoes'
ATIVA = VERSOES / 'ativa.json'
ESTADO = RAIZ / 'dados' / 'atualizacao.json'
LOG = RAIZ / 'logs' / 'atualizacao.log'
TRAVA = VERSOES / '_atualizando.lock'
TAMANHO_MAX = 20 * 1024 * 1024
INTERVALO_MIN_S = 10 * 60  # não procura de novo antes disso (ex.: dois cliques seguidos no ícone)
MANTER_VERSOES = 3
SEM_JANELA = 0x08000000 if sys.platform == 'win32' else 0
log = logging.getLogger('buscacarros.atualizador')


# --------------------------------------------------------------------------- utilidades
def chave_versao(v):
    return tuple(int(x) for x in re.findall(r'\d+', v or '0'))


def _ler_json(arq):
    try:
        d = json.loads(Path(arq).read_text(encoding='utf-8'))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _gravar_json(arq, dados):
    arq = Path(arq)
    arq.parent.mkdir(parents=True, exist_ok=True)
    tmp = arq.with_name(arq.name + '.tmp')
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding='utf-8')
    os.replace(tmp, arq)


def anotar(texto):
    log.info(texto)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(f'{datetime.now():%d/%m/%Y %H:%M:%S} {texto}\n')
    except OSError:
        pass


def base_instalada():
    return int(_ler_json(RAIZ / 'base.json').get('base') or 1)


def pode_atualizar():
    """Só numa instalação com o iniciador (não na pasta de desenvolvimento)."""
    return (RAIZ / 'iniciar.py').is_file() and VERSOES.is_dir() and 'DEFINIR' not in REPOSITORIO


def url_manifesto():
    return f'{URL_BASE}/{REPOSITORIO}/releases/latest/download/atualizacao.json'


def url_pacote(info):
    return f"{URL_BASE}/{REPOSITORIO}/releases/download/v{info['versao']}/{info['pacote']}"


def url_instalador():
    return f'{URL_BASE}/{REPOSITORIO}/releases/latest/download/BuscaCarro-Instalador.zip'


def estado():
    """Situação da última procura, para o painel."""
    d = _ler_json(ESTADO)
    d['versao_em_uso'] = __version__
    d['versao_ativa'] = _ler_json(ATIVA).get('versao') or __version__
    d['url_instalador'] = url_instalador() if 'DEFINIR' not in REPOSITORIO else None
    d['automatica'] = pode_atualizar()
    return d


# --------------------------------------------------------------------------- manifesto
def validar_manifesto(m):
    if not isinstance(m, dict):
        raise ValueError('formato inválido')
    v = str(m.get('versao', ''))
    if not re.fullmatch(r'\d+\.\d+\.\d+', v):
        raise ValueError('versão inválida')
    pacote = str(m.get('pacote', ''))
    if not re.fullmatch(r'buscacarros-\d+\.\d+\.\d+\.zip', pacote):
        raise ValueError('nome de pacote inválido')
    sha = str(m.get('sha256', '')).lower()
    if not re.fullmatch(r'[0-9a-f]{64}', sha):
        raise ValueError('SHA-256 inválido')
    tamanho = int(m.get('tamanho') or 0)
    if not 0 < tamanho <= TAMANHO_MAX:
        raise ValueError('tamanho inválido')
    return {'versao': v, 'pacote': pacote, 'sha256': sha, 'tamanho': tamanho,
            'base_minima': int(m.get('base_minima') or 1), 'notas': str(m.get('notas') or '')[:1000],
            'publicada_em': str(m.get('publicada_em') or '')[:40]}


def buscar_manifesto(sessao, timeout=8):
    r = sessao.get(url_manifesto(), timeout=timeout, allow_redirects=True)
    if r.status_code == 404:
        return None  # nenhuma versão publicada ainda
    r.raise_for_status()
    return validar_manifesto(r.json())


# --------------------------------------------------------------------------- instalação de uma versão
def _baixar(sessao, info, destino):
    h = hashlib.sha256()
    total = 0
    with sessao.get(url_pacote(info), timeout=30, stream=True, allow_redirects=True) as r:
        r.raise_for_status()
        with open(destino, 'wb') as f:
            for bloco in r.iter_content(64 * 1024):
                total += len(bloco)
                if total > info['tamanho'] or total > TAMANHO_MAX:
                    raise ValueError('o pacote baixado é maior que o anunciado')
                h.update(bloco)
                f.write(bloco)
    if total != info['tamanho']:
        raise ValueError(f'pacote incompleto ({total} de {info["tamanho"]} bytes)')
    if h.hexdigest() != info['sha256']:
        raise ValueError('o pacote baixado não confere (SHA-256 diferente)')


def _extrair(zip_path, pasta):
    """Extrai só arquivos dentro de buscacarros/ (nada de caminhos absolutos ou '..')."""
    with zipfile.ZipFile(zip_path) as z:
        nomes = z.namelist()
        if 'buscacarros/__init__.py' not in nomes:
            raise ValueError('pacote sem o programa')
        for n in nomes:
            partes = Path(n).parts
            if n.startswith(('/', '\\')) or '..' in partes or ':' in n or not partes or partes[0] != 'buscacarros':
                raise ValueError(f'caminho não permitido no pacote: {n}')
        z.extractall(pasta)


def _versao_do_pacote(pasta):
    texto = (pasta / 'buscacarros' / '__init__.py').read_text(encoding='utf-8')
    m = re.search(r"__version__\s*=\s*['\"]([^'\"]+)['\"]", texto)
    return m.group(1) if m else None


def testar_versao(pasta, timeout=90):
    """Carrega a versão nova num processo separado. Retorna (ok, mensagem)."""
    codigo = ('import sys; sys.path.insert(0, sys.argv[1]); '
              'import buscacarros.principal, buscacarros.painel, buscacarros.atualizador, buscacarros.sites, '
              'buscacarros.navegador; print("ok")')
    env = dict(os.environ, BUSCACARRO_RAIZ=str(RAIZ))
    try:
        r = subprocess.run([sys.executable, '-c', codigo, str(pasta)], capture_output=True, text=True, timeout=timeout,
                           cwd=str(RAIZ), env=env, stdin=subprocess.DEVNULL, creationflags=SEM_JANELA)
    except Exception as e:
        return False, f'teste não rodou: {e}'
    if r.returncode != 0 or 'ok' not in (r.stdout or ''):
        erro = (r.stderr or r.stdout or '').strip().splitlines()
        return False, erro[-1][:300] if erro else f'código {r.returncode}'
    return True, ''


def instalar(sessao, info):
    v = info['versao']
    VERSOES.mkdir(parents=True, exist_ok=True)
    nova = VERSOES / f'{v}.novo'
    zip_tmp = VERSOES / f'_{info["pacote"]}'
    shutil.rmtree(nova, ignore_errors=True)
    try:
        _baixar(sessao, info, zip_tmp)
        nova.mkdir()
        _extrair(zip_tmp, nova)
        if _versao_do_pacote(nova) != v:
            raise ValueError('a versão dentro do pacote não confere')
        ok, msg = testar_versao(nova)
        if not ok:
            raise RuntimeError(f'a versão {v} não carregou no teste: {msg}')
        final = VERSOES / v
        if final.exists():
            shutil.rmtree(final)
        os.replace(nova, final)
    finally:
        shutil.rmtree(nova, ignore_errors=True)
        try:
            zip_tmp.unlink()
        except OSError:
            pass
    ativa = _ler_json(ATIVA)
    anterior = ativa.get('versao') or __version__
    ativa.update({'versao': v, 'anterior': anterior if anterior != v else ativa.get('anterior'),
                  'instalada_em': time.time()})
    _gravar_json(ATIVA, ativa)
    limpar_versoes_antigas()


def limpar_versoes_antigas():
    ativa = _ler_json(ATIVA)
    manter = {ativa.get('versao'), ativa.get('anterior')}
    pastas = sorted((p for p in VERSOES.iterdir() if p.is_dir() and re.fullmatch(r'\d+\.\d+\.\d+', p.name)),
                    key=lambda p: chave_versao(p.name), reverse=True)
    for p in pastas[MANTER_VERSOES:]:
        if p.name not in manter:
            shutil.rmtree(p, ignore_errors=True)


# --------------------------------------------------------------------------- rotina
class _Trava:
    """Uma procura por vez (ex.: painel e busca automática abrindo juntos)."""

    def __init__(self):
        self.minha = False

    def __enter__(self):
        try:
            if TRAVA.exists() and time.time() - TRAVA.stat().st_mtime < 600:
                return None  # outra procura em andamento
            TRAVA.write_text(str(os.getpid()), encoding='utf-8')
            self.minha = True
            return self
        except OSError:
            return None

    def __exit__(self, *exc):
        if self.minha:
            try:
                TRAVA.unlink()
            except OSError:
                pass


def procurar_e_instalar(forcar=False):
    """Retorna o novo estado (também gravado em dados/atualizacao.json)."""
    if not pode_atualizar():
        return estado()
    anterior = _ler_json(ESTADO)
    if not forcar and time.time() - (anterior.get('verificado_em') or 0) < INTERVALO_MIN_S:
        return estado()
    with _Trava() as trava:
        if trava is None:
            return estado()
        import requests
        novo = {k: anterior.get(k) for k in ('instalada', 'notas_instalada', 'instalada_em')}
        novo['verificado_em'] = time.time()
        ativa = _ler_json(ATIVA)
        atual = ativa.get('versao') or __version__
        try:
            with requests.Session() as s:
                s.headers['User-Agent'] = f'BuscaCarro/{atual}'
                info = buscar_manifesto(s)
                if info is None:
                    novo.update(situacao='atual', mensagem='Nenhuma versão publicada ainda.')
                elif chave_versao(info['versao']) <= chave_versao(atual):
                    novo.update(situacao='atual', ultima_versao=info['versao'], mensagem='Versão mais recente.')
                elif info['versao'] in (ativa.get('ruins') or []):
                    novo.update(situacao='ignorada', ultima_versao=info['versao'],
                                mensagem=f'A versão {info["versao"]} deu problema neste computador; aguardando a próxima.')
                elif info['base_minima'] > base_instalada():
                    novo.update(situacao='precisa_instalador', ultima_versao=info['versao'], notas=info['notas'],
                                mensagem=f'A versão {info["versao"]} precisa do instalador novo.')
                    anotar(f'versão {info["versao"]} precisa do instalador novo (base {info["base_minima"]})')
                else:
                    anotar(f'baixando a versão {info["versao"]} (em uso: {atual})')
                    try:
                        instalar(s, info)
                    except Exception as e:
                        if isinstance(e, RuntimeError):  # não carregou no teste: não tenta de novo esta versão
                            a = _ler_json(ATIVA)
                            a['ruins'] = sorted(set(a.get('ruins') or []) | {info['versao']}, key=chave_versao)
                            _gravar_json(ATIVA, a)
                        raise
                    novo.update(situacao='instalada', ultima_versao=info['versao'], instalada=info['versao'],
                                notas_instalada=info['notas'], instalada_em=time.time(),
                                mensagem=f'Atualizado para a versão {info["versao"]}.')
                    anotar(f'versão {info["versao"]} instalada')
        except Exception as e:
            if isinstance(e, (requests.ConnectionError, requests.Timeout)):
                msg = 'sem conexão com a internet (ou com o GitHub)'
            else:
                msg = str(e).splitlines()[0][:200] if str(e) else type(e).__name__
            novo.update(situacao='erro', mensagem=f'Não foi possível procurar atualização: {msg}')
            anotar(f'falha ao atualizar: {type(e).__name__}: {msg}')
        _gravar_json(ESTADO, novo)
    return estado()


def main(argv=None):
    argv = list(argv or [])
    try:
        procurar_e_instalar(forcar='--forcar' in argv)
    except Exception as e:  # nunca impede o programa de abrir
        anotar(f'erro inesperado na atualização: {e}')
    return 0
