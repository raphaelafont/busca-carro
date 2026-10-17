"""Mercado Livre: lê o estado embutido na página de busca e segue os filtros do próprio site."""
from collections import OrderedDict
from datetime import date
from urllib.parse import urlparse

from .. import progresso
from ..texto import UFS, inteiro, para_uf, slug

NOME = 'Mercado Livre'


def montar_caminho(busca):
    base = f"/veiculos/carros-caminhonetes/{slug(busca['marca'])}/{slug(busca['modelo'])}"
    if busca['uf']:
        local = slug(UFS[busca['uf']])
        if busca['cidade']:
            local = slug(busca['cidade']) + '-' + local
        base += f'-em-{local}/'
    else:
        base += '/'
    suf = ''
    if busca['km_max']:
        suf += f"_KILOMETERS_*-{busca['km_max']}km"
    if busca['preco_max']:
        suf += f"_PriceRange_0-{busca['preco_max']}"
    if busca['ano_de'] or busca['ano_ate']:
        suf += f"_YearRange_{busca['ano_de'] or 1950}-{busca['ano_ate'] or date.today().year + 1}"
    return base + suf + '_NoIndex_True'


def _vendedor(tipo):
    if not tipo:
        return None
    return 'Particular' if tipo in ('normal', 'private', 'particular') else 'Loja'


def buscar(nav, busca, limites, mem=None):
    caminho = montar_caminho(busca)
    ok, motivo = nav.ir('https://lista.mercadolivre.com.br' + caminho, espera=3)
    if not ok:
        if motivo == 'BLOQUEIO':
            return {'status': 'bloqueado', 'mensagem': 'O site pediu verificação anti-robô.', 'items': []}
        return {'status': 'erro', 'mensagem': motivo, 'items': []}
    blind = 'sim' if busca['blindado'] is True else ('nao' if busca['blindado'] is False else None)
    res = nav.executar('ml_busca.js', {'basePath': caminho, 'blindado': blind, 'cambio': busca['cambio'],
                                       'maxPages': limites['paginas'], 'maxItems': limites['anuncios']}) or {}
    items = res.get('items', [])
    avisos = list(res.get('avisos', []))

    # detalhes: só dos anúncios que ainda não foram lidos em rodadas anteriores
    guardados = {it['id']: mem.detalhe(it['id']) for it in items} if mem else {}
    novos = [it for it in items if not guardados.get(it['id'])]
    por_host = OrderedDict()
    for it in novos:
        por_host.setdefault(urlparse(it['url']).netloc, []).append(it)
    detalhes = {}
    if items:
        ja = len(items) - len(novos)
        progresso.detalhe(f'{len(items)} anúncios na lista' + (f'; {ja} já lidos em rodadas anteriores' if ja else '')
                          + (f'; abrindo {len(novos)} anúncios para ler os detalhes' if novos else ''))
    for host, grupo in por_host.items():
        ok, _ = nav.ir(grupo[0]['url'], espera=2)
        if not ok:
            avisos.append(f'Sem detalhes de {host} (página bloqueada).')
            continue
        detalhes.update(nav.executar('ml_detalhes.js', {'urls': [g['url'] for g in grupo]}, orcamento_s=180) or {})
    faltaram = sum(1 for it in novos if it['id'].replace('ml-', '') not in detalhes)
    if novos and faltaram and nav.ritmo['limitacoes']:
        avisos.append(f'{faltaram} anúncios ficaram sem detalhes (o site limitou as consultas); serão lidos na próxima rodada.')

    for it in items:
        d = detalhes.get(it['id'].replace('ml-', ''))
        if d and mem:
            mem.guardar_detalhe(it['id'], d)
        d = d or guardados.get(it['id'])
        if not d:
            continue
        it['versao'] = d.get('versao') or it['versao']
        it['marca'] = d.get('marca')
        it['modelo'] = d.get('modelo')
        it['cambio'] = d.get('cambio')
        it['combustivel'] = d.get('combustivel')
        it['cor'] = d.get('cor')
        it['descricao'] = d.get('descricao') or ''
        it['vendedor'] = _vendedor(d.get('vendedor'))
        if d.get('blindado') in ('Sim', 'Não'):
            it['blindado'] = d['blindado'] == 'Sim'
        if d.get('km'):
            it['km'] = inteiro(d['km'])
        if d.get('local') and ',' in d['local']:
            cidade, estado = [x.strip() for x in d['local'].rsplit(',', 1)]
            it['cidade'] = cidade
            it['uf'] = para_uf(estado)
    return {'status': res.get('status', 'erro'), 'mensagem': res.get('erro') or '; '.join(avisos),
            'items': items, 'total_site': res.get('total')}
