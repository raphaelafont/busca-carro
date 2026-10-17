"""Navegador automatizado (Playwright) usado para ler os sites."""
import logging
import random
import time
from pathlib import Path

from . import progresso

log = logging.getLogger(__name__)

PASTA_JS = Path(__file__).parent / 'sites' / 'js'

SINAIS_BLOQUEIO = ('access denied', 'just a moment', 'um momento', 'attention required', 'px-captcha',
                   'pardon our interruption', 'verifique se você é humano', 'verificando se você é humano',
                   'are you a robot', 'request unsuccessful', 'incapsula', 'acesso negado')


class Navegador:
    def __init__(self, pasta_perfil: Path, mostrar=False):
        self.pasta_perfil = Path(pasta_perfil)
        self.mostrar = mostrar
        self.janela = mostrar        # navegador com janela (visível ou fora da tela)
        self.fora_da_tela = False
        self.pw = None
        self.ctx = None
        self.page = None
        self._js = {}
        self.calmo = False      # consultar devagar desde o início (site usado há pouco ou que pediu pausa)
        self.pode_pedir_ajuda = False  # rodada iniciada pelo painel: há alguém para resolver uma verificação
        self.ritmo = self._ritmo_zerado()

    # ------------------------------------------------------------------ ciclo de vida
    def _abrir(self, user_agent=None):
        args = ['--disable-blink-features=AutomationControlled', '--lang=pt-BR']
        if self.fora_da_tela:  # janela real, mas posicionada fora da área visível
            args += ['--window-position=-32000,-32000', '--disable-features=CalculateNativeWinOcclusion']
        opcoes = dict(user_data_dir=str(self.pasta_perfil), headless=not self.janela, args=args,
                      locale='pt-BR', timezone_id='America/Sao_Paulo', viewport={'width': 1366, 'height': 900})
        if user_agent:
            opcoes['user_agent'] = user_agent
        # Google Chrome, depois Microsoft Edge (vem em todo Windows 10/11), por fim o Chromium do Playwright
        erros = []
        for canal in ('chrome', 'msedge', None):
            try:
                if canal:
                    return self.pw.chromium.launch_persistent_context(channel=canal, **opcoes)
                return self.pw.chromium.launch_persistent_context(**opcoes)
            except Exception as e:
                erros.append(f"{canal or 'chromium'}: {str(e).splitlines()[0][:150]}")
                log.info('Navegador %s indisponível; tentando o próximo.', canal or 'chromium')
        raise RuntimeError('Não encontrei Google Chrome nem Microsoft Edge neste computador. ' + ' | '.join(erros))

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self.pasta_perfil.mkdir(parents=True, exist_ok=True)
        self.pw = sync_playwright().start()
        self._iniciar()
        return self

    def _iniciar(self):
        self.ctx = self._abrir()
        page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        ua = page.evaluate('navigator.userAgent')
        if 'Headless' in ua:  # esconde o "HeadlessChrome" do identificador do navegador
            self.ctx.close()
            self.ctx = self._abrir(user_agent=ua.replace('HeadlessChrome', 'Chrome'))
        self.ctx.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
        # as páginas avisam o andamento (página lida, descrições...) por esta função
        try:
            self.ctx.expose_function('__bcProgresso', lambda msg: progresso.detalhe(msg))
        except Exception as e:
            log.info('Sem andamento detalhado das páginas: %s', str(e).splitlines()[0])
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        self.page.set_default_timeout(60000)

    def com_janela(self):
        """Reabre o navegador com janela (fora da tela, se o usuário não pediu para vê-la).
        Alguns sites liberam com mais facilidade um navegador com janela do que um sem janela."""
        if self.janela:
            return False
        try:
            self.ctx.close()
        except Exception:
            pass
        self.janela, self.fora_da_tela = True, not self.mostrar
        self._iniciar()
        return True

    def pode_abrir_janela(self):
        return not self.janela

    def com_janela_visivel(self):
        """Reabre o navegador com a janela na tela, para a pessoa resolver uma verificação do site."""
        if self.janela and not self.fora_da_tela:
            return False
        try:
            self.ctx.close()
        except Exception:
            pass
        self.janela, self.fora_da_tela = True, False
        self._iniciar()
        return True

    def __exit__(self, *exc):
        try:
            if self.ctx:
                self.ctx.close()
        finally:
            if self.pw:
                self.pw.stop()

    # ------------------------------------------------------------------ uso
    def ir(self, url, espera=2.5):
        """Abre a página. Retorna (ok, motivo)."""
        try:
            resp = self.page.goto(url, wait_until='domcontentloaded', timeout=60000)
        except Exception as e:
            return False, 'Não foi possível abrir a página: ' + str(e).splitlines()[0]
        self.page.wait_for_timeout(int((espera + random.random()) * 1000))
        if not self._bloqueada(resp):
            return True, ''
        # verificação anti-robô: muitas se resolvem sozinhas em alguns segundos num navegador de verdade
        progresso.detalhe('O site está fazendo uma verificação anti-robô; aguardando liberar')
        for _ in range(10):
            self.page.wait_for_timeout(3000)
            if not self._bloqueada(None):
                progresso.detalhe('Verificação concluída; seguindo')
                self.page.wait_for_timeout(1500)
                return True, ''
        if self.pode_pedir_ajuda and self._pedir_ajuda(url):
            return True, ''
        return False, 'BLOQUEIO'

    def _pedir_ajuda(self, url, limite_s=180):
        """Mostra a janela do navegador para a própria pessoa resolver a verificação do site (só em rodadas
        iniciadas pelo painel). A liberação fica guardada no perfil do navegador e vale para as próximas rodadas."""
        self.pode_pedir_ajuda = False  # no máximo uma vez por rodada
        try:
            if self.com_janela_visivel():
                self.page.goto(url, wait_until='domcontentloaded', timeout=60000)
                self.page.wait_for_timeout(2500)
                if not self._bloqueada(None):
                    return True
            self.page.bring_to_front()
        except Exception as e:
            log.info('Não consegui mostrar a janela para a verificação: %s', str(e).splitlines()[0])
            return False
        progresso.detalhe(f'VERIFICAÇÃO: o site pediu para confirmar que é uma pessoa. Resolva na janela do navegador '
                          f'que abriu; a busca continua sozinha em seguida (aguardando até {limite_s // 60} min)')
        fim = time.time() + limite_s
        while time.time() < fim:
            try:
                self.page.wait_for_timeout(2000)
                if not self._bloqueada(None):
                    progresso.detalhe('Verificação resolvida; seguindo')
                    self.page.wait_for_timeout(1500)
                    return True
            except Exception:
                return False
        progresso.detalhe('A verificação não foi resolvida a tempo; seguindo sem este site')
        return False

    def _bloqueada(self, resp):
        try:
            titulo = (self.page.title() or '').lower()
            corpo = (self.page.evaluate("document.body ? document.body.innerText.slice(0, 3000) : ''") or '').lower()
        except Exception:
            return False
        if any(s in titulo or s in corpo for s in SINAIS_BLOQUEIO):
            return True
        return resp is not None and resp.status in (403, 429) and len(corpo) < 1500

    def url_atual(self):
        return self.page.url

    # ------------------------------------------------------------------ ritmo das consultas
    @staticmethod
    def _ritmo_zerado():
        return {'limitacoes': 0, 'parado_s': 0, 'desistiu': False}

    def preparar_site(self, calmo=False):
        """Zera o ritmo para o próximo site. calmo=True: começa devagar (uma consulta por vez)."""
        self.calmo = bool(calmo)
        self.ritmo = self._ritmo_zerado()

    def _fonte(self, arquivo_js):
        if arquivo_js not in self._js:
            self._js[arquivo_js] = (PASTA_JS / arquivo_js).read_text(encoding='utf-8').strip().rstrip(';')
        return self._js[arquivo_js]

    def executar(self, arquivo_js, args, orcamento_s=300):
        """Roda um leitor (sites/js) na página atual, com o ritmo compartilhado de ritmo.js.
        orcamento_s: tempo máximo parado esperando o site liberar antes de desistir das consultas restantes."""
        script = ('async (a) => { const R = (' + self._fonte('ritmo.js') + ')(a.__ritmo); '
                  'const resultado = await (' + self._fonte(arquivo_js) + ')(a, R); '
                  'return { resultado: resultado, ritmo: R.resumo() }; }')
        res = self.page.evaluate(script, {**args, '__ritmo': {'calmo': self.calmo, 'orcamentoS': orcamento_s}}) or {}
        rt = res.get('ritmo') or {}
        self.ritmo['limitacoes'] += rt.get('limitacoes') or 0
        self.ritmo['parado_s'] += rt.get('parado_s') or 0
        self.ritmo['desistiu'] = self.ritmo['desistiu'] or bool(rt.get('desistiu'))
        if rt.get('calmo'):
            self.calmo = True  # as próximas consultas a este site já começam devagar
        return res.get('resultado')
