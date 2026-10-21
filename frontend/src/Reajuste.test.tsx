import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Reajuste from "./Reajuste";

const { api, apiForm } = vi.hoisted(() => ({ api: vi.fn(), apiForm: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api, apiForm }));

describe("Reajuste", () => {
  afterEach(() => { cleanup(); api.mockReset(); });

  it("mostra o pleito não enviado e abre o fluxo com a data-base", async () => {
    api.mockImplementation(async (caminho: string) => caminho.endsWith("/reajuste")
      ? { ciclos: [{ data_base_mes: "2024-06", indice: "INCC-DI", ciclo: 2026, aniversario: "2026-06-01",
                     situacao: "pleito_pendente", dias: -14, pleito: null, apostilamento: null }], pleitos: [] }
      : { instrumentos: [] });
    render(<Reajuste contratoId={7} podeEditar />);
    expect(await screen.findByText("pleito não enviado")).toBeTruthy();
    // um cartao por data-base (com ancora), e a linha do ciclo com os dias do servidor
    expect(screen.getByRole("region", { name: /^Data-base 06\/2024 · INCC-DI/ }).closest("[id]")?.id).toBe("db-2024-06");
    expect(screen.getByText("Ciclo de 2026 · fez aniversário em 01/06/2026 (há 14 dias)")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Enviar pleito" }));
    expect(screen.getByRole("form", { name: "Novo ofício" }).textContent).toContain("06/2024");
    expect(screen.getByLabelText("Nº do ofício (CT)")).toBeTruthy();
  });

  it("mostra a previsão gravada do ciclo, competência × valor com a origem (issue #272)", async () => {
    const prev = (competencia: string, valor: number, origem: string, ciclo = 2026) => ({ data_base_mes: "2024-06",
      ciclo, competencia, valor_previsto_centavos: valor, origem, pleito_id: 3 });
    api.mockImplementation(async (caminho: string) => caminho.endsWith("/reajuste")
      ? { ciclos: [{ data_base_mes: "2024-06", indice: "INCC-DI", ciclo: 2026, aniversario: "2026-06-01",
                     situacao: "pleito_pendente", dias: -14, pleito: null, apostilamento: null }], pleitos: [],
          previsoes: [prev("2026-07", 123456, "pleito"), prev("2026-08", 700, "manual"), prev("2025-07", 1, "pleito", 2025)] }
      : { instrumentos: [] });
    render(<Reajuste contratoId={7} podeEditar />);
    const tabela = await screen.findByRole("table", { name: "Previsão de reajuste do ciclo de 2026" });
    const linhas = within(tabela).getAllByRole("row");
    expect(linhas).toHaveLength(1 + 2 + 1);                   // so' o ciclo corrente; cabeca e total
    expect(linhas[1].textContent).toContain("07/2026");
    expect(linhas[1].textContent).toContain("R$ 1.234,56");
    expect(linhas[1].textContent).toContain("planilha do pleito");
    expect(linhas[2].textContent).toContain("digitada");
    expect(linhas[3].textContent).toContain("R$ 1.241,56");
  });

  it("mostra a parte do contrato de cada data-base ao lado do mês (issue #257)", async () => {
    const ciclo = { ciclo: 2026, situacao: "pleito_pendente", dias: 10, pleito: null, apostilamento: null };
    api.mockImplementation(async (caminho: string) => caminho.endsWith("/reajuste")
      ? { ciclos: [{ ...ciclo, data_base_mes: "2024-06", indice: "INCC-DI", aplica_a: "itens SINAPI", aniversario: "2026-06-01" },
                   { ...ciclo, data_base_mes: "2024-09", indice: "FGV/DNIT", aplica_a: "", aniversario: "2026-09-01" }],
          pleitos: [] }
      : { instrumentos: [] });
    render(<Reajuste contratoId={7} podeEditar={false} />);
    expect(await screen.findByRole("region", { name: "Data-base 06/2024 (itens SINAPI) · INCC-DI" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "Data-base 09/2024 · FGV/DNIT" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "06/2024 (itens SINAPI) · INCC-DI" })).toBeTruthy();
  });
});
