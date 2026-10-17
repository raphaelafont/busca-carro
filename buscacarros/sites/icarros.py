"""iCarros: em out/2026 o site desativou a busca de classificados (só catálogo, FIPE e notícias).
Este módulo apenas verifica se a busca voltou, para avisar no relatório."""
from .. import progresso
from ..texto import slug

NOME = 'iCarros'
CAPITAIS = {'AC': 'Rio Branco', 'AL': 'Maceió', 'AP': 'Macapá', 'AM': 'Manaus', 'BA': 'Salvador', 'CE': 'Fortaleza',
            'DF': 'Brasília', 'ES': 'Vitória', 'GO': 'Goiânia', 'MA': 'São Luís', 'MT': 'Cuiabá',
            'MS': 'Campo Grande', 'MG': 'Belo Horizonte', 'PA': 'Belém', 'PB': 'João Pessoa', 'PR': 'Curitiba',
            'PE': 'Recife', 'PI': 'Teresina', 'RJ': 'Rio de Janeiro', 'RN': 'Natal', 'RS': 'Porto Alegre',
            'RO': 'Porto Velho', 'RR': 'Boa Vista', 'SC': 'Florianópolis', 'SP': 'São Paulo', 'SE': 'Aracaju',
            'TO': 'Palmas'}


def buscar(nav, busca, limites, mem=None):
    uf = busca['uf'] or 'SP'
    cidade = busca['cidade'] or CAPITAIS.get(uf, 'São Paulo')
    url = f"https://www.icarros.com.br/comprar/{slug(cidade)}-{uf.lower()}/{slug(busca['marca'])}/{slug(busca['modelo'])}"
    progresso.detalhe('Conferindo se a busca do iCarros voltou a funcionar')
    ok, motivo = nav.ir(url, espera=2)
    if not ok and motivo != 'BLOQUEIO':
        return {'status': 'erro', 'mensagem': motivo, 'items': []}
    if '/catalogo' in nav.url_atual():
        return {'status': 'indisponivel', 'mensagem': 'busca de anúncios desativada pelo próprio site (só catálogo e FIPE). O programa confere a cada rodada se ela voltou.', 'items': []}
    return {'status': 'erro', 'mensagem': 'A busca do iCarros voltou a funcionar, mas o leitor deste site ainda precisa ser adaptado.', 'items': []}
