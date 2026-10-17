"""Iniciador do Busca Carro (fica na pasta da instalação e não é trocado pelas atualizações).

Uso:  pythonw iniciar.py painel [--sem-navegador]
      pythonw iniciar.py busca [opções da busca, ex.: --forcar]
      pythonw iniciar.py atualizar

- O programa fica em versoes/<versão>/buscacarros; versoes/ativa.json diz qual versão usar.
- Antes de abrir o painel ou a busca, procura uma versão nova na internet (num processo separado e com
  tempo limite: sem internet, ou se algo der errado, segue com a versão instalada).
- Se a versão ativa nem carregar, volta sozinho para a anterior.
"""
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
VERSOES = RAIZ / 'versoes'
ATIVA = VERSOES / 'ativa.json'
LOG = RAIZ / 'logs' / 'atualizacao.log'
MODOS = ('painel', 'busca', 'atualizar')
SEM_JANELA = 0x08000000 if sys.platform == 'win32' else 0  # CREATE_NO_WINDOW


def anotar(texto):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(f'{datetime.now():%d/%m/%Y %H:%M:%S} {texto}\n')
    except OSError:
        pass


def chave_versao(v):
    return tuple(int(x) for x in re.findall(r'\d+', v or '0'))


def ler_ativa():
    try:
        d = json.loads(ATIVA.read_text(encoding='utf-8'))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def gravar_ativa(d):
    tmp = ATIVA.with_name('ativa.json.tmp')
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding='utf-8')
    os.replace(tmp, ATIVA)


def instalada(v):
    return bool(v) and (VERSOES / v / 'buscacarros' / '__init__.py').is_file()


def escolher():
    """(versão, pasta que contém o pacote buscacarros)."""
    d = ler_ativa()
    for v in (d.get('versao'), d.get('anterior')):
        if instalada(v):
            return v, VERSOES / v
    if VERSOES.is_dir():
        candidatas = sorted((p.name for p in VERSOES.iterdir() if instalada(p.name)), key=chave_versao, reverse=True)
        if candidatas:
            return candidatas[0], VERSOES / candidatas[0]
    if (RAIZ / 'buscacarros' / '__init__.py').is_file():  # instalação antiga ou pasta de desenvolvimento
        return None, RAIZ
    raise SystemExit('Busca Carro: programa não encontrado nesta pasta. Rode o instalador de novo.')


def voltar_para_anterior(ruim, erro):
    d = ler_ativa()
    if d.get('versao') != ruim or not instalada(d.get('anterior')):
        return False
    d['ruins'] = sorted(set(d.get('ruins') or []) | {ruim}, key=chave_versao)
    d['versao'], d['anterior'] = d['anterior'], None
    d['voltou_de'] = {'versao': ruim, 'quando': time.time(), 'erro': erro[:300]}
    gravar_ativa(d)
    anotar(f'versão {ruim} não abriu ({erro[:200]}); voltando para {d["versao"]}')
    return True


def procurar_atualizacao():
    """Roda 'iniciar.py atualizar' num processo separado, com tempo limite."""
    if os.environ.get('BUSCACARRO_SEM_ATUALIZAR') == '1' or not VERSOES.is_dir():
        return
    try:
        subprocess.run([sys.executable, str(Path(__file__).resolve()), 'atualizar'], cwd=str(RAIZ),
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=150, creationflags=SEM_JANELA)
    except Exception as e:  # sem atualização desta vez; o programa abre do mesmo jeito
        anotar(f'procura de atualização interrompida: {e}')


def main(argv):
    modo = argv[0] if argv and argv[0] in MODOS else 'painel'
    resto = argv[1:] if argv and argv[0] in MODOS else argv
    os.environ['BUSCACARRO_RAIZ'] = str(RAIZ)
    if modo in ('painel', 'busca'):
        procurar_atualizacao()
    versao, pasta = escolher()
    sys.path.insert(0, str(pasta))
    try:
        if modo == 'painel':
            from buscacarros import painel as alvo
        elif modo == 'busca':
            from buscacarros import principal as alvo
        else:
            from buscacarros import atualizador as alvo
    except Exception as e:
        # a versão ativa não carrega: volta para a anterior e reabre num processo novo (sem misturar módulos)
        if versao and voltar_para_anterior(versao, f'{type(e).__name__}: {e}'):
            env = dict(os.environ, BUSCACARRO_SEM_ATUALIZAR='1')
            return subprocess.call([sys.executable, str(Path(__file__).resolve()), modo] + resto, cwd=str(RAIZ),
                                   env=env, creationflags=SEM_JANELA)
        anotar(f'o programa não abriu: {type(e).__name__}: {e}')
        raise
    if modo == 'painel':
        return alvo.main('--sem-navegador' not in resto)
    return alvo.main(resto)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
