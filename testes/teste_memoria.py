"""Memória de anúncios, reaproveitamento de leituras e ritmo entre rodadas (sem internet)."""
import json, sys, time, types, tempfile, shutil
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import buscacarros.principal as P
import buscacarros.navegador as N
import buscacarros.sites as S
from buscacarros.memoria import Memoria
from buscacarros.sites import webmotors, olx, mercadolivre

tmp = Path(tempfile.mkdtemp())
P.DADOS = tmp
P.time.sleep = lambda s: print(f'   (sleep {s}s simulado)')

# ---------- 1. Memoria básica
relogio = [1_000_000.0]
m = Memoria(tmp, 120, agora=lambda: relogio[0])
busca = {'id': 'b1', 'titulo': 'GWM Ora', 'marca': 'GWM', 'modelo': 'Ora', 'versao': None, 'ano_de': None, 'ano_ate': None,
         'km_max': None, 'uf': 'SP', 'cidade': None, 'preco_max': None, 'cambio': None, 'combustivel': None, 'blindado': None}
m.guardar_detalhe('wm-1', {'descricao': 'abc'})
m.guardar_leitura('Webmotors', busca, {'status': 'ok', 'items': [{'id': 'wm-1'}], 'mensagem': ''})
m.guardar_leitura('OLX', busca, {'status': 'bloqueado', 'items': [], 'mensagem': 'x'})
m.registrar_uso('Webmotors', limitou=False); m.registrar_uso('OLX', limitou=True)
m.salvar()
relogio[0] += 10 * 60
m2 = Memoria(tmp, 120, agora=lambda: relogio[0])
assert m2.detalhe('wm-1') == {'descricao': 'abc'}
assert m2.ids_guardados('wm-') == ['1']
assert m2.leitura_recente('Webmotors', busca)['ha_min'] == 10
assert m2.leitura_recente('OLX', busca) is None, 'bloqueado não deve ser reaproveitado'
assert m2.leitura_recente('Webmotors', {**busca, 'ano_de': 2022}) is None, 'outra busca não reaproveita'
assert m2.motivo_para_calma('Webmotors') == 'foi consultado há 10 min'
assert m2.motivo_para_calma('OLX') == 'pediu uma pausa há 10 min'
assert m2.minutos_desde_ultimo_uso() == 10
relogio[0] += 121 * 60
m3 = Memoria(tmp, 120, agora=lambda: relogio[0])
assert m3.leitura_recente('Webmotors', busca) is None and m3.motivo_para_calma('OLX') is None
assert Memoria(tmp, 0, agora=lambda: relogio[0] - 121 * 60).leitura_recente('Webmotors', busca) is None, 'reaproveitar=0 desliga'
relogio[0] += 7 * 86400
assert Memoria(tmp, 120, agora=lambda: relogio[0]).detalhe('wm-1') is None, 'detalhe expira em 7 dias'
print('1. memória: ok')

# ---------- 2. módulos dos sites preenchem/guardam detalhes
for f in tmp.glob('*.json'): f.unlink()
class NavFalso:
    def __init__(self, respostas): self.respostas = respostas; self.chamadas = []; self.ritmo = {'limitacoes': 0, 'parado_s': 0, 'desistiu': False}; self.calmo = False; self.janela = False
    def ir(self, url, espera=2.5): self.chamadas.append(('ir', url)); return True, ''
    def executar(self, arq, args, orcamento_s=300): self.chamadas.append((arq, args)); return self.respostas[arq](args)
mem = Memoria(tmp, 120)
lim = {'paginas': 15, 'anuncios': 300}
def wm_js(args):
    itens = []
    for uid in (1, 2, 3):
        lido = str(uid) not in args['pular']
        itens.append({'id': f'wm-{uid}', 'url': 'u', 'foto': None, 'descricao': f'desc {uid}' if lido else '', 'combustivel': 'Flex' if lido else None,
                      'atributos': ['Único dono'] if lido else [], 'publicado': '2026-10-01' if lido else None, '_det': lido})
    return {'status': 'ok', 'items': itens, 'avisos': [], 'total': 3}
