"""Publica uma versão nova do Busca Carro no GitHub; os PCs com o programa instalado se atualizam sozinhos.

Uso:
  python publicar.py --notas "O que mudou, em uma ou duas frases"            (publica)
  python publicar.py --notas "..." --so-gerar                                (só gera os arquivos em dist/)

Antes: aumente __version__ em buscacarros/__init__.py e faça commit/push do código.
Gera em dist/<versão>/:
  buscacarros-<versão>.zip   o programa (só a pasta buscacarros)
  atualizacao.json           versão, SHA-256, tamanho, base mínima e notas (lido pelos PCs)
  BuscaCarro-Instalador.exe  instalador completo (link fixo: .../releases/latest/download/BuscaCarro-Instalador.exe)
e cria a release v<versão> com esses três arquivos. O token do GitHub vem de GITHUB_TOKEN ou de `gh auth token`.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import requests

PROJETO = Path(__file__).resolve().parent
API = 'https://api.github.com'


def ler(padrao, arquivo):
    m = re.search(padrao, (PROJETO / arquivo).read_text(encoding='utf-8'))
    if not m:
        sys.exit(f'Não encontrei {padrao!r} em {arquivo}.')
    return m.group(1)


def versao():
    return ler(r"__version__\s*=\s*'([^']+)'", 'buscacarros/__init__.py')


def repositorio():
    return ler(r"REPOSITORIO\s*=\s*'([^']+)'", 'buscacarros/atualizador.py')


def base():
    return int(ler(r'(?m)^BASE\s*=\s*(\d+)', 'instalador/construir.py'))


def gerar_pacote(v, destino):
    """Zip determinístico só com a pasta buscacarros (sem __pycache__)."""
    arq = destino / f'buscacarros-{v}.zip'
    arquivos = sorted(p for p in (PROJETO / 'buscacarros').rglob('*')
                      if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc')
    with zipfile.ZipFile(arq, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in arquivos:
            info = zipfile.ZipInfo(p.relative_to(PROJETO).as_posix(), date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, p.read_bytes())
    return arq


def gerar_manifesto(v, pacote, notas, destino):
    dados = pacote.read_bytes()
    m = {
        'versao': v,
        'pacote': pacote.name,
        'sha256': hashlib.sha256(dados).hexdigest(),
        'tamanho': len(dados),
        'base_minima': base(),
        'notas': notas.strip(),
        'publicada_em': datetime.now(timezone.utc).isoformat(timespec='seconds'),
    }
    arq = destino / 'atualizacao.json'
    arq.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding='utf-8')
    return arq, m


def rodar_testes():
    for t in sorted((PROJETO / 'testes').glob('teste_*.py')):
        print('Teste:', t.name, flush=True)
        r = subprocess.run([sys.executable, str(t)], cwd=str(PROJETO))
        if r.returncode:
            sys.exit(f'O teste {t.name} falhou; nada foi publicado.')


def gerar_instalador(destino):
    subprocess.run([sys.executable, str(PROJETO / 'instalador' / 'construir.py')], check=True)
    exe = PROJETO / 'instalador' / 'saida' / 'BuscaCarro-Instalador.exe'
    shutil.copyfile(exe, destino / exe.name)
    return destino / exe.name


def token():
    t = os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN')
    if not t:
        try:
            t = subprocess.run(['gh', 'auth', 'token'], capture_output=True, text=True, check=True).stdout.strip()
        except Exception:
            t = ''
    if not t:
        sys.exit('Sem token do GitHub (defina GITHUB_TOKEN ou faça login com `gh auth login`).')
    return t


def publicar(repo, v, notas, arquivos):
    s = requests.Session()
    s.headers.update({'Authorization': f'Bearer {token()}', 'Accept': 'application/vnd.github+json',
                      'X-GitHub-Api-Version': '2022-11-28'})
    if s.get(f'{API}/repos/{repo}/releases/tags/v{v}', timeout=30).status_code == 200:
        sys.exit(f'A versão {v} já foi publicada. Aumente __version__ em buscacarros/__init__.py.')
    r = s.post(f'{API}/repos/{repo}/releases', timeout=60, json={
        'tag_name': f'v{v}', 'name': f'Busca Carro {v}', 'body': notas, 'draft': True, 'prerelease': False})
    r.raise_for_status()
    rel = r.json()
    upload = rel['upload_url'].split('{')[0]
    for arq in arquivos:
        tipo = 'application/json' if arq.suffix == '.json' else 'application/octet-stream'
        with open(arq, 'rb') as f:
            u = s.post(upload, params={'name': arq.name}, data=f, timeout=600, headers={'Content-Type': tipo})
        u.raise_for_status()
        print('Enviado:', arq.name)
    # só depois de todos os arquivos no lugar a versão vira "latest" (os PCs nunca veem uma versão pela metade)
    s.patch(f'{API}/repos/{repo}/releases/{rel["id"]}', json={'draft': False, 'make_latest': 'true'},
            timeout=60).raise_for_status()
    print(f'Publicada: https://github.com/{repo}/releases/tag/v{v}')


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--notas', required=True, help='o que mudou (aparece no painel de quem recebe a atualização)')
    p.add_argument('--so-gerar', action='store_true', help='gera os arquivos em dist/ sem publicar')
    p.add_argument('--sem-testes', action='store_true')
    p.add_argument('--sem-instalador', action='store_true', help='não gera o instalador (só com --so-gerar)')
    a = p.parse_args()
    v, repo = versao(), repositorio()
    if 'DEFINIR' in repo and not a.so_gerar:
        sys.exit('Defina REPOSITORIO em buscacarros/atualizador.py (dono/busca-carro).')
    if a.sem_instalador and not a.so_gerar:
        sys.exit('Toda versão publicada leva o instalador (o link fixo de download aponta para a mais recente).')
    if not a.sem_testes:
        rodar_testes()
    destino = PROJETO / 'dist' / v
    shutil.rmtree(destino, ignore_errors=True)
    destino.mkdir(parents=True)
    pacote = gerar_pacote(v, destino)
    manifesto, m = gerar_manifesto(v, pacote, a.notas, destino)
    print(f'Pacote {pacote.name}: {m["tamanho"]} bytes, SHA-256 {m["sha256"]}')
    arquivos = [manifesto, pacote]
    if not a.sem_instalador:
        arquivos.append(gerar_instalador(destino))
    if a.so_gerar:
        print('Arquivos em', destino)
        return
    publicar(repo, v, a.notas.strip(), arquivos)


if __name__ == '__main__':
    main()
