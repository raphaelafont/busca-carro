async (args, R) => {
  // Executa numa página de anúncio da OLX (ex.: sp.olx.com.br) e busca os outros anúncios do mesmo domínio.
  // args: { urls: [...] }  -> { listId: { descricao, fipe } }
  // R = ritmo das consultas (ritmo.js): até 2 por vez, uma por vez se o site pedir pausa.
  const sleep = R.sleep;
  const avisar = R.avisar;
  const res = {};
  const urls = args.urls.slice();
  let i = 0;
  let feitos = 0;
  avisar('Lendo descrições dos anúncios: 0 de ' + urls.length);
  const lerJson = (html) => {
    const m = html.match(/<script[^>]*id="initial-data"[^>]*data-json="([^"]*)"/s);
    if (!m) return null;
    const t = document.createElement('textarea');
    t.innerHTML = m[1];
    try { return JSON.parse(t.value); } catch (e) { return null; }
  };
  const worker = async (n) => {
    while (i < urls.length) {
      if (R.desistiu || (n > 0 && R.calmo)) return;
      const u = urls[i++];
      try {
        const path = new URL(u).pathname;
        const r = await R.pedir(path, {}, 2);
        if (r.ok) {
          const j = lerJson(await r.text());
          const ad = j && j.ad;
          if (ad) {
            res[String(ad.listId)] = {
              descricao: String(ad.body || '').replace(/<br\s*\/?>/gi, '\n').replace(/<[^>]+>/g, ''),
              fipe: ad.abuyFipePrice && ad.abuyFipePrice.fipePrice ? ad.abuyFipePrice.fipePrice : null,
            };
          }
        }
      } catch (e) { /* segue */ }
      feitos++;
      avisar('Lendo descrições dos anúncios: ' + feitos + ' de ' + urls.length);
      if (i < urls.length) await sleep(R.intervalo());
    }
  };
  await Promise.all(Array.from({ length: R.workers() }, (_, n) => worker(n)));
  return res;
}