nav = NavFalso({'webmotors_busca.js': wm_js})
mem.guardar_detalhe('wm-2', {'descricao': 'guardada 2', 'combustivel': 'Gasolina', 'atributos': ['IPVA pago'], 'publicado': None})
r = webmotors.buscar(nav, busca, lim, mem)
assert nav.chamadas[1][1]['pular'] == ['2']
d = {i['id']: i for i in r['items']}
assert d['wm-2']['descricao'] == 'guardada 2' and d['wm-2']['atributos'] == ['IPVA pago'] and '_det' not in d['wm-2']
assert mem.detalhe('wm-1')['descricao'] == 'desc 1' and mem.detalhe('wm-3')['combustivel'] == 'Flex'
print('2a. Webmotors: pula guardados, preenche e guarda: ok')

def olx_busca(args):
    return {'status': 'ok', 'total': 3, 'avisos': [], 'items': [
        {'id': f'olx-{i}', 'url': f'https://sp.olx.com.br/a/{i}', 'foto': None, 'descricao': ''} for i in (10, 11, 12)]}
pedidos_olx = []
def olx_det(args):
    pedidos_olx.extend(args['urls'])
    return {u.rsplit('/', 1)[1]: {'descricao': 'nova ' + u.rsplit('/', 1)[1], 'fipe': 99} for u in args['urls']}
mem.guardar_detalhe('olx-11', {'descricao': 'guardada 11', 'fipe': 50})
nav = NavFalso({'olx_busca.js': olx_busca, 'olx_detalhes.js': olx_det})
r = olx.buscar(nav, busca, lim, mem)
assert pedidos_olx == ['https://sp.olx.com.br/a/10', 'https://sp.olx.com.br/a/12'], pedidos_olx
d = {i['id']: i for i in r['items']}
assert d['olx-11']['descricao'] == 'guardada 11' and d['olx-11']['fipe_site'] == 50 and d['olx-10']['descricao'] == 'nova 10'
assert mem.detalhe('olx-12')['descricao'] == 'nova 12'
# todos guardados: nem abre página de anúncio
pedidos_olx.clear(); nav = NavFalso({'olx_busca.js': olx_busca, 'olx_detalhes.js': olx_det})
olx.buscar(nav, busca, lim, mem)
assert pedidos_olx == [] and [c for c in nav.chamadas if c[0] == 'ir'] == [('ir', 'https://www.olx.com.br/autos-e-pecas/carros-vans-e-utilitarios/gwm/estado-sp')]
print('2b. OLX: só abre anúncios novos (e nenhum quando todos estão guardados): ok')

def ml_busca(args):
    return {'status': 'ok', 'total': 2, 'avisos': [], 'items': [
        {'id': f'ml-MLB{i}', 'url': f'https://carro.mercadolivre.com.br/MLB-{i}-x', 'versao': 't', 'km': 1, 'descricao': '', 'blindado': None, 'cidade': 'x', 'uf': None} for i in (7, 8)]}
pedidos_ml = []
def ml_det(args):
    pedidos_ml.extend(args['urls'])
    return {'MLB' + u.split('MLB-')[1].split('-')[0]: {'descricao': 'ml nova', 'versao': 'GT', 'local': 'Campinas, São Paulo', 'km': '12.000 km', 'vendedor': 'normal'} for u in args['urls']}
mem.guardar_detalhe('ml-MLB8', {'descricao': 'ml guardada', 'versao': 'Skin', 'local': 'Santos, São Paulo'})
nav = NavFalso({'ml_busca.js': ml_busca, 'ml_detalhes.js': ml_det})
r = mercadolivre.buscar(nav, busca, lim, mem)
d = {i['id']: i for i in r['items']}
assert pedidos_ml == ['https://carro.mercadolivre.com.br/MLB-7-x'] and d['ml-MLB8']['descricao'] == 'ml guardada' and d['ml-MLB8']['cidade'] == 'Santos'
assert d['ml-MLB7']['km'] == 12000 and mem.detalhe('ml-MLB7')['versao'] == 'GT'
print('2c. Mercado Livre: só abre anúncios novos: ok')

