"""Rotina principal: coleta, trata e gera o relatório."""
import argparse
import json
import logging
import shutil
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

from . import agenda, analise, historico, progresso, relatorio
from .configuracao import RAIZ, ErroConfig, busca_no_site, ler_buscas, ler_config
from .fipe import Fipe, tokens
from .memoria import CALMO_SE_USADO_HA_MIN, Memoria

DADOS = RAIZ / 'dados'
RESULTADOS = RAIZ / 'resultados'
LOGS = RAIZ / 'logs'
ARQ_PROGRESSO = DADOS / 'progresso.jsonl'
PEDIDO_PARADA = DADOS / 'parar.pedido'  # criado pelo painel no botão "Parar e gerar relatório"
log = logging.getLogger('buscacarros')
FORMATO = logging.Formatter('%(asctime)s %(levelname)s %(message)s', '%H:%M:%S')


# --------------------------------------------------------------------------- registros
def configurar_log():
    LOGS.mkdir(parents=True, exist_ok=True)
    raiz = logging.getLogger()
    raiz.setLevel(logging.INFO)
    if sys.stderr is not None:  # pythonw (execução silenciosa) não tem console
        sh = logging.StreamHandler()
        sh.setFormatter(FORMATO)
        raiz.addHandler(sh)
    else:
        # sem console: o driver do navegador herda esta saída de erros (e ela fica registrada)
        try:
            sys.stderr = open(LOGS / 'saida_tecnica.log', 'a', encoding='utf-8', buffering=1)
        except OSError:
            pass
    raiz.addHandler(progresso.Manipulador())
    for ruidoso in ('urllib3', 'asyncio'):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)


def log_da_rodada():
    arq = LOGS / f"execucao_{datetime.now():%Y-%m-%d_%H%M%S}.log"
    fh = logging.FileHandler(arq, encoding='utf-8')
    fh.setFormatter(FORMATO)
    logging.getLogger().addHandler(fh)
    return arq


def anotar_checagem(texto):
    try:
        arq = LOGS / 'checagens.log'
        linhas = arq.read_text(encoding='utf-8').splitlines()[-200:] if arq.exists() else []
        linhas.append(f'{datetime.now():%d/%m/%Y %H:%M} {texto}')
        arq.write_text('\n'.join(linhas) + '\n', encoding='utf-8')
    except OSError:
        pass


def parada_pedida():
    return PEDIDO_PARADA.exists()


def limpar_pedido_parada():
    try:
        PEDIDO_PARADA.unlink()
    except OSError:
        pass


def limpar_antigos(pasta: Path, padrao: str, manter: int):
    for a in sorted(pasta.glob(padrao))[:-manter]:
        try:
            a.unlink()
        except OSError:
            pass


# --------------------------------------------------------------------------- coleta
def _ler_site(nav, mod, busca, cfg, mem):
    """Lê um site respeitando o ritmo que ele aceita. Retorna o resultado do módulo do site."""
    motivo = mem.motivo_para_calma(mod.NOME)
    nav.preparar_site(calmo=bool(motivo))
    if motivo:
        progresso.detalhe(f'{mod.NOME} {motivo}; consultando mais devagar para não ser bloqueado')
    try:
        r = mod.buscar(nav, busca, cfg['limites'], mem)
        if r['status'] == 'bloqueado' and nav.pode_abrir_janela() and not parada_pedida():
            # segunda tentativa, depois de uma pausa, com o navegador em janela (fora da tela),
            # que passa mais nas verificações; tentar na hora só reforça o bloqueio
            progresso.detalhe('Bloqueado; aguardando 1 minuto e tentando de novo, devagar, com o navegador em janela')
            time.sleep(60)
            nav.com_janela()
            nav.calmo = True
            r = mod.buscar(nav, busca, cfg['limites'], mem)
    except Exception as e:
        log.error('%s falhou: %s\n%s', mod.NOME, e, traceback.format_exc())
        r = {'status': 'erro', 'mensagem': f'Erro inesperado: {str(e).splitlines()[0][:200]}', 'items': []}
    if parada_pedida():
        # leitura cortada no meio: fica o que já foi lido, e ela não é reaproveitada numa próxima busca
        qtd = len(r.get('items', []))
        r['status'] = 'ok' if qtd else 'interrompido'
        r['mensagem'] = f'parado no meio pela pessoa ({qtd} anúncios lidos até ali)' if qtd else 'parado pela pessoa'
        mem.registrar_uso(mod.NOME, nav.ritmo['limitacoes'] > 0)
        return r
    limitou = r['status'] == 'bloqueado' or nav.ritmo['limitacoes'] > 0
    if mod.NOME != 'iCarros':
        mem.registrar_uso(mod.NOME, limitou)
    mem.guardar_leitura(mod.NOME, busca, r)
    return r


