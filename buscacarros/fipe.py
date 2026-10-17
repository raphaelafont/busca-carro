"""Tabela FIPE: consulta à API pública (fipe.parallelum.com.br), cache mensal e casamento de versões."""
import json
import logging
import re
import time
from datetime import date
from pathlib import Path

import requests

from .texto import norm, preco_fipe

log = logging.getLogger(__name__)

API = 'https://fipe.parallelum.com.br/api/v2/cars'

# Palavras que não ajudam a distinguir versões
IGNORAR = {
    'flex', 'flexone', 'flexfuel', 'flexstart', 'gasolina', 'alcool', 'etanol', 'diesel', 'gnv', 'tetrafuel',
    'aut', 'automatico', 'automatica', 'automatizado', 'automatizada', 'mec', 'manual', 'mecanico',
    'cvt', 'tiptronic', 'sequencial', 'hatch', 'hatchback', 'sedan', 'sedã', 'portas', 'porta', 'p',
    'cv', 'e', 'de', 'com', 'km', 'v', 'at', 'mt', 'gas', 'alc', 'fl', 'dsg', 'dct', '4x2',
}
ALIASES_MARCA = {'vw': 'volkswagen', 'gm': 'chevrolet', 'chevy': 'chevrolet', 'mercedes': 'mercedes-benz', 'citroen': 'citroen'}


def tokens(texto, ignorar=()):
    t = norm(texto)
    t = re.sub(r'[/(),+\-]', ' ', t)
    out = set()
    for x in re.findall(r'\d+\.\d+|[a-z0-9]+', t):
        if x in IGNORAR or x in ignorar:
            continue
        if re.fullmatch(r'\d+v', x) or re.fullmatch(r'\d+p', x) or re.fullmatch(r'(19|20)\d\d', x):
            continue
        out.add(x)
    return out


def _trans_fipe(nome):
    n = norm(nome)
    aut = bool(re.search(r'\baut|\bcvt\b|tiptronic|automat', n))
    mec = bool(re.search(r'\bmec', n))
    return aut, mec


