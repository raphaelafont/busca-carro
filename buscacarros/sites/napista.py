"""NaPista: busca em linguagem natural no próprio endereço do site; a descrição, o câmbio e a blindagem vêm da
página de cada anúncio. No NaPista só anunciam lojas: com o filtro "só particulares", o site fica de fora."""
from .. import progresso
from ..texto import slug

NOME = 'NaPista'
CAMPOS_DETALHE = ('descricao', 'blindado', 'cambio', 'combustivel', 'cor', 'fipe_site', 'fipe_site_tipo')


def montar_termos(busca):
    """Ex.: honda-fit-automatico-a-partir-de-2015-ate-2018-ate-100000-km-em-campinas-sp.
    A versão e o preço máximo ficam de fora (o site não os entende bem); eles são aplicados depois."""
    t = [busca['marca'], busca['modelo']]
    if busca['cambio'] == 'automatico':
        t.append('automatico')
    elif busca['cambio'] == 'manual':
        t.append('manual')
    if busca['blindado'] is True:
        t.append('blindado')
    if busca['ano_de']:
        t.append(f"a partir de {busca['ano_de']}")
    if busca['ano_ate']:
        t.append(f"ate {busca['ano_ate']}")
    if busca['km_max']:
        t.append(f"ate {busca['km_max']} km")
    if busca['uf']:
        t.append(f"em {busca['cidade']} {busca['uf']}" if busca['cidade'] else f"em {busca['uf']}")
    return slug(' '.join(str(x) for x in t))


def buscar(nav, busca, limites, mem=None):
    if busca.get('vendedor') == 'particular':
        return {'status': 'ok', 'mensagem': 'o NaPista só tem anúncios de lojas', 'items': []}
    termos = montar_termos(busca)
    ok, motivo = nav.ir('https://napista.com.br/busca/' + termos, espera=2)
    if not ok:
        if motivo == 'BLOQUEIO':
            return {'status': 'bloqueado', 'mensagem': 'O site pediu verificação anti-robô.', 'items': []}
        return {'status': 'erro', 'mensagem': motivo, 'items': []}
    progresso.detalhe('Página de busca aberta; consultando os anúncios')
    res = nav.executar('napista_busca.js', {
        'termos': termos,
        'maxPages': limites['paginas'],
        'maxItems': limites['anuncios'],
        'maxDetails': limites['anuncios'],
        'pular': mem.ids_guardados('np-') if mem else [],
    }) or {}
    items = res.get('items', [])
    for it in items:
        lido_agora = it.pop('_det', False)
        if not mem:
            continue
        if lido_agora:
            mem.guardar_detalhe(it['id'], {c: it.get(c) for c in CAMPOS_DETALHE})
        else:
            guardado = mem.detalhe(it['id'])
            if guardado:
                it.update({c: v for c, v in guardado.items() if v is not None and v != ''})
    return {'status': res.get('status', 'erro'), 'mensagem': res.get('erro') or '; '.join(res.get('avisos', [])),
            'items': items, 'total_site': res.get('total')}
