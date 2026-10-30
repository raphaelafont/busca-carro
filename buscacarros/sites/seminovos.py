"""Seminovos BH (seminovos.com.br): lê as páginas de busca do próprio site; a descrição e os acessórios
(onde aparece a blindagem) vêm da página de cada anúncio. O site é quase todo de Minas Gerais."""
from .. import progresso
from ..texto import slug

NOME = 'Seminovos BH'
CAMPOS_DETALHE = ('descricao', 'atributos', 'blindado')
ACESSORIO_BLINDADO = 10


def montar_filtros(busca):
    """Filtros no formato do endereço do site. O câmbio fica de fora de propósito: o filtro do site é um
    "acessório" que nem todo anúncio com CVT marca; ele é aplicado depois, pelo câmbio de cada anúncio."""
    f = ''
    if busca['ano_de'] or busca['ano_ate']:
        f += f"/ano-{busca['ano_de'] or ''}-{busca['ano_ate'] or ''}"
    if busca['preco_max']:
        f += f"/preco--{busca['preco_max']}"
    if busca['km_max']:
        f += f"/km--{busca['km_max']}"
    if busca.get('vendedor') == 'particular':
        f += '/origem-particular'
    elif busca.get('vendedor') == 'loja':
        f += '/origem-revenda'
    if busca['blindado'] is True:
        f += f'/listaAcessorios[]-{ACESSORIO_BLINDADO}'
    return f


def buscar(nav, busca, limites, mem=None):
    marca_modelo = f"/carro/{slug(busca['marca'])}/{slug(busca['modelo'])}"
    ok, motivo = nav.ir('https://seminovos.com.br' + marca_modelo, espera=2)
    if not ok:
        if motivo == 'BLOQUEIO':
            return {'status': 'bloqueado', 'mensagem': 'O site pediu verificação anti-robô.', 'items': []}
        return {'status': 'erro', 'mensagem': motivo, 'items': []}
    progresso.detalhe('Página de busca aberta; consultando os anúncios')
    res = nav.executar('seminovos_busca.js', {
        'marcaModelo': marca_modelo,
        'filtros': montar_filtros(busca),
        'cidade': busca['cidade'],
        'uf': busca['uf'],
        'maxPages': limites['paginas'],
        'maxItems': limites['anuncios'],
        'maxDetails': limites['anuncios'],
        'pular': mem.ids_guardados('sbh-') if mem else [],
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
                it.update({c: v for c, v in guardado.items() if v})
    avisos = list(res.get('avisos', []))
    if busca['uf'] and busca['uf'] != 'MG' and not items:
        avisos.append('o Seminovos BH tem quase só anúncios de Minas Gerais')
    return {'status': res.get('status', 'erro'), 'mensagem': res.get('erro') or '; '.join(avisos),
            'items': items, 'total_site': res.get('total')}
