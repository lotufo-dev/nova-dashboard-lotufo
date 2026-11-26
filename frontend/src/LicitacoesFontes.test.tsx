import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiErro } from "./api";
import {
  fmtCentesimos, fmtMilesimos, type FonteDoRadar, type ParConferido, type ParParaConferir, type QuadroDeResultados,
  type RespostaFontes, type RespostaResultados,
} from "./licitacoes";
import LicitacoesFontes from "./LicitacoesFontes";
import LicitacoesResultados from "./LicitacoesResultados";
import { HOJE_DO_TESTE, leitura, linha } from "./licitacoesTeste";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

// Fontes e Resultados (fatia 4 da #906). Licitações, fontes, regras e números inventados. 24/11/2026, 11h em Cuiabá.

const fonte = (nome: string, situacao: FonteDoRadar["situacao"], extra: Partial<FonteDoRadar> = {}): FonteDoRadar => ({
  fonte: nome.toLowerCase(), nome, estado: null, lidos: 10, hora: "09:01", problema: null, aguardando: null, situacao, ...extra });
const PAR: ParParaConferir = { id: 7, par: "p-1-2", motivo: "mesmo objeto e mesma data", a: linha(1), b: linha(2) };
const CONFERIDO: ParConferido = { ...PAR, id: 8, par: "p-3-4", a: linha(3), b: linha(4), resposta: "outro", resposta_rotulo: "É outro",
  quem: "Admin", quando: "2026-11-24T14:00:00+00:00" };
const RESPOSTAS: RespostaFontes["respostas"] = [{ resposta: "mesmo", rotulo: "É o mesmo" }, { resposta: "outro", rotulo: "É outro" }];
const fontes = (extra: Partial<RespostaFontes> = {}): RespostaFontes => ({
  leitura: leitura(), decisoes: "radar", pode_decidir: false, respostas: RESPOSTAS,
  fontes: [fonte("PNCP", "feito", { lidos: 412 }), fonte("Diário de Exemplo", "critico", { problema: "a página não respondeu", lidos: 0 }),
    fonte("Agregador", "breve", { aguardando: "a próxima janela do robô", lidos: null, hora: null })],
  alertas: [{ regra: "interesse", nome: "Órgãos de interesse", linhas: [linha(5), linha(6)] }, { regra: "gv", nome: "Grande vulto", linhas: [] }],
  pares: [PAR], conferidos: [CONFERIDO], ...extra });

function servidor(leituras: unknown[], falhaNoPost?: Error) {
  let n = 0;
  api.mockImplementation(async (_caminho: string, opcoes?: RequestInit) => {
    if (opcoes?.method === "POST") { if (falhaNoPost) throw falhaNoPost; return { id: 0 }; }
    return leituras[Math.min(n++, leituras.length - 1)];
  });
}
const regiao = (nome: string) => screen.getByRole("region", { name: nome });
const posts = () => api.mock.calls.filter(c => c[1]?.method === "POST").map(c => [c[0], JSON.parse(c[1].body)]);

