async (args, R) => {
  // Executa dentro de uma página lista.mercadolivre.com.br. R = ritmo das consultas (ritmo.js).
  // args: { basePath, blindado: 'sim'|'nao'|null, cambio: 'automatico'|'manual'|null, maxPages, maxItems }
  const sleep = R.sleep;
  const avisar = R.avisar;
  const out = { status: 'ok', total: 0, items: [], avisos: [] };

  const extractObj = (s, from) => {
    let d = 0, j = from, inStr = false;
    for (; j < s.length; j++) {
      const c = s[j];
      if (inStr) { if (c === '\\') { j++; continue; } if (c === '"') inStr = false; continue; }
      if (c === '"') { inStr = true; continue; }
      if (c === '[' || c === '{') d++;
      else if (c === ']' || c === '}') { d--; if (d === 0) break; }
    }
    return JSON.parse(s.slice(from, j + 1));
  };
  const estado = async (path) => {
    let r;
    try { r = await R.pedir(path, {}, 4); } catch (e) { throw new Error(e.message === 'LIMITE' ? 'BLOQUEIO' : e.message); }
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const h = await r.text();
    const k = h.indexOf('_n.ctx.r=');
    if (k < 0) {
      const bloqueio = /captcha|challenge|access denied/i.test(h);
      throw new Error(bloqueio ? 'BLOQUEIO' : 'Estrutura da página mudou');
    }
    return extractObj(h, h.indexOf('{', k)).appProps.pageProps.initialState;
  };
  const filtros = (init) => {
    const res = {};
    (function walk(o) {
      if (!o || typeof o !== 'object') return;
      if (o.id && Array.isArray(o.values) && (o.name || o.label)) {
        res[o.id] = o.values.map((v) => ({ name: v.name || v.label || '', url: v.url || '' }));
        return;
      }
      for (const k in o) walk(o[k]);
    })(init.sidebar || init);
    return res;
  };
  const cards = (init) => {
    const c = [];
    (function walk(o) {
      if (!o || typeof o !== 'object') return;
      if (o.polycard) { c.push(o.polycard); return; }
      for (const k in o) walk(o[k]);
    })(init.results);
    return c;
  };
  const caminho = (u) => {
    const x = String(u || '').split('#')[0];
    return x.replace(/^https?:\/\/[^/]+/, '');
  };
  const proxima = (init) => {
    const pg = init.pagination;
    if (!pg || !Array.isArray(pg.pagination_nodes_url)) return null;
    const alvo = String((pg.selected_page || 1) + 1);
    const n = pg.pagination_nodes_url.find((x) => String(x.value) === alvo);
    if (n && n.url) return caminho(n.url);
    if (pg.next_page && pg.next_page.url) return caminho(pg.next_page.url);
    return null;
  };

  let init;
  try { init = await estado(args.basePath); } catch (e) {
    return { status: e.message === 'BLOQUEIO' ? 'bloqueado' : 'erro', erro: e.message === 'BLOQUEIO' ? 'O site pediu verificação anti-robô.' : 'Falha na busca: ' + e.message, total: 0, items: [], avisos: [] };
  }

  avisar('Página de busca aberta; aplicando filtros');
  // Filtro de blindagem (segue o link do próprio site, que mantém os demais filtros)
  if (args.blindado === 'sim' || args.blindado === 'nao') {
    const f = filtros(init).ARMORED || [];
    const re = args.blindado === 'sim' ? /^é blindado/i : /^não é blindado/i;
    const v = f.find((x) => re.test(x.name.trim()));
    if (v) {
      await sleep(R.entrePaginas());
      try { init = await estado(caminho(v.url)); } catch (e) { out.avisos.push('Filtro de blindagem falhou; filtrado depois.'); }
    } else if (args.blindado === 'sim') {
      return out; // nenhum blindado disponível nesta busca
    } else {
      out.avisos.push('Filtro de blindagem indisponível; filtrado depois.');
    }
  }

  // Câmbio: pode haver mais de um valor (ex.: "Automática" e "Automática sequencial")
  let pontos = [{ path: null, init }];
  if (args.cambio === 'automatico' || args.cambio === 'manual') {
    const f = filtros(init).TRANSMISSION || [];
    const re = args.cambio === 'automatico' ? /autom|cvt/i : /manual/i;
    const vals = f.filter((x) => re.test(x.name));
    if (vals.length) pontos = vals.map((v) => ({ path: caminho(v.url), init: null }));
    else if (f.length) return out; // há filtro de câmbio, mas nenhum do tipo pedido
  }

  const vistos = new Set();
  const lista = [];
  for (const pt of pontos) {
    let atual = pt.init;
    let path = pt.path;
    for (let p = 1; p <= args.maxPages; p++) {
      if (!atual) {
        await sleep(R.entrePaginas());
        try { atual = await estado(path); } catch (e) { out.avisos.push('Página falhou: ' + e.message); break; }
      }
      for (const c of cards(atual)) {
        const m = c.metadata || {};
        if (m.is_pad === 'true' || m.is_pad === true) continue; // anúncio patrocinado fora do filtro
        if (!m.id || vistos.has(m.id)) continue;
        vistos.add(m.id);
        lista.push(c);
      }
      avisar('Página ' + p + (pontos.length > 1 ? ' (câmbio ' + (pontos.indexOf(pt) + 1) + ' de ' + pontos.length + ')' : '') + ' lida: ' + lista.length + ' anúncios');
      if (lista.length >= args.maxItems) break;
      const prox = proxima(atual);
      if (!prox) break;
      path = prox;
      atual = null;
    }
    if (lista.length >= args.maxItems) { out.avisos.push('Limite de ' + args.maxItems + ' anúncios atingido.'); break; }
  }
  out.total = lista.length;

  for (const c of lista.slice(0, args.maxItems)) {
    const comp = (t) => (c.components || []).find((x) => x.type === t);
    const titulo = comp('title') ? comp('title').title.text : '';
    const preco = comp('price') ? comp('price').price.current_price.value : null;
    const at = comp('attributes_list') ? comp('attributes_list').attributes_list.texts : [];
    const loc = comp('location') ? comp('location').location.text : '';
    const pic = c.pictures && c.pictures.pictures && c.pictures.pictures[0] ? c.pictures.pictures[0].id : null;
    let url = String(c.metadata.url || '');
    if (url && !/^https?:/.test(url)) url = 'https://' + url;
    url = url.split('#')[0].split('?')[0];
    const ano = at.find((x) => /^\d{4}$/.test(String(x).trim()));
    const km = at.find((x) => /km/i.test(String(x)));
    out.items.push({
      site: 'Mercado Livre',
      id: 'ml-' + c.metadata.id,
      url: url,
      titulo: titulo,
      marca: null,
      modelo: null,
      versao: titulo,
      ano_fab: null,
      ano_modelo: ano ? parseInt(ano, 10) : null,
      km: km ? parseInt(String(km).replace(/[^\d]/g, ''), 10) : null,
      preco: preco,
      cidade: loc,
      uf: null,
      foto: pic ? 'https://http2.mlstatic.com/D_NQ_NP_' + pic + '-O.webp' : null,
      descricao: '',
      vendedor: null,
      cambio: null,
      combustivel: null,
      blindado: args.blindado === 'sim' ? true : null,
      leilao: null,
      atributos: [],
      cor: null,
      fipe_site: null,
      fipe_site_tipo: null,
      publicado: null,
    });
  }
  return out;
}
