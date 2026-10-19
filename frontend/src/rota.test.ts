import { describe, expect, it } from "vitest";
import { buscaDosAvisosEmObras, caminhoDe, hrefDe, origemPara, parseRota, substituir, type Rota } from "./rota";

describe("rota", () => {
  it("toda rota tem um caminho canônico e volta igual", () => {
    const rotas: Rota[] = [
      { tela: "inicio" }, { tela: "medicoes" }, { tela: "carteira" }, { tela: "obras" },
      { tela: "documentos" }, { tela: "admin" }, { tela: "conta" }, { tela: "avisos" },
      { tela: "obra", id: 7, aba: "medicoes" },
      { tela: "medicao", obra: 7, id: 723 },
      { tela: "obra", id: 7, aba: "documentos" },
      { tela: "obra", id: 12, aba: "reajuste" },
      { tela: "obra", id: 12, aba: "prazos" },
      { tela: "obra", id: 12, aba: "contrato" },
      { tela: "a-receber" }, { tela: "carteira", aba: "qdop" }, { tela: "carteira", aba: "producao" },
      { tela: "admin", aba: "reconciliacao" }, { tela: "admin", aba: "usuarios" }, { tela: "admin", aba: "auditoria" },
      { tela: "notas-envio", id: 55 },
      { tela: "documentos-empresa", id: 3 }, { tela: "documentos-empresa", id: 3, aba: "regularidade" },
      { tela: "documentos-empresa", id: 3, aba: "garantia" },
      { tela: "medicoes", aba: "sem-medicao" }, { tela: "medicoes", aba: "faturamento" },
      { tela: "medicoes", aba: "aguardando-nota" }, { tela: "medicoes", aba: "enviar-nota" },
      { tela: "medicoes", aba: "aguardando-pagamento" },
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
    expect(parseRota("/contratos/7")).toEqual({ tela: "obra", id: 7, aba: "medicoes" });
    expect(parseRota("/contratos/7/prazos")).toEqual({ tela: "obra", id: 7, aba: "prazos" });
    expect(parseRota("/diretoria")).toEqual({ tela: "carteira" });
    expect(parseRota("/painel")).toEqual({ tela: "carteira" });
    expect(parseRota("/certidoes")).toEqual({ tela: "documentos" });
    expect(caminhoDe(parseRota("/contratos/7/prazos"))).toBe("/obras/7/prazos");
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
    expect(caminhoDe(parseRota("/contratos/7/notas"))).toBe("/obras/7");
  });

  it("a aba padrão (da obra, da Carteira) não entra na URL; filtros e seção entram", () => {
    expect(caminhoDe({ tela: "obra", id: 7, aba: "medicoes" })).toBe("/obras/7");
    expect(parseRota("/obras/7/medicoes")).toEqual({ tela: "obra", id: 7, aba: "medicoes" });
    expect(caminhoDe({ tela: "carteira", aba: "resumo" })).toBe("/carteira");
    expect(parseRota("/carteira/resumo")).toEqual({ tela: "carteira" });
    expect(parseRota("/admin/saude")).toEqual({ tela: "admin" });
    expect(hrefDe({ tela: "documentos" }, { pendentes: "1", vazio: "" }, "emp-3")).toBe("/documentos?pendentes=1#emp-3");
    expect(hrefDe({ tela: "avisos" }, { familia: "prazo", obra: "7" })).toBe("/avisos?familia=prazo&obra=7");
  });

  it("Medições tem abas; o Resumo é a padrão e não entra na URL", () => {
    expect(caminhoDe({ tela: "medicoes" })).toBe("/medicoes");
    expect(caminhoDe({ tela: "medicoes", aba: "resumo" })).toBe("/medicoes");
    expect(parseRota("/medicoes/resumo")).toEqual({ tela: "medicoes" });
    expect(caminhoDe({ tela: "medicoes", aba: "enviar-nota" })).toBe("/medicoes/enviar-nota");
    expect(parseRota("/medicoes/aguardando-pagamento")).toEqual({ tela: "medicoes", aba: "aguardando-pagamento" });
    for (const c of ["/medicoes/x", "/medicoes/enviar-nota/1"]) expect(parseRota(c)).toEqual({ tela: "raiz" });
  });

  it("as notas viraram abas de Medições: os links antigos abrem a aba; o envio de um protocolo continua", () => {
    expect(parseRota("/notas")).toEqual({ tela: "medicoes", aba: "enviar-nota" });
    expect(parseRota("/notas/aguardando")).toEqual({ tela: "medicoes", aba: "aguardando-pagamento" });
    expect(hrefDe(parseRota("/notas"), { grupo: "SINFRA" })).toBe("/medicoes/enviar-nota?grupo=SINFRA");
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

  it("/avisos abre Obras com os Avisos abertos, de todas as obras, mantendo os filtros do link (#159)", () => {
    expect(parseRota("/avisos")).toEqual({ tela: "avisos" });
    expect(buscaDosAvisosEmObras({})).toEqual({ c: "todas", avisos: "1" });
    expect(buscaDosAvisosEmObras({ obra: "7", familia: "prazos" })).toEqual({ c: "todas", avisos: "1", obra: "7", familia: "prazos" });
    window.history.replaceState(null, "", "/avisos?obra=7#x");
    substituir({ tela: "obras" }, { busca: buscaDosAvisosEmObras({ obra: "7" }) });
    expect(`${window.location.pathname}${window.location.search}${window.location.hash}`).toBe("/obras?c=todas&avisos=1&obra=7#x");
    window.history.replaceState(null, "", "/contratos?q=x");
    substituir({ tela: "obras" });
    expect(window.location.pathname + window.location.search).toBe("/obras?q=x");
  });
});
