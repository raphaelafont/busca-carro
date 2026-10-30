"""OLX: lê os dados que a própria página de busca traz embutidos; a descrição vem da página de cada anúncio."""
from collections import OrderedDict
from urllib.parse import urlparse

from .. import progresso
from ..texto import slug

NOME = 'OLX'


def montar_caminho(busca):
    """(caminho da marca, sufixo de região, parâmetros). O modelo entra entre a marca e a região."""
    marca = f"/autos-e-pecas/carros-vans-e-utilitarios/{slug(busca['marca'])}"
    sufixo = f"/estado-{busca['uf'].lower()}" if busca['uf'] else ''
    p = []
    if busca['ano_de']:
        p.append(('rs', busca['ano_de']))
    if busca['ano_ate']:
        p.append(('re', busca['ano_ate']))
    if busca['cambio'] == 'automatico':
        p += [('gb', 2), ('gb', 3), ('gb', 4)]
    elif busca['cambio'] == 'manual':
        p.append(('gb', 1))
    if busca['blindado'] is True:
        p.append(('cf', 10))
    if busca['preco_max']:
        p.append(('pe', busca['preco_max']))
    if busca['km_max']:
        p.append(('me', busca['km_max']))
    if busca.get('vendedor') == 'particular':
        p.append(('f', 'p'))
    elif busca.get('vendedor') == 'loja':
        p.append(('f', 'c'))
    return marca, sufixo, ('?' + '&'.join(f'{k}={v}' for k, v in p) if p else '')


def buscar(nav, busca, limites, mem=None):
    marca, sufixo, query = montar_caminho(busca)
    ok, motivo = nav.ir('https://www.olx.com.br' + marca + sufixo, espera=3)
    if not ok:
        if motivo == 'BLOQUEIO':
            return {'status': 'bloqueado', 'mensagem': 'O site pediu verificação anti-robô.', 'items': []}
        return {'status': 'erro', 'mensagem': motivo, 'items': []}
    res = nav.executar('olx_busca.js', {'marcaPath': marca, 'modeloSlug': slug(busca['modelo']),
                                        'modeloTexto': busca['modelo'], 'sufixo': sufixo, 'query': query,
                                        'maxPages': limites['paginas'], 'maxItems': limites['anuncios']}) or {}
    items = res.get('items', [])
    avisos = list(res.get('avisos', []))

    # descrição e FIPE informada pela OLX: abre um anúncio de cada domínio e lê os demais dali
    # (só os anúncios que ainda não foram lidos em rodadas anteriores)
    guardados = {it['id']: mem.detalhe(it['id']) for it in items} if mem else {}
    novos = [it for it in items if not guardados.get(it['id'])]
    por_host = OrderedDict()
    for it in novos:
        por_host.setdefault(urlparse(it['url']).netloc, []).append(it)
    detalhes = {}
    if items:
        ja = len(items) - len(novos)
        progresso.detalhe(f'{len(items)} anúncios na lista' + (f'; {ja} descrições já lidas em rodadas anteriores' if ja else '')
                          + (f'; abrindo {len(novos)} anúncios para ler as descrições' if novos else ''))
    for host, grupo in por_host.items():
        ok, _ = nav.ir(grupo[0]['url'], espera=2)
        if not ok:
            avisos.append(f'Sem descrições de {host} (página bloqueada).')
            continue
        detalhes.update(nav.executar('olx_detalhes.js', {'urls': [g['url'] for g in grupo]}, orcamento_s=180) or {})
    faltaram = sum(1 for it in novos if it['id'].replace('olx-', '') not in detalhes)
    if novos and faltaram and nav.ritmo['limitacoes']:
        avisos.append(f'{faltaram} anúncios ficaram sem descrição (o site limitou as consultas); serão lidos na próxima rodada.')
    for it in items:
        if it.get('foto') and 'img.olx.com.br/images/' in it['foto']:  # miniatura em vez da foto em tamanho cheio
            it['foto'] = it['foto'].replace('/images/', '/thumbs500x360/')
        d = detalhes.get(it['id'].replace('olx-', ''))
        if d and mem:
            mem.guardar_detalhe(it['id'], d)
        d = d or guardados.get(it['id'])
        if d:
            it['descricao'] = d.get('descricao') or ''
            if d.get('fipe'):
                it['fipe_site'] = d['fipe']
                it['fipe_site_tipo'] = 'informada'
    return {'status': res.get('status', 'erro'), 'mensagem': res.get('erro') or '; '.join(avisos),
            'items': items, 'total_site': res.get('total')}
