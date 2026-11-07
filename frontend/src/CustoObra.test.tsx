import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import CustoObra from "./CustoObra";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

const linhaGrupo = (nome: string, tipo: string, medido: number | null, apontado: number, rateado: number) => ({
  nome, tipo, medido_centavos: medido, apontado_centavos: apontado, rateado_centavos: rateado,
  custo_centavos: apontado + rateado, diferenca_centavos: (medido ?? 0) - apontado - rateado,
});
const CUSTO = {
  contrato_id: 7, obra: "Obra Alfa", grupos: ["Terraplenagem", "Pavimentação"],
  rm: { sincronizado_em: "2026-11-03T14:05:00+00:00", desatualizado: true },
  linhas: [
    { competencia: "2026-03", medicoes: [{ id: 1, numero: 1, nome: "1ª medição" }], medido_centavos: 300_00,
      apontado_centavos: 40_00, rateado_centavos: 10_01, custo_centavos: 50_01, diferenca_centavos: 249_99,
      previsto_centavos: 1_000_00,
      grupos: [linhaGrupo("Terraplenagem", "grupo", 100_00, 40_00, 10_01), linhaGrupo("Pavimentação", "grupo", 200_00, 0, 0)] },
    { competencia: "2026-04", medicoes: [{ id: 2, numero: 2, nome: "2ª medição" }], medido_centavos: 450_01,
      apontado_centavos: 0, rateado_centavos: 25_00, custo_centavos: 25_00, diferenca_centavos: 425_01,
      previsto_centavos: null,
      grupos: [linhaGrupo("Terraplenagem", "grupo", null, 0, 0), linhaGrupo("Pavimentação", "grupo", null, 0, 0),
               linhaGrupo("Sem grupo", "sem_grupo", null, 0, 25_00),
               linhaGrupo("Medido por grupo não lido", "nao_lido", 450_01, 0, 0)] },
  ],
  acumulado: { medido_centavos: 750_01, apontado_centavos: 40_00, rateado_centavos: 35_01, custo_centavos: 75_01,
               diferenca_centavos: 675_00, previsto_centavos: 1_000_00 },
};

function responder(custo: unknown = CUSTO, obras: unknown = [{ contrato_id: 7, obra: "Obra Alfa" }, { contrato_id: 9, obra: "Obra Beta" }]) {
  api.mockImplementation((url: string) => {
    if (url === "/api/diretoria/custo") return Promise.resolve(obras);
    if (url.startsWith("/api/diretoria/custo/")) return Promise.resolve({ ...(custo as object), contrato_id: Number(url.split("/").pop()) });
    return Promise.reject(new Error(url));
  });
}

afterEach(() => { cleanup(); api.mockReset(); });

describe("CustoObra (#491)", () => {
  it("mostra o seletor só com as obras do servidor e a tabela da primeira, com grupos e rodapé", async () => {
    responder();
    render(<CustoObra />);
    const seletor = await screen.findByLabelText("Obra");
    expect(within(seletor).getAllByRole("option").map(o => o.textContent)).toEqual(["Obra Alfa", "Obra Beta"]);
    expect(await screen.findByRole("heading", { name: "Custo lançado no RM" })).toBeTruthy();
    const tabela = screen.getByRole("table");
    expect(within(tabela).getAllByText("Terraplenagem").length).toBeGreaterThan(0);
    expect(within(tabela).getByText("Sem grupo")).toBeTruthy();
    expect(within(tabela).getByText("Medido por grupo não lido")).toBeTruthy();
    expect(within(tabela).getByText("1ª medição")).toBeTruthy();
    expect(within(tabela).getAllByText("R$ 1.000,00")).toHaveLength(2);  // previsto da competência e o acumulado
    const rodape = tabela.querySelector("tfoot")!;
    expect(within(rodape as HTMLElement).getByText("Acumulado")).toBeTruthy();
    expect(within(rodape as HTMLElement).getByText("R$ 750,01")).toBeTruthy();
    expect(within(rodape as HTMLElement).getByText("R$ 75,01")).toBeTruthy();
    expect(within(rodape as HTMLElement).getByText("R$ 675,00")).toBeTruthy();
    fireEvent.change(seletor, { target: { value: "9" } });
    await screen.findByRole("heading", { name: "Custo lançado no RM" });
    expect(api).toHaveBeenCalledWith("/api/diretoria/custo/9");
  });

  it("avisa a data da última sincronização do RM só quando passou de um dia", async () => {
    responder();
    render(<CustoObra />);
    expect(await screen.findByText(/RM sincronizado pela última vez em 03\/11\/2026 10:05/)).toBeTruthy();
    cleanup();
    responder({ ...CUSTO, rm: { sincronizado_em: "2026-11-07T10:00:00+00:00", desatualizado: false } });
    render(<CustoObra />);
    await screen.findByRole("heading", { name: "Custo lançado no RM" });
    expect(screen.queryByText(/RM sincronizado pela última vez/)).toBeNull();
  });

  it("nenhum texto de margem, lucro ou resultado na tela", async () => {
    responder();
    const { container } = render(<CustoObra />);
    await screen.findByRole("heading", { name: "Custo lançado no RM" });
    expect(container.textContent!.toLowerCase()).not.toMatch(/margem|lucro|resultado/);
  });

  it("sem obra com cadastro de custo, uma linha curta no lugar da tabela", async () => {
    responder(CUSTO, []);
    render(<CustoObra />);
    expect(await screen.findByText("Nenhuma obra com cadastro de custo.")).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("erro de uma obra fica nela: o seletor continua e outra obra abre", async () => {
    api.mockImplementation((url: string) => {
      if (url === "/api/diretoria/custo") return Promise.resolve([{ contrato_id: 7, obra: "Obra Alfa" }, { contrato_id: 9, obra: "Obra Beta" }]);
      if (url === "/api/diretoria/custo/7") return Promise.reject(new Error("falhou"));
      return Promise.resolve({ ...CUSTO, contrato_id: 9 });
    });
    render(<CustoObra />);
    expect(await screen.findByRole("alert")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Obra"), { target: { value: "9" } });
    expect(await screen.findByRole("table")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
