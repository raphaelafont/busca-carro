async (args, R) => {
  // Executa numa página carro.mercadolivre.com.br e lê os outros anúncios do mesmo domínio.
  // args: { urls: [...] } -> { MLBxxxx: {...} }
  // R = ritmo das consultas (ritmo.js): até 2 por vez, uma por vez se o site pedir pausa.
  const sleep = R.sleep;
  const avisar = R.avisar;
  const res = {};
  const urls = args.urls.slice();
  let i = 0;
  let feitos = 0;
  avisar('Lendo detalhes dos anúncios: 0 de ' + urls.length);
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
  const worker = async (n) => {
    while (i < urls.length) {
      if (R.desistiu || (n > 0 && R.calmo)) return;
      const u = urls[i++];
      try {
        const r = await R.pedir(new URL(u).pathname, {}, 2);
        const h = await r.text();
        const k = h.indexOf('_n.ctx.r=');
        if (r.ok && k >= 0) {
          const init = extractObj(h, h.indexOf('{', k)).appProps.pageProps.initialState;
          const comps = init.components || {};
          const attrs = {};
          (function walk(o) {
            if (!o || typeof o !== 'object') return;
            if (Array.isArray(o.attributes) && o.attributes[0] && o.attributes[0].id !== undefined && o.attributes[0].text !== undefined) {
              for (const a of o.attributes) if (!(a.id in attrs)) attrs[a.id] = a.text;
            }
            for (const kk in o) walk(o[kk]);
          })(comps);
          let local = null;
          (function walk(o) {
            if (local || !o || typeof o !== 'object') return;
            if (Array.isArray(o.content_rows)) {
              for (const row of o.content_rows) {
                const l = row && row.label;
                const t = typeof l === 'string' ? l : (l && l.text);
                if (t && /,/.test(t)) { local = t; return; }
              }
            }
            for (const kk in o) walk(o[kk]);
          })(comps.short_description);
          const ev = (comps.track && comps.track.melidata_event && comps.track.melidata_event.event_data) || {};
          const id = ev.item_id || (u.match(/MLB-?(\d+)/) ? 'MLB' + u.match(/MLB-?(\d+)/)[1] : null);
          if (id) {
            res[id] = {
              versao: attrs['Versão'] || null,
              marca: attrs['Marca'] || null,
              modelo: attrs['Modelo'] || null,
              ano: attrs['Ano'] || null,
              km: attrs['Quilômetros'] || null,
              cambio: attrs['Transmissão'] || null,
              combustivel: attrs['Tipo de combustível'] || null,
              blindado: attrs['Blindado'] || null,
              cor: attrs['Cor'] || null,
              descricao: (comps.description && comps.description.content) || '',
              vendedor: ev.seller_type || null,
              local: local || ev.city || null,
              preco: ev.price || null,
            };
          }
        }
      } catch (e) { /* segue */ }
      feitos++;
      avisar('Lendo detalhes dos anúncios: ' + feitos + ' de ' + urls.length);
      if (i < urls.length) await sleep(R.intervalo());
    }
  };
  await Promise.all(Array.from({ length: R.workers() }, (_, n) => worker(n)));
  return res;
}
