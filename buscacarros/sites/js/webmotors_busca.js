async (args, R) => {
  // Executa dentro de uma página www.webmotors.com.br. R = ritmo das consultas (ritmo.js).
  // args: { baseUrl (sem modelo e sem câmbio), cambioParam, modelo, maxPages, maxItems, maxDetails,
  //         pular: [UniqueId de anúncios cuja descrição já está guardada] }
  const sleep = R.sleep;
  const avisar = R.avisar;
  const out = { status: 'ok', total: 0, items: [], avisos: [] };
  const slug = (v) => String(v || '').normalize('NFD').replace(/[̀-ͯ]/g, '')
    .toLowerCase().replace(/\./g, '').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
  const norm = (v) => String(v || '').normalize('NFD').replace(/[̀-ͯ]/g, '')
    .toUpperCase().replace(/[-_./]/g, ' ').replace(/\s+/g, ' ').trim();
  const apiUrl = (u, p, menu) => '/api/search/car?url=' + encodeURIComponent(u) + '&actualPage=' + p +
    '&displayPerPage=24&order=1&showMenu=' + (menu ? 'true' : 'false') +
    '&showCount=true&showBreadCrumb=false&testAB=false&returnUrl=false';
  const getJson = async (u, tentativas) => {
    // o site responde 403/429 quando as consultas ficam rápidas demais: o ritmo pausa e segue mais devagar
    let r;
    try { r = await R.pedir(u, { headers: { Accept: 'application/json' } }, tentativas); } catch (e) {
      throw new Error(e.message === 'LIMITE' ? 'o site limitou as consultas' : e.message);
    }
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return await r.json();
  };

  // 1. Catálogo de modelos da marca, no nome exato que o site usa (ex.: "Ora" -> "ORA 03" e "ORA 5")
  let usarCambio = !!args.cambioParam;
  let base;
  try {
    base = await getJson(apiUrl(args.baseUrl + (usarCambio ? args.cambioParam : ''), 1, true), 3);
    if (typeof base.Count !== 'number' && usarCambio) {
      out.avisos.push('Filtro de câmbio não aceito pelo site; o câmbio foi filtrado depois da coleta.');
      usarCambio = false;
      base = await getJson(apiUrl(args.baseUrl, 1, true));
    }
  } catch (e) {
    if (R.desistiu) return { status: 'bloqueado', erro: 'O site limitou as consultas.', total: 0, items: [], avisos: out.avisos };
    return { status: 'erro', erro: 'Falha na busca: ' + e.message, total: 0, items: [], avisos: out.avisos };
  }
  const filtroMarca = Object.values(base.Filters || {}).find((f) => f.name === 'Make');
  const marca = filtroMarca && (filtroMarca.items || []).find((i) => i.selected);
  const catalogo = marca && Array.isArray(marca.items) ? marca.items.map((m) => m.name).filter(Boolean) : null;
  let modelos;
  if (!catalogo) {
    modelos = [String(args.modelo).toUpperCase()];
  } else {
    const alvo = norm(args.modelo);
    const junto = (x) => x.replace(/ /g, '');
    modelos = catalogo.filter((m) => norm(m) === alvo || junto(norm(m)) === junto(alvo));
    if (!modelos.length) modelos = catalogo.filter((m) => norm(m).startsWith(alvo + ' '));
    if (!modelos.length) {
      out.avisos.push('Nenhum anúncio de ' + args.modelo + ' na Webmotors com esses filtros.');
      return out;
    }
  }
  if (catalogo && modelos.length > 1) avisar('Modelos encontrados no site: ' + modelos.join(', '));

  // 2. Busca de cada modelo, página por página
  let results = [];
  for (const nomeModelo of modelos) {
    const url = args.baseUrl + '&modelo1=' + encodeURIComponent(nomeModelo) + (usarCambio ? args.cambioParam : '');
    let first;
    try {
      first = await getJson(apiUrl(url, 1, false));
    } catch (e) {
      out.avisos.push(nomeModelo + ': ' + e.message);
      continue;
    }
    const total = typeof first.Count === 'number' ? first.Count : 0;
    out.total += total;
    let deste = first.SearchResults || [];
    const pageTotal = Math.min((first.Pagination && first.Pagination.PageTotal) || 1, args.maxPages);
    avisar((modelos.length > 1 ? nomeModelo + ': ' : '') + total + ' anúncios no site; página 1 de ' + pageTotal + ' lida');
    for (let p = 2; p <= pageTotal && results.length + deste.length < args.maxItems; p++) {
      await sleep(R.entrePaginas());
      try {
        const j = await getJson(apiUrl(url, p, false));
        const r = j.SearchResults || [];
        if (!r.length) break;
        deste = deste.concat(r);
        avisar((modelos.length > 1 ? nomeModelo + ': ' : '') + 'página ' + p + ' de ' + pageTotal + ' lida (' + deste.length + ' anúncios)');
      } catch (e) {
        out.avisos.push((modelos.length > 1 ? nomeModelo + ', ' : '') + 'página ' + p + ' falhou: ' + e.message);
        break;
      }
    }
    results = results.concat(deste);
    if (modelos.length > 1) await sleep(R.entrePaginas());
  }
  if (out.total > results.length && results.length >= args.maxItems) {
    out.avisos.push('Limite de ' + args.maxItems + ' anúncios atingido (o site tinha ' + out.total + ').');
  }
  results = results.slice(0, args.maxItems);

  const detailPath = (r) => {
    const s = r.Specification || {};
    return '/' + [slug(s.Make && s.Make.Value), slug(s.Model && s.Model.Value), slug(s.Version && s.Version.Value),
      (s.NumberPorts || '4') + '-portas', s.YearFabrication + '-' + s.YearModel, r.UniqueId].join('/');
  };

  // Detalhes (descrição do vendedor, combustível, data): só dos anúncios ainda não lidos em rodadas anteriores
  const detalhes = {};
  const guardados = new Set((args.pular || []).map(String));
  const fila = results.filter((r) => !guardados.has(String(r.UniqueId))).slice(0, args.maxDetails);
  const jaLidos = results.length - results.filter((r) => !guardados.has(String(r.UniqueId))).length;
  if (jaLidos) avisar(jaLidos + ' descrições já lidas em rodadas anteriores; ' + (fila.length ? 'lendo só as ' + fila.length + ' novas' : 'nenhuma nova para ler'));
  let idx = 0;
  let feitos = 0;
  if (fila.length) avisar('Lendo descrições dos anúncios: 0 de ' + fila.length);
  const worker = async (n) => {
    while (idx < fila.length) {
      if (R.desistiu || (n > 0 && R.calmo)) return; // devagar = uma consulta por vez
      const r = fila[idx++];
      try {
        detalhes[r.UniqueId] = await getJson('/api/detail/car' + detailPath(r), 2);
      } catch (e) { /* segue sem detalhe */ }
      feitos++;
      avisar('Lendo descrições dos anúncios: ' + feitos + ' de ' + fila.length);
      if (idx < fila.length) await sleep(R.intervalo());
    }
  };
  await Promise.all(Array.from({ length: R.workers() }, (_, n) => worker(n)));
  const semDescricao = fila.filter((r) => !detalhes[r.UniqueId]).length;
  if (semDescricao) out.avisos.push(semDescricao + ' anúncios ficaram sem descrição (o site limitou as consultas); serão lidos na próxima rodada.');

  for (const r of results) {
    const s = r.Specification || {};
    const d = detalhes[r.UniqueId] || {};
    const ds = d.Specification || {};
    const seller = r.Seller || {};
    const ufm = String(seller.State || '').match(/\(([A-Z]{2})\)/);
    const foto = r.PhotoPath || (r.Media && r.Media.Photos && r.Media.Photos[0] && r.Media.Photos[0].PhotoPath);
    const attrs = (ds.VehicleAttributes || s.VehicleAttributes || []).map((a) => a.Name).filter(Boolean);
    const preco = (r.Prices && (r.Prices.Price || r.Prices.SearchPrice)) || null;
    out.items.push({
      site: 'Webmotors',
      id: 'wm-' + r.UniqueId,
      url: 'https://www.webmotors.com.br/comprar' + detailPath(r),
      titulo: s.Title || '',
      marca: s.Make && s.Make.Value,
      modelo: s.Model && s.Model.Value,
      versao: s.Version && s.Version.Value,
      ano_fab: parseInt(s.YearFabrication) || null,
      ano_modelo: parseInt(s.YearModel) || null,
      km: s.Odometer != null ? Math.round(s.Odometer) : null,
      preco: preco,
      cidade: seller.City || null,
      uf: ufm ? ufm[1] : null,
      foto: foto ? 'https://image.webmotors.com.br/_fotos/anunciousados/gigante/' + String(foto).replace(/\\/g, '/') : null,
      descricao: d.LongComment || '',
      vendedor: seller.SellerType === 'PF' ? 'Particular' : 'Loja',
      cambio: s.Transmission || null,
      combustivel: ds.Fuel || null,
      blindado: s.Armored === 'S' ? true : (s.Armored === 'N' ? false : null),
      leilao: typeof s.Auction === 'boolean' ? s.Auction : null,
      atributos: attrs,
      cor: s.Color && s.Color.Primary,
      fipe_site: r.FipePercent && preco ? Math.round(preco / (r.FipePercent / 100)) : null,
      fipe_site_tipo: r.FipePercent ? 'estimada' : null,
      publicado: d.CreatedDate || null,
      _det: !!detalhes[r.UniqueId],
    });
  }
  return out;
}
