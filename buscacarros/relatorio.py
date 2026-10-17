"""Geração do relatório HTML."""
import json
import re
from pathlib import Path

from .texto import norm

MODELO = Path(__file__).parent / 'modelos' / 'relatorio.html'
CURTOS = {'flex', 'gnv'}


def _parte(p):
    if not p:
        return p
    if re.search(r'\d', p) or (len(p) <= 3 and p.isalpha() and p.lower() not in CURTOS):
        return p.upper()
    return p[:1].upper() + p[1:].lower()


def _palavra(p):
    return '/'.join(_parte(x) for x in p.split('/'))


def titulo_exibicao(item, busca):
    versao = item.get('versao') or item.get('titulo') or ''
    # tira marca, modelo e ano repetidos no começo da versão
    ign = [norm(busca['marca']), norm(busca['modelo'])]
    partes = versao.split()
    while partes and (norm(partes[0]) in ign or re.fullmatch(r'(19|20)\d\d', partes[0])):
        partes.pop(0)
    versao = ' '.join(_palavra(p) for p in partes)
    return f"{busca['marca'].title() if busca['marca'].isupper() or busca['marca'].islower() else busca['marca']} " \
           f"{busca['modelo'].title() if busca['modelo'].isupper() or busca['modelo'].islower() else busca['modelo']} {versao}".strip()


def para_exibicao(c, busca):
    return {
        'id': c['id'],
        'busca_id': busca['id'],
        'titulo_exibicao': titulo_exibicao(c, busca),
        'versao': c.get('versao'),
        'ano_fab': c.get('ano_fab'),
        'ano_modelo': c.get('ano_modelo'),
        'km': c.get('km'),
        'preco': c.get('preco'),
        'fipe': c.get('fipe'),
        'dif_rs': c.get('dif_rs'),
        'dif_pct': c.get('dif_pct'),
        'cidade': c.get('cidade'),
        'uf': c.get('uf'),
        'foto': c.get('foto'),
        'descricao': c.get('descricao_curta'),
        'selos': c.get('selos', []),
        'alertas': c.get('alertas', []),
        'vendedor': c.get('vendedor'),
        'cambio': c.get('cambio'),
        'cor': c.get('cor'),
        'links': c.get('links', []),
    }


def gerar(dados, destino: Path):
    js = json.dumps(dados, ensure_ascii=False).replace('</', '<\\/')
    html = MODELO.read_text(encoding='utf-8').replace('/*__DADOS__*/null', js)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(html, encoding='utf-8')
    return destino
