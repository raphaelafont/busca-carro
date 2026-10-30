"""Webmotors: usa a API interna de busca do próprio site, chamada de dentro da página."""
from urllib.parse import quote

from .. import progresso
from ..texto import UFS, slug

NOME = 'Webmotors'
CAMPOS_DETALHE = ('descricao', 'combustivel', 'atributos', 'publicado')  # o que vem da página de cada anúncio
CAMBIO = {'automatico': 'Automática|CVT|Automatizada|Semi-automática', 'manual': 'Manual'}


def montar_url(busca):
    """Endereço da busca sem o modelo e sem o câmbio (o modelo é resolvido no catálogo do próprio site)."""
    marca, uf = busca['marca'], busca['uf']
    local = (uf.lower() if uf else 'estoque')
    url = f'https://www.webmotors.com.br/carros/{local}/{slug(marca)}'
    p = [('tipoveiculo', 'carros')]
    if uf:
        p.append(('estadocidade', UFS[uf] + (f" - {busca['cidade']}" if busca['cidade'] else '')))
    p.append(('marca1', marca.upper()))
    if busca['ano_de']:
        p.append(('anode', str(busca['ano_de'])))
    if busca['ano_ate']:
        p.append(('anoate', str(busca['ano_ate'])))
    if busca['preco_max']:
        p.append(('precoate', str(busca['preco_max'])))
    if busca['km_max']:
        p.append(('kmate', str(busca['km_max'])))
    if busca.get('vendedor') == 'particular':
        p.append(('anunciante', 'Pessoa Física'))
    elif busca.get('vendedor') == 'loja':
        p.append(('anunciante', 'Loja|Concessionária'))
    if busca['blindado'] is True:
        p.append(('blindado', 'Com blindagem'))
    elif busca['blindado'] is False:
        p.append(('blindado', 'Sem blindagem'))
    return url + '?' + '&'.join(f'{k}={quote(v, safe="|")}' for k, v in p)


def parametro_cambio(busca):
    if busca['cambio'] in CAMBIO:
        return '&cambio=' + quote(CAMBIO[busca['cambio']], safe='|')
    return ''


def buscar(nav, busca, limites, mem=None):
    url = montar_url(busca)
    ok, motivo = nav.ir(url.split('?')[0], espera=3)
    if not ok:
        if motivo == 'BLOQUEIO':
            return {'status': 'bloqueado', 'mensagem': 'O site pediu verificação anti-robô.', 'items': []}
        return {'status': 'erro', 'mensagem': motivo, 'items': []}
    progresso.detalhe('Página de busca aberta; consultando os anúncios')
    res = nav.executar('webmotors_busca.js', {
        'baseUrl': url,
        'cambioParam': parametro_cambio(busca),
        'modelo': busca['modelo'],
        'maxPages': limites['paginas'],
        'maxItems': limites['anuncios'],
        'maxDetails': limites['anuncios'],
        'pular': mem.ids_guardados('wm-') if mem else [],
    }) or {}
    for it in res.get('items', []):
        if it.get('foto'):
            it['foto'] += '?s=fill&w=440&h=330&q=70'
        lido_agora = it.pop('_det', False)
        if not mem:
            continue
        if lido_agora:
            mem.guardar_detalhe(it['id'], {c: it.get(c) for c in CAMPOS_DETALHE})
        else:
            guardado = mem.detalhe(it['id'])
            if guardado:
                it.update({c: v for c, v in guardado.items() if v})
    return {'status': res.get('status', 'erro'), 'mensagem': res.get('erro') or '; '.join(res.get('avisos', [])),
            'items': res.get('items', []), 'total_site': res.get('total')}
