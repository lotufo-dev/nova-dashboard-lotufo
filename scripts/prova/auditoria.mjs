// Auditoria visual de uma tela aberta (acabamento do redesenho, #717): o que o olho acharia numa captura, achado
// pela conta. `capturar.mjs` chama em cada tela e largura; sai como aviso (com `--estrito`, como problema).
//
// Acha: texto cortado por uma caixa; texto fora da vista (passa da borda da janela sem caixa que role); um texto
// por cima de outro; letra fora da familia ou dos tamanhos das variaveis de `frontend/src/tokens.css`; e canto
// arredondado (a fundacao so' tem o avatar redondo). Texto com reticencias e' corte de proposito e sai a parte.
// Com uma janela aberta (<dialog>), olha so' a janela: o resto esta' atras do veu.

// Os tamanhos de letra de `tokens.css` em px (1rem = 16): mini, meta, corpo, titulo de bloco e valor menor, marca,
// valor, numero e titulo da pagina. O que usa clamp() (os valores do Inicio) fica entre dois deles e entra em
// TAMANHO_LIVRE, com o motivo.
const TAMANHOS = [12, 14, 16, 19.2, 22, 23.04, 27.648, 33.184];
const FAMILIAS = ["Archivo", "Barlow Condensed", "Barlow Semi Condensed"];
// seletores cujo tamanho de letra e' calculado pela largura da caixa (clamp com cqi) ou relativo ao texto em volta
const TAMANHO_LIVRE = ".ini-etapa__valor, .ini-previsao__valor, .ini-numero__valor, .ini-numeros *, .ini-etapas *, .ini-previsao *, "
  + ".pag-numeros__valor, code";

