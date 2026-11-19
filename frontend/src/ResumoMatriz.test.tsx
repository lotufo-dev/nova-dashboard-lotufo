import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import ResumoMatriz, { type RespostaMatriz } from "./ResumoMatriz";

// A matriz obra por competencia (#659), que saiu da Inicio para o Resumo das medicoes em 19/11/2026 (decisao do dono,
// #805). Os casos sao os que ela tinha na Inicio. Dado sintetico; as 12 competencias terminam no mes anterior ao de hoje.
type Celula = RespostaMatriz["grupos"][number]["obras"][number]["celulas"][number];
const celulas = (ultimas: Celula[]): Celula[] => [...Array<Celula>(12 - ultimas.length).fill(null), ...ultimas];
const COMPETENCIAS = ["2025-10", "2025-11", "2025-12", "2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07",
  "2026-08", "2026-09"];
const MATRIZ: RespostaMatriz = {
  competencias: COMPETENCIAS,
  grupos: [
    { contratante: "Contratante A", obras: [
      { contrato_id: 7, obra: "Obra A", celulas: celulas([{ etapa: "recebida", medicao_id: 81 }, { etapa: "atrasado", medicao_id: 82 },
        { etapa: "protocolado", medicao_id: 83 }, { etapa: "em_analise", medicao_id: 84 }]) },
      { contrato_id: 8, obra: "Obra B", celulas: celulas([{ etapa: "nota", medicao_id: 91 }, null, { etapa: "boletim", medicao_id: 92 }]) }] },
    { contratante: "Contratante B", obras: [{ contrato_id: 9, obra: "Obra C", celulas: celulas([]) }] },
  ],
};
const NOME = "Medições por obra e competência";
/** O texto do elemento com espaco simples no lugar do espaco inseparavel. */
const limpo = (el: Element | null | undefined) => (el?.textContent ?? "").replace(/\s/g, " ");

describe("Matriz obra por competência no Resumo das medições (#659, #805)", () => {
  afterEach(cleanup);

  it("uma linha por obra, agrupada por contratante, 12 competências e a legenda das etapas", () => {
    render(<ResumoMatriz matriz={MATRIZ} />);
    const regiao = screen.getByRole("region", { name: NOME });
    const legenda = within(regiao).getByRole("list", { name: "Legenda das etapas" });
    // #805: a chave de cor de cada etapa e' a peca MarcaEtapa, a mesma do cabecalho das colunas do Fechamento
    expect([...legenda.children].map(li => [limpo(li), li.querySelector(".marca-etapa__cor")?.className])).toEqual([
      ["Em análise", "marca-etapa__cor marca-etapa__cor--em_analise"], ["Boletim", "marca-etapa__cor marca-etapa__cor--boletim"],
      ["Nota", "marca-etapa__cor marca-etapa__cor--nota"], ["Protocolado", "marca-etapa__cor marca-etapa__cor--protocolado"],
      ["Recebido", "marca-etapa__cor marca-etapa__cor--recebido"], ["Atrasado", "marca-etapa__cor marca-etapa__cor--atrasado"]]);
    // o cabecalho: o mes em cada coluna; o ano so' na primeira e em janeiro
    expect([...regiao.querySelectorAll(".rdm-matriz__mes")].map(m => [...m.children].map(limpo).join(" "))).toEqual(
      ["out 25", "nov", "dez", "jan 26", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set"]);
    expect(within(regiao).getAllByRole("heading", { level: 4 }).map(limpo)).toEqual(["Contratante A", "Contratante B"]);
    const linhas = [...regiao.querySelectorAll(".rdm-matriz__linha--obra")];
    expect(linhas.map(l => limpo(l.querySelector(".rdm-matriz__obra")))).toEqual(["Obra A", "Obra B", "Obra C"]);
    expect(linhas.map(l => l.querySelectorAll(".rdm-matriz__celula").length)).toEqual([12, 12, 12]);
  });

  it("cada célula pintada tem a cor da etapa, nome acessível e é um link para a medição; a vazia não", () => {
    render(<ResumoMatriz matriz={MATRIZ} />);
    const regiao = screen.getByRole("region", { name: NOME });
    const links = within(regiao).getAllByRole("link");
    expect(links.map(a => [a.getAttribute("aria-label"), a.getAttribute("href"), a.className.replace("rdm-matriz__celula ", "")])).toEqual([
      ["Obra A, 06/2026: Recebido", "/obras/7/medicoes/81", "rdm-matriz__celula--recebida"],
      ["Obra A, 07/2026: Atrasado", "/obras/7/medicoes/82", "rdm-matriz__celula--atrasado"],
      ["Obra A, 08/2026: Protocolado", "/obras/7/medicoes/83", "rdm-matriz__celula--protocolado"],
      ["Obra A, 09/2026: Em análise", "/obras/7/medicoes/84", "rdm-matriz__celula--em_analise"],
      ["Obra B, 07/2026: Nota", "/obras/8/medicoes/91", "rdm-matriz__celula--nota"],
      ["Obra B, 09/2026: Boletim", "/obras/8/medicoes/92", "rdm-matriz__celula--boletim"],
    ]);
    expect(links.every(a => a.getAttribute("title") === a.getAttribute("aria-label"))).toBe(true);
    const vazias = [...regiao.querySelectorAll(".rdm-matriz__celula:not(a)")];
    expect(vazias).toHaveLength(36 - 6);
    expect(vazias.every(v => v.className === "rdm-matriz__celula" && v.getAttribute("aria-hidden") === "true")).toBe(true);
  });

  it("a matriz tem a tabela equivalente, dentro de um div sr-only", () => {
    render(<ResumoMatriz matriz={MATRIZ} />);
    const regiao = screen.getByRole("region", { name: NOME });
    const tabela = within(regiao).getByRole("table", { name: "Etapa da medição de cada obra por competência" });
    expect(tabela.className).toBe("");
    expect(tabela.parentElement?.tagName).toBe("DIV");
    expect(tabela.parentElement?.className).toBe("sr-only");
    const t = "—";
    expect(within(tabela).getAllByRole("row").map(l => [...l.children].map(limpo))).toEqual([
      ["Obra", "Contratante", "10/2025", "11/2025", "12/2025", "01/2026", "02/2026", "03/2026", "04/2026", "05/2026", "06/2026",
        "07/2026", "08/2026", "09/2026"],
      ["Obra A", "Contratante A", t, t, t, t, t, t, t, t, "Recebido", "Atrasado", "Protocolado", "Em análise"],
      ["Obra B", "Contratante A", t, t, t, t, t, t, t, t, t, "Nota", t, "Boletim"],
      ["Obra C", "Contratante B", t, t, t, t, t, t, t, t, t, t, t, t],
    ]);
  });

  it("sem obra ativa, uma linha curta no lugar da matriz", () => {
    render(<ResumoMatriz matriz={{ competencias: COMPETENCIAS, grupos: [] }} />);
    const regiao = screen.getByRole("region", { name: NOME });
    expect(within(regiao).getByText("Nenhuma obra ativa.")).toBeTruthy();
    expect(regiao.querySelector(".rdm-matriz__grade, table")).toBeNull();
  });
});