# ---------- 3. coletar(): reaproveitamento, calma e bloqueio
for f in tmp.glob('*.json'): f.unlink()
contagem = {}
estado_site = {'Webmotors': 'ok', 'OLX': 'bloqueado'}
def mod_falso(nome, chave):
    def buscar(nav, b, limites, mem=None):
        contagem[nome] = contagem.get(nome, 0) + 1
        st = estado_site[nome]
        if nome == 'OLX' and nav.janela and estado_site.get('OLX_janela'): st = estado_site['OLX_janela']
        return {'status': st, 'mensagem': '', 'items': [{'id': f'{chave}-1'}] if st == 'ok' else [], 'total_site': 1}
    return types.SimpleNamespace(NOME=nome, buscar=buscar)
S.SITES = {'webmotors': mod_falso('Webmotors', 'wm'), 'olx': mod_falso('OLX', 'olx')}
calmos = []
class NavCtx:
    def __init__(self, pasta, mostrar=False): self.janela = False; self.calmo = False; self.ritmo = {'limitacoes': 0}
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def preparar_site(self, calmo=False): self.calmo = calmo; calmos.append(calmo); self.ritmo = {'limitacoes': 0}
    def pode_abrir_janela(self): return not self.janela
    def com_janela(self): self.janela = True; return True
N.Navegador = NavCtx
eventos = []
P.progresso.detalhe = lambda m: eventos.append(m)
P.progresso.etapa = lambda m, chave=None: None
P.progresso.site = lambda *a, **k: None
cfg = {'sites': {'webmotors': True, 'olx': True, 'icarros': False, 'mercadolivre': False}, 'execucao': {'mostrar_navegador': False, 'reaproveitar_minutos': 120}, 'limites': lim}
busca['rotulo'] = 'x'
c1 = P.coletar(cfg, [busca])
st1 = {r['site']: r['status'] for r in c1['resultados']}
assert st1 == {'Webmotors': 'ok', 'OLX': 'bloqueado'} and contagem == {'Webmotors': 1, 'OLX': 2}, (st1, contagem)
assert any('aguardando 1 minuto' in e for e in eventos)
print('3a. 1a rodada: OLX bloqueado tenta de novo após pausa, com janela: ok')
eventos.clear(); calmos.clear()
estado_site['OLX'] = 'ok'
c2 = P.coletar(cfg, [busca])
st2 = {r['site']: (r['status'], r['mensagem']) for r in c2['resultados']}
assert contagem == {'Webmotors': 1, 'OLX': 3}, contagem   # Webmotors reaproveitado; OLX consultado de novo
assert st2['Webmotors'][0] == 'ok' and 'reaproveitada' in st2['Webmotors'][1] and len(c2['resultados'][0]['items']) == 1
assert calmos == [True], calmos                        # OLX pediu pausa há pouco -> começa devagar
assert any('A última busca foi há' in e for e in eventos) and any('pediu uma pausa há' in e for e in eventos)
print('3b. 2a rodada em seguida: reaproveita o que deu certo, refaz só o que falhou, devagar: ok')
c3 = P.coletar(cfg, [busca], reaproveitar=False)
assert contagem == {'Webmotors': 2, 'OLX': 4}
print('3c. --sem-reaproveitar consulta tudo: ok')
busca2 = {**busca, 'id': 'b2', 'modelo': 'Haval H6', 'titulo': 'GWM Haval H6'}
calmos.clear()
P.coletar(cfg, [busca2])
assert contagem == {'Webmotors': 3, 'OLX': 5} and calmos == [True, True], (contagem, calmos)
print('3d. outro carro logo em seguida: consulta tudo, devagar: ok')
shutil.rmtree(tmp)
print('TUDO OK')
