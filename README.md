# Busca Carro

Procura um carro usado na Webmotors, na OLX e no Mercado Livre, compara cada anúncio com a tabela FIPE e
gera um relatório com filtros e ordenação (e um e-mail com os melhores abaixo da FIPE). Roda no Windows de
cada pessoa, sozinho a cada 2 dias ou quando ela mandar pelo painel.

**Baixar o instalador (sempre a versão mais recente):**
https://github.com/raphaelafont/busca-carro/releases/latest/download/BuscaCarro-Instalador.exe

Depois de instalado, o programa se atualiza sozinho: a cada vez que o painel abre ou a busca automática
começa, ele confere se há versão nova aqui e, se houver, baixa, testa e passa a usá-la.

## Como funciona a atualização

- O instalador põe o Python embutido, o Playwright e o programa em `%LOCALAPPDATA%\BuscaCarro`.
  O código fica em `versoes\<versão>\buscacarros`; `versoes\ativa.json` diz qual versão usar.
- `iniciar.py` (estável, só muda com o instalador) é o que os atalhos e a tarefa agendada chamam:
  procura atualização num processo separado, com tempo limite, e abre a versão ativa. Se ela não carregar,
  volta para a anterior.
- `buscacarros/atualizador.py` lê `releases/latest/download/atualizacao.json`. Ele recusa o pacote se
  tamanho ou SHA-256 não conferirem ou se o zip tiver caminhos perigosos. Testa a versão nova num processo
  separado antes de ativá-la; uma versão que não carrega não é tentada de novo.
- `BASE` em `instalador/construir.py` só muda quando o Python ou as dependências mudam. Aí os PCs não
  se atualizam sozinhos: o painel avisa e mostra o link do instalador.
- Dados de cada pessoa (`config.ini` com a senha de app do Gmail, `buscas.json`, `dados\`, `logs\`,
  `resultados\`) ficam só no PC dela e nunca vêm para cá.

## Publicar uma versão nova

1. Faça a mudança e aumente `__version__` em `buscacarros/__init__.py` (ex.: 1.3.0 → 1.3.1).
2. `python testes/teste_memoria.py` e `python testes/teste_atualizacao.py`.
3. Commit e push.
4. `python publicar.py --notas "O que mudou, em uma ou duas frases"`

`publicar.py` roda os testes e gera o pacote, o `atualizacao.json` e o instalador completo. Depois cria a
release `v<versão>` como rascunho, envia os três arquivos e só então a torna pública. Assim os PCs nunca
veem uma versão pela metade. Precisa de `makensis` (pacote nsis), Pillow e um token do GitHub
(`GITHUB_TOKEN` ou `gh auth login`).

## Estrutura

- `buscacarros/`: o programa.
  - `principal.py`: rodada.
  - `painel.py` e `modelos/painel.html`: painel local em 127.0.0.1.
  - `sites/`: leitores de cada site (`sites/js/*.js` rodam dentro das páginas; `ritmo.js` controla o
    ritmo das consultas).
  - `memoria.py`: memória entre rodadas para consultar os sites o mínimo possível.
  - `fipe.py`, `analise.py`, `relatorio.py`, `email_envio.py`.
  - `atualizador.py`: atualização automática.
- `iniciar.py`: iniciador instalado na raiz da instalação.
- `instalador/`: `construir.py` (monta o instalador NSIS no Linux), `BuscaCarro.nsi`, ícone e scripts
  do Windows.
- `testes/`: testes que rodam sem internet.
- Notas de projeto (decisões e como cada site é lido) ficam fora do repositório, no projeto "Buscador de Carros" do Claude.
