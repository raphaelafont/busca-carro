async (args, R) => {
  // Executa dentro de uma página www.olx.com.br. R = ritmo das consultas (ritmo.js).
  // args: { marcaPath, modeloSlug, modeloTexto, sufixo, query, maxPages, maxItems }
  const sleep = R.sleep;
  const avisar = R.avisar;
  const out = { status: 'ok', total: 0, items: [], avisos: [] };

  const decode = (html) => {
    let s = '';
    const re = /self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)/gs;
    let m;
    while ((m = re.exec(html))) { try { s += JSON.parse(m[1]); } catch (e) { /* ignora */ } }
    return s;
  };
  const extractArray = (s, key) => {
    const k = '"' + key + '":[';
    const i = s.indexOf(k);
    if (i < 0) return null;
    let d = 0, j = i + k.length - 1, inStr = false;
    for (; j < s.length; j++) {
      const c = s[j];
      if (inStr) { if (c === '\\') { j++; continue; } if (c === '"') inStr = false; continue; }
      if (c === '"') { inStr = true; continue; }
      if (c === '[' || c === '{') d++;
      else if (c === ']' || c === '}') { d--; if (d === 0) break; }
    }
    try { return JSON.parse(s.slice(i + k.length - 1, j + 1)); } catch (e) { return null; }
  };
  const prop = (ad, name) => {
    const p = (ad.properties || []).find((x) => x.name === name);
    return p ? p.value : null;
  };
  const num = (v) => {
    if (v == null) return null;
    const n = parseInt(String(v).replace(/[^\d]/g, ''), 10);
    return isNaN(n) ? null : n;
  };

  const baixar = async (u, tentativas) => {
    let r;
    try { r = await R.pedir(u, {}, tentativas); } catch (e) {
      throw new Error(e.message === 'LIMITE' ? 'o site limitou as consultas' : e.message);
    }
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return await r.text();
  };
  const bloqueada = (html) => /captcha|challenge|access denied|cf-chl/i.test(html);
  const totalDe = (s) => { const t = s.match(/"totalOfAds":(\d+)/); return t ? parseInt(t[1], 10) : null; };
  const BLOQUEIO = { status: 'bloqueado', erro: 'O site pediu verificação anti-robô.', total: 0, items: [], avisos: [] };

  // 1. Modelos da marca no nome que a OLX usa no endereço (ex.: "Haval H6" -> "haval", "Ora" -> "ora").
  //    Com um modelo que ela não conhece, a OLX mostraria a marca inteira; por isso a conferência.
  let htmlMarca;
  try { htmlMarca = await baixar(args.marcaPath + args.sufixo + args.query, 3); } catch (e) {
    if (R.desistiu) return BLOQUEIO;
    return { status: 'erro', erro: 'Falha na busca: ' + e.message, total: 0, items: [], avisos: [] };
  }
  const sMarca = decode(htmlMarca);
  if (!extractArray(sMarca, 'ads')) {
    if (bloqueada(htmlMarca)) return BLOQUEIO;
    return { status: 'erro', erro: 'Estrutura da página mudou (lista de anúncios não encontrada).', total: 0, items: [], avisos: [] };
  }
  const totalMarca = totalDe(sMarca);
  if (totalMarca === 0) { out.avisos.push('Nenhum anúncio de ' + args.modeloTexto + ' na OLX com esses filtros.'); return out; }
  const escRe = args.marcaPath.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const reModelo = new RegExp(escRe + '/([a-z0-9-]+)(?=[/?"\\\\#&]|$)', 'g');
  const slugs = new Set();
  let mm;
  while ((mm = reModelo.exec(htmlMarca))) {
    if (!/^(\d{4}|estado-.*|ddd-.*|regiao-.*)$/.test(mm[1])) slugs.add(mm[1]);
  }
  const alvo = args.modeloSlug;
  let escolhidos = [];
  if (slugs.has(alvo)) escolhidos = [alvo];
  else {
    const amplo = [...slugs].filter((x) => alvo.startsWith(x + '-')).sort((a, b) => b.length - a.length);
    const estreito = [...slugs].filter((x) => x.startsWith(alvo + '-'));
    escolhidos = amplo.length ? [amplo[0]] : estreito;
  }
  if (!escolhidos.length) {
    try {  // o modelo pode não aparecer entre os links da página: confere pelo total de anúncios
      await sleep(R.entrePaginas());
      const t = totalDe(decode(await baixar(args.marcaPath + '/' + alvo + args.sufixo + args.query)));
      if (t !== null && totalMarca !== null && (t < totalMarca || slugs.size <= 1)) escolhidos = [alvo];
    } catch (e) { /* sem conferência */ }
  }
  if (!escolhidos.length) {
    out.avisos.push('Nenhum anúncio de ' + args.modeloTexto + ' na OLX com esses filtros.');
    return out;
  }

  // 2. Anúncios de cada modelo, página por página
  let ads = [];
  const vistos = new Set();
  for (const slugModelo of escolhidos) {
    const listPath = args.marcaPath + '/' + slugModelo + args.sufixo + args.query;
    const sep = listPath.includes('?') ? '&' : '?';
    let totalDeste = 0, lidos = 0;
    for (let p = 1; p <= args.maxPages; p++) {
      const u = listPath + (p > 1 ? sep + 'o=' + p : '');
      let html;
      await sleep(R.entrePaginas());
      try { html = await baixar(u); } catch (e) {
        if (p === 1 && !ads.length) {
          if (R.desistiu) return BLOQUEIO;
          return { status: 'erro', erro: 'Falha na busca: ' + e.message, total: 0, items: [], avisos: [] };
        }
        out.avisos.push('Página ' + p + ' falhou: ' + e.message);
        break;
      }
      const sp = decode(html);
      const lista = extractArray(sp, 'ads');
      if (!lista) {
        if (p === 1 && !ads.length) return bloqueada(html) ? BLOQUEIO : { status: 'erro', erro: 'Estrutura da página mudou (lista de anúncios não encontrada).', total: 0, items: [], avisos: [] };
        break;
      }
      if (p === 1) { totalDeste = totalDe(sp) || 0; out.total += totalDeste; }
      const novos = lista.filter((a) => a && a.subject && a.listId && !vistos.has(a.listId));
      if (!novos.length) break;
      novos.forEach((a) => vistos.add(a.listId));
      ads = ads.concat(novos);
      lidos += novos.length;
      avisar((escolhidos.length > 1 ? slugModelo + ': ' : '') + 'página ' + p + ' lida: ' + lidos + ' de ' + totalDeste + ' anúncios');
      if (ads.length >= args.maxItems || lidos >= totalDeste) break;
    }
    if (ads.length >= args.maxItems) break;
  }
  if (out.total > ads.length && ads.length >= args.maxItems) {
    out.avisos.push('Limite de ' + args.maxItems + ' anúncios atingido (o site tinha ' + out.total + ').');
  }
  ads = ads.slice(0, args.maxItems);

  for (const a of ads) {
    const ld = a.locationDetails || {};
    const feats = String(prop(a, 'car_features') || '');
    const attrs = [];
    if (prop(a, 'owner') === 'Sim') attrs.push('Único dono');
    if (prop(a, 'has_paid_ipva') === 'Sim') attrs.push('IPVA pago');
    if (prop(a, 'exchange') === 'Sim') attrs.push('Aceita troca');
    const url = String(a.url || '').split('?')[0].split('#')[0];
    const img = a.images && a.images[0] ? (a.images[0].original || a.images[0].originalWebp) : (a.thumbnail || null);
    out.items.push({
      site: 'OLX',
      id: 'olx-' + a.listId,
      url: url,
      titulo: a.subject,
      marca: prop(a, 'vehicle_brand'),
      modelo: null,
      versao: prop(a, 'vehicle_model') || a.subject,
      ano_fab: null,
      ano_modelo: num(prop(a, 'regdate')),
      km: num(prop(a, 'mileage')),
      preco: num(a.price || a.priceValue),
      cidade: ld.municipality || null,
      uf: ld.uf || null,
      foto: img,
      descricao: '',
      vendedor: a.professionalAd ? 'Loja' : 'Particular',
      cambio: prop(a, 'gearbox'),
      combustivel: prop(a, 'fuel'),
      blindado: /blindad/i.test(feats) ? true : null,
      leilao: prop(a, 'has_auction') === 'Sim' ? true : (prop(a, 'has_auction') === 'Não' ? false : null),
      atributos: attrs,
      cor: prop(a, 'carcolor'),
      fipe_site: null,
      fipe_site_tipo: null,
      publicado: a.date ? new Date(a.date * 1000).toISOString() : null,
    });
  }
  return out;
}
