"""Monta o instalador único do Busca Carro (BuscaCarro-Instalador.exe).

Roda em Linux com: python3, pip, makensis (pacote nsis) e Playwright (só para gerar o ícone).
Passos:
  1. Python 3.13 embutível oficial para Windows (pacote python-embed do PyPI; binários assinados pela PSF).
  2. Dependências (playwright, openpyxl, requests) baixadas como wheels win_amd64 / cp313.
  3. Programa em versoes/<versão>/buscacarros + iniciar.py (escolhe a versão ativa e procura atualizações)
     + ícone + scripts auxiliares.
  4. makensis gera o .exe.
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

from PIL import Image

AQUI = Path(__file__).resolve().parent
PROJETO = AQUI.parent
TRABALHO = AQUI / 'construcao'
PAYLOAD = TRABALHO / 'payload'
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
    for nome in ('LEIA-ME.txt', 'agendar.ps1', 'parar.ps1', 'icone.ico'):
        shutil.copyfile(AQUI / nome, PAYLOAD / nome)


def imagem_lateral():
    """Imagem 164x314 das páginas de boas-vindas/conclusão do instalador."""
    w, h = 164, 314
    img = Image.new('RGB', (w, h))
    topo, base = (0x21, 0x69, 0xCC), (0x10, 0x3F, 0x86)
    for y in range(h):
        t = y / (h - 1)
        cor = tuple(round(topo[i] + (base[i] - topo[i]) * t) for i in range(3))
        for x in range(w):
            img.putpixel((x, y), cor)
    icone = Image.open(AQUI / 'icone_256.png').convert('RGBA').resize((128, 128), Image.LANCZOS)
    img.paste(icone, ((w - 128) // 2, 70), icone)
    img.save(TRABALHO / 'lateral.bmp', format='BMP')


def instalador():
    SAIDA.mkdir(exist_ok=True)
    for nome in ('BuscaCarro.nsi', 'icone.ico', 'parar.ps1'):
        shutil.copyfile(AQUI / nome, TRABALHO / nome)
    exe = SAIDA / 'BuscaCarro-Instalador.exe'
    rodar(os.environ.get('MAKENSIS', 'makensis'), '-V2', f'-DVERSAO={VERSAO}', '-DPAYLOAD=payload', f'-DSAIDA={exe}', 'BuscaCarro.nsi',
          cwd=TRABALHO)
    print(f'Instalador: {exe} ({exe.stat().st_size / 1e6:.1f} MB)')
    return exe


def main():
    shutil.rmtree(TRABALHO, ignore_errors=True)
    PAYLOAD.mkdir(parents=True)
    if not (AQUI / 'icone.ico').exists():
        rodar(sys.executable, AQUI / 'gerar_icone.py')
    python_embutido()
    dependencias()
    programa()
    imagem_lateral()
    return instalador()


if __name__ == '__main__':
    main()
