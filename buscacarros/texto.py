"""Funções de texto: normalização, slugs, números e estados."""
import re
import unicodedata

UFS = {
    'AC': 'Acre', 'AL': 'Alagoas', 'AP': 'Amapá', 'AM': 'Amazonas', 'BA': 'Bahia',
    'CE': 'Ceará', 'DF': 'Distrito Federal', 'ES': 'Espírito Santo', 'GO': 'Goiás',
    'MA': 'Maranhão', 'MT': 'Mato Grosso', 'MS': 'Mato Grosso do Sul', 'MG': 'Minas Gerais',
    'PA': 'Pará', 'PB': 'Paraíba', 'PR': 'Paraná', 'PE': 'Pernambuco', 'PI': 'Piauí',
    'RJ': 'Rio de Janeiro', 'RN': 'Rio Grande do Norte', 'RS': 'Rio Grande do Sul',
    'RO': 'Rondônia', 'RR': 'Roraima', 'SC': 'Santa Catarina', 'SP': 'São Paulo',
    'SE': 'Sergipe', 'TO': 'Tocantins',
}


def sem_acento(s):
    s = unicodedata.normalize('NFD', str(s or ''))
    return ''.join(c for c in s if unicodedata.category(c) != 'Mn')


def norm(s):
    """minúsculas, sem acento, espaços simples."""
    return re.sub(r'\s+', ' ', sem_acento(s).lower()).strip()


def slug(s):
    s = norm(s).replace('.', '')
    return re.sub(r'[^a-z0-9]+', '-', s).strip('-')


_NOMES_UF = {norm(v): k for k, v in UFS.items()}


def uf_de_nome(nome):
    """'São Paulo' -> 'SP'; 'SP' -> 'SP'."""
    if not nome:
        return None
    n = norm(nome)
    if n.upper() in UFS:
        return n.upper()
    return _NOMES_UF.get(n)


def para_uf(valor):
    """Aceita sigla ou nome do estado."""
    if not valor:
        return None
    v = str(valor).strip()
    if v.upper() in UFS:
        return v.upper()
    return uf_de_nome(v)


def cidade_normalizada(cidade):
    """Remove sufixos de região usados pelo Mercado Livre ('São Paulo Zona Sul' -> 'sao paulo')."""
    c = norm(cidade)
    c = re.sub(r'\s+(zona\s+(norte|sul|leste|oeste|central)|centro)$', '', c)
    return c


def inteiro(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v)
    d = re.sub(r'[^\d]', '', str(v))
    return int(d) if d else None


def preco_fipe(texto):
    """'R$ 84.049,00' -> 84049.0"""
    if texto is None:
        return None
    if isinstance(texto, (int, float)):
        return float(texto)
    t = re.sub(r'[^\d,]', '', str(texto)).replace(',', '.')
    try:
        return float(t)
    except ValueError:
        return None


def sim_nao(v):
    """Interpreta células como sim/não/indiferente."""
    n = norm(v)
    if n in ('sim', 's', 'yes', 'y', 'x', 'true', '1', 'so blindados', 'somente'):
        return True
    if n in ('nao', 'n', 'no', 'false', '0', 'excluir'):
        return False
    return None


def tipo_cambio(v):
    n = norm(v)
    if not n:
        return None
    if re.search(r'autom|cvt|tiptronic|dsg|dct|sequencial|aut\b|aut\.', n):
        return 'automatico'
    if re.search(r'manual|mec', n):
        return 'manual'
    return None


def tipo_combustivel(v):
    n = norm(v)
    if not n:
        return None
    if 'flex' in n or ('gasolina' in n and 'alcool' in n) or ('gasolina' in n and 'etanol' in n):
        return 'flex'
    if 'hibrid' in n:
        return 'hibrido'
    if 'eletric' in n:
        return 'eletrico'
    if 'diesel' in n:
        return 'diesel'
    if 'gasolina' in n:
        return 'gasolina'
    if 'alcool' in n or 'etanol' in n:
        return 'alcool'
    return None


def limpar_descricao(texto):
    t = str(texto or '')
    t = re.sub(r'<br\s*/?>', '\n', t, flags=re.I)
    t = re.sub(r'<[^>]+>', ' ', t)
    t = re.sub(r'(^|\n)\s*[?*•\-–]+\s*', r'\1', t)   # marcadores e emojis perdidos no início da linha
    t = re.sub(r'\s+\?\s+', ' · ', t)                 # emojis perdidos no meio da frase
    t = re.sub(r'\s+\?$', '', t)
    t = re.sub(r'\.{2,}', '.', t)
    t = re.sub(r'\s*\n\s*', ' · ', t.strip())
    t = re.sub(r'(\s*·\s*){2,}', ' · ', t)
    t = re.sub(r'\s{2,}', ' ', t)
    return t.strip(' ·')


def resumo(texto, limite=170):
    t = limpar_descricao(texto)
    if len(t) <= limite:
        return t
    corte = t[:limite].rsplit(' ', 1)[0]
    return corte.rstrip(' ,.;:·-') + '…'
