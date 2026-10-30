"""Histórico de buscas: um registro por relatório gerado (dados/historico.json), para o painel listar as
buscas anteriores e abrir o relatório de cada uma. Só ficam os registros cujo relatório ainda existe
(o programa guarda os 30 relatórios mais recentes). Relatórios de antes do histórico entram pelo que
está gravado dentro do próprio arquivo."""
import json
import re
from datetime import datetime
from pathlib import Path

NOME_RELATORIO = re.compile(r'^relatorio_(\d{4})-(\d\d)-(\d\d)_(\d\d)(\d\d)\.html$')
MAXIMO = 200


def _arquivo(dados_dir):
    return Path(dados_dir) / 'historico.json'


def _ler(dados_dir):
    try:
        lista = json.loads(_arquivo(dados_dir).read_text(encoding='utf-8'))
        return lista if isinstance(lista, list) else []
    except (OSError, ValueError):
        return []


def _gravar(dados_dir, lista):
    arq = _arquivo(dados_dir)
    tmp = arq.with_suffix('.tmp')
    tmp.write_text(json.dumps(lista[:MAXIMO], ensure_ascii=False, indent=1), encoding='utf-8')
    tmp.replace(arq)


def _resumo_busca(b):
    return {'titulo': b.get('titulo') or b.get('rotulo') or '', 'detalhes': b.get('detalhes') or ''}


def registrar(resultados_dir, dados_dir, destino, buscas, dados, resumo):
    """Anota a busca que acabou de gerar o relatório `destino`."""
    try:
        lista = [r for r in _ler(dados_dir) if r.get('arquivo') != destino.name]
        lista.insert(0, {
            'arquivo': destino.name,
            'fim': datetime.now().isoformat(timespec='seconds'),
            'buscas': [_resumo_busca(b) for b in buscas],
            'carros': resumo.get('carros', 0),
            'abaixo_fipe': resumo.get('abaixo_fipe', 0),
            'parcial': bool(resumo.get('parcial')),
            'origem': resumo.get('origem'),
            'duracao_s': resumo.get('duracao_s'),
            'sites': [{'site': s['site'], 'status': s['status'], 'qtd': s['qtd']} for s in dados.get('status', [])],
        })
        _gravar(dados_dir, lista)
    except OSError:
        pass  # o histórico nunca impede o relatório


def _do_relatorio(caminho):
    """Registro reconstruído a partir de um relatório antigo (os dados vão gravados dentro dele)."""
    m = NOME_RELATORIO.match(caminho.name)
    if not m:
        return None
    fim = datetime(*map(int, m.groups())).isoformat(timespec='seconds')
    reg = {'arquivo': caminho.name, 'fim': fim, 'buscas': [], 'carros': None, 'abaixo_fipe': None,
           'parcial': False, 'origem': None, 'sites': []}
    try:
        html = caminho.read_text(encoding='utf-8')
        i = html.index('const DADOS = ') + len('const DADOS = ')
        dados, _ = json.JSONDecoder().raw_decode(html, i)
        reg['buscas'] = [{'titulo': '', 'detalhes': b.get('rotulo') or ''} for b in dados.get('buscas', [])]
        carros = dados.get('carros') or []
        reg['carros'] = len(carros)
        reg['abaixo_fipe'] = sum(1 for c in carros if c.get('dif_pct') is not None and c['dif_pct'] < 0)
        por_site = {}
        for s in dados.get('status', []):
            p = por_site.setdefault(s['site'], {'site': s['site'], 'status': s['status'], 'qtd': 0})
            p['qtd'] += s.get('qtd') or 0
            if s['status'] == 'ok':
                p['status'] = 'ok'
        reg['sites'] = list(por_site.values())
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return reg


def listar(resultados_dir, dados_dir):
    """Buscas anteriores, da mais recente para a mais antiga, só com relatórios que ainda existem."""
    resultados_dir = Path(resultados_dir)
    lista = _ler(dados_dir)
    existentes = {p.name: p for p in resultados_dir.glob('relatorio_*.html') if NOME_RELATORIO.match(p.name)}
    validos = [r for r in lista if r.get('arquivo') in existentes]
    conhecidos = {r['arquivo'] for r in validos}
    novos = [_do_relatorio(p) for n, p in existentes.items() if n not in conhecidos]
    validos += [r for r in novos if r]
    validos.sort(key=lambda r: r.get('fim') or '', reverse=True)
    if validos != lista:
        try:
            _gravar(dados_dir, validos)
        except OSError:
            pass
    return validos


def caminho_relatorio(resultados_dir, nome):
    """Arquivo de um relatório pelo nome, só se for mesmo um relatório desta pasta."""
    if not NOME_RELATORIO.match(nome or ''):
        return None
    p = Path(resultados_dir) / nome
    return p if p.is_file() else None
