import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fmtCentesimos, fmtMilesimos, type QuadroDeResultados, type RespostaResultados } from "./licitacoes";
import LicitacoesResultados from "./LicitacoesResultados";
import { leitura } from "./licitacoesTeste";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

// Resultados (fatia 4 da #906). Licitações e números inventados.

const servidor = (resposta: RespostaResultados) => api.mockResolvedValue(resposta);
const regiao = (nome: string) => screen.getByRole("region", { name: nome });

const QUADRO: QuadroDeResultados = {
  funil: [{ rotulo: "Analisadas", n: 30 }, { rotulo: "Propostas", n: 12 }, { rotulo: "Vencidas", n: 3 }],
  por_tipo: [{ grupo: "Rodovia", participadas: 7, vencidas: 2, taxa: 286 }, { grupo: "Ponte", participadas: 0, vencidas: 0, taxa: null }],
  por_modalidade: [{ grupo: "Concorrência", participadas: 12, vencidas: 3, taxa: 250 }],
  perdas: [{ licitacao: "PME · CE 010/2026", motivo: "preço", data: "2026-10-20" }],
  descontos: [{ licitacao: "PME · CE 010/2026", empresa: 812, vencedor: 1530, vencemos: false },
    { licitacao: "DER-EX · CE 007/2026", empresa: 1105, vencedor: null, vencemos: true }],
};

describe("Resultados", () => {
  afterEach(() => { cleanup(); api.mockReset(); });

  it("formata a taxa em milésimos e o desconto em centésimos de ponto, como o servidor manda", () => {
    expect([fmtMilesimos(286), fmtMilesimos(0), fmtMilesimos(1000)]).toEqual(["28,6%", "0,0%", "100,0%"]);
    expect([fmtCentesimos(812), fmtCentesimos(1530), fmtCentesimos(-50)]).toEqual(["8,12%", "15,30%", "-0,50%"]);
  });

  it("o funil, as taxas por grupo, as perdas e os descontos do último quadro", async () => {
    servidor({ leitura: leitura(), lido_em: "2026-11-24T13:05:00+00:00", resultados: QUADRO } satisfies RespostaResultados);
    render(<LicitacoesResultados />);
    await screen.findByRole("region", { name: "Por tipo de obra" });
    // o quadro e' da ultima leitura: a data dele nao se repete
    expect(screen.queryByText(/Quadro da leitura de/)).toBeNull();
    expect([...screen.getByLabelText("Funil das licitações").querySelectorAll(".lic-numero")].map(n => n.textContent))
      .toEqual(["Analisadas30", "Propostas12", "Vencidas3"]);
    const tipos = within(regiao("Por tipo de obra")).getAllByRole("row").slice(1).map(l => [...l.querySelectorAll("th, td")].map(c => c.textContent));
    expect(tipos).toEqual([["Rodovia", "7", "2", "28,6%"], ["Ponte", "0", "0", "—"]]);
    const descontos = within(regiao("Descontos")).getAllByRole("row").slice(1).map(l => [...l.querySelectorAll("th, td")].map(c => c.textContent));
    expect(descontos).toEqual([["PME · CE 010/2026", "8,12%", "15,30%"], ["DER-EX · CE 007/2026Vencida", "11,05%", "—"]]);
    expect(within(regiao("Perdas")).getByText("20/10/2026")).toBeTruthy();
  });

  it("o quadro de uma leitura anterior diz de quando é", async () => {
    servidor({ leitura: leitura(), lido_em: "2026-11-20T13:05:00+00:00", resultados: QUADRO } satisfies RespostaResultados);
    render(<LicitacoesResultados />);
    expect((await screen.findByText(/Quadro da leitura de/)).textContent).toBe("Quadro da leitura de 20/11 às 09:05");
  });

  it("sem quadro: a linha curta", async () => {
    servidor({ leitura: leitura(), lido_em: null, resultados: null } satisfies RespostaResultados);
    render(<LicitacoesResultados />);
    expect(await screen.findByText("O radar ainda não mandou resultados.")).toBeTruthy();
  });
});
