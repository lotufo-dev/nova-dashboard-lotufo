// Dados inventados e regras de apresentacao comuns as duas telas de Documentos (documentos.html e
// documentos-empresa.html). As regras repetem as de frontend/src/matriz.ts e Documentos.tsx:
// pendencia = certidao exigida vencida, faltando ou vencendo em ate' 30 dias, mais a regularidade do mes fora do dia.
window.DOC = (function () {
  const HOJE = "2026-10-16";
  const JANELA = 30;      // decisao 5: pendencia ate' 30 dias
  const LIMIAR = 15;      // o servidor chama de "vencendo" a partir de 15 dias
  const CNPJ = "00.000.000/0001-00";

  const TIPOS = [
    { chave: "federal", curto: "Federal", rotulo: "Federal (RFB/PGFN)" },
    { chave: "estadual", curto: "Estadual", rotulo: "Estadual (SEFAZ/PGE)" },
    { chave: "municipal", curto: "Municipal", rotulo: "Municipal (Prefeitura)" },
    { chave: "fgts", curto: "FGTS", rotulo: "FGTS (CRF)" },
    { chave: "trabalhista", curto: "Trabalhista", rotulo: "Trabalhista (CNDT)" },
    { chave: "falencia", curto: "Falência", rotulo: "Falência (Tribunal de Justiça)" },
  ];

  // c(emissao, validade, extra) monta uma certidao; sem datas = faltando
  const c = (emissao, validade, extra) => Object.assign({ exigida: true, emissao, validade, natureza: "negativa", leitura: "pdf" }, extra || {});
  const falta = () => ({ exigida: true, emissao: null, validade: null });
  const naoExigida = () => ({ exigida: false, emissao: null, validade: null });
  const naoSeAplica = () => ({ exigida: true, naoSeAplica: true, emissao: null, validade: null });

  const EMPRESAS = [
    { id: 1, nome: "Construtora Exemplo", papel: "empresa", consorcios: [3],
      cert: { federal: c("2026-04-10", "2026-10-07"), estadual: c("2026-08-20", "2026-12-18"),
              municipal: c("2026-09-01", "2026-12-30"), fgts: c("2026-10-06", "2026-12-05"),
              trabalhista: c("2026-10-05", "2027-04-03"), falencia: c("2026-10-08", "2026-11-19") },
      reg: { situacao: "ok", competencia: "2026-09", esperada: "2026-09",
             historico: [["2026-09", "2026-10-08"], ["2026-08", "2026-09-09"], ["2026-07", "2026-08-07"]] },
      obras: ["Ponte do Ribeirão", "Avenida das Palmeiras", "Terminal Norte"] },
    { id: 2, nome: "Pavimentação Beta", papel: "consorciada", consorcios: [3],
      cert: { federal: c("2026-08-24", "2027-02-20"), estadual: c("2026-07-14", "2027-01-10"),
              municipal: c("2026-08-30", "2026-12-28"), fgts: c("2026-09-23", "2026-10-22"),
              trabalhista: falta(), falencia: c("2026-10-09", "2026-11-20") },
      reg: { situacao: "ok", competencia: "2026-09", esperada: "2026-09",
             historico: [["2026-09", "2026-10-06"], ["2026-08", "2026-09-05"]] },
      obras: ["Terminal Norte"] },
    { id: 3, nome: "Consórcio Vale Norte", papel: "consorcio", consorciadas: [1, 2],
      cert: { federal: c("2026-09-16", "2027-03-15", { natureza: "positiva_efeito_negativa" }),
              estadual: c("2026-08-24", "2026-12-22"), municipal: c("2026-07-02", "2026-10-31"),
              fgts: c("2026-10-01", "2026-10-31"), trabalhista: c("2026-10-03", "2027-04-01"),
              falencia: naoExigida() },
      reg: null, obras: ["Terminal Norte"] },
    { id: 4, nome: "Engenharia Alfa", papel: "consorciada", consorcios: [5],
      cert: { federal: c("2026-09-02", "2027-03-01"), estadual: c("2026-09-12", "2027-01-09", { leitura: "manual" }),
              municipal: c("2026-09-20", "2027-01-17"), fgts: c("2026-10-10", "2026-12-08"),
              trabalhista: c("2026-09-30", "2027-03-29"), falencia: c("2026-10-14", "2026-12-01") },
      reg: { situacao: "atrasada", competencia: "2026-08", esperada: "2026-09",
             historico: [["2026-08", "2026-09-11"], ["2026-07", "2026-08-12"]] },
      obras: ["Anel Viário Sul", "Hospital Regional"] },
    { id: 5, nome: "Consórcio Rio Claro", papel: "consorcio", consorciadas: [4, 6],
      cert: { federal: c("2026-08-18", "2027-02-14"), estadual: c("2026-09-05", "2027-01-03"),
              municipal: naoSeAplica(), fgts: c("2026-10-12", "2026-12-10"),
              trabalhista: c("2026-08-28", "2027-02-24"), falencia: c("2026-10-13", "2026-11-30") },
      reg: null, obras: ["Hospital Regional"] },
    { id: 6, nome: "Saneamento Gama", papel: "empresa", consorcios: [5],
      cert: { federal: c("2026-09-10", "2027-03-09"), estadual: c("2026-09-03", "2027-01-01"),
              municipal: c("2026-09-25", "2027-01-22"), fgts: c("2026-10-07", "2026-12-06"),
              trabalhista: c("2026-10-01", "2027-03-30"), falencia: c("2026-10-15", "2026-11-28") },
      reg: { situacao: "ok", competencia: "2026-09", esperada: "2026-09",
             historico: [["2026-09", "2026-10-09"], ["2026-08", "2026-09-10"], ["2026-07", "2026-08-11"]] },
      obras: ["Parque Linear", "Escola Modelo", "Hospital Regional"] },
  ];

  // Garantia e ART por obra, pela empresa contratada (issue #65)
  const CONTRATOS = [
    { obra: "Ponte do Ribeirão", entidade: 1, garantia: { fim: "2027-06-30", origem: "contrato", apolice: "0012345", baixada: false }, art: { numero: "1234567", anexada: true, exigida: true } },
    { obra: "Avenida das Palmeiras", entidade: 1, garantia: { fim: "2026-10-28", origem: "endosso", apolice: "0045678", baixada: false }, art: { numero: "2345678", anexada: true, exigida: true } },
    { obra: "Terminal Norte", entidade: 3, garantia: { fim: "2027-03-15", origem: "contrato", apolice: "0078901", baixada: false }, art: { numero: null, anexada: false, exigida: true } },
    { obra: "Hospital Regional", entidade: 5, garantia: null, art: { numero: null, anexada: false, exigida: false } },
    { obra: "Anel Viário Sul", entidade: 4, garantia: { fim: "2027-08-10", origem: "contrato", apolice: "0034512", baixada: false }, art: { numero: "3456789", anexada: true, exigida: true } },
    { obra: "Parque Linear", entidade: 6, garantia: { fim: "2026-06-30", origem: "contrato", apolice: "0056734", baixada: true }, art: { numero: "4567890", anexada: true, exigida: true } },
    { obra: "Escola Modelo", entidade: 6, garantia: { fim: "2027-02-28", origem: "endosso", apolice: "0067845", baixada: false }, art: { numero: "5678901", anexada: true, exigida: true } },
  ];

  // ---------------------------------------------------------------- datas
  const dia = s => new Date(s + "T12:00:00");
  const dias = s => Math.round((dia(s) - dia(HOJE)) / 864e5);
  const data = s => s ? s.slice(8, 10) + "/" + s.slice(5, 7) + "/" + s.slice(0, 4) : "—";
  const mes = s => s ? s.slice(5, 7) + "/" + s.slice(0, 4) : "—";
  const venceTxt = d => d <= 0 ? "vence hoje" : d === 1 ? "vence amanhã" : "vence em " + d + " dias";

  // ------------------------------------------------------- uma certidao
  // nivel: ok | atencao | acao | neutro ; texto da pilula ; nota embaixo
  function linha(e, t) {
    const x = e.cert[t.chave];
    const l = { tipo: t, exigida: x.exigida, emissao: x.emissao, validade: x.validade, natureza: x.natureza, leitura: x.leitura,
                dias: x.validade ? dias(x.validade) : null };
    if (x.naoSeAplica) { l.situacao = "nao_se_aplica"; l.nivel = "neutro"; l.texto = "não se aplica"; l.nota = "declarado"; }
    else if (!x.exigida) { l.situacao = "nao_exigida"; l.nivel = "neutro"; l.texto = "não exigida"; }
    else if (!x.validade) { l.situacao = "faltando"; l.nivel = "acao"; l.texto = "falta"; }
    else if (l.dias < 0) { l.situacao = "vencida"; l.nivel = "acao"; l.texto = "vencida"; l.nota = "em " + data(x.validade); }
    else if (l.dias <= JANELA) { l.situacao = l.dias <= LIMIAR ? "vencendo" : "ok"; l.nivel = "atencao"; l.texto = venceTxt(l.dias); }
    else { l.situacao = "ok"; l.nivel = "ok"; l.texto = "em dia"; }
    l.pendente = x.exigida && !x.naoSeAplica && (l.nivel === "acao" || l.nivel === "atencao");
    return l;
  }
  const linhas = e => TIPOS.map(t => linha(e, t));

  const REG_TXT = { ok: "em dia", atrasada: "atrasada", faltando: "nenhuma anexada" };

  function resumo(e) {
    const ls = linhas(e);
    const vencidas = ls.filter(l => l.situacao === "vencida").length;
    const faltas = ls.filter(l => l.situacao === "faltando").length;
    const vencendo = ls.filter(l => l.pendente && l.nivel === "atencao");
    const regFora = e.reg && e.reg.situacao !== "ok";
    const partes = [];
    if (vencidas) partes.push(vencidas + (vencidas === 1 ? " vencida" : " vencidas"));
    if (faltas) partes.push(faltas + (faltas === 1 ? " falta" : " faltam"));
    if (vencendo.length === 1) partes.push("1 " + venceTxt(vencendo[0].dias));
    else if (vencendo.length > 1) partes.push(vencendo.length + " vencem em até " + Math.max(...vencendo.map(l => l.dias)) + " dias");
    if (regFora) partes.push("regularidade " + REG_TXT[e.reg.situacao]);
    const gravidade = vencidas || faltas || regFora ? 0 : vencendo.length ? 1 : 2;
    const nivel = vencidas || faltas ? "acao" : gravidade < 2 ? "atencao" : "ok";
    const pendencias = ls.filter(l => l.pendente).length + (regFora ? 1 : 0);
    const menor = Math.min(999, ...ls.filter(l => l.pendente && l.dias !== null).map(l => l.dias));
    const futuras = ls.filter(l => l.exigida && l.dias !== null && l.dias >= 0).sort((a, b) => a.dias - b.dias);
    return { linhas: ls, texto: partes.length ? partes.join(" · ") : "em dia", nivel, gravidade, pendencias, menor,
             proxima: futuras[0] || null, regFora };
  }

  // a mesma ordem da matriz: o que ja' trava, o que vence, o resto; depois a que vence primeiro
  function ordenadas(soPendentes) {
    return EMPRESAS.map((e, i) => ({ e, r: resumo(e), i }))
      .filter(x => !soPendentes || x.r.pendencias > 0)
      .sort((a, b) => a.r.gravidade - b.r.gravidade || a.r.menor - b.r.menor || a.i - b.i);
  }

  function garantia(g) {
    if (!g) return { nivel: "neutro", texto: "sem vigência no cadastro", nota: "" };
    const d = dias(g.fim), ate = data(g.fim);
    const nota = (d < 0 ? "venceu em " + ate : "até " + ate) + (g.origem === "endosso" ? " (endosso)" : "") + (g.apolice ? " · apólice " + g.apolice : "");
    if (g.baixada) return { nivel: "neutro", texto: "baixada", nota };
    if (d < 0) return { nivel: "acao", texto: "vencida", nota, forte: true };
    if (d <= 30) return { nivel: d <= 15 ? "acao" : "atencao", texto: venceTxt(d), nota };
    return { nivel: "ok", texto: "em dia", nota };
  }
  function art(a) {
    if (a.anexada) return { nivel: "ok", texto: "anexada", nota: a.numero ? "nº " + a.numero : "" };
    if (a.exigida) return { nivel: "atencao", texto: "não anexada", nota: "" };
    return { nivel: "neutro", texto: "não exigida", nota: "" };
  }
  // o que a garantia e a ART pedem da empresa (aparece no cartao da pagina 1)
  function avisosObra(e) {
    const out = [];
    CONTRATOS.filter(k => k.entidade === e.id).forEach(k => {
      const g = garantia(k.garantia), a = art(k.art);
      if (g.nivel === "acao" || g.nivel === "atencao") out.push({ nivel: g.nivel, texto: "Garantia de " + k.obra + ": " + g.texto });
      if (a.nivel === "atencao") out.push({ nivel: "atencao", texto: "ART de " + k.obra + ": não anexada" });
    });
    return out;
  }

  // ------------------------------------------------------------- pedacos
  const esc = s => String(s).replace(/[&<>"]/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch]));
  function selo(nivel, texto, forte) {
    if (nivel === "ok") return '<span class="estado estado--ok"><span class="estado__ponto" aria-hidden="true"></span>' + esc(texto.charAt(0).toUpperCase() + texto.slice(1)) + "</span>";
    const cls = nivel === "neutro" ? "" : " selo--" + nivel;
    return '<span class="selo' + cls + (forte ? " selo--forte" : "") + '"><span class="selo__ponto" aria-hidden="true"></span><span class="selo__texto">' + esc(texto) + "</span></span>";
  }
  // pilula sempre com fundo (situacao geral no cabecalho e no cartao)
  function pilula(nivel, texto) {
    const cls = nivel === "neutro" ? "" : " selo--" + nivel;
    return '<span class="selo doc-pilula' + cls + '"><span class="selo__ponto" aria-hidden="true"></span><span class="selo__texto">' + esc(texto) + "</span></span>";
  }

  // copia do CNPJ: navigator.clipboard e, sem ele, a copia antiga; o retorno aparece ao lado do botao
  async function copiar(botao, nome) {
    let ok = false;
    try { if (navigator.clipboard) { await navigator.clipboard.writeText(CNPJ); ok = true; } } catch (_) { ok = false; }
    if (!ok) {
      const a = document.createElement("textarea"); a.value = CNPJ; a.style.position = "fixed"; a.style.opacity = "0";
      document.body.appendChild(a); a.select(); try { ok = document.execCommand("copy"); } catch (_) { ok = false; } a.remove();
    }
    const nota = botao.parentElement.querySelector(".doc-copia");
    if (nota) { nota.textContent = ok ? "CNPJ copiado" : "Não copiou: selecione o número"; nota.hidden = false; }
    const viva = document.getElementById("anuncio");
    if (viva) viva.textContent = ok ? "CNPJ de " + nome + " copiado." : "Não deu para copiar o CNPJ de " + nome + ": selecione o número.";
  }

  // ------------------------------------------------- fila de anexar certidoes
  // Simula o que o servidor faz ao ler o PDF arrastado: le tipo, empresa e validade e a pessoa confere e grava;
  // sem texto, le por OCR; sem datas legiveis, abre a digitacao; o que nao e' certidao e' recusado.
  let seq = 0;
  function montarFila(opts) {
    const zona = opts.zona, lista = opts.lista, entrada = opts.entrada;
    const empresaPadrao = opts.empresa || null;   // na pagina da empresa, a leitura cai nela
    const anunciar = t => { const v = document.getElementById("anuncio"); if (v) v.textContent = t; };

    function adivinhaTipo(nome, i) {
      const n = nome.toLowerCase();
      const achado = TIPOS.find(t => n.includes(t.chave) || (t.chave === "trabalhista" && n.includes("cndt")) || (t.chave === "fgts" && n.includes("crf")));
      return achado || TIPOS[i % TIPOS.length];
    }
    function receber(arquivos, tipoForcado) {
      Array.from(arquivos).forEach((arq, i) => {
        const chave = ++seq;
        const li = document.createElement("li");
        li.className = "documentos__item doc-fila__item";
        li.innerHTML = '<span class="documentos__arquivo">' + esc(arq.name) + '</span><span class="campo__nota">lendo…</span>';
        lista.prepend(li);
        lista.hidden = false;
        setTimeout(() => resolver(li, arq, chave, tipoForcado || adivinhaTipo(arq.name, chave)), 700 + i * 500);
      });
    }
    function resolver(li, arq, chave, tipo) {
      const caso = (chave - 1) % 4;
      const emp = empresaPadrao || EMPRESAS[chave % EMPRESAS.length];
      const nome = '<span class="documentos__arquivo">' + esc(arq.name) + "</span>";
      const descartar = '<button type="button" class="btn btn--pequeno" data-descartar>Descartar</button>';
      if (caso === 0 || caso === 1) {
        const validade = tipo.chave === "falencia" ? "27/11/2026" : "14/04/2027";
        li.innerHTML = nome + "<span>" + esc(emp.nome) + " · " + esc(tipo.rotulo) + " · negativa · emitida em 16/10/2026 · válida até " + validade +
          (tipo.chave === "falencia" ? " (30 dias úteis)" : "") + " · nº 2026." + (100000 + chave * 731) + "</span>" +
          (caso === 1 ? '<span class="campo__nota">PDF sem texto, lido por OCR: confira empresa e datas com o PDF antes de gravar.</span>' : "") +
          '<span class="form-inline"><button type="button" class="btn btn--pequeno" data-gravar data-acao="Gravaria a certidão ' + esc(tipo.curto) + " de " + esc(emp.nome) + ' (válida até ' + validade + ')">Gravar certidão</button>' + descartar + "</span>";
        anunciar(arq.name + ": lida, confira e grave.");
      } else if (caso === 2) {
        const id = "d" + chave;
        const opEmp = EMPRESAS.map(x => '<option value="' + x.id + '"' + (empresaPadrao && x.id === empresaPadrao.id ? " selected" : "") + ">" + esc(x.nome) + "</option>").join("");
        const opTipo = TIPOS.map(t => '<option value="' + t.chave + '"' + (t.chave === tipo.chave ? " selected" : "") + ">" + esc(t.rotulo) + "</option>").join("");
        li.innerHTML = nome + '<form class="form-inline doc-digitar">' +
          '<span class="campo__nota doc-digitar__msg">Não deu para ler as datas deste PDF: digite os dados.</span>' +
          '<div class="campo"><label class="campo__rotulo" for="' + id + 'e">Empresa</label><select id="' + id + 'e" required><option value="">—</option>' + opEmp + "</select></div>" +
          '<div class="campo"><label class="campo__rotulo" for="' + id + 't">Tipo</label><select id="' + id + 't" required><option value="">—</option>' + opTipo + "</select></div>" +
          '<div class="campo"><label class="campo__rotulo" for="' + id + 'm">Emissão</label><input id="' + id + 'm" type="date" required></div>' +
          '<div class="campo"><label class="campo__rotulo" for="' + id + 'v">Validade<span data-falencia>' + (tipo.chave === "falencia" ? " (vazia: 30 dias úteis)" : "") + '</span></label><input id="' + id + 'v" type="date"></div>' +
          '<div class="campo"><label class="campo__rotulo" for="' + id + 'n">Natureza</label><select id="' + id + 'n"><option>negativa</option><option>positiva com efeito de negativa</option></select></div>' +
          '<button type="submit" class="btn btn--pequeno" data-acao="Gravaria a certidão com os dados digitados (marcada como digitada)">Gravar certidão</button>' + descartar + "</form>";
        const selTipo = li.querySelector("#" + id + "t");
        selTipo.addEventListener("change", () => { li.querySelector("[data-falencia]").textContent = selTipo.value === "falencia" ? " (vazia: 30 dias úteis)" : ""; });
        li.querySelector("form").addEventListener("submit", ev => ev.preventDefault());
        anunciar(arq.name + ": não deu para ler; digite os dados.");
      } else {
        li.innerHTML = nome + '<span class="notas__diverge">Recusada: o PDF não é uma certidão conhecida (nenhum tipo de certidão no texto).</span>' + descartar;
        anunciar(arq.name + ": recusada.");
      }
    }
    lista.addEventListener("click", ev => {
      const d = ev.target.closest("[data-descartar]");
      if (d) { d.closest("li").remove(); if (!lista.children.length) lista.hidden = true; return; }
      const g = ev.target.closest("[data-gravar]");
      if (g) {
        const li = g.closest("li");
        const desc = li.querySelector("span:nth-child(2)").textContent.split(" · ").slice(0, 2).join(" · ");
        li.innerHTML = li.querySelector(".documentos__arquivo").outerHTML + '<span class="notas__ok">gravada: ' + esc(desc) + " (no protótipo, nada foi salvo)</span>";
      }
    });
    entrada.addEventListener("change", () => { receber(entrada.files, entrada._tipo || null); entrada._tipo = null; entrada.value = ""; });
    ["dragenter", "dragover"].forEach(t => zona.addEventListener(t, ev => { ev.preventDefault(); zona.classList.add("doc-zona--sobre"); }));
    ["dragleave", "drop"].forEach(t => zona.addEventListener(t, ev => { ev.preventDefault(); zona.classList.remove("doc-zona--sobre"); }));
    zona.addEventListener("drop", ev => { const fs = Array.from(ev.dataTransfer.files || []).filter(f => /pdf$/i.test(f.name) || f.type === "application/pdf"); if (fs.length) receber(fs, null); });
    return { escolher(tipo) { entrada._tipo = tipo || null; entrada.click(); } };
  }

  return { HOJE, JANELA, CNPJ, TIPOS, EMPRESAS, CONTRATOS, data, mes, dias, linhas, resumo, ordenadas, garantia, art,
           avisosObra, selo, pilula, esc, copiar, montarFila, REG_TXT,
           porId: id => EMPRESAS.find(e => e.id === id) };
})();