def coletar(cfg, buscas, reaproveitar=True, interativo=False):
    from .navegador import Navegador
    from .sites import SITES
    resultados = []
    ativos = [(k, m) for k, m in SITES.items() if cfg['sites'].get(k, True)]
    mem = Memoria(DADOS, cfg['execucao']['reaproveitar_minutos'] if reaproveitar else 0)
    progresso.etapa('Abrindo o navegador automático', chave='navegador')
    desde = mem.minutos_desde_ultimo_uso()
    if desde is not None and desde < CALMO_SE_USADO_HA_MIN:
        progresso.detalhe(f'A última busca foi há {desde} min: o programa vai reaproveitar o que já leu e consultar '
                          'os sites mais devagar, para não ser bloqueado')
    with Navegador(DADOS / 'perfil_navegador', mostrar=cfg['execucao']['mostrar_navegador']) as nav:
        nav.pode_pedir_ajuda = interativo  # rodada pelo painel: a pessoa pode resolver uma verificação do site
        nav.deve_parar = parada_pedida
        for nb, busca in enumerate(buscas, 1):
            for chave, mod in SITES.items():
                if not busca_no_site(busca, chave):
                    continue
                if not cfg['sites'].get(chave, True):
                    resultados.append({'busca_id': busca['id'], 'site': mod.NOME, 'status': 'desativado',
                                       'mensagem': 'desligado no config.ini', 'items': []})
                    continue
                id_etapa = f"{busca['id']}:{chave}"
                if parada_pedida():
                    progresso.site(busca['id'], mod.NOME, 'interrompido', 0, 'não consultado: a busca foi parada', chave=id_etapa)
                    resultados.append({'busca_id': busca['id'], 'site': mod.NOME, 'status': 'interrompido',
                                       'mensagem': 'não consultado: a busca foi parada', 'items': []})
                    continue
                progresso.etapa(f"{mod.NOME}: abrindo o site para {busca['titulo']}", chave=id_etapa)
                inicio = time.time()
                recente = mem.leitura_recente(mod.NOME, busca)
                if recente:
                    progresso.detalhe(f"Esta mesma busca foi lida às {recente['quando']} (há {recente['ha_min']} min); "
                                      'reaproveitando a leitura em vez de consultar o site de novo')
                    r = dict(recente['resultado'])
                    r['mensagem'] = '; '.join(x for x in (f"leitura das {recente['quando']} reaproveitada",
                                                          r.get('mensagem')) if x)
                else:
                    r = _ler_site(nav, mod, busca, cfg, mem)
                    mem.salvar()
                qtd = len(r.get('items', []))
                log.info('%s: %s, %d anúncios em %.0f s %s', mod.NOME, r['status'], qtd, time.time() - inicio,
                         ('(' + r['mensagem'] + ')') if r.get('mensagem') else '')
                progresso.site(busca['id'], mod.NOME, r['status'], qtd, r.get('mensagem') or '', chave=id_etapa)
                resultados.append({'busca_id': busca['id'], 'site': mod.NOME, **r})
    return {'coletado_em': datetime.now().isoformat(timespec='minutes'), 'buscas': buscas, 'resultados': resultados,
            'sites_ativos': [m.NOME for _, m in ativos]}