export async function auditar(pagina) {
  return pagina.evaluate(({ TAMANHOS, FAMILIAS, TAMANHO_LIVRE }) => {
    const achados = [];
    const vistos = new Set();
    const classeDe = el => (typeof el.className === "string" && el.className.trim()
      ? "." + el.className.trim().split(/\s+/).join(".") : "");
    const achar = (tipo, el, texto, detalhe) => {
      const onde = el.tagName.toLowerCase() + classeDe(el);
      const chave = `${tipo}|${onde}|${detalhe ?? ""}`;
      if (vistos.has(chave)) return;
      vistos.add(chave);
      achados.push({ tipo, onde, texto: (texto ?? "").replace(/\s+/g, " ").trim().slice(0, 60), detalhe: detalhe ?? "" });
    };
    const larguraDaJanela = document.documentElement.clientWidth;
    const raiz = document.querySelector("dialog[open]") ?? document.body;
    const estilos = new Map();
    const estilo = el => { let s = estilos.get(el); if (!s) { s = getComputedStyle(el); estilos.set(el, s); } return s; };

    // caixa que rola de lado (tabela larga dentro da propria caixa): permitido, mas fica dito para quem confere
    for (const el of raiz.querySelectorAll("*")) {
      const s = estilo(el);
      if (/auto|scroll/.test(s.overflowX) && el.scrollWidth > el.clientWidth + 1 && el.clientWidth > 0) {
        achar("caixa rolando de lado", el, "", `${el.scrollWidth} px de conteúdo em ${el.clientWidth} px`);
      }
    }

    // cantos: so' o avatar e' redondo (--raio-avatar); a caixa de opcao (radio) e' do navegador
    for (const el of raiz.querySelectorAll("*")) {
      const s = estilo(el), b = el.getBoundingClientRect();
      if (b.width < 2 || b.height < 2 || s.visibility === "hidden") continue;
      if (parseFloat(s.borderTopLeftRadius) > 0 && !/avatar/.test(String(el.className)) && el.type !== "radio") {
        achar("canto arredondado", el, "", s.borderTopLeftRadius);
      }
    }

    const caminhante = document.createTreeWalker(raiz, NodeFilter.SHOW_TEXT);
    const caixas = [];
    for (let no = caminhante.nextNode(); no; no = caminhante.nextNode()) {
      const texto = no.textContent.trim();
      const pai = no.parentElement;
      if (!texto || !pai || ["SCRIPT", "STYLE", "OPTION", "TITLE", "NOSCRIPT"].includes(pai.tagName) || pai.closest("svg")) continue;
      // dentro de <details> fechado o texto tem caixa mas nao aparece
      if (typeof pai.checkVisibility === "function" && !pai.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) continue;
      const faixa = document.createRange();
      faixa.selectNodeContents(no);
      const linhas = [...faixa.getClientRects()].filter(r => r.width > 1 && r.height > 1);
      if (!linhas.length) continue;
      // O que os ancestrais deixam ver: caixa que corta (hidden, clip) ou que rola (auto, scroll). Fixo e grudado
      // ficam fora da comparacao de sobreposicao (aviso flutuante, cabecalho preso).
      let invisivel = false, flutua = false, reticencias = false;
      const cortes = [];
      for (let a = pai; a && a !== document.documentElement; a = a.parentElement) {
        const s = estilo(a);
        if (s.visibility === "hidden" || s.opacity === "0") { invisivel = true; break; }
        if (s.position === "fixed" || s.position === "sticky") flutua = true;
        if (s.textOverflow === "ellipsis") reticencias = true;
        const x = s.overflowX, y = s.overflowY;
        if (x !== "visible" || y !== "visible") {
          cortes.push({ el: a, caixa: a.getBoundingClientRect(), cortaX: /hidden|clip/.test(x), cortaY: /hidden|clip/.test(y),
            rolaX: /auto|scroll/.test(x), rolaY: /auto|scroll/.test(y) });
        }
      }
      if (invisivel) continue;
      let aVista = false;
      for (const linha of linhas) {
        const v = { e: linha.left, d: linha.right, t: linha.top, b: linha.bottom };
        let some = false, rolando = false;
        for (const c of cortes) {
          const antes = { ...v };
          if (c.cortaX || c.rolaX) { v.e = Math.max(v.e, c.caixa.left); v.d = Math.min(v.d, c.caixa.right); }
          if (c.cortaY || c.rolaY) { v.t = Math.max(v.t, c.caixa.top); v.b = Math.min(v.b, c.caixa.bottom); }
          // sr-only, rotulo do menu recolhido, linha rolada para fora: escondido de proposito
          if (v.d - v.e < 2 || v.b - v.t < 2) { some = true; break; }
          const cortouX = antes.d - v.d > 1.5 || v.e - antes.e > 1.5;
          const cortouY = antes.b - v.b > 3 || v.t - antes.t > 3;
          if ((cortouX && c.rolaX) || (cortouY && c.rolaY)) rolando = true;
          else if ((cortouX && c.cortaX) || (cortouY && c.cortaY)) {
            achar(reticencias ? "texto com reticências" : "texto cortado", pai, texto,
              "pela caixa " + c.el.tagName.toLowerCase() + classeDe(c.el).split(".").slice(0, 2).join("."));
          }
        }
        if (some) continue;
        aVista = true;
        if (!rolando && !flutua && (v.d > larguraDaJanela + 1 || v.e < -1)) {
          achar("texto fora da vista", pai, texto, `de ${Math.round(v.e)} a ${Math.round(v.d)} px numa janela de ${larguraDaJanela}`);
        }
        if (!flutua) caixas.push({ ...v, no, pai, texto });
      }
      if (!aVista) continue;
      const s = estilo(pai);
      const familia = s.fontFamily.split(",")[0].replace(/["']/g, "").trim();
      const tamanho = parseFloat(s.fontSize);
      if (!FAMILIAS.includes(familia)) achar("letra fora da família", pai, texto, familia);
      if (!TAMANHOS.some(t => Math.abs(t - tamanho) < 0.2) && !pai.closest(TAMANHO_LIVRE)) {
        achar("tamanho de letra solto", pai, texto, `${Math.round(tamanho * 100) / 100}px`);
      }
    }
    // Uma caixa com fundo proprio que cobre a outra (menu aberto, lista suspensa) nao e' texto sobreposto: o de
    // baixo esta' tampado de proposito. Sobe do texto ate' o ancestral comum procurando fundo pintado.
    const tampa = (deCima, deBaixo) => {
      for (let a = deCima; a && !a.contains(deBaixo); a = a.parentElement) {
        const cor = estilo(a).backgroundColor;
        if (cor && cor !== "transparent" && !/rgba\(.*, 0\)$/.test(cor)) return true;
      }
      return false;
    };
    // um texto por cima de outro: duas linhas de texto, de nos diferentes, que se cruzam
    for (let i = 0; i < caixas.length; i++) {
      const a = caixas[i];
      for (let j = i + 1; j < caixas.length; j++) {
        const b = caixas[j];
        if (a.no === b.no) continue;
        const x = Math.min(a.d, b.d) - Math.max(a.e, b.e), y = Math.min(a.b, b.b) - Math.max(a.t, b.t);
        if (x <= 3 || y <= 4 || tampa(a.pai, b.pai) || tampa(b.pai, a.pai)) continue;
        achar("texto sobreposto", a.pai, a.texto, `com "${b.texto.slice(0, 40)}"`);
      }
    }
    return achados;
  }, { TAMANHOS, FAMILIAS, TAMANHO_LIVRE });
}

/** Os achados que reprovam com `--estrito`. As reticencias sao corte de proposito e so' entram no resumo. */
export const REPROVA = ["texto cortado", "texto fora da vista", "texto sobreposto", "letra fora da família",
  "tamanho de letra solto", "canto arredondado"];