class Fipe:
    def __init__(self, pasta_dados: Path, token: str = '', nome_cache: str = 'fipe_cache.json'):
        self.arq = Path(pasta_dados) / nome_cache
        self.sessao = requests.Session()
        self.sessao.headers['User-Agent'] = 'BuscaCarros/1.0'
        if token:
            self.sessao.headers['X-Subscription-Token'] = token
        self.indisponivel = False
        self.chamadas = 0
        self.timeout = 20
        self.tentativas = 3
        self.cache = self._carregar()

    # ---------- cache ----------
    def _carregar(self):
        mes = date.today().strftime('%Y-%m')
        try:
            c = json.loads(self.arq.read_text(encoding='utf-8'))
        except Exception:
            c = {}
        if c.get('mes') != mes:
            c = {'mes': mes, 'referencia': None, 'marcas': c.get('marcas', []), 'modelos': {}, 'anos': {}, 'precos': {}}
        for k in ('modelos', 'anos', 'precos'):
            c.setdefault(k, {})
        c.setdefault('marcas', [])
        return c

    def salvar(self):
        try:
            self.arq.parent.mkdir(parents=True, exist_ok=True)
            self.arq.write_text(json.dumps(self.cache, ensure_ascii=False), encoding='utf-8')
        except Exception as e:
            log.warning('Não foi possível salvar o cache da FIPE: %s', e)

    def _get(self, caminho):
        if self.indisponivel:
            return None
        for tentativa in range(self.tentativas):
            try:
                self.chamadas += 1
                r = self.sessao.get(API + caminho, timeout=self.timeout)
                if r.status_code == 429:
                    log.warning('API da FIPE: limite diário de consultas atingido.')
                    self.indisponivel = True
                    return None
                if r.status_code == 404:
                    return None
                r.raise_for_status()
                time.sleep(0.15)
                return r.json()
            except requests.RequestException as e:
                log.info('API da FIPE falhou (%s), tentativa %d', e, tentativa + 1)
                if tentativa + 1 < self.tentativas:
                    time.sleep(2)
        self.indisponivel = True
        return None

    # ---------- consultas ----------
    def marca(self, nome):
        if not self.cache['marcas']:
            j = self._get('/brands')
            if j:
                self.cache['marcas'] = j
        alvo = norm(ALIASES_MARCA.get(norm(nome), nome))
        melhor = None
        for m in self.cache['marcas']:
            n = norm(m['name'])
            partes = set(re.split(r'[\s\-]+', n))
            if n == alvo or alvo in partes or n.replace('-', ' ') == alvo.replace('-', ' '):
                return m['code']
            if alvo and alvo in n and melhor is None:
                melhor = m['code']
        return melhor

    def modelos(self, cod_marca, nome_modelo):
        lista = self.cache['modelos'].get(str(cod_marca))
        if lista is None:
            lista = self._get(f'/brands/{cod_marca}/models') or []
            if lista:
                self.cache['modelos'][str(cod_marca)] = lista
        alvo = re.sub(r'[\-/]', ' ', norm(nome_modelo)).strip()
        res = []
        for m in lista:
            n = re.sub(r'[\-/]', ' ', norm(m['name'])).strip()
            if n == alvo or n.startswith(alvo + ' '):
                res.append(m)
        return res

    def anos(self, cod_marca, cod_modelo):
        k = f'{cod_marca}/{cod_modelo}'
        if k not in self.cache['anos']:
            j = self._get(f'/brands/{cod_marca}/models/{cod_modelo}/years')
            if j is None:
                return []
            self.cache['anos'][k] = [y['code'] for y in j]
        return self.cache['anos'][k]

    def preco(self, cod_marca, cod_modelo, cod_ano):
        k = f'{cod_marca}/{cod_modelo}/{cod_ano}'
        if k not in self.cache['precos']:
            j = self._get(f'/brands/{cod_marca}/models/{cod_modelo}/years/{cod_ano}')
            if not j:
                return None
            self.cache['precos'][k] = {'price': j.get('price'), 'codeFipe': j.get('codeFipe'),
                                       'referenceMonth': j.get('referenceMonth')}
            if j.get('referenceMonth'):
                self.cache['referencia'] = j['referenceMonth']
        p = self.cache['precos'][k]
        return {'valor': preco_fipe(p['price']), 'codigo': p.get('codeFipe'), 'referencia': p.get('referenceMonth')}

    # ---------- casamento anúncio -> versão FIPE ----------
    def avaliar(self, marca, modelo, versao, ano_modelo, cambio=None):
        """Retorna dict com valor FIPE (exato ou faixa) ou None."""
        if not (marca and modelo and ano_modelo):
            return None
        cod_marca = self.marca(marca)
        if not cod_marca:
            return None
        candidatos = self.modelos(cod_marca, modelo)
        if not candidatos:
            return None
        ignorar = tokens(marca) | tokens(modelo)
        L = tokens(versao or '', ignorar)

        # filtra por câmbio
        filtrados = []
        for m in candidatos:
            aut, mec = _trans_fipe(m['name'])
            if cambio == 'automatico' and mec and not aut:
                continue
            if cambio == 'manual' and aut and not mec:
                continue
            filtrados.append(m)
        candidatos = filtrados or candidatos

        # só modelos que têm o ano
        com_ano = []
        for m in candidatos:
            anos = self.anos(cod_marca, m['code'])
            cod_ano = next((a for a in anos if a.split('-')[0] == str(ano_modelo)), None)
            if cod_ano:
                com_ano.append((m, cod_ano))
        if not com_ano:
            return None

        pontuados = []
        for m, cod_ano in com_ano:
            F = tokens(m['name'], ignorar)
            score = len(L & F) - len(L - F) - 0.1 * len(F - L)
            pontuados.append((score, m, cod_ano, F))
        melhor = max(p[0] for p in pontuados)
        alfa_L = {t for t in L if re.search(r'[a-z]', t)}

        if melhor > 0 and (not alfa_L or any(alfa_L & p[3] for p in pontuados if p[0] >= melhor - 0.05)):
            escolhidos = [p for p in pontuados if p[0] >= melhor - 0.05]
            aproximada = len(escolhidos) > 1
        else:
            # versão não identificada: usa a faixa das versões com o mesmo motor (se houver)
            motor = {t for t in L if re.fullmatch(r'\d\.\d', t)}
            escolhidos = [p for p in pontuados if not motor or (motor & p[3])] or pontuados
            aproximada = True

        precos = []
        for _, m, cod_ano, _F in escolhidos:
            p = self.preco(cod_marca, m['code'], cod_ano)
            if p and p['valor']:
                precos.append((p['valor'], m['name'], p))
        if not precos:
            return None
        valores = [x[0] for x in precos]
        if len(precos) == 1:
            v, nome, p = precos[0]
            return {'valor': v, 'min': v, 'max': v, 'exata': not aproximada, 'modelo': nome,
                    'codigo': p['codigo'], 'referencia': p['referencia'], 'fonte': 'FIPE'}
        return {'valor': round(sum(valores) / len(valores)), 'min': min(valores), 'max': max(valores),
                'exata': False, 'modelo': f'{len(precos)} versões possíveis',
                'codigo': None, 'referencia': precos[0][2]['referencia'], 'fonte': 'FIPE'}