# --------------------------------------------------------------------------- tratamento
def processar(coleta, cfg, fipe):
    buscas = {b['id']: b for b in coleta['buscas']}
    limite = cfg['alertas']['abaixo_fipe_pct']
    status, por_busca = [], {b: [] for b in buscas}
    total = sum(len(r.get('items', [])) for r in coleta['resultados'])
    feitos = 0
    for r in coleta['resultados']:
        busca = buscas.get(r['busca_id'])
        if not busca:
            continue
        aceitos = []
        for item in r.get('items', []):
            feitos += 1
            progresso.detalhe(f'Comparando com a FIPE: {feitos} de {total}')
            item = analise.completar(dict(item))
            if not analise.passa_filtros(item, busca):
                continue
            analise.aplicar_fipe(item, fipe, busca)
            item['selos'] = analise.destaques(item)
            item['alertas'] = analise.alertas(item, limite)
            aceitos.append(item)
        por_busca[busca['id']].extend(aceitos)
        status.append({'busca': busca['rotulo'], 'site': r['site'], 'status': r['status'],
                       'mensagem': r.get('mensagem') or '', 'qtd': len(aceitos)})

    carros = []
    for bid, itens in por_busca.items():
        b = buscas[bid]
        agrupados = analise.agrupar(itens, tokens(b['marca']) | tokens(b['modelo']))
        carros += [relatorio.para_exibicao(c, b) for c in agrupados]
    carros.sort(key=lambda c: (c['dif_pct'] is None, c['dif_pct'] if c['dif_pct'] is not None else 0))

    dados = {
        'gerado_em': datetime.fromisoformat(coleta['coletado_em']).strftime('%d/%m/%Y às %H:%M'),
        'referencia_fipe': (fipe.cache.get('referencia') if fipe else None),
        'buscas': [{'id': b['id'], 'rotulo': b['rotulo']} for b in coleta['buscas']],
        'status': status,
        'carros': carros,
    }
    return dados, carros


# --------------------------------------------------------------------------- execução
def rodada(args, cfg, buscas):
    """Uma rodada completa, já com a trava adquirida."""
    from .sites import SITES
    t0 = time.time()
    limpar_pedido_parada()
    sites_rodada = [(k, m) for k, m in SITES.items()
                    if cfg['sites'].get(k, True) and any(busca_no_site(b, k) for b in buscas)]
    n_sites = len(sites_rodada)
    progresso.iniciar(ARQ_PROGRESSO, origem=args.origem,
                      buscas=[{'id': b['id'], 'titulo': b['titulo'], 'detalhes': b['detalhes']} for b in buscas],
                      sites=[{'chave': k, 'nome': m.NOME} for k, m in sites_rodada],
                      etapas=len(buscas) * n_sites + 2)
    log.info('Rodada iniciada (%s): %d %s.', args.origem, len(buscas), 'busca' if len(buscas) == 1 else 'buscas')

    if args.reprocessar:
        coleta = json.loads(Path(args.reprocessar).read_text(encoding='utf-8'))
    else:
        if not agenda.aguardar_internet(avisar=progresso.detalhe):
            log.error('Sem conexão com a internet; a busca fica para a próxima vez.')
            progresso.fim('erro', msg='Sem conexão com a internet.')
            return 3
        coleta = coletar(cfg, buscas, reaproveitar=not args.sem_reaproveitar, interativo=args.origem == 'painel')
        (DADOS / 'ultima_coleta.json').write_text(json.dumps(coleta, ensure_ascii=False), encoding='utf-8')

    progresso.etapa('Comparando os anúncios com a tabela FIPE', chave='fipe')
    fipe = Fipe(DADOS, cfg['fipe']['token'])
    dados, carros = processar(coleta, cfg, fipe)
    fipe.salvar()
    if fipe.indisponivel:
        log.warning('A API da FIPE não respondeu; usei a FIPE informada pelos sites quando havia.')

    progresso.etapa('Gerando o relatório', chave='relatorio')
    destino = RESULTADOS / f"relatorio_{datetime.now():%Y-%m-%d_%H%M}.html"
    relatorio.gerar(dados, destino)
    shutil.copyfile(destino, RESULTADOS / 'ultimo_relatorio.html')
    log.info('Relatório: %s (%d carros)', destino.name, len(carros))

    abaixo = sum(1 for c in carros if c.get('dif_pct') is not None and c['dif_pct'] < 0)
    algum_ok = any(s['status'] == 'ok' for s in dados['status'])
    parcial = parada_pedida() or any(s['status'] == 'interrompido' for s in dados['status'])
    resumo = {'carros': len(carros), 'abaixo_fipe': abaixo, 'relatorio': destino.name,
              'duracao_s': round(time.time() - t0), 'origem': args.origem, 'parcial': parcial,
              'sites': {s['site']: {'status': s['status'], 'qtd': s['qtd']} for s in dados['status']}}
    if not args.reprocessar and algum_ok and not parcial:  # busca parada no meio não conta como a rodada dos 2 dias
        agenda.registrar(DADOS, resumo)
    historico.registrar(RESULTADOS, DADOS, destino, coleta['buscas'], dados, resumo)
    if parcial:
        msg = 'Busca parada antes do fim; o relatório tem o que foi coletado até ali.'
    else:
        msg = None if algum_ok else 'Nenhum site respondeu; confira o registro abaixo.'
    progresso.fim('ok' if (algum_ok or parcial) else 'erro', **resumo, msg=msg)
    limpar_pedido_parada()
    limpar_antigos(RESULTADOS, 'relatorio_*.html', 30)
    limpar_antigos(LOGS, 'execucao_*.log', 30)
    if args.abrir:
        import webbrowser
        webbrowser.open(destino.resolve().as_uri())
    return 0


