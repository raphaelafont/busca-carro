(cfg) => {
  // Ritmo das consultas a um site, compartilhado por todas as consultas de uma mesma leitura.
  // - Começa com no máximo 2 consultas ao mesmo tempo, com intervalo entre elas.
  // - Quando o site responde 429/403 ("pediu uma pausa"), TODAS as consultas param juntas (uma pausa só),
  //   e dali em diante segue uma por vez, mais devagar. Se o site insistir, as pausas crescem.
  // - Há um teto de tempo parado: passado ele, desiste das consultas restantes em vez de insistir
  //   (insistir com o site limitando só prolonga o bloqueio).
  cfg = cfg || {};
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const avisar = (m) => { try { if (window.__bcProgresso) window.__bcProgresso(m); } catch (e) { /* sem painel */ } };
  const ESPERAS = [20, 45, 90, 150]; // segundos, crescendo a cada nova limitação
  const st = {
    calmo: !!cfg.calmo,
    pausaAte: 0,
    limitacoes: 0,
    paradoMs: 0,
    desistiu: false,
    parar: false, // a pessoa pediu para parar e gerar o relatório com o que já foi lido
    orcamentoMs: (cfg.orcamentoS || 300) * 1000,
  };
  const R = {
    st,
    sleep,
    avisar,
    get calmo() { return st.calmo; },
    get desistiu() { return st.desistiu || st.parar; },
    get parou() { return st.parar; },
    workers() { return st.calmo ? 1 : 2; },
    intervalo() { return st.calmo ? 1800 + Math.random() * 1700 : 800 + Math.random() * 700; },
    entrePaginas() { return st.calmo ? 2500 + Math.random() * 2000 : 1100 + Math.random() * 900; },
    async esperarVez() {
      let falta;
      while ((falta = st.pausaAte - Date.now()) > 0 && !st.parar) {
        await sleep(Math.min(falta, 2000));
        await R.checarParada();
      }
    },
    async checarParada() {
      try { if (!st.parar && window.__bcParar && await window.__bcParar()) { st.parar = true; avisar('Parada pedida: terminando com o que já foi lido'); } } catch (e) { /* sem painel */ }
      return st.parar;
    },
    limitou(retryAfter) {
      const agora = Date.now();
      if (st.pausaAte > agora) return; // resposta de consulta que já estava a caminho: a pausa já está valendo
      const n = Math.min(st.limitacoes, ESPERAS.length - 1);
      st.limitacoes++;
      st.calmo = true;
      let espera = ESPERAS[n] * 1000 + Math.random() * 5000;
      const ra = parseInt(retryAfter, 10);
      if (ra > 0) espera = Math.max(espera, Math.min(ra, 300) * 1000);
      if (st.paradoMs + espera > st.orcamentoMs) {
        st.desistiu = true;
        avisar('O site continua limitando as consultas; parando de insistir nesta leitura');
        return;
      }
      st.paradoMs += espera;
      st.pausaAte = agora + espera;
      avisar('O site pediu uma pausa; aguardando ' + Math.round(espera / 1000) + ' s e seguindo mais devagar');
    },
    // fetch na mesma origem, respeitando a pausa compartilhada; 429/403 viram pausa e nova tentativa.
    // Lança Error('LIMITE') se o site continuar limitando.
    async pedir(url, opcoes, tentativas) {
      tentativas = tentativas || 4;
      for (let t = 0; t < tentativas; t++) {
        if (st.desistiu || await R.checarParada()) break;
        await R.esperarVez();
        if (st.desistiu || st.parar) break;
        const r = await fetch(url, Object.assign({ credentials: 'include' }, opcoes || {}));
        if (r.status === 429 || r.status === 403) {
          R.limitou(r.headers.get('Retry-After'));
          continue;
        }
        return r;
      }
      throw new Error('LIMITE');
    },
    resumo() {
      return { limitacoes: st.limitacoes, parado_s: Math.round(st.paradoMs / 1000), desistiu: st.desistiu, calmo: st.calmo, parou: st.parar };
    },
  };
  return R;
}