describe("Fontes", () => {
  beforeEach(() => { vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(HOJE_DO_TESTE); });
  afterEach(() => { cleanup(); api.mockReset(); vi.useRealTimers(); });

  it("cada fonte com a situação que o servidor leu, a palavra ao lado e o que aconteceu", async () => {
    servidor([fontes()]);
    render(<LicitacoesFontes />);
    await screen.findByRole("region", { name: "Situação das fontes" });
    const linhas = within(regiao("Situação das fontes")).getAllByRole("row").slice(1);
    expect(linhas.map(l => [...l.querySelectorAll("th, td")].map(c => c.textContent))).toEqual([
      ["PNCP", "Lida", "412", "09:01", "—"],
      ["Diário de Exemplo", "Com problema", "0", "09:01", "a página não respondeu"],
      ["Agregador", "Aguardando", "—", "—", "a próxima janela do robô"]]);
    expect(linhas[1].querySelector(".selo")!.className).toMatch(/critico/);
  });

  it("os alertas do dia, cada regra com as licitações dela; a regra sem nenhuma fica com o traço", async () => {
    servidor([fontes()]);
    render(<LicitacoesFontes />);
    await screen.findByRole("region", { name: "Alertas do dia" });
    const grupos = within(regiao("Alertas do dia")).getAllByRole("columnheader").filter(c => c.getAttribute("scope") === "colgroup");
    expect(grupos.map(g => g.textContent)).toEqual(["Órgãos de interesse22 licitações", "Grande vulto00 licitações"]);
    expect(within(regiao("Alertas do dia")).getAllByRole("rowheader").map(c => c.textContent?.slice(0, 14))).toEqual(
      ["PME · CE 005/2", "PME · CE 006/2"]);
  });

  it("antes do corte a conferência só mostra: os pares e os respondidos, sem botão", async () => {
    servidor([fontes()]);
    render(<LicitacoesFontes />);
    await screen.findByRole("region", { name: "Conferência" });
    expect(within(regiao("Conferência")).queryAllByRole("button")).toEqual([]);
    expect(within(regiao("Conferência")).getByText("mesmo objeto e mesma data")).toBeTruthy();
    expect(within(regiao("Conferência")).getByText("É outro")).toBeTruthy();
    expect(regiao("Conferência").textContent).toMatch(/Admin · 24\/11\/2026/);
  });

  it("depois do corte: É o mesmo, É outro e Refazer gravam pelo par e a página lê de novo", async () => {
    const corte = { decisoes: "dashboard" as const, pode_decidir: true };
    servidor([fontes(corte), fontes({ ...corte, pares: [], conferidos: [CONFERIDO, { ...PAR, resposta: "mesmo", resposta_rotulo: "É o mesmo", quem: "Admin", quando: "2026-11-24T15:00:00+00:00" }] })]);
    render(<LicitacoesFontes />);
    await screen.findByRole("region", { name: "Conferência" });
    expect(within(regiao("Conferência")).getAllByRole("button").map(b => b.textContent)).toEqual(["É o mesmo", "É outro", "Refazer"]);
    fireEvent.click(screen.getByRole("button", { name: "É o mesmo: PME · CE 001/2026 e PME · CE 002/2026" }));
    await waitFor(() => expect(screen.getByText("Nenhum par a conferir.")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Refazer: PME · CE 003/2026 e PME · CE 004/2026" }));
    await waitFor(() => expect(posts()).toHaveLength(2));
    expect(posts()).toEqual([["/api/licitacoes/pares/7/conferencia", { resposta: "mesmo" }],
      ["/api/licitacoes/pares/8/conferencia/desfazer", {}]]);
  });

  it("a recusa do servidor aparece junto do par", async () => {
    const corte = { decisoes: "dashboard" as const, pode_decidir: true };
    servidor([fontes(corte)], new ApiErro(422, "Escolha a resposta: é o mesmo ou é outro"));
    render(<LicitacoesFontes />);
    await screen.findByRole("region", { name: "Conferência" });
    fireEvent.click(screen.getByRole("button", { name: /^É outro: PME · CE 001/ }));
    expect(await within(regiao("Conferência")).findByText("Escolha a resposta: é o mesmo ou é outro")).toBeTruthy();
  });

  it("sem leitura nenhuma: o aviso e as três linhas curtas", async () => {
    servidor([fontes({ leitura: leitura({ lido_em: null, atrasada: true }), fontes: [], alertas: [], pares: [], conferidos: [] })]);
    render(<LicitacoesFontes />);
    expect(await screen.findByText("O radar ainda não entregou leitura.")).toBeTruthy();
    for (const t of ["Nenhuma fonte na última leitura.", "Nenhum alerta na última leitura.", "Nenhum par a conferir."]) {
      expect(screen.getByText(t)).toBeTruthy();
    }
  });
});

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
    servidor([{ leitura: leitura(), lido_em: "2026-11-24T13:05:00+00:00", resultados: QUADRO } satisfies RespostaResultados]);
    render(<LicitacoesResultados />);
    await screen.findByRole("region", { name: "Por tipo de obra" });
    expect(screen.getByText(/Quadro da leitura de/).textContent).toBe("Quadro da leitura de 24/11 às 09:05");
    expect([...screen.getByLabelText("Funil das licitações").querySelectorAll(".lic-numero")].map(n => n.textContent))
      .toEqual(["Analisadas30", "Propostas12", "Vencidas3"]);
    const tipos = within(regiao("Por tipo de obra")).getAllByRole("row").slice(1).map(l => [...l.querySelectorAll("th, td")].map(c => c.textContent));
    expect(tipos).toEqual([["Rodovia", "7", "2", "28,6%"], ["Ponte", "0", "0", "—"]]);
    const descontos = within(regiao("Descontos")).getAllByRole("row").slice(1).map(l => [...l.querySelectorAll("th, td")].map(c => c.textContent));
    expect(descontos).toEqual([["PME · CE 010/2026", "8,12%", "15,30%"], ["DER-EX · CE 007/2026Vencida", "11,05%", "—"]]);
    expect(within(regiao("Perdas")).getByText("20/10/2026")).toBeTruthy();
  });

  it("sem quadro: a linha curta", async () => {
    servidor([{ leitura: leitura(), lido_em: null, resultados: null } satisfies RespostaResultados]);
    render(<LicitacoesResultados />);
    expect(await screen.findByText("O radar ainda não mandou resultados.")).toBeTruthy();
  });
});
