"""Memória entre rodadas, para consultar os sites o mínimo possível (é o excesso de consultas que gera bloqueio).

- Detalhes já lidos de cada anúncio (descrição etc.) valem 7 dias: nas rodadas seguintes só os anúncios
  novos são abertos.
- A leitura completa de um site vale por um tempo (padrão 2 horas): repetir a mesma busca logo em seguida
  reaproveita essa leitura e só consulta de novo os sites que falharam.
- Ritmo de cada site: quando foi consultado e quando pediu pausa pela última vez. Se foi há pouco,
  a próxima leitura já começa devagar.

Nada disso é histórico de preços: o relatório continua mostrando só o que está anunciado agora.
"""
import hashlib
import json
import time
from datetime import datetime
from pathlib import Path

VALIDADE_DETALHES_DIAS = 7
MAX_DETALHES = 6000
CALMO_SE_USADO_HA_MIN = 30     # site consultado há menos que isso -> próxima leitura começa devagar
CALMO_SE_LIMITOU_HA_MIN = 120  # site que pediu pausa há menos que isso -> próxima leitura começa devagar
CAMPOS_BUSCA = ('marca', 'modelo', 'versao', 'ano_de', 'ano_ate', 'km_max', 'uf', 'cidade', 'preco_max',
                'cambio', 'combustivel', 'blindado')


def _ler(arq: Path):
    try:
        dados = json.loads(arq.read_text(encoding='utf-8'))
        return dados if isinstance(dados, dict) else {}
    except (OSError, ValueError):
        return {}


def _gravar(arq: Path, dados):
    tmp = arq.with_name(arq.name + '.tmp')
    tmp.write_text(json.dumps(dados, ensure_ascii=False), encoding='utf-8')
    tmp.replace(arq)


def _minutos(segundos):
    return max(1, round(segundos / 60))


class Memoria:
    def __init__(self, pasta: Path, reaproveitar_min=120, agora=None):
        self.pasta = Path(pasta)
        self.pasta.mkdir(parents=True, exist_ok=True)
        self.arq_detalhes = self.pasta / 'memoria_anuncios.json'
        self.arq_leituras = self.pasta / 'leituras_recentes.json'
        self.arq_ritmo = self.pasta / 'ritmo_sites.json'
        self.reaproveitar_min = max(0, int(reaproveitar_min or 0))
        self._agora = agora or time.time
        corte = self._agora() - VALIDADE_DETALHES_DIAS * 86400
        self.detalhes = {k: v for k, v in _ler(self.arq_detalhes).items()
                         if isinstance(v, dict) and v.get('_t', 0) >= corte}
        self.leituras = _ler(self.arq_leituras)
        self.ritmo = _ler(self.arq_ritmo)

    # ------------------------------------------------------------------ detalhes de anúncios
    def detalhe(self, id_anuncio):
        d = self.detalhes.get(id_anuncio)
        return {k: v for k, v in d.items() if k != '_t'} if d else None

    def ids_guardados(self, prefixo):
        """IDs (sem o prefixo do site) cujos detalhes estão guardados. Ex.: prefixo 'wm-'."""
        return [k[len(prefixo):] for k in self.detalhes if k.startswith(prefixo)]

    def guardar_detalhe(self, id_anuncio, dados):
        self.detalhes[id_anuncio] = {**dados, '_t': int(self._agora())}

    # ------------------------------------------------------------------ leitura recente de um site
    @staticmethod
    def chave_busca(busca):
        base = json.dumps([busca.get(c) for c in CAMPOS_BUSCA], ensure_ascii=False, sort_keys=True)
        return hashlib.sha1(base.encode('utf-8')).hexdigest()[:16]

    def leitura_recente(self, site, busca):
        """Leitura bem-sucedida da mesma busca neste site há menos de `reaproveitar_min` minutos, ou None."""
        if not self.reaproveitar_min:
            return None
        lt = self.leituras.get(site)
        if not isinstance(lt, dict) or lt.get('chave') != self.chave_busca(busca):
            return None
        idade = self._agora() - lt.get('_t', 0)
        if idade < -60 or idade > self.reaproveitar_min * 60:
            return None
        return {**lt, 'ha_min': _minutos(idade)}

    def guardar_leitura(self, site, busca, resultado):
        if resultado.get('status') != 'ok':
            return
        self.leituras[site] = {
            'chave': self.chave_busca(busca),
            '_t': int(self._agora()),
            'quando': datetime.fromtimestamp(self._agora()).strftime('%H:%M'),
            'resultado': {k: resultado.get(k) for k in ('status', 'mensagem', 'items', 'total_site')},
        }

    # ------------------------------------------------------------------ ritmo de cada site
    def motivo_para_calma(self, site):
        """Texto explicando por que começar devagar neste site, ou None."""
        r = self.ritmo.get(site) or {}
        agora = self._agora()
        if r.get('limite') and -60 <= agora - r['limite'] < CALMO_SE_LIMITOU_HA_MIN * 60:
            return f"pediu uma pausa há {_minutos(agora - r['limite'])} min"
        if r.get('uso') and -60 <= agora - r['uso'] < CALMO_SE_USADO_HA_MIN * 60:
            return f"foi consultado há {_minutos(agora - r['uso'])} min"
        return None

    def registrar_uso(self, site, limitou=False):
        r = dict(self.ritmo.get(site) or {})
        r['uso'] = int(self._agora())
        if limitou:
            r['limite'] = r['uso']
        self.ritmo[site] = r

    def minutos_desde_ultimo_uso(self):
        usos = [r.get('uso') for r in self.ritmo.values() if isinstance(r, dict) and r.get('uso')]
        if not usos:
            return None
        return max(0, round((self._agora() - max(usos)) / 60))

    # ------------------------------------------------------------------ gravação
    def salvar(self):
        if len(self.detalhes) > MAX_DETALHES:
            recentes = sorted(self.detalhes.items(), key=lambda kv: kv[1].get('_t', 0), reverse=True)
            self.detalhes = dict(recentes[:MAX_DETALHES])
        for arq, dados in ((self.arq_detalhes, self.detalhes), (self.arq_leituras, self.leituras),
                           (self.arq_ritmo, self.ritmo)):
            try:
                _gravar(arq, dados)
            except OSError:
                pass
