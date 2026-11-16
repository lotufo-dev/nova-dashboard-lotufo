import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Instrumentos from "./Instrumentos";
import type { InstrumentoCadastro } from "./obra";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

describe("Instrumentos", () => {
  afterEach(() => { cleanup(); api.mockReset(); });

  const apostilamento = (id: number, dados: Record<string, unknown>): InstrumentoCadastro => ({
    id, chave: `ap-${id}`, tipo: "apostilamento_reajuste", numero: `AP-${id}`, data: `2026-0${id}-10`, dados });

  /** O texto da coluna Efeito de cada apostilamento, pelo número do termo. */
  async function efeitos(cadastro: InstrumentoCadastro[]): Promise<Record<string, string | null>> {
    api.mockImplementation(async (caminho: string) => caminho.endsWith("/aditivos") ? []
      : { situacao: { instrumentos: [] } });
    render(<Instrumentos contratoId={7} cadastro={cadastro} erroCadastro="" />);
    const tabela = await screen.findByRole("table");
    expect(tabela.textContent).not.toContain("NaN");
    return Object.fromEntries(within(tabela).getAllByRole("row").slice(1).map(tr => {
      const td = tr.querySelectorAll("td");
      return [td[2].textContent, td[3].textContent];
    }));
  }

  it("o percentual do apostilamento de reajuste lê o que o cadastro guarda: número, texto e vírgula decimal", async () => {
    expect(await efeitos([
      apostilamento(1, { percentual: 4.5, data_base: "2025-01" }),
      apostilamento(2, { percentual: "4.5", data_base: "2025-01" }),
      apostilamento(3, { percentual: "3,50", data_base: "2025-01" }),
      apostilamento(4, { percentual: "4,125%", eficacia: "2026-04-15", data_base: "2025-01" }),
    ])).toEqual({
      "AP-1": "4,5% · data-base 01/2025",
      "AP-2": "4,5% · data-base 01/2025",
      "AP-3": "3,5% · data-base 01/2025",
      "AP-4": "4,125% · eficácia 15/04/2026 · data-base 01/2025",
    });
  });

  it("percentual que não é número sai da linha, sem \"NaN%\"; sem mais nada, o efeito é o tracinho", async () => {
    expect(await efeitos([
      apostilamento(1, { percentual: "a definir", data_base: "2025-01" }),
      apostilamento(2, { percentual: "", eficacia: "2026-02-15" }),
      apostilamento(3, { percentual: "a definir" }),
      apostilamento(4, { percentual: null }),
    ])).toEqual({
      "AP-1": "data-base 01/2025",
      "AP-2": "eficácia 15/02/2026",
      "AP-3": "—",
      "AP-4": "—",
    });
  });
});
