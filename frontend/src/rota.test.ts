import { describe, expect, it } from "vitest";
import { buscaDosAvisos, caminhoDe, hrefDe, origemPara, parseRota, substituir, type Rota } from "./rota";

describe("rota", () => {
  it("toda rota tem um caminho canônico e volta igual", () => {
    const rotas: Rota[] = [
      { tela: "inicio" }, { tela: "medicoes" }, { tela: "resumo-medicoes" }, { tela: "fechamento" }, { tela: "obras" },
      { tela: "obras", aba: "todas" }, { tela: "obras", aba: "andamento" }, { tela: "obras", aba: "qdop" },
      { tela: "contratante", chave: "sinfra" }, { tela: "contratante", chave: "pref-cuiaba" },
      { tela: "documentos" }, { tela: "admin" }, { tela: "conta" }, { tela: "avisos" }, { tela: "siga" },
      { tela: "obra", id: 7, aba: "ficha" },
      { tela: "medicao", obra: 7, id: 723 },
      { tela: "obra", id: 7, aba: "documentos" },
      { tela: "obra", id: 12, aba: "reajuste" },
      { tela: "obra", id: 12, aba: "prazos" },
      { tela: "obra", id: 12, aba: "contrato" },
      { tela: "admin", aba: "reconciliacao" }, { tela: "admin", aba: "usuarios" }, { tela: "admin", aba: "auditoria" }, { tela: "admin", aba: "pendencias" },
      { tela: "notas-envio", id: 55 },
      { tela: "documentos-empresa", id: 3 }, { tela: "documentos-empresa", id: 3, aba: "regularidade" },
      { tela: "documentos-empresa", id: 3, aba: "garantia" },
      { tela: "medicoes" },
    ];
    for (const r of rotas) expect(parseRota(caminhoDe(r))).toEqual(r);
  });

  it("a empresa em Documentos tem endereço e cada aba tem o seu; a aba padrão não entra na URL (#161)", () => {
    expect(caminhoDe({ tela: "documentos-empresa", id: 3 })).toBe("/documentos/3");
    expect(caminhoDe({ tela: "documentos-empresa", id: 3, aba: "certidoes" })).toBe("/documentos/3");
    expect(caminhoDe({ tela: "documentos-empresa", id: 3, aba: "garantia" })).toBe("/documentos/3/garantia");
    expect(parseRota("/documentos/3/certidoes")).toEqual({ tela: "documentos-empresa", id: 3 });
    expect(parseRota("/documentos/abc")).toEqual({ tela: "raiz" });
    expect(parseRota("/documentos/3/outra")).toEqual({ tela: "raiz" });
    expect(parseRota("/documentos/3/garantia/x")).toEqual({ tela: "raiz" });
  });

  it("os caminhos antigos abrem a tela nova (o App troca a URL pela canônica)", () => {
    expect(parseRota("/contratos")).toEqual({ tela: "obras" });
    expect(parseRota("/contratos/7")).toEqual({ tela: "obra", id: 7, aba: "ficha" });
    expect(parseRota("/contratos/7/prazos")).toEqual({ tela: "obra", id: 7, aba: "prazos" });
    // #805: o Resumo da Carteira (os totais por contratante) e' a vista "Por contratante", a entrada de Obras
    expect(parseRota("/diretoria")).toEqual({ tela: "obras" });
    expect(parseRota("/painel")).toEqual({ tela: "obras" });
    expect(parseRota("/certidoes")).toEqual({ tela: "documentos" });
    expect(caminhoDe(parseRota("/contratos/7/prazos"))).toBe("/obras/7/prazos");
  });

  it("A receber e Carteira saíram (#748): os links antigos abrem o Fechamento ou a vista de Obras que as absorveu", () => {
    expect(parseRota("/a-receber")).toEqual({ tela: "fechamento" });
    expect(parseRota("/carteira")).toEqual({ tela: "obras" });
    expect(parseRota("/carteira/resumo")).toEqual({ tela: "obras" });
    expect(parseRota("/carteira/qdop")).toEqual({ tela: "obras", aba: "qdop" });
    expect(parseRota("/carteira/producao")).toEqual({ tela: "fechamento" });
    expect(parseRota("/carteira/custo")).toEqual({ tela: "obras" });
    expect(caminhoDe(parseRota("/carteira/qdop"))).toBe("/obras/qdop");
    expect(parseRota("/obras/x")).toEqual({ tela: "raiz" });
  });

  it("Obras em níveis (#805): as quatro vistas, a página do contratante e os endereços de antes", () => {
    expect(caminhoDe({ tela: "obras" })).toBe("/obras");                                  // "Por contratante", a entrada
    expect(caminhoDe({ tela: "obras", aba: "todas" })).toBe("/obras/todas");
    expect(caminhoDe({ tela: "obras", aba: "andamento" })).toBe("/obras/andamento");
    expect(caminhoDe({ tela: "contratante", chave: "sinfra" })).toBe("/obras/contratante/sinfra");
    expect(parseRota("/obras/contratante/pref-cuiaba")).toEqual({ tela: "contratante", chave: "pref-cuiaba" });
    // a Posição era a tabela de todas as obras; o Resumo, os totais por contratante
    expect(parseRota("/obras/posicao")).toEqual({ tela: "obras", aba: "todas" });
    expect(caminhoDe(parseRota("/obras/posicao"))).toBe("/obras/todas");
    expect(parseRota("/obras/resumo")).toEqual({ tela: "obras" });
    // sem chave, com chave que não é chave ou com sobra no caminho: caminho desconhecido
    for (const c of ["/obras/contratante", "/obras/contratante/", "/obras/contratante/a%20b", "/obras/contratante/sinfra/x", "/obras/todas/x"]) {
      expect(parseRota(c)).toEqual({ tela: "raiz" });
    }
    // a página do contratante não é detalhe com origem: a obra aberta a partir dela guarda a página como origem
    expect(origemPara({ tela: "contratante", chave: "sinfra" }, "/obras/contratante/sinfra", { tela: "obra", id: 7, aba: "ficha" }, undefined))
      .toEqual({ tela: "contratante", href: "/obras/contratante/sinfra" });
  });

  it("as telas que saíram no bloco 9 caem na entrada do perfil", () => {
    expect(parseRota("/sugestoes")).toEqual({ tela: "raiz" });
    expect(parseRota("/engenharia")).toEqual({ tela: "raiz" });
  });

  it("links antigos das abas abrem a seção que as absorveu", () => {
    expect(parseRota("/contratos/7/protocolo")).toEqual({ tela: "obra", id: 7, aba: "medicoes" });
    expect(parseRota("/contratos/7/cronograma")).toEqual({ tela: "obra", id: 7, aba: "contrato" });
    expect(parseRota("/obras/7/aditivos")).toEqual({ tela: "obra", id: 7, aba: "contrato" });
    // a aba Notas saiu: as notas moram na medicao e na coluna Notas das medicoes da obra
    expect(caminhoDe(parseRota("/contratos/7/notas"))).toBe("/obras/7/medicoes");
  });

  it("a aba padrão (da obra, da Carteira) não entra na URL; filtros e seção entram", () => {
    expect(caminhoDe({ tela: "obra", id: 7, aba: "ficha" })).toBe("/obras/7");
    expect(caminhoDe({ tela: "obra", id: 7, aba: "medicoes" })).toBe("/obras/7/medicoes");
    expect(parseRota("/obras/7")).toEqual({ tela: "obra", id: 7, aba: "ficha" });
    expect(parseRota("/obras/7/medicoes")).toEqual({ tela: "obra", id: 7, aba: "medicoes" });
    expect(caminhoDe({ tela: "obras", aba: "contratantes" })).toBe("/obras");
    expect(parseRota("/obras/contratantes")).toEqual({ tela: "obras" });
    expect(caminhoDe({ tela: "obras", aba: "qdop" })).toBe("/obras/qdop");
    expect(parseRota("/admin/saude")).toEqual({ tela: "admin" });
    expect(hrefDe({ tela: "documentos" }, { pendentes: "1", vazio: "" }, "emp-3")).toBe("/documentos?pendentes=1#emp-3");
    expect(hrefDe({ tela: "avisos" }, { familia: "prazo", obra: "7" })).toBe("/avisos?familia=prazo&obra=7");
  });

  it("Medições é uma tela só, o quadro do mês; Iniciar medição e Em andamento levam a ela (#643)", () => {
    expect(caminhoDe({ tela: "medicoes" })).toBe("/medicoes");
    expect(parseRota("/medicoes")).toEqual({ tela: "medicoes" });
    expect(parseRota("/medicoes/iniciar")).toEqual({ tela: "medicoes" });
    expect(parseRota("/medicoes/em-andamento")).toEqual({ tela: "medicoes" });
    for (const c of ["/medicoes/x", "/medicoes/enviar-nota/1", "/medicoes/em-andamento/1"]) expect(parseRota(c)).toEqual({ tela: "raiz" });
  });

  it("as abas antigas de Medições levam ao quadro", () => {
    for (const a of ["resumo", "sem-medicao", "planilha-gerada", "planilha-enviada", "boletim-recebido", "faturamento",
      "aguardando-nota", "enviar-nota", "aguardando-pagamento"]) {
      expect(parseRota(`/medicoes/${a}`)).toEqual({ tela: "medicoes" });
    }
  });

  it("as telas Notas antigas abrem o quadro; o envio de um protocolo continua", () => {
    expect(parseRota("/notas")).toEqual({ tela: "medicoes" });
    expect(parseRota("/notas/aguardando")).toEqual({ tela: "medicoes" });
    expect(caminhoDe({ tela: "notas-envio", id: 55 })).toBe("/notas/envio/55");
    for (const c of ["/notas/envio", "/notas/envio/abc", "/notas/x", "/notas/envio/5/x"]) expect(parseRota(c)).toEqual({ tela: "raiz" });
  });

  it("caminho desconhecido vira raiz, nunca uma obra inventada", () => {
    for (const c of ["/", "/nada", "/obras/abc", "/contratos/0", "/obras/1e3",
                     "/obras/9007199254740993",   // acima do inteiro seguro: arredondaria
                     "/obras/7/outra", "/obras/7/toString", "/contratos/7/protocolo/x", "/painel/x", "/carteira/x", "/admin/x"]) {
      expect(parseRota(c)).toEqual({ tela: "raiz" });
    }
  });

  it("o detalhe guarda de onde se veio; trocar de aba mantém a origem; o menu não guarda", () => {
    const obra: Rota = { tela: "obra", id: 7, aba: "medicoes" };
    const vinda = origemPara({ tela: "medicoes" }, "/medicoes?obra=7", obra, undefined);
    expect(vinda).toEqual({ tela: "medicoes", href: "/medicoes?obra=7" });
    expect(origemPara(obra, "/obras/7", { tela: "obra", id: 7, aba: "prazos" }, vinda)).toEqual(vinda);
    expect(origemPara(obra, "/obras/7", { tela: "documentos" }, vinda)).toBeUndefined();
  });

  it("/avisos é a página Avisos; o endereço de antes (/obras?avisos=1) leva para ela com os filtros equivalentes (#805)", () => {
    expect(parseRota("/avisos")).toEqual({ tela: "avisos" });
    expect(caminhoDe({ tela: "avisos" })).toBe("/avisos");
    // `c=todas` era o padrão; `avisos`, `nivel`, `agrupar` e os filtros da lista de Obras ficam para trás
    expect(buscaDosAvisos({ c: "todas", avisos: "1" })).toEqual({});
    expect(buscaDosAvisos({ c: "todas", avisos: "1", obra: "7", familia: "prazos", nivel: "critico", agrupar: "obra", q: "granito" }))
      .toEqual({ familia: "prazos", obra: "7" });
    // o contratante do link continua valendo, também no `?orgao=` mais antigo
    expect(buscaDosAvisos({ c: "SINFRA", avisos: "1" })).toEqual({ c: "SINFRA" });
    expect(buscaDosAvisos({ orgao: "SINFRA - SUEF II", avisos: "1" })).toEqual({ c: "SINFRA - SUEF II" });
    window.history.replaceState(null, "", "/obras?c=todas&avisos=1&obra=7#x");
    substituir({ tela: "avisos" }, { busca: buscaDosAvisos({ c: "todas", avisos: "1", obra: "7" }) });
    expect(`${window.location.pathname}${window.location.search}${window.location.hash}`).toBe("/avisos?obra=7#x");
    window.history.replaceState(null, "", "/contratos?q=x");
    substituir({ tela: "obras" });
    expect(window.location.pathname + window.location.search).toBe("/obras?q=x");
  });
});
