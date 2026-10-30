async (args, R) => {
  // Executa dentro de uma página seminovos.com.br. R = ritmo das consultas (ritmo.js).
  // As páginas de busca vêm prontas do servidor (20 anúncios por página, ?page=N); os filtros vão no
  // caminho: /carro/<marca>/<modelo>/ano-DE-ATE/preco--MAX/km--MAX/origem-particular|revenda/...
  // Uma busca sem nenhum anúncio responde 404.
  // args: { marcaModelo, filtros, cidade, uf, maxPages, maxItems, pular, maxDetails }
  const sleep = R.sleep;
  const avisar = R.avisar;
  const out = { status: 'ok', total: 0, items: [], avisos: [] };
  const BLOQUEIO = { status: 'bloqueado', erro: 'O site pediu verificação anti-robô.', total: 0, items: [], avisos: [] };
  const parser = new DOMParser();
  const bloqueada = (html) => /captcha|cf-chl|access denied|just a moment/i.test(html.slice(0, 5000));
  const num = (v) => {
    if (v == null) return null;
    const n = parseInt(String(v).replace(/[^\d]/g, ''), 10);
    return isNaN(n) ? null : n;
  };
  const texto = (el) => (el ? el.textContent.replace(/\s+/g, ' ').trim() : '');
  const sAcento = (s) => String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().trim();

  const baixar = async (u, tentativas) => {
    let r;
    try { r = await R.pedir(u, {}, tentativas); } catch (e) {
      throw new Error(e.message === 'LIMITE' ? 'o site limitou as consultas' : e.message);
    }
    if (r.status === 404) return null;
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return await r.text();
  };

  // 1. cidades do site: o filtro de cidade usa o código dela; o estado de cada anúncio sai do nome da cidade
  let cidades = [];
  try {
    const r = await R.pedir('/cidades', { headers: { 'X-Requested-With': 'XMLHttpRequest', Accept: 'application/json' } }, 2);
    if (r.ok) cidades = ((await r.json()) || {}).data || [];
  } catch (e) { /* segue sem: estado vem como desconhecido */ }
  const ufsDaCidade = {};
  for (const c of cidades) (ufsDaCidade[sAcento(c.cidade)] = ufsDaCidade[sAcento(c.cidade)] || []).push(c.sigla);
  const ufDe = (cidade) => {
    const ufs = ufsDaCidade[sAcento(cidade)] || [];
    if (!ufs.length) return null;
    if (args.uf && ufs.includes(args.uf)) return args.uf;
    if (ufs.includes('MG')) return 'MG'; // o site é de Minas: cidade com nome repetido em vários estados é a de MG
    return ufs.length === 1 ? ufs[0] : null;
  };
  let filtroCidade = '';
  if (args.cidade) {
    const c = cidades.find((x) => sAcento(x.cidade) === sAcento(args.cidade) && (!args.uf || x.sigla === args.uf));
    if (c) filtroCidade = '/cidade[]-' + c.idCidade;
    else out.avisos.push('Cidade não encontrada no site; a busca foi feita sem ela e filtrada depois.');
  }

  // 2. o modelo existe no site? (endereço sem filtros; 404 = marca/modelo com outro nome no site)
  let html;
  try { html = await baixar(args.marcaModelo, 3); } catch (e) {
    if (R.desistiu) return BLOQUEIO;
    return { status: 'erro', erro: 'Falha na busca: ' + e.message, total: 0, items: [], avisos: [] };
  }
  if (html === null) {
    return { status: 'ok', erro: 'modelo não encontrado no site', total: 0, items: [], avisos: [] };
  }
  if (bloqueada(html) && !/anuncio-thumb-new/.test(html)) return BLOQUEIO;

  // 3. páginas da busca com os filtros
  const caminho = args.marcaModelo + filtroCidade + args.filtros;
  const vistos = new Set();
  const lerCards = (doc) => {
    const novos = [];
    for (const card of doc.querySelectorAll('.anuncio-thumb-new')) {
      const link = [...card.querySelectorAll('a[href]')].map((a) => a.getAttribute('href')).find((h) => /-\d{5,}$/.test(h || ''));
      if (!link) continue;
      const id = link.match(/-(\d{5,})$/)[1];
      if (vistos.has(id)) continue;
      vistos.add(id);
      const folhas = [...card.querySelectorAll('*')].filter((x) => !x.children.length).map(texto).filter(Boolean);
      const titulo = texto(card.querySelector('h3, .h5, .h-5'));
      const ano = folhas.find((t) => /^\d{4}\/\d{4}$/.test(t));
      const km = folhas.find((t) => /km$/i.test(t) || /^n[aã]o informada$/i.test(t));
      const iAno = folhas.indexOf(ano);
      const preco = folhas.find((t) => /^R\$\s*[\d.]+/.test(t));
      // depois do título vem a versão e o anunciante ("Anunciante particular" ou o nome da loja)
      const iTit = folhas.indexOf(titulo);
      const versao = iTit >= 0 ? folhas[iTit + 1] : '';
      const anunciante = iTit >= 0 ? folhas[iTit + 2] : '';
      // a cidade é o último texto do card (antes vêm botões como "Comparar" e "Favoritar")
      const cidade = folhas.filter((t) => !/^(•|comparar|remover|favoritar|desfavoritar)/i.test(t)).pop() || '';
      const img = card.querySelector('img[src*="seminovos"], img[data-src], img[src]');
      const foto = img ? (img.getAttribute('data-src') || img.getAttribute('src')) : null;
      const [anoFab, anoMod] = ano ? ano.split('/').map((x) => parseInt(x, 10)) : [null, null];
      novos.push({
        site: 'Seminovos BH',
        id: 'sbh-' + id,
        url: 'https://seminovos.com.br' + link,
        titulo: (titulo + ' ' + (versao || '')).trim(),
        versao: versao || null,
        ano_fab: anoFab,
        ano_modelo: anoMod,
        km: km && /km$/i.test(km) ? num(km) : null,
        preco: preco ? Math.round(parseFloat(preco.replace(/[^\d,]/g, '').replace(',', '.'))) : null,
        cidade: cidade || null,
        uf: ufDe(cidade),
        foto: foto && /^https?:/.test(foto) ? foto : null,
        vendedor: /anunciante particular/i.test(anunciante || '') ? 'Particular' : (anunciante ? 'Loja' : null),
        loja: anunciante && !/anunciante particular/i.test(anunciante) ? anunciante : null,
        combustivel: folhas[iAno + 2] || null,
        cambio: folhas[iAno + 3] || null,
        descricao: '',
      });
    }
    return novos;
  };

  for (let p = 1; p <= args.maxPages; p++) {
    if (R.desistiu) break;
    let h;
    try { h = await baixar(caminho + (p > 1 ? '?page=' + p : ''), 4); } catch (e) {
      if (p === 1) {
        if (R.desistiu) return BLOQUEIO;
        return { status: 'erro', erro: 'Falha na busca: ' + e.message, total: 0, items: [], avisos: out.avisos };
      }
      out.avisos.push('Parou na página ' + p + ': ' + e.message);
      break;
    }
    if (h === null) break; // sem anúncios com esses filtros (ou passou da última página)
    const doc = parser.parseFromString(h, 'text/html');
    if (p === 1) {
      const m = doc.body.textContent.match(/(\d[\d.]*)\s*AN[UÚ]NCIOS/i);
      out.total = m ? num(m[1]) : 0;
    }
    const novos = lerCards(doc);
    out.items.push(...novos);
    const paginas = Math.ceil((out.total || 0) / 20);
    avisar('Página ' + p + (paginas ? ' de ' + Math.min(paginas, args.maxPages) : '') + ' lida: ' + out.items.length + ' anúncios');
    if (!novos.length || out.items.length >= args.maxItems || p >= paginas) break;
    await sleep(R.entrePaginas());
  }
  out.items = out.items.slice(0, args.maxItems);

  // 4. descrição e acessórios (blindagem): só dos anúncios ainda não lidos em rodadas anteriores
  const pular = new Set(args.pular || []);
  const fila = out.items.filter((it) => !pular.has(it.id.replace('sbh-', ''))).slice(0, args.maxDetails);
  let i = 0, feitos = 0;
  if (fila.length) avisar('Lendo descrições dos anúncios: 0 de ' + fila.length);
  const worker = async (n) => {
    while (i < fila.length) {
      if (R.desistiu || (n > 0 && R.calmo)) return;
      const it = fila[i++];
      try {
        const h = await baixar(new URL(it.url).pathname, 2);
        if (h) {
          const doc = parser.parseFromString(h, 'text/html');
          const desc = doc.querySelector('.description-print');
          const acess = [...new Set([...doc.querySelectorAll('.section-acessorios li')].map(texto).filter(Boolean))];
          it.descricao = desc ? desc.textContent.replace(/[ \t]+/g, ' ').replace(/\n\s*\n+/g, '\n').trim() : '';
          it.atributos = acess.slice(0, 60);
          it.blindado = acess.some((a) => /blindad/i.test(a)) ? true : null;
          it._det = true;
        }
      } catch (e) { /* fica para a próxima rodada */ }
      feitos++;
      avisar('Lendo descrições dos anúncios: ' + feitos + ' de ' + fila.length);
      if (i < fila.length) await sleep(R.intervalo());
    }
  };
  await Promise.all(Array.from({ length: R.workers() }, (_, n) => worker(n)));
  const falta = fila.filter((it) => !it._det).length;
  if (falta && R.st.limitacoes) out.avisos.push(falta + ' anúncios ficaram sem descrição (o site limitou as consultas); serão lidos na próxima rodada.');
  return out;
}
