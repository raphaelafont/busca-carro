"""Publica uma versão nova do Busca Carro; os PCs com o programa instalado se atualizam sozinhos.

Passo a passo:
  1. Faça a mudança e aumente __version__ em buscacarros/__init__.py (ex.: 1.3.0 -> 1.3.1).
  2. Escreva em notas/<versão>.txt o que mudou, em uma ou duas frases (aparece no painel de cada pessoa).
  3. Commit e push para main.
  4. python publicar.py

O passo 4 roda os testes, confere que está tudo enviado e cria a tag v<versão>. A tag dispara o GitHub
Actions (.github/workflows/publicar.yml), que gera o pacote, o atualizacao.json e o instalador e cria a
release. Os PCs passam a ver a versão nova quando ela fica pronta, nunca pela metade.

Também usado pelo GitHub Actions:
  python publicar.py --so-gerar     gera em dist/<versão>/ os três arquivos da release:
      buscacarros-<versão>.zip   o programa (só a pasta buscacarros)
      atualizacao.json           versão, SHA-256, tamanho, base mínima e notas (lido pelos PCs)
      BuscaCarro-Instalador.exe  instalador completo (link fixo: .../releases/latest/download/BuscaCarro-Instalador.exe)
"""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

PROJETO = Path(__file__).resolve().parent


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


def notas(v):
    arq = PROJETO / 'notas' / f'{v}.txt'
    if not arq.is_file() or not arq.read_text(encoding='utf-8').strip():
        sys.exit(f'Escreva o que mudou em notas/{v}.txt (aparece no painel de quem recebe a atualização).')
    return arq.read_text(encoding='utf-8').strip()


def git(*args, check=True):
    r = subprocess.run(['git', *args], cwd=str(PROJETO), capture_output=True, text=True)
    if check and r.returncode:
        sys.exit(f'git {" ".join(args)} falhou: {r.stderr.strip()}')
    return r.stdout.strip()


# --------------------------------------------------------------------------- arquivos da release
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


def gerar_manifesto(v, pacote, texto, destino):
    dados = pacote.read_bytes()
    m = {
        'versao': v,
        'pacote': pacote.name,
        'sha256': hashlib.sha256(dados).hexdigest(),
        'tamanho': len(dados),
        'base_minima': base(),
        'notas': texto,
        'publicada_em': datetime.now(timezone.utc).isoformat(timespec='seconds'),
    }
    arq = destino / 'atualizacao.json'
    arq.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding='utf-8')
    return arq, m


def gerar_instalador(destino):
    subprocess.run([sys.executable, str(PROJETO / 'instalador' / 'construir.py')], check=True)
    exe = PROJETO / 'instalador' / 'saida' / 'BuscaCarro-Instalador.exe'
    shutil.copyfile(exe, destino / exe.name)
    return destino / exe.name


def rodar_testes():
    for t in sorted((PROJETO / 'testes').glob('teste_*.py')):
        print('Teste:', t.name, flush=True)
        if subprocess.run([sys.executable, str(t)], cwd=str(PROJETO)).returncode:
            sys.exit(f'O teste {t.name} falhou; nada foi publicado.')


def so_gerar(v, sem_instalador=False):
    destino = PROJETO / 'dist' / v
    shutil.rmtree(destino, ignore_errors=True)
    destino.mkdir(parents=True)
    pacote = gerar_pacote(v, destino)
    manifesto, m = gerar_manifesto(v, pacote, notas(v), destino)
    print(f'Pacote {pacote.name}: {m["tamanho"]} bytes, SHA-256 {m["sha256"]}')
    if not sem_instalador:
        gerar_instalador(destino)
    print('Arquivos em', destino)


# --------------------------------------------------------------------------- publicação (tag -> GitHub Actions)
def publicar(v, repo, sem_testes=False):
    notas(v)
    if 'DEFINIR' in repo:
        sys.exit('Defina REPOSITORIO em buscacarros/atualizador.py (dono/busca-carro).')
    if git('status', '--porcelain'):
        sys.exit('Há mudanças sem commit. Faça commit e push antes de publicar.')
    git('fetch', '-q', 'origin', 'main')
    if git('rev-parse', 'HEAD') != git('rev-parse', 'FETCH_HEAD'):
        sys.exit('O commit atual não é o que está no GitHub (main). Faça push (ou pull) antes de publicar.')
    if git('ls-remote', '--tags', 'origin', f'refs/tags/v{v}'):
        sys.exit(f'A versão {v} já foi publicada. Aumente __version__ em buscacarros/__init__.py.')
    if not sem_testes:
        rodar_testes()
    git('tag', '-a', f'v{v}', '-m', f'Busca Carro {v}')
    git('push', 'origin', f'v{v}')
    print(f'Tag v{v} enviada. O GitHub Actions gera e publica a versão em alguns minutos:')
    print(f'  https://github.com/{repo}/actions')
    print(f'  https://github.com/{repo}/releases/tag/v{v}')


def aguardar(v, repo, limite_s=900):
    """Espera a release ficar pública (consulta o mesmo endereço que os PCs usam)."""
    import requests
    url = f'https://github.com/{repo}/releases/latest/download/atualizacao.json'
    inicio = time.time()
    while time.time() - inicio < limite_s:
        try:
            r = requests.get(url, timeout=20)
            if r.ok and r.json().get('versao') == v:
                print(f'Versão {v} publicada e disponível para os PCs.')
                return True
        except Exception:
            pass
        time.sleep(20)
    print(f'A versão {v} ainda não apareceu; confira https://github.com/{repo}/actions')
    return False


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--so-gerar', action='store_true', help='só gera os arquivos da release em dist/<versão>/')
    p.add_argument('--sem-instalador', action='store_true', help='com --so-gerar: não gera o instalador')
    p.add_argument('--sem-testes', action='store_true')
    p.add_argument('--aguardar', action='store_true', help='depois da tag, espera a versão ficar disponível')
    a = p.parse_args()
    v, repo = versao(), repositorio()
    if a.so_gerar:
        so_gerar(v, a.sem_instalador)
        return
    publicar(v, repo, a.sem_testes)
    if a.aguardar:
        aguardar(v, repo)


if __name__ == '__main__':
    main()
