async (args, R) => {
  // Executa dentro de uma página napista.com.br. R = ritmo das consultas (ritmo.js).
  // A busca do NaPista é em linguagem natural no endereço (/busca/honda-fit-automatico-a-partir-de-2015-em-sp);
  // cada página traz os anúncios no __NEXT_DATA__ (48 por página, ?pn=N). Só lojas anunciam no NaPista.
  // args: { termos, maxPages, maxItems, pular, maxDetails }
  const sleep = R.sleep;
  const avisar = R.avisar;
  const out = { status: 'ok', total: 0, items: [], avisos: [], termos: null };
  const BLOQUEIO = { status: 'bloqueado', erro: 'O site pediu verificação anti-robô.', total: 0, items: [], avisos: [] };

  const baixar = async (u, tentativas) => {
    let r;
    try { r = await R.pedir(u, {}, tentativas); } catch (e) {
      throw new Error(e.message === 'LIMITE' ? 'o site limitou as consultas' : e.message);
    }
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return await r.text();
  };
  const dados = (html) => {
    const m = html.match(/<script id="__NEXT_DATA__"[^>]*>([\s\S]*?)<\/script>/);
    if (!m) return null;
    try { return JSON.parse(m[1]).props.pageProps; } catch (e) { return null; }
  };
  const foto = (o) => {
    const p = (o.photos || [])[0];
    if (!p) return null;
    const u = typeof p === 'string' ? p : (p.url || p.path || p.src || p.photoUrl || null);
    if (!u) return null;
    return /^https?:/.test(u) ? u : 'https://img.napista.com.br/' + String(u).replace(/^\//, '');
  };

  const caminho = '/busca/' + args.termos;
  for (let p = 1; p <= args.maxPages; p++) {
    if (R.desistiu) break;
    let pp;
    try {
      const h = await baixar(caminho + (p > 1 ? '?pn=' + p : ''), 4);
      pp = dados(h);
      if (!pp) {
        if (p === 1 && /captcha|cf-chl|access denied/i.test(h.slice(0, 5000))) return BLOQUEIO;
        throw new Error('página sem dados');
      }
    } catch (e) {
      if (p === 1) {
        if (R.desistiu) return BLOQUEIO;
        return { status: 'erro', erro: 'Falha na busca: ' + e.message, total: 0, items: [], avisos: [] };
      }
      out.avisos.push('Parou na página ' + p + ': ' + e.message);
      break;
    }
    const sr = pp.searchResult || {};
    if (p === 1) {
      out.total = sr.offersTotal || 0;
      out.termos = sr.nlTerms || null; // como o site entendeu a busca
    }
    const offers = sr.offers || [];
    for (const o of offers) {
      const loc = o.location || {};
      out.items.push({
        site: 'NaPista',
        id: 'np-' + o.id,
        url: 'https://napista.com.br/anuncios/' + o.id,
        titulo: o.versionName || ((o.makeName || '') + ' ' + (o.modelName || '')).trim(),
        marca: o.makeName || null,
        modelo: o.modelName || null,
        versao: o.compVersionName || o.versionName || null,
        ano_fab: o.manufacturedYear || null,
        ano_modelo: o.modelYear || null,
        km: o.mileage != null ? Math.round(o.mileage) : null,
        preco: o.price || null,
        cidade: loc.city || null,
        uf: loc.uf || null,
        foto: foto(o),
        vendedor: 'Loja',
        loja: o.seller || null,
        atributos: (o.equipments || []).map((x) => (typeof x === 'string' ? x : x && (x.name || x.description))).filter(Boolean),
        descricao: '',
        publicado: o.createdDate || null,
      });
    }
    const paginas = Math.ceil(out.total / 48);
    avisar('Página ' + p + (paginas ? ' de ' + Math.min(paginas, args.maxPages) : '') + ' lida: ' + out.items.length + ' anúncios');
    if (!offers.length || out.items.length >= args.maxItems || p >= paginas) break;
    await sleep(R.entrePaginas());
  }
  out.items = out.items.slice(0, args.maxItems);

  // descrição, câmbio, combustível e blindagem: página de cada anúncio, só dos ainda não lidos
  const pular = new Set(args.pular || []);
  const fila = out.items.filter((it) => !pular.has(it.id.replace('np-', ''))).slice(0, args.maxDetails);
  let i = 0, feitos = 0;
  if (fila.length) avisar('Lendo descrições dos anúncios: 0 de ' + fila.length);
  const nome = (v) => (v == null ? null : typeof v === 'string' ? v : (v.name || v.description || v.label || v.value || null));
  const worker = async (n) => {
    while (i < fila.length) {
      if (R.desistiu || (n > 0 && R.calmo)) return;
      const it = fila[i++];
      try {
        const pp = dados(await baixar('/anuncios/' + it.id.replace('np-', ''), 2));
        const o = pp && pp.offer && pp.offer.offer;
        if (o) {
          it.descricao = String(o.description || '').trim();
          it.blindado = typeof o.armoured === 'boolean' ? o.armoured : null;
          it.cambio = nome(o.transmissionType);
          it.combustivel = nome(o.fuelType) || (pp.offer.modelDetails && pp.offer.modelDetails.fuelType) || null;
          it.cor = nome(o.color);
          const fipe = pp.offer.pricingDetails && pp.offer.pricingDetails.fipePrice;
          if (fipe) { it.fipe_site = fipe; it.fipe_site_tipo = 'informada'; }
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
