import { describe, expect, it } from "vitest";
import type { Aviso } from "./Alertas";
import { FAMILIAS, familiaDoAviso, filtrarAvisos, porFamilia, porObra, quandoDoAviso } from "./avisos";

const av = (tipo: string, nivel: Aviso["nivel"], contrato_id: number | null, aba: string | null, data: string | null = null): Aviso => ({
  tipo, nivel, publico: ["operacao"], contrato_id, obra: contrato_id ? `Obra ${contrato_id}` : null, dias: null,
  valor_centavos: null, mensagem: tipo, data,
  destino: aba === "documentos" ? { tela: "documentos" } : aba && contrato_id ? { tela: "contrato", id: contrato_id, aba } : null });

describe("avisos", () => {
  const lista = [
    av("reajuste_apostilamento", "atencao", 7, "reajuste", "2026-03-22"),
    av("execucao_vencendo", "critico", 12, "prazos", "2026-09-13"),
    { ...av("documentos_empresa", "critico", null, "documentos", "2026-07-26"), entidade_id: 2, entidade: "Oriundi" },
    av("nota_divergente", "critico", 7, "notas"),
    av("aviso_de_medicao", "acao", 9, "medicoes", "2026-06-01"),
    av("folga_quebrada", "acao", 15, "prazos"),
    av("tipo_novo", "atencao", 3, null),
  ];

  it("a família vem do lar do aviso (o destino); lar desconhecido é Outros", () => {
    expect(lista.map(familiaDoAviso)).toEqual(["reajuste", "prazo", "documentos", "nota", "outros", "prazo", "outros"]);
  });

  it("o pagamento atrasado saiu (#255): sem família Dinheiro e sem destino próprio", () => {
    expect(FAMILIAS.map(f => f.id)).toEqual(["prazo", "reajuste", "nota", "siga", "documentos", "outros"]);
    const antigo = { ...av("pagamento_atrasado", "acao", 9, "medicoes"), medicao_id: 722 };
    expect(familiaDoAviso(antigo)).toBe("outros");
  });

  it("os avisos do SIGA (#330) formam a família SIGA, entre Nota e Documentos", () => {
    const parado: Aviso = { ...av("siga_parado", "atencao", 7, null), destino: { tela: "siga", processo: 4 } };
    const sem: Aviso = { ...av("siga_sem_leitura", "acao", null, null), destino: { tela: "siga" } };
    expect([parado, sem].map(familiaDoAviso)).toEqual(["siga", "siga"]);
    expect(porFamilia([...lista, parado, sem]).map(g => g.rotulo)).toEqual(
      ["Prazo", "Reajuste", "Nota", "SIGA", "Documentos", "Outros"]);
  });

  it("por família, na ordem do mapa, do mais grave ao mais atrasado", () => {
    expect(porFamilia(lista).map(g => `${g.rotulo}: ${g.itens.map(a => a.tipo).join(", ")}`)).toEqual([
      "Prazo: execucao_vencendo, folga_quebrada", "Reajuste: reajuste_apostilamento", "Nota: nota_divergente",
      "Documentos: documentos_empresa", "Outros: aviso_de_medicao, tipo_novo"]);
  });

  it("por obra, a do aviso mais grave primeiro; os de empresa por empresa (A11), na posição do mais grave", () => {
    expect(porObra(lista).map(g => `${g.rotulo} (${g.itens.length})`)).toEqual([
      "Documentos · Oriundi (1)", "Obra 12 (1)", "Obra 7 (2)", "Obra 9 (1)", "Obra 15 (1)", "Obra 3 (1)"]);
  });

  it("quando, pelos dias e o sentido do servidor (A8)", () => {
    expect(quandoDoAviso({ ...lista[1], dias: -12, sentido: "prazo" }).replace(/\u00a0/g, " ")).toBe("venceu há 12 dias");
    expect(quandoDoAviso({ ...lista[1], dias: 3, sentido: "prazo" }).replace(/\u00a0/g, " ")).toBe("vence em 3 dias");
    expect(quandoDoAviso({ ...lista[0], dias: 187, sentido: "desde" }).replace(/\u00a0/g, " ")).toBe("há 187 dias");
  });

  it("filtra por família, nível e obra, como a URL pede", () => {
    expect(filtrarAvisos(lista, { familia: "prazo", nivel: "critico" }).map(a => a.tipo)).toEqual(["execucao_vencendo"]);
    expect(filtrarAvisos(lista, { obra: 7 }).map(a => a.tipo)).toEqual(["reajuste_apostilamento", "nota_divergente"]);
  });
});
