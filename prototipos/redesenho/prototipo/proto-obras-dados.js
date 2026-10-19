// Dados inventados das telas de Obras (obras.html, obras-lista.html, pagina-da-obra.html).
// Uma fonte so': os totais de cada tela sao somas destes numeros, feitas aqui. Valores em centavos inteiros.
(function () {
  "use strict";

  /* ------------------------------------------------------------ formato */
  const nf = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const brl = c => (c < 0 ? "−" : "") + "R$ " + nf.format(Math.abs(c) / 100);
  const pct = (parte, todo) => (todo ? Math.round((parte / todo) * 100) : 0);
  const pctBp = bp => (bp / 100).toLocaleString("pt-BR", { maximumFractionDigits: 2 }) + "%";

  const hoje = (() => { const d = new Date(); return new Date(d.getFullYear(), d.getMonth(), d.getDate()); })();
  const data = iso => { const [a, m, d] = iso.split("-").map(Number); return new Date(a, m - 1, d); };
  const isoDe = d => d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
  const fmtData = iso => { if (!iso) return "—"; const [a, m, d] = iso.slice(0, 10).split("-"); return d + "/" + m + "/" + a; };
  const fmtComp = c => { const [a, m] = c.split("-"); return m + "/" + a; };
  const MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
  const mesCurto = c => { const [a, m] = c.split("-"); return MESES[Number(m) - 1] + "/" + a.slice(2); };
  const diasAte = iso => Math.round((data(iso) - hoje) / 864e5);
  const somaDias = n => { const d = new Date(hoje); d.setDate(d.getDate() + n); return isoDe(d); };
  const diasTxt = n => n + " " + (Math.abs(n) === 1 ? "dia" : "dias");
  const quandoVence = n => n > 0 ? "vence em " + diasTxt(n) : n === 0 ? "vence hoje" : "venceu há " + diasTxt(-n);
  const addMes = (c, k) => { const [a, m] = c.split("-").map(Number); const t = a * 12 + (m - 1) + k; return Math.floor(t / 12) + "-" + String((t % 12) + 1).padStart(2, "0"); };
  const mesesEntre = (c1, c2) => { const [a1, m1] = c1.split("-").map(Number), [a2, m2] = c2.split("-").map(Number); return (a2 * 12 + m2) - (a1 * 12 + m1); };
  const fimDoMes = c => { const [a, m] = c.split("-").map(Number); return isoDe(new Date(a, m, 0)); };
  const maisDias = (iso, n) => { const d = data(iso); d.setDate(d.getDate() + n); return isoDe(d); };
  // a ultima competencia medida do retrato inventado (as datas de prazo, essas, andam com o dia de hoje)
  const COMP_ATUAL = "2026-09";

  /* ------------------------------------------------------------ cadastro */
  const CONTRATANTES = [
    { id: "so", nome: "Secretaria de Obras" },
    { id: "ap", nome: "Agência de Parcerias" },
    { id: "pm", nome: "Prefeitura Municipal" },
    { id: "ss", nome: "Secretaria de Saúde" },
    { id: "vv", nome: "Prefeitura de Vale Verde" },
  ];

  const STATUS = {
    ativo: { rotulo: "Ativo", classe: "" },
    suspenso: { rotulo: "Suspenso", classe: "selo--atencao" },
    em_encerramento: { rotulo: "Em encerramento", classe: "selo--atencao" },
    encerrado: { rotulo: "Encerrado", classe: "" },
  };

  // etapas: numero da medicao -> { e: etapa, ha: dias na etapa, atrasado }. Sem entrada, a medicao foi recebida.
  const OBRAS = [
    { id: "ponte", nome: "Ponte do Ribeirão", c: "so", instrumento: "045/2025", empresa: "Consórcio Ribeirão",
      consorciadas: ["Construtora Exemplo", "Engenharia Modelo"], cotaBp: 6000, status: "ativo",
      vig: 2431055200, med: 1388210410, delta: 231055200,
      execIni: "2025-02-02", execFim: "2027-06-30", vigIni: "2025-02-02", vigFim: "2027-12-31",
      objeto: "Construção da ponte sobre o Ribeirão, com acessos e contenções.", municipio: "Vale do Ribeirão",
      dataBase: { mes: "2025-02", indice: "INCC-DI", situacao: "apostilamento_pendente", ha: 41 },
      etapas: { 20: { e: "envio", ha: 9 }, 19: { e: "pag", ha: 21 } },
      extras: [{ numero: 1, tipo: "reajuste", comp: "2026-03", valor: 41288030 }] },
    { id: "palmeiras", nome: "Avenida das Palmeiras", c: "so", instrumento: "112/2024", empresa: "Construtora Exemplo",
      consorciadas: [], cotaBp: 10000, status: "ativo", vig: 1864000000, med: 1510238840, delta: 0,
      execIni: "2024-11-04", execFim: "2027-02-28", vigIni: "2024-11-04", vigFim: "2027-08-31",
      objeto: "Duplicação e drenagem da Avenida das Palmeiras.", municipio: "Capital",
      dataBase: { mes: "2024-11", indice: "INCC-DI", situacao: "apostilado" },
      pedido: { oficio: "CT-118/2026", ha: 23, dias: 180 },
      etapas: { 23: { e: "fat", ha: 3 }, 22: { e: "pag", ha: 18 } } },
    { id: "anel", nome: "Anel Viário Sul", c: "so", instrumento: "067/2024", empresa: "Consórcio Anel Sul",
      consorciadas: ["Construtora Exemplo", "Pavimentos do Vale"], cotaBp: 5000, status: "ativo",
      vig: 3120000000, med: 2152800000, delta: 120000000,
      execIni: "2024-07-01", execFim: "2027-03-31", vigIni: "2024-07-01", vigFim: "2027-09-30",
      objeto: "Implantação do Anel Viário Sul, trecho entre a rodovia estadual e o distrito industrial.", municipio: "Capital",
      dataBase: { mes: "2024-07", indice: "INCC-DI", situacao: "apostilado" },
      etapas: { 27: { e: "nota", ha: 2 } } },
    { id: "viaduto", nome: "Viaduto Central", c: "so", instrumento: "023/2025", empresa: "Construtora Exemplo",
      consorciadas: [], cotaBp: 10000, status: "ativo", vig: 1248090000, med: 973510200, delta: 0,
      execIni: "2025-03-10", execFim: isoDe(new Date(hoje.getFullYear(), hoje.getMonth(), hoje.getDate() + 28)),
      vigIni: "2025-03-10", vigFim: "2027-05-31",
      objeto: "Viaduto sobre a linha férrea no centro, com rampas de acesso.", municipio: "Capital",
      dataBase: { mes: "2025-03", indice: "INCC-DI", situacao: "futuro" },
      etapas: { 19: { e: "envio", ha: 2 } } },
    { id: "contorno", nome: "Contorno Leste", c: "so", instrumento: "081/2026", empresa: "Construtora Exemplo",
      consorciadas: [], cotaBp: 10000, status: "ativo", vig: 987000000, med: 207270000, delta: 0,
      execIni: "2026-03-02", execFim: "2027-11-30", vigIni: "2026-03-02", vigFim: "2028-05-31",
      objeto: "Contorno viário leste, terraplenagem e pavimentação.", municipio: "Capital",
      dataBase: { mes: "2026-03", indice: "INCC-DI", situacao: "futuro" },
      etapas: { 7: { e: "espelho", ha: 1 } } },

    { id: "terminal", nome: "Terminal Norte", c: "ap", instrumento: "PPP-09/2024", empresa: "Consórcio Terminal Norte",
      consorciadas: ["Construtora Exemplo", "Estruturas Planalto"], cotaBp: 5500, status: "ativo",
      vig: 4290000000, med: 1758900000, delta: 0,
      execIni: "2024-10-01", execFim: "2027-09-30", vigIni: "2024-10-01", vigFim: "2027-10-31", folgaExigida: 60,
      objeto: "Terminal rodoviário norte, com plataformas, cobertura e sistema viário do entorno.", municipio: "Capital",
      dataBase: { mes: "2024-10", indice: "IPCA", situacao: "apostilado" },
      etapas: { 24: { e: "pag", ha: 12 } } },
    { id: "parque", nome: "Parque Linear", c: "ap", instrumento: "PPP-14/2025", empresa: "Construtora Exemplo",
      consorciadas: [], cotaBp: 10000, status: "ativo", vig: 1530000000, med: 994500000, delta: 0,
      execIni: "2025-01-06", execFim: "2027-01-31", vigIni: "2025-01-06", vigFim: "2027-07-31",
      objeto: "Parque linear ao longo do córrego, com ciclovia e iluminação.", municipio: "Capital",
      dataBase: { mes: "2025-01", indice: "IPCA", situacao: "apostilado" },
      etapas: { 21: { e: "fat", ha: 5 } } },
    { id: "serra", nome: "Rodovia Serra Azul", c: "ap", instrumento: "PPP-03/2025", empresa: "Consórcio Serra Azul",
      consorciadas: ["Construtora Exemplo", "Pavimentos do Vale"], cotaBp: 5000, status: "suspenso",
      paralisadaDesde: "2026-08-03", ultimaComp: "2026-07",
      vig: 2775000000, med: 1026750000, delta: 0,
      execIni: "2025-04-01", execFim: "2027-12-31", vigIni: "2025-04-01", vigFim: "2028-06-30",
      objeto: "Restauração e alargamento da Rodovia Serra Azul.", municipio: "Serra Azul",
      dataBase: { mes: "2025-04", indice: "IPCA", situacao: "futuro" },
      etapas: { 16: { e: "pag", ha: 44 } } },
    { id: "passarela", nome: "Passarela da Estação", c: "ap", instrumento: "PPP-02/2023", empresa: "Construtora Exemplo",
      consorciadas: [], cotaBp: 10000, status: "encerrado", vig: 342000000, med: 342000000, delta: 0,
      execIni: "2023-05-02", execFim: "2024-06-30", vigIni: "2023-05-02", vigFim: "2024-12-31",
      objeto: "Passarela metálica sobre a avenida da estação.", municipio: "Capital", ultimaComp: "2024-06",
      dataBase: { mes: "2023-05", indice: "IPCA", situacao: "apostilado" }, etapas: {} },

    { id: "escola", nome: "Escola Modelo", c: "pm", instrumento: "031/2025", empresa: "Construtora Exemplo",
      consorciadas: [], cotaBp: 10000, status: "ativo", vig: 894000000, med: 679440000, delta: 0,
      execIni: "2025-09-01", execFim: "2027-02-28", vigIni: "2025-09-01", vigFim: "2027-08-31",
      objeto: "Construção da Escola Modelo de ensino fundamental, com quadra coberta.", municipio: "Capital",
      dataBase: { mes: "2025-09", indice: "INCC-DI", situacao: "futuro" },
      etapas: { 9: { e: "pag", ha: 38, atrasado: true }, 12: { e: "pag", ha: 14 }, 13: { e: "nota", ha: 4 } } },
    { id: "esportivo", nome: "Centro Esportivo", c: "pm", instrumento: "044/2025", empresa: "Construtora Exemplo",
      consorciadas: [], cotaBp: 10000, status: "ativo", vig: 1125000000, med: 798750000, delta: 0,
      execIni: "2025-06-02", execFim: isoDe(new Date(hoje.getFullYear(), hoje.getMonth(), hoje.getDate() + 65)),
      vigIni: "2025-06-02", vigFim: "2027-06-30",
      objeto: "Centro esportivo municipal com ginásio, piscina e pista.", municipio: "Capital",
      dataBase: { mes: "2025-06", indice: "INCC-DI", situacao: "pleito_pendente" },
      etapas: { 16: { e: "envio", ha: 1 } } },
    { id: "praca", nome: "Praça da Matriz", c: "pm", instrumento: "009/2025", empresa: "Construtora Exemplo",
      consorciadas: [], cotaBp: 10000, status: "em_encerramento", fluxoAntigo: true,
      vig: 438000000, med: 302220000, delta: 0, encerramentoDesde: "2026-09-30",
      execIni: "2025-02-03", execFim: "2026-09-30", vigIni: "2025-02-03", vigFim: "2027-03-31",
      objeto: "Requalificação da Praça da Matriz.", municipio: "Capital",
      dataBase: { mes: "2025-02", indice: "INCC-DI", situacao: "apostilado" },
      etapas: { 20: { e: "fat", ha: 6 } } },

    { id: "hospital", nome: "Hospital Regional", c: "ss", instrumento: "SES-07/2025", empresa: "Consórcio Saúde Regional",
      consorciadas: ["Construtora Exemplo", "Engenharia Modelo"], cotaBp: 6000, status: "ativo",
      vig: 5860000000, med: 2285400000, delta: 0,
      execIni: "2025-09-01", execFim: "2028-02-29", vigIni: "2025-09-01", vigFim: "2028-08-31",
      objeto: "Construção do Hospital Regional, 220 leitos, com central de utilidades.", municipio: "Polo Regional",
      dataBase: { mes: "2025-09", indice: "INCC-DI", situacao: "pleito_pendente" },
      etapas: { 13: { e: "nota", ha: 6 }, 12: { e: "pag", ha: 19, diverge: true } } },
    { id: "policlinica", nome: "Policlínica Oeste", c: "ss", instrumento: "SES-11/2025", empresa: "Construtora Exemplo",
      consorciadas: [], cotaBp: 10000, status: "ativo", vig: 1420000000, med: 539600000, delta: 0,
      execIni: "2025-11-03", execFim: "2027-10-31", vigIni: "2025-11-03", vigFim: "2028-04-30",
      objeto: "Policlínica da região oeste, com centro de imagem.", municipio: "Capital",
      dataBase: { mes: "2025-11", indice: "INCC-DI", situacao: "futuro" },
      etapas: { 11: { e: "fat", ha: 2 } } },

    { id: "drenagem", nome: "Drenagem do Córrego Fundo", c: "vv", instrumento: "PVV-04/2025", empresa: "Construtora Exemplo",
      consorciadas: [], cotaBp: 10000, status: "ativo", vig: 2180000000, med: 1329800000, delta: 0,
      execIni: "2025-01-13", execFim: "2027-04-30", vigIni: "2025-01-13", vigFim: "2027-10-31",
      objeto: "Macrodrenagem do Córrego Fundo, com galerias e canal aberto.", municipio: "Vale Verde",
      dataBase: { mes: "2025-01", indice: "INCC-DI", situacao: "apostilado" },
      etapas: { 21: { e: "pag", ha: 10 } } },
    { id: "pavimentacao", nome: "Pavimentação do Centro", c: "vv", instrumento: "PVV-12/2023", empresa: "Construtora Exemplo",
      consorciadas: [], cotaBp: 10000, status: "encerrado", vig: 610000000, med: 610000000, delta: 0,
      execIni: "2023-08-01", execFim: "2024-11-30", vigIni: "2023-08-01", vigFim: "2025-05-31", ultimaComp: "2024-11",
      objeto: "Pavimentação das ruas do centro de Vale Verde.", municipio: "Vale Verde",
      dataBase: { mes: "2023-08", indice: "INCC-DI", situacao: "apostilado" }, etapas: {} },
  ];
  // na Agencia de Parcerias o orgao prorroga a vigencia junto com a execucao
  OBRAS.forEach(o => { o.vigAutomatica = o.c === "ap"; });
  const obra = id => OBRAS.find(o => o.id === id);
  const contratante = id => CONTRATANTES.find(c => c.id === id);

  /* ------------------------------------------------------------ medicoes (geradas, somam o medido) */
  function aleatorio(semente) {
    let s = 0; for (const ch of semente) s = (s * 31 + ch.charCodeAt(0)) >>> 0;
    return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; };
  }
  function repartir(total, pesos) {
    const soma = pesos.reduce((a, b) => a + b, 0);
    const v = pesos.map(p => Math.round((total * p) / soma));
    v[v.length - 1] += total - v.reduce((a, b) => a + b, 0);
    return v;
  }
  // os nomes e as cores das etapas sao os das abas aprovadas de Medicoes (app-medicoes.css: .sit-pilula--*)
  const ETAPAS = {
    espelho: { rotulo: "Espelho", classe: "sit-pilula--sem-medicao", passo: "Gerar e conferir o espelho" },
    fat: { rotulo: "Faturamento", classe: "sit-pilula--faturamento", passo: "Enviar o espelho ao faturamento" },
    nota: { rotulo: "Aguardando nota", classe: "sit-pilula--aguardando-nota", passo: "Aguardar a nota do faturamento" },
    envio: { rotulo: "Enviar nota", classe: "sit-pilula--enviar-nota", passo: "Enviar a nota ao órgão" },
    pag: { rotulo: "Aguardando pagamento", classe: "sit-pilula--aguardando-pagamento", passo: "Aguardar o pagamento" },
    ok: { rotulo: "Recebida", classe: "", passo: "" },
  };
  const cache = {};
  function medicoesDe(o) {
    if (cache[o.id]) return cache[o.id];
    const ini = o.execIni.slice(0, 7), fim = o.ultimaComp || COMP_ATUAL;
    const n = mesesEntre(ini, fim) + 1, total = mesesEntre(ini, o.execFim.slice(0, 7)) + 1;
    const r = aleatorio(o.id);
    const pesos = Array.from({ length: n }, (_, i) => (0.35 + Math.sin(Math.PI * (i + 0.5) / total)) * (0.82 + 0.36 * r()));
    const valores = repartir(o.med, pesos);
    const base = OBRAS.indexOf(o) * 100 + 1200;
    const lista = valores.map((v, i) => {
      const numero = i + 1, comp = addMes(ini, i), et = o.etapas[numero] || { e: "ok" };
      const m = { numero, tipo: "execucao", comp, valor: v, etapa: et.e, ha: et.ha ?? null, atrasado: !!et.atrasado, diverge: !!et.diverge };
      if (["envio", "pag", "ok"].includes(m.etapa)) m.nf = String(base + numero);
      if (m.etapa === "ok") m.recebidaEm = maisDias(fimDoMes(comp), 38 + Math.floor(r() * 14));
      if (m.ha !== null) m.desde = somaDias(-m.ha);
      return m;
    });
    for (const x of o.extras || []) {
      lista.push({ numero: x.numero, tipo: x.tipo, comp: x.comp, valor: x.valor, etapa: "ok", nf: String(base + 90 + x.numero),
        recebidaEm: maisDias(fimDoMes(x.comp), 44), ha: null, atrasado: false });
    }
    // a de numero 20 nao e' diferente: o lote da competencia mais recente primeiro
    lista.sort((a, b) => b.comp.localeCompare(a.comp) || b.numero - a.numero);
    cache[o.id] = lista;
    return lista;
  }
  const tituloMedicao = m => m.numero + "ª" + (m.tipo === "reajuste" ? " de reajuste" : m.tipo === "projeto" ? " de projeto" : "");

  /** Os numeros da obra, todos derivados: medido = soma das medicoes de execucao; faturado = soma das que ja' tem
   *  nota; a receber = das faturadas, as que ainda nao foram recebidas. */
  function numeros(o) {
    const ms = medicoesDe(o);
    const medido = ms.filter(m => m.tipo === "execucao").reduce((a, m) => a + m.valor, 0);
    const faturado = ms.filter(m => m.nf).reduce((a, m) => a + m.valor, 0);
    const aReceber = ms.filter(m => m.nf && m.etapa !== "ok").reduce((a, m) => a + m.valor, 0);
    return { vigente: o.vig, medido, faturado, aReceber, saldo: o.vig - medido, pct: pct(medido, o.vig),
      cota: Math.round((o.vig * o.cotaBp) / 10000) };
  }

  /** Previsto (cronograma) e medido por competencia, do inicio ao fim da execucao. */
  function cronograma(o) {
    const ini = o.execIni.slice(0, 7), total = mesesEntre(ini, o.execFim.slice(0, 7)) + 1;
    const s = x => x * x * (3 - 2 * x);
    const acum = Array.from({ length: total }, (_, i) => Math.round(o.vig * s((i + 1) / total)));
    const previsto = acum.map((v, i) => v - (i ? acum[i - 1] : 0));
    const ms = medicoesDe(o);
    return Array.from({ length: total }, (_, i) => {
      const comp = addMes(ini, i);
      const doMes = ms.filter(m => m.comp === comp);
      const exec = doMes.filter(m => m.tipo === "execucao");
      return { comp, previsto: previsto[i],
        execucao: exec.reduce((a, m) => a + m.valor, 0),
        reajuste: doMes.filter(m => m.tipo === "reajuste").reduce((a, m) => a + m.valor, 0),
        projeto: 0, provisorio: exec.some(m => m.etapa !== "ok" && m.etapa !== "pag"),
        medida: comp <= (o.ultimaComp || COMP_ATUAL) };
    });
  }

  /* ------------------------------------------------------------ avisos */
  // nivel: critico | acao | atencao (o servidor decide; aqui, inventado). familia: o lar do aviso.
  const NIVEL = {
    critico: { rotulo: "Crítico", classe: "selo--acao", forte: false, peso: 0 },
    acao: { rotulo: "Ação", classe: "selo--atencao", forte: true, peso: 1 },
    atencao: { rotulo: "Atenção", classe: "selo--atencao", forte: false, peso: 2 },
  };
  const FAMILIAS = [["prazo", "Prazo"], ["reajuste", "Reajuste"], ["nota", "Nota"], ["documentos", "Documentos"], ["dinheiro", "Dinheiro"], ["outros", "Outros"]];
  const aba = (id, a) => "pagina-da-obra.html?o=" + id + "&aba=" + a;
  function avisos() {
    const dPonte = 3, viaduto = diasAte(obra("viaduto").execFim), esportivo = diasAte(obra("esportivo").execFim);
    const paralisada = -diasAte(obra("serra").paralisadaDesde);
    const escola9 = medicoesDe(obra("escola")).find(m => m.numero === 9);
    const lista = [
      { obra: "ponte", nivel: "critico", familia: "documentos", texto: "Certidão federal do Consórcio Ribeirão " + quandoVence(dPonte),
        curto: "Certidão federal " + quandoVence(dPonte), quando: quandoVence(dPonte), dias: dPonte, onde: "Documentos · Consórcio Ribeirão", href: "documentos.html" },
      { obra: "ponte", nivel: "acao", familia: "nota", texto: "20ª medição parada há 9 dias em Enviar nota", curto: "20ª medição parada há 9 dias no envio",
        quando: "há 9 dias", dias: -9, onde: "Notas da medição", href: "medicao.html?obra=ponte&m=20" },
      { obra: "ponte", nivel: "atencao", familia: "reajuste", texto: "Reajuste da data-base 02/2025 aguardando apostilamento",
        curto: "Reajuste aguardando apostilamento", quando: "há 41 dias", dias: -41, onde: "Reajuste · data-base 02/2025", href: aba("ponte", "reajuste") },
      { obra: "palmeiras", nivel: "atencao", familia: "prazo", texto: "Pedido de prorrogação CT-118/2026 sem instrumento",
        curto: "Prorrogação pedida há 23 dias, sem instrumento", quando: "há 23 dias", dias: -23, onde: "Prazos", href: aba("palmeiras", "prazos") },
      { obra: "viaduto", nivel: "acao", familia: "prazo", texto: "Fim da execução " + quandoVence(viaduto),
        curto: "Execução " + quandoVence(viaduto), quando: quandoVence(viaduto), dias: viaduto, onde: "Prazos", href: aba("viaduto", "prazos") },
      { obra: "terminal", nivel: "atencao", familia: "prazo", texto: "Folga entre execução e vigência de 31 dias; o órgão pede 60",
        curto: "Folga de prazo abaixo da exigida", quando: "—", dias: null, onde: "Prazos", href: aba("terminal", "prazos") },
      { obra: "serra", nivel: "atencao", familia: "prazo", texto: "Obra paralisada desde " + fmtData(obra("serra").paralisadaDesde),
        curto: "Paralisada desde " + fmtData(obra("serra").paralisadaDesde), quando: "há " + diasTxt(paralisada), dias: -paralisada, onde: "Prazos", href: aba("serra", "prazos") },
      { obra: "escola", nivel: "critico", familia: "dinheiro", texto: "Pagamento da 9ª medição atrasado", curto: "Pagamento da 9ª medição atrasado há 38 dias",
        quando: "há 38 dias", dias: -38, valor: escola9.valor, onde: "Recebimento da medição", href: "medicao.html?obra=escola&m=9" },
      { obra: "escola", nivel: "atencao", familia: "documentos", texto: "Regularidade do DP de " + fmtComp(COMP_ATUAL) + " ainda não anexada",
        curto: "Regularidade do DP não anexada", quando: "há 12 dias", dias: -12, onde: "Documentos exigidos", href: aba("escola", "documentos") },
      { obra: "esportivo", nivel: "atencao", familia: "prazo", texto: "Fim da execução " + quandoVence(esportivo),
        curto: "Execução " + quandoVence(esportivo), quando: quandoVence(esportivo), dias: esportivo, onde: "Prazos", href: aba("esportivo", "prazos") },
      { obra: "esportivo", nivel: "acao", familia: "reajuste", texto: "Pleito da data-base 06/2025 não enviado",
        curto: "Pleito de reajuste não enviado há " + diasTxt(-diasAte("2026-06-01")), quando: "há " + diasTxt(-diasAte("2026-06-01")), dias: diasAte("2026-06-01"), onde: "Reajuste · data-base 06/2025", href: aba("esportivo", "reajuste") },
      { obra: "praca", nivel: "atencao", familia: "prazo", texto: "Conclusão ainda não comunicada ao órgão",
        curto: "Conclusão não comunicada", quando: "há 16 dias", dias: -16, onde: "Prazos", href: aba("praca", "prazos") },
      { obra: "hospital", nivel: "acao", familia: "reajuste", texto: "Pleito da data-base 09/2025 não enviado",
        curto: "Pleito de reajuste não enviado há " + diasTxt(-diasAte("2026-09-01")), quando: "há " + diasTxt(-diasAte("2026-09-01")), dias: diasAte("2026-09-01"), onde: "Reajuste · data-base 09/2025", href: aba("hospital", "reajuste") },
      { obra: "drenagem", nivel: "critico", familia: "documentos", texto: "Certidão municipal da Construtora Exemplo venceu há 2 dias",
        curto: "Certidão municipal vencida há 2 dias", quando: "venceu há 2 dias", dias: -2, onde: "Documentos · Construtora Exemplo", href: "documentos.html" },
      { obra: null, entidade: "Engenharia Modelo", nivel: "atencao", familia: "documentos", texto: "Certidão trabalhista vence em 6 dias",
        curto: "Certidão trabalhista vence em 6 dias", quando: "vence em 6 dias", dias: 6, onde: "Documentos · Engenharia Modelo", href: "documentos.html" },
    ];
    // do mais grave ao mais atrasado
    return lista.sort((a, b) => NIVEL[a.nivel].peso - NIVEL[b.nivel].peso || (a.dias ?? 999) - (b.dias ?? 999));
  }

  /* ------------------------------------------------------------ resumo por contratante */
  function resumo(lista) {
    const ativas = lista.filter(o => o.status !== "encerrado");
    const vig = ativas.reduce((a, o) => a + o.vig, 0);
    const med = ativas.reduce((a, o) => a + numeros(o).medido, 0);
    const av = avisos();
    const comAviso = ativas.filter(o => av.some(a => a.obra === o.id));
    const nivelMax = av.filter(a => ativas.some(o => o.id === a.obra)).map(a => a.nivel)[0] || null;
    const criticos = av.filter(a => a.nivel === "critico" && ativas.some(o => o.id === a.obra)).length;
    return { obras: ativas.length, encerradas: lista.length - ativas.length, vig, med, saldo: vig - med, pct: pct(med, vig),
      comAviso: comAviso.length, nivelMax, criticos };
  }

  window.DADOS = { CONTRATANTES, OBRAS, STATUS, ETAPAS, NIVEL, FAMILIAS, obra, contratante, medicoesDe, numeros, cronograma,
    avisos, resumo, tituloMedicao, COMP_ATUAL };
  window.FMT = { brl, pct, pctBp, hoje, data, isoDe, fmtData, fmtComp, mesCurto, diasAte, somaDias, diasTxt, quandoVence, addMes,
    mesesEntre, maisDias };
})();
