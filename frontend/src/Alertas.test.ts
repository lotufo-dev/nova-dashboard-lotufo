import { describe, expect, it } from "vitest";
import { avisosDaObra, destinoDoAviso, type Aviso } from "./Alertas";
import { hrefDe } from "./rota";

const base: Omit<Aviso, "tipo" | "contrato_id" | "destino"> = {
  nivel: "acao", publico: ["operacao"], obra: null, dias: 3, valor_centavos: null, mensagem: "x" };

describe("destino do aviso", () => {
  it("a aba da obra vira a rota da obra; o de documento leva à empresa", () => {
    const prazo: Aviso = { ...base, tipo: "execucao_vencendo", contrato_id: 7, destino: { tela: "contrato", id: 7, aba: "prazos" } };
    const doc: Aviso = { ...base, tipo: "documentos_empresa", contrato_id: 7, destino: { tela: "documentos" }, entidade_id: 3 };
    const d1 = destinoDoAviso(prazo)!, d2 = destinoDoAviso(doc)!;
    expect(hrefDe(d1.para, undefined, d1.secao)).toBe("/obras/7/prazos");
    expect(hrefDe(d2.para, d2.busca, d2.secao)).toBe("/documentos/3");
    // #161: o aviso da regularidade do mes cai direto na aba dela, na pagina da empresa
    const reg: Aviso = { ...base, tipo: "regularidade_mes", contrato_id: null, destino: { tela: "documentos" }, entidade_id: 3 };
    const dr = destinoDoAviso(reg)!;
    expect(hrefDe(dr.para, dr.busca, dr.secao)).toBe("/documentos/3/regularidade");
    // A2: o aviso de nota leva as notas da medicao dela
    const nota: Aviso = { ...base, tipo: "nota_divergente", contrato_id: 7, medicao_id: 723, destino: { tela: "contrato", id: 7, aba: "notas" } };
    const d3 = destinoDoAviso(nota)!;
    expect(hrefDe(d3.para, undefined, d3.secao)).toBe("/obras/7/medicoes/723#notas");
    // A10: o aviso de reajuste leva ao ciclo da data-base
    const reaj: Aviso = { ...base, tipo: "reajuste_apostilamento", contrato_id: 7, data_base_mes: "2023-01", destino: { tela: "contrato", id: 7, aba: "reajuste" } };
    const d4 = destinoDoAviso(reaj)!;
    expect(hrefDe(d4.para, undefined, d4.secao)).toBe("/obras/7/reajuste#db-2023-01");
    // o pagamento atrasado (sem destino proprio) abre nas medicoes em andamento da obra
    const pag: Aviso = { ...base, tipo: "pagamento_atrasado", contrato_id: 9, destino: { tela: "contrato", id: 9, aba: "medicoes" } };
    const d5 = destinoDoAviso(pag)!;
    expect(hrefDe(d5.para, undefined, d5.secao)).toBe("/obras/9#em-andamento");
  });
});

describe("avisos da obra", () => {
  it("só os da obra, do mais grave ao mais atrasado, sem o nome da obra no começo", () => {
    const a = (tipo: string, nivel: Aviso["nivel"], contrato_id: number | null, data: string | null, mensagem: string): Aviso =>
      ({ ...base, tipo, nivel, contrato_id, obra: contrato_id === 7 ? "MT-388" : "Outra", data, mensagem, destino: null });
    const lista = [
      a("prazo", "atencao", 7, "2026-10-20", "MT-388: execução termina em 22 dias"),
      a("pleito", "atencao", 7, "2026-03-22", "MT-388: pleito enviado há 187 dias"),
      a("nota", "critico", 7, null, "MT-388: nota 1843 diverge do espelho"),
      a("prazo", "critico", 9, "2026-09-01", "Outra: vigência vencida"),
    ];
    expect(avisosDaObra(lista, 7).map(x => x.mensagem)).toEqual([
      "nota 1843 diverge do espelho", "pleito enviado há 187 dias", "execução termina em 22 dias"]);
  });
});

describe("aviso de garantia (#161)", () => {
  it("leva à aba Garantia por obra da empresa contratada", () => {
    for (const tipo of ["garantia_vencendo", "garantia_aquem_execucao"]) {
      const a: Aviso = { ...base, tipo, contrato_id: 7, destino: { tela: "documentos" }, entidade_id: 2 };
      const d = destinoDoAviso(a)!;
      expect(hrefDe(d.para, d.busca, d.secao)).toBe("/documentos/2/garantia");
    }
  });
});
