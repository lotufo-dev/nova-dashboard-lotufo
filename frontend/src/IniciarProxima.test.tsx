import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import IniciarProxima from "./IniciarProxima";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

function responder(regra: string | null, medicoes: object[]) {
  api.mockImplementation(async (url: string) => (url.endsWith("/espelho") ? { regra: regra ? { situacao: regra } : null, espelhos: [] } : medicoes));
}

// 16/10/2026: o "Gerar espelho" da página da obra virou o atalho "Iniciar a Nª medição"; desde a #289 o primeiro
// passo é a planilha/carta: "Nova planilha/carta da Nª medição"
describe("Atalho Nova planilha/carta da Nª medição (página da obra)", () => {
  afterEach(() => { cleanup(); api.mockReset(); });

  it("sem medição prevista: leva à página da medição nova, com o número seguinte", async () => {
    responder("ativa", [{ id: 5, numero: 6, tipo: "execucao", estado: "recebida" }, { id: 6, numero: 6, tipo: "reajuste", estado: "recebida" }]);
    render(<IniciarProxima contratoId={9} versao={0} aoCriar={() => {}} />);
    const link = await screen.findByRole("link", { name: "Nova planilha/carta da 7ª medição" });
    expect(link.getAttribute("href")).toBe("/obras/9/medicoes/nova");
    expect(screen.queryByRole("button", { name: /Gerar espelho/ })).toBeNull();
  });

  it("com medição prevista no cronograma: leva à página dela", async () => {
    responder("ativa", [{ id: 8, numero: 3, tipo: "execucao", estado: "prevista" }]);
    render(<IniciarProxima contratoId={9} versao={0} aoCriar={() => {}} />);
    expect((await screen.findByRole("link", { name: "Nova planilha/carta da 3ª medição" })).getAttribute("href")).toBe("/obras/9/medicoes/8");
  });

  it("prevista de reajuste não entra no atalho da planilha/carta", async () => {
    responder("ativa", [{ id: 5, numero: 6, tipo: "execucao", estado: "recebida" }, { id: 7, numero: 6, tipo: "reajuste", estado: "prevista" }]);
    render(<IniciarProxima contratoId={9} versao={0} aoCriar={() => {}} />);
    expect((await screen.findByRole("link", { name: "Nova planilha/carta da 7ª medição" })).getAttribute("href")).toBe("/obras/9/medicoes/nova");
  });

  it("o nº do atalho é o seguinte da execução, como o do formulário (gate Sol, PR #382)", async () => {
    responder("ativa", [{ id: 5, numero: 6, tipo: "execucao", estado: "recebida" }, { id: 9, numero: 20, tipo: "projeto", estado: "recebida" }]);
    render(<IniciarProxima contratoId={9} versao={0} aoCriar={() => {}} />);
    expect(await screen.findByRole("link", { name: "Nova planilha/carta da 7ª medição" })).toBeTruthy();
  });

  it("obra do fluxo antigo: continua com a medição à mão, sem o atalho", async () => {
    responder(null, []);
    render(<IniciarProxima contratoId={9} versao={0} aoCriar={() => {}} />);
    expect(await screen.findByRole("form", { name: "Nova medição" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: /Nova planilha\/carta/ })).toBeNull();
  });
});
