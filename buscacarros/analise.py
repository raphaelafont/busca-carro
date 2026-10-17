"""Tratamento dos anúncios: filtros, alertas, destaques, FIPE e agrupamento de duplicados."""
import re

from .fipe import tokens
from .texto import (cidade_normalizada, norm, resumo, tipo_cambio, tipo_combustivel)

# ---------------------------------------------------------------- alertas
TERMOS_ALERTA = [
    (r'leil[aã]o|leiload', 'Menciona leilão'),
    (r'sinistr', 'Menciona sinistro'),
    (r'repasse', 'Carro de repasse'),
    (r'recuperad[oa] de (financiamento|roubo|furto)|recuperad[oa] (pela|por) (seguradora|financeira)', 'Recuperado de financiamento/roubo'),
    (r'indenizad', 'Indenizado por seguradora'),
    (r'perda total', 'Perda total'),
    (r'(m[eé]dia|grande|pequena) monta', 'Monta (dano estrutural)'),
    (r'remarcad', 'Chassi/motor remarcado'),
    (r'batid[oa]|colis[aã]o', 'Menciona batida'),
    (r'enchente|alagad|alagament', 'Menciona enchente'),
    (r'com apontamento|apontamentos? n[oa]', 'Laudo com apontamento'),
    (r'reprovad', 'Laudo/vistoria reprovado'),
    (r'sem documento|document(o|a[cç][aã]o) (atrasad|pendent|irregular)|busca e apreens', 'Documentação irregular'),
]
NEGACOES = re.compile(r'(sem|n[aã]o|nunca|zero|livre de|isento de|nada consta|jamais|nenhum[a]?)\W+(\w+\W+){0,3}$', re.I)


def _mencoes(texto, padrao):
    for m in re.finditer(padrao, texto, re.I):
        antes = texto[max(0, m.start() - 40):m.start()]
        if NEGACOES.search(antes):
            continue
        return True
    return False


def alertas(item, limite_abaixo_fipe=-25.0):
    res = []
    if item.get('leilao') is True:
        res.append('Passagem por leilão (informado no site)')
    texto = ' '.join([item.get('titulo') or '', item.get('descricao') or ''])
    for padrao, rotulo in TERMOS_ALERTA:
        if rotulo == 'Menciona leilão' and item.get('leilao') is True:
            continue
        if _mencoes(texto, padrao):
            res.append(rotulo)
    if item.get('dif_pct') is not None and item['dif_pct'] <= limite_abaixo_fipe:
        res.append(f"Preço {abs(item['dif_pct']):.0f}% abaixo da FIPE — confira com cuidado")
    return res


# ---------------------------------------------------------------- destaques
def destaques(item):
    t = norm(' '.join([item.get('descricao') or ''] + list(item.get('atributos') or [])))
    s = []
    if re.search(r'unico dono|1[ºo°]? dono|primeiro dono', t):
        s.append('Único dono')
    if re.search(r'ipva (\d{4} )?pago|ipva (\d{4} )?quitado|ipva \d{4} (ok|pago)', t):
        s.append('IPVA pago')
    if re.search(r'revis\w* (feitas? |realizadas? )?(\w+ ){0,3}(na |em )?(concession|autorizad)|todas as revisoes', t):
        s.append('Revisões em concessionária')
    elif re.search(r'\brevisad[oa]|revisoes em dia', t):
        s.append('Revisado')
    if re.search(r'laudo|cautelar|pericia|periciad|vistoria aprovad|vistoriad', t) and not re.search(r'reprovad|com apontamento', t):
        s.append('Laudo/cautelar')
    if re.search(r'garantia', t):
        s.append('Garantia')
    if re.search(r'chave reserva', t):
        s.append('Chave reserva')
    if item.get('blindado'):
        m = re.search(r'nivel\s*(iii\s*-?\s*a|3\s*-?\s*a|iii|ii|i|3|2|1)\b', norm(item.get('descricao') or ''))
        nivel = None
        if m:
            n = re.sub(r'[\s\-]', '', m.group(1))
            nivel = {'iiia': '3A', '3a': '3A', 'iii': '3', 'ii': '2', 'i': '1'}.get(n, n.upper())
        s.append('Blindado' + (f' nível {nivel}' if nivel else ''))
    if 'aceita troca' in t:
        s.append('Aceita troca')
    return s


