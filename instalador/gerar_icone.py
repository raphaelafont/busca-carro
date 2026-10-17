"""Gera icone.ico (vários tamanhos) a partir de icone.svg, renderizando no Chromium do Playwright."""
import io
import sys
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

AQUI = Path(__file__).parent
TAMANHOS = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]


def main(destino=AQUI / 'icone.ico'):
    svg = (AQUI / 'icone.svg').read_text(encoding='utf-8')
    imagens = []
    with sync_playwright() as p:
        b = p.chromium.launch(args=['--no-sandbox'])
        for t in TAMANHOS:
            pg = b.new_page(viewport={'width': t, 'height': t}, device_scale_factor=1)
            html = ('<html><body style="margin:0;background:transparent">'
                    + svg.replace('width="512" height="512"', f'width="{t}" height="{t}"') + '</body></html>')
            pg.set_content(html)
            png = pg.screenshot(omit_background=True, clip={'x': 0, 'y': 0, 'width': t, 'height': t})
            imagens.append(Image.open(io.BytesIO(png)).convert('RGBA'))
            pg.close()
        b.close()
    maior = imagens[-1]
    maior.save(destino, format='ICO', sizes=[(t, t) for t in TAMANHOS], append_images=imagens[:-1])
    maior.save(AQUI / 'icone_256.png')
    # prévia lado a lado para conferência
    previa = Image.new('RGBA', (sum(TAMANHOS) + 10 * len(TAMANHOS), 260), (243, 245, 246, 255))
    x = 0
    for im in imagens:
        previa.paste(im, (x, 0), im)
        x += im.width + 10
    previa.save(AQUI / 'icone_previa.png')
    return destino


if __name__ == '__main__':
    print(main(*sys.argv[1:]))