def executar(args):
    configurar_log()
    for p in (DADOS, RESULTADOS):
        p.mkdir(parents=True, exist_ok=True)
    try:
        cfg = ler_config()
        buscas = ler_buscas()
    except ErroConfig as e:
        log_da_rodada()
        log.error('Configuração: %s', e)
        anotar_checagem(f'erro de configuração: {e}')
        return 2
    if args.mostrar_navegador:
        cfg['execucao']['mostrar_navegador'] = True

    if not args.forcar and not args.reprocessar:
        rodar, proxima = agenda.deve_rodar(DADOS, cfg['execucao']['intervalo_dias'])
        if not rodar:
            msg = f"ainda não é dia de rodar; próxima rodada a partir de {proxima.strftime('%d/%m/%Y')}"
            log.info(msg[0].upper() + msg[1:] + '.')
            anotar_checagem(msg)
            return 0
    if not buscas:
        log.error('A lista de busca está vazia. Adicione um carro no painel.')
        anotar_checagem('lista de busca vazia')
        return 2

    try:
        with agenda.Trava(DADOS, origem=args.origem):
            log_da_rodada()
            anotar_checagem(f'rodada iniciada ({args.origem})')
            try:
                return rodada(args, cfg, buscas)
            except Exception as e:
                limpar_pedido_parada()
                log.error('Falha inesperada:\n%s', traceback.format_exc())
                progresso.fim('erro', msg=f'Falha inesperada: {str(e).splitlines()[0][:200]}')
                return 1
    except RuntimeError as e:  # outra rodada em andamento
        log.info(str(e))
        anotar_checagem(str(e))
        return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog='buscacarros', description='Busca carros usados e compara com a FIPE.')
    p.add_argument('--forcar', action='store_true', help='roda agora, mesmo que a última rodada tenha sido há menos de 2 dias')
    p.add_argument('--sem-email', action='store_true', help=argparse.SUPPRESS)  # aceito por compatibilidade; não há mais e-mail
    p.add_argument('--abrir', action='store_true', help='abre o relatório no navegador ao terminar')
    p.add_argument('--mostrar-navegador', action='store_true', help='mostra a janela do navegador durante a coleta')
    p.add_argument('--origem', default='automatica', choices=('automatica', 'painel', 'manual'),
                   help='quem iniciou a rodada (aparece no painel)')
    p.add_argument('--sem-reaproveitar', action='store_true',
                   help='consulta todos os sites de novo, mesmo que a mesma busca tenha sido lida há pouco')
    p.add_argument('--reprocessar', metavar='ARQUIVO', help='refaz o relatório a partir de uma coleta salva (dados/ultima_coleta.json)')
    args = p.parse_args(argv)
    try:
        return executar(args)
    except Exception:
        log.error('Falha inesperada:\n%s', traceback.format_exc())
        return 1