# ---------------------------------------------------------------- normalização por site
def completar(item):
    """Campos derivados comuns a todos os sites."""
    item['cambio_tipo'] = tipo_cambio(item.get('cambio')) or tipo_cambio(item.get('versao')) or tipo_cambio(item.get('titulo'))
    item['combustivel_tipo'] = tipo_combustivel(item.get('combustivel')) or tipo_combustivel(item.get('versao'))
    texto = norm(' '.join([item.get('titulo') or '', item.get('descricao') or '']))
    if item.get('blindado') is None:
        if re.search(r'blindad|blindagem', texto) and not re.search(r'(nao|sem)\s+(e\s+)?blindad', texto):
            item['blindado'] = True
    cidade = (item.get('cidade') or '').strip()
    if ' - ' in cidade:  # "Bairro - Cidade" (lista do Mercado Livre)
        cidade = cidade.rsplit(' - ', 1)[1]
    cidade = re.sub(r'\s+(zona\s+(norte|sul|leste|oeste|central)|centro)$', '', cidade, flags=re.I)
    item['cidade'] = cidade or None
    item['cidade_norm'] = cidade_normalizada(cidade)
    item['descricao_curta'] = resumo(item.get('descricao') or '')
    return item


# ---------------------------------------------------------------- filtros pós-coleta
def passa_filtros(item, busca):
    am = item.get('ano_modelo')
    if busca['ano_de'] and am and am < busca['ano_de']:
        return False
    if busca['ano_ate'] and am and am > busca['ano_ate']:
        return False
    if busca['km_max'] and item.get('km') is not None and item['km'] > busca['km_max']:
        return False
    if busca['preco_max'] and item.get('preco') and item['preco'] > busca['preco_max']:
        return False
    if not item.get('preco'):
        return False
    if busca['cambio'] and item.get('cambio_tipo') and item['cambio_tipo'] != busca['cambio']:
        return False
    if busca['combustivel'] and item.get('combustivel_tipo') and item['combustivel_tipo'] != busca['combustivel']:
        return False
    if busca['blindado'] is True and item.get('blindado') is not True:
        return False
    if busca['blindado'] is False and item.get('blindado') is True:
        return False
    if busca['uf'] and item.get('uf') and item['uf'] != busca['uf']:
        return False
    if busca['cidade'] and item.get('cidade_norm') and item['cidade_norm'] != cidade_normalizada(busca['cidade']):
        return False
    if busca['versao']:
        ign = tokens(busca['marca']) | tokens(busca['modelo'])
        pedido = tokens(busca['versao'], ign)
        tem = tokens(' '.join([item.get('versao') or '', item.get('titulo') or '']), ign)
        if pedido and not pedido <= tem:
            return False
    if item.get('modelo'):
        mod = re.sub(r'[\-/]', ' ', norm(item['modelo']))
        alvo = re.sub(r'[\-/]', ' ', norm(busca['modelo']))
        if not (mod == alvo or mod.startswith(alvo + ' ')):
            return False
    else:
        # sem o campo modelo (OLX, parte do Mercado Livre): o modelo pedido tem de aparecer no título/versão
        pedido = _palavras(busca['modelo']) - _palavras(busca['marca'])
        texto = _palavras(' '.join([item.get('titulo') or '', item.get('versao') or '']))
        if pedido and not pedido <= texto:
            return False
    return True


def _palavras(t):
    return set(re.findall(r'[a-z0-9]+', norm(t)))


# ---------------------------------------------------------------- FIPE
def aplicar_fipe(item, fipe, busca):
    res = None
    if fipe is not None:
        try:
            res = fipe.avaliar(busca['marca'], busca['modelo'], item.get('versao') or item.get('titulo'),
                               item.get('ano_modelo'), item.get('cambio_tipo'))
        except Exception:
            res = None
    if res is None and item.get('fipe_site'):
        exata = item.get('fipe_site_tipo') != 'estimada'
        res = {'valor': item['fipe_site'], 'min': item['fipe_site'], 'max': item['fipe_site'], 'exata': exata,
               'modelo': 'informada pelo ' + item['site'] if exata else 'estimada pelo ' + item['site'],
               'codigo': None, 'referencia': None, 'fonte': item['site']}
    item['fipe'] = res
    if res and item.get('preco'):
        item['dif_rs'] = round(item['preco'] - res['valor'])
        item['dif_pct'] = round((item['preco'] - res['valor']) / res['valor'] * 100, 1)
    else:
        item['dif_rs'] = None
        item['dif_pct'] = None
    return item


