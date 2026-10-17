"""Eventos de progresso de uma rodada, gravados em dados/progresso.jsonl para o painel acompanhar ao vivo.

Cada linha é um JSON com 'tipo':
  inicio   {rodada, origem, buscas, sites, etapas}
  etapa    {msg, chave}            começa uma etapa (ex.: um site de uma busca)
  detalhe  {msg, chave}            andamento dentro da etapa (página lida, descrições...)
  site     {busca, site, status, qtd, msg, chave}   etapa de site concluída
  log      {nivel, msg}
  fim      {status, resumo...}
"""
import json
import logging
import re
import threading
import time
import uuid
from pathlib import Path

_lock = threading.Lock()
_arq = None
_rodada = None
_chave = None
_ultimo_detalhe = 0.0


def iniciar(arquivo: Path, **dados):
    global _arq, _rodada
    _arq = Path(arquivo)
    _arq.parent.mkdir(parents=True, exist_ok=True)
    _rodada = uuid.uuid4().hex[:10]
    _arq.write_text('', encoding='utf-8')
    evento('inicio', rodada=_rodada, **dados)
    return _rodada


def evento(tipo, **dados):
    if _arq is None:
        return
    linha = json.dumps({'tipo': tipo, 'ts': round(time.time(), 2), 'rodada': _rodada, **dados}, ensure_ascii=False)
    with _lock:
        try:
            with open(_arq, 'a', encoding='utf-8') as f:
                f.write(linha + '\n')
        except OSError:
            pass


def etapa(msg, chave=None):
    global _chave
    _chave = chave
    evento('etapa', msg=msg, chave=chave)
    logging.getLogger('buscacarros').info(msg)


def detalhe(msg):
    """Andamento fino (chamado inclusive de dentro das páginas). Contadores ficam limitados a ~3 por segundo."""
    global _ultimo_detalhe
    agora = time.time()
    m = re.search(r'(\d+) de (\d+)$', str(msg))
    contador = bool(m)
    if contador and m.group(1) != m.group(2) and m.group(1) != '0' and agora - _ultimo_detalhe < 0.35:
        return
    _ultimo_detalhe = agora
    evento('detalhe', msg=str(msg)[:300], chave=_chave)
    logging.getLogger('buscacarros.detalhe').info('   %s', msg)


def site(busca, site, status, qtd, msg, chave=None):
    evento('site', busca=busca, site=site, status=status, qtd=qtd, msg=msg, chave=chave or _chave)


def fim(status, **resumo):
    evento('fim', status=status, **resumo)


class Manipulador(logging.Handler):
    """Envia avisos e erros do log para o painel."""

    def emit(self, record):
        if record.name.startswith('buscacarros.detalhe'):
            return
        if record.levelno >= logging.WARNING:
            evento('log', nivel=record.levelname.lower(), msg=record.getMessage())


def ler(arquivo: Path, desde=0):
    """Lê eventos a partir de um deslocamento em bytes. Retorna (eventos, novo_deslocamento, rodada)."""
    arquivo = Path(arquivo)
    if not arquivo.exists():
        return [], 0, None
    with open(arquivo, 'rb') as f:
        primeira = f.readline()
        try:
            rodada = json.loads(primeira).get('rodada')
        except Exception:
            rodada = None
        tamanho = f.seek(0, 2)
        if desde > tamanho:
            desde = 0
        f.seek(desde)
        bruto = f.read()
    # só linhas completas
    corte = bruto.rfind(b'\n') + 1
    eventos = []
    for linha in bruto[:corte].splitlines():
        try:
            eventos.append(json.loads(linha))
        except Exception:
            pass
    return eventos, desde + corte, rodada
