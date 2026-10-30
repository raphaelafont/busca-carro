"""Monta o instalador do Busca Carro (BuscaCarro-Instalador.zip).

Por que .zip e não .exe: o Controle Inteligente de Aplicativos do Windows 11 bloqueia qualquer .exe sem
assinatura digital, sem opção de "Executar assim mesmo". O zip só tem programas assinados (o Python
oficial, assinado pela PSF) e scripts: a pessoa extrai e roda o Instalar.bat, que chama instalar.py.

Roda em Linux com: python3 e pip (e Playwright só para gerar o ícone, se faltar).
Passos:
  1. Python 3.13 embutível oficial para Windows (pacote python-embed do PyPI; binários assinados pela PSF).
  2. Dependências baixadas como wheels win_amd64 / cp313.
  3. Programa em versoes/<versão>/buscacarros + iniciar.py (escolhe a versão ativa e procura atualizações)
     + ícone + instalar.py / desinstalar.py.
  4. Tudo vai para BuscaCarro-Instalador/ (Instalar.bat, LEIA-ME.txt, programa/) dentro do zip.
A versão vem de buscacarros/__init__.py. BASE muda só quando o Python ou as dependências mudam: aí as
atualizações automáticas avisam que é preciso rodar o instalador novo.
"""
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

AQUI = Path(__file__).resolve().parent
PROJETO = AQUI.parent
TRABALHO = AQUI / 'construcao'
PASTA_ZIP = TRABALHO / 'BuscaCarro-Instalador'
PAYLOAD = PASTA_ZIP / 'programa'
SAIDA = AQUI / 'saida'
VERSAO = re.search(r"__version__\s*=\s*'([^']+)'", (PROJETO / 'buscacarros' / '__init__.py').read_text(encoding='utf-8')).group(1)
BASE = 1  # geração do Python embutido + dependências (ver atualizacao.json: base_minima)

PY_EMBED = ('python-embed', '3.13.0')
PY_EMBED_SHA256 = '7176a402790181e0f48b34d9391f9c9565f3754b1879f67dce23830e83374e8f'  # data.zip (Python 3.13.2)
# Versões fixas: são o que roda nos PCs (BASE 1, testado no Windows em out/2026). As atualizações
# automáticas só trocam o código do programa; mudar algo aqui exige aumentar BASE e reinstalar.
PACOTES = ('playwright==1.63.0', 'pyee==13.0.1', 'greenlet==3.5.6', 'requests==2.34.2', 'urllib3==2.8.0',
           'certifi==2026.7.22', 'charset_normalizer==3.5.2', 'idna==3.20', 'typing_extensions==4.16.0')
PTH = 'python313.zip\n.\nLib\\site-packages\n..\nimport site\n'


def rodar(*cmd, **kw):
    print('$', ' '.join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def python_embutido():
    destino = PAYLOAD / 'python'
    baixa = TRABALHO / 'download'
    baixa.mkdir(parents=True, exist_ok=True)
    sdist = baixa / 'python_embed.tar.gz'
    if not sdist.exists():
        meta = json.load(urllib.request.urlopen(f'https://pypi.org/pypi/{PY_EMBED[0]}/{PY_EMBED[1]}/json', timeout=60))
        url = next(u['url'] for u in meta['urls'] if u['url'].endswith('.tar.gz'))
        sdist.write_bytes(urllib.request.urlopen(url, timeout=300).read())
    with tarfile.open(sdist) as tf:
        membro = next(m for m in tf.getmembers() if m.name.endswith('python_embed/data.zip'))
        dados = tf.extractfile(membro).read()
    if hashlib.sha256(dados).hexdigest() != PY_EMBED_SHA256:
        sys.exit('O pacote do Python embutível mudou (SHA-256 diferente). Confira antes de seguir.')
    with zipfile.ZipFile(io.BytesIO(dados)) as z:
        for info in z.infolist():
            if info.is_dir() or not info.filename.startswith('cp313/'):
                continue
            alvo = destino / info.filename[len('cp313/'):]
            alvo.parent.mkdir(parents=True, exist_ok=True)
            alvo.write_bytes(z.read(info))
    (destino / 'python313._pth').write_text(PTH, encoding='ascii', newline='')
    for desnecessario in ('sqlite3.dll', '_sqlite3.pyd'):  # o programa não usa SQLite
        (destino / desnecessario).unlink()
    print('Python embutível: ok')


def dependencias():
    sp = PAYLOAD / 'python' / 'Lib' / 'site-packages'
    sp.mkdir(parents=True, exist_ok=True)
    rodar(sys.executable, '-m', 'pip', 'install', '-q', '--no-compile', '--target', sp,
          '--platform', 'win_amd64', '--python-version', '3.13', '--implementation', 'cp', '--abi', 'cp313',
          '--only-binary=:all:', *PACOTES)
    # partes do Playwright que o programa não usa (visualizador de traces, gravador e tipos TypeScript)
    driver = sp / 'playwright' / 'driver' / 'package'
    for lixo in (sp / 'bin', driver / 'lib' / 'vite', driver / 'types'):
        shutil.rmtree(lixo, ignore_errors=True)
    for d in sp.rglob('__pycache__'):
        shutil.rmtree(d, ignore_errors=True)
    nomes = sorted(p.name for p in sp.glob('*.dist-info'))
    print('Dependências:', ', '.join(n.replace('.dist-info', '') for n in nomes))


def programa():
    versoes = PAYLOAD / 'versoes'
    shutil.copytree(PROJETO / 'buscacarros', versoes / VERSAO / 'buscacarros',
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    (versoes / 'ativa.json').write_text(json.dumps({'versao': VERSAO, 'anterior': None}), encoding='utf-8')
    (PAYLOAD / 'base.json').write_text(json.dumps({'base': BASE, 'instalador': VERSAO}), encoding='utf-8')
    shutil.copyfile(PROJETO / 'iniciar.py', PAYLOAD / 'iniciar.py')
    shutil.copyfile(PROJETO / 'config.exemplo.ini', PAYLOAD / 'config.exemplo.ini')
    for nome in ('LEIA-ME.txt', 'icone.ico', 'instalar.py', 'desinstalar.py', 'Desinstalar.bat'):
        shutil.copyfile(AQUI / nome, PAYLOAD / nome)
    for nome in ('Instalar.bat', 'LEIA-ME.txt'):
        shutil.copyfile(AQUI / nome, PASTA_ZIP / nome)


def instalador():
    SAIDA.mkdir(exist_ok=True)
    arq = SAIDA / 'BuscaCarro-Instalador.zip'
    arquivos = sorted(p for p in PASTA_ZIP.rglob('*') if p.is_file())
    with zipfile.ZipFile(arq, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in arquivos:
            info = zipfile.ZipInfo(p.relative_to(TRABALHO).as_posix(), date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, p.read_bytes(), compresslevel=9)
    maior = max(len(p.relative_to(TRABALHO).as_posix()) for p in arquivos)
    print(f'Instalador: {arq} ({arq.stat().st_size / 1e6:.1f} MB, {len(arquivos)} arquivos, maior caminho {maior})')
    return arq


def main():
    shutil.rmtree(TRABALHO, ignore_errors=True)
    PAYLOAD.mkdir(parents=True)
    if not (AQUI / 'icone.ico').exists():
        rodar(sys.executable, AQUI / 'gerar_icone.py')
    python_embutido()
    dependencias()
    programa()
    return instalador()


if __name__ == '__main__':
    main()
