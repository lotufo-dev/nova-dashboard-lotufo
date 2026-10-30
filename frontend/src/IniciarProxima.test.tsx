import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import IniciarProxima from "./IniciarProxima";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

function responder(regra: string | null, medicoes: object[]) {
  api.mockImplementation(async (url: string) => (url.endsWith("/espelho") ? { regra: regra ? { situacao: regra } : null, espelhos: [] } : medicoes));
}

// 16/10/2026: o "Gerar espelho" da página da obra virou o atalho "Iniciar a Nª medição"
describe("Atalho Iniciar a Nª medição (página da obra)", () => {
  afterEach(() => { cleanup(); api.mockReset(); });

  it("sem medição prevista: leva à página da medição nova, com o número seguinte", async () => {
    responder("ativa", [{ id: 5, numero: 6, tipo: "execucao", estado: "recebida" }, { id: 6, numero: 6, tipo: "reajuste", estado: "recebida" }]);
    render(<IniciarProxima contratoId={9} versao={0} aoCriar={() => {}} />);
    const link = await screen.findByRole("link", { name: /Iniciar a 7ª medição/ });
    expect(link.getAttribute("href")).toBe("/obras/9/medicoes/nova");
    expect(screen.queryByRole("button", { name: /Gerar espelho/ })).toBeNull();
  });

  it("com medição prevista no cronograma: leva à página dela", async () => {
    responder("ativa", [{ id: 8, numero: 3, tipo: "execucao", estado: "prevista" }]);
    render(<IniciarProxima contratoId={9} versao={0} aoCriar={() => {}} />);
    expect((await screen.findByRole("link", { name: /Iniciar a 3ª medição/ })).getAttribute("href")).toBe("/obras/9/medicoes/8");
  });

  it("obra do fluxo antigo: continua com a medição à mão, sem o atalho", async () => {
    responder(null, []);
    render(<IniciarProxima contratoId={9} versao={0} aoCriar={() => {}} />);
    expect(await screen.findByRole("form", { name: "Nova medição" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: /Iniciar a/ })).toBeNull();
  });
});