# ---------------------------------------------------------------- duplicados
def _texto_compacto(t):
    return re.sub(r'[^a-z0-9]', '', norm(t))


def _descricoes_iguais(a, b):
    """Mesma descrição (ou uma contém o começo da outra), comum quando a loja anuncia em vários sites."""
    ta, tb = _texto_compacto(a.get('descricao')), _texto_compacto(b.get('descricao'))
    if len(ta) < 50 or len(tb) < 50:
        return False
    for x, y in ((ta, tb), (tb, ta)):
        for ini in (0, 10, 20):
            trecho = x[ini:ini + 50]
            if len(trecho) == 50 and trecho in y:
                return True
    return False


def _mesmo_carro(a, b, ignorar):
    if a.get('ano_modelo') != b.get('ano_modelo') or not a.get('ano_modelo'):
        return False
    ka, kb = a.get('km'), b.get('km')
    if ka is None or kb is None or not a.get('preco') or not b.get('preco'):
        return False
    if abs(ka - kb) > max(1500, 0.03 * max(ka, kb)):
        return False
    # Mesma descrição + mesmo ano + km parecido: mesmo carro, mesmo com preço diferente em cada site
    if _descricoes_iguais(a, b):
        return True
    if abs(ka - kb) > max(1500, 0.02 * max(ka, kb)):
        return False
    if abs(a['preco'] - b['preco']) > 0.03 * max(a['preco'], b['preco']):
        return False
    ta = tokens(a.get('versao') or a.get('titulo') or '', ignorar)
    tb = tokens(b.get('versao') or b.get('titulo') or '', ignorar)
    alfa_a = {t for t in ta if re.search(r'[a-z]', t)}
    alfa_b = {t for t in tb if re.search(r'[a-z]', t)}
    if alfa_a and alfa_b and not (alfa_a & alfa_b):
        return False
    ca, cb = a.get('cidade_norm'), b.get('cidade_norm')
    if ca and cb and ca != cb:
        return False
    return True


def agrupar(itens, ignorar=frozenset()):
    """Junta o mesmo carro anunciado em sites diferentes. Retorna lista de carros."""
    pai = list(range(len(itens)))

    def raiz(i):
        while pai[i] != i:
            pai[i] = pai[pai[i]]
            i = pai[i]
        return i

    for i in range(len(itens)):
        for j in range(i + 1, len(itens)):
            if _mesmo_carro(itens[i], itens[j], ignorar):
                pai[raiz(i)] = raiz(j)
    grupos = {}
    for i, it in enumerate(itens):
        grupos.setdefault(raiz(i), []).append(it)

    carros = []
    for g in grupos.values():
        g.sort(key=lambda x: (x.get('preco') or 9e12, 0 if x.get('descricao') else 1))
        base = dict(g[0])
        if not base.get('descricao_curta'):
            outro = next((x for x in g if x.get('descricao_curta')), None)
            if outro:
                base['descricao_curta'] = outro['descricao_curta']
                base['descricao'] = outro['descricao']
        if not base.get('foto'):
            base['foto'] = next((x['foto'] for x in g if x.get('foto')), None)
        if not base.get('fipe') or not base['fipe'].get('exata'):
            melhor = next((x for x in g if x.get('fipe') and x['fipe'].get('exata')), None)
            if melhor:
                base['fipe'] = melhor['fipe']
                base['dif_rs'] = round(base['preco'] - melhor['fipe']['valor'])
                base['dif_pct'] = round((base['preco'] - melhor['fipe']['valor']) / melhor['fipe']['valor'] * 100, 1)
        base['links'] = [{'site': x['site'], 'url': x['url'], 'preco': x.get('preco'), 'km': x.get('km')} for x in g]
        sel, al = [], []
        for x in g:
            for s in x.get('selos', []):
                if s not in sel:
                    sel.append(s)
            for a in x.get('alertas', []):
                if a not in al:
                    al.append(a)
        if 'Revisões em concessionária' in sel and 'Revisado' in sel:
            sel.remove('Revisado')
        blind = [s for s in sel if s.startswith('Blindado')]
        if len(blind) > 1:  # mantém só o selo de blindagem mais detalhado
            mais = max(blind, key=len)
            sel = [s for s in sel if not s.startswith('Blindado') or s == mais]
        base['selos'] = sel
        base['alertas'] = al
        base['vendedor'] = next((x['vendedor'] for x in g if x.get('vendedor')), None)
        carros.append(base)
    return carros
