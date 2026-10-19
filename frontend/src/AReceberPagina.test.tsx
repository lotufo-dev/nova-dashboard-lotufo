import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import AReceberPagina from "./AReceberPagina";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

const mes = (competencia: string, previsto: number | null, recebido: number | null, atual = false, futuro = false) =>
  ({ competencia, atual, futuro, previsto_centavos: previsto, recebido_centavos: futuro ? null : recebido });
const MESES = [
  mes("2026-05", 1_000_000, 800_000), mes("2026-06", 1_200_000, 900_000), mes("2026-07", 1_100_000, 1_000_000),
  mes("2026-08", 1_300_000, 1_250_000), mes("2026-09", 1_500_000, 1_400_000), mes("2026-10", 2_000_000, 1_000_001, true),
  mes("2026-11", 2_100_000, null, false, true), mes("2026-12", 2_200_000, null, false, true), mes("2027-01", 2_300_000, null, false, true),
];
const item = (contrato_id: number, obra: string, medicao_id: number, numero: number, protocolada_em: string, valor_centavos: number | null) =>
  ({ contrato_id, obra, medicao_id, numero, tipo: "execucao", nota_numero: null, competencia: "2026-09", protocolada_em, valor_centavos });
const RESPOSTA = {
  hoje: "2026-10-16", total_a_receber_liberado: true,
  total: { quantidade: 4, obras: 2, valor_centavos: 1_500_003 },
  mes: MESES[5], meses: MESES,
  por_obra: [{ contrato_id: 1, obra: "Avenida das Palmeiras", quantidade: 2, valor_centavos: 1_000_002 },
             { contrato_id: 2, obra: "Terminal Norte", quantidade: 2, valor_centavos: 500_001 }],
  itens: [item(1, "Avenida das Palmeiras", 11, 11, "2026-09-05", 400_001), item(2, "Terminal Norte", 21, 6, "2026-09-18", 500_001),
          item(1, "Avenida das Palmeiras", 12, 12, "2026-10-10", 600_001),
          { contrato_id: 2, obra: "Terminal Norte", medicao_id: null, numero: null, tipo: "nota", nota_numero: "900", competencia: null,
            protocolada_em: "2026-06-01", valor_centavos: 0 }],
};

afterEach(() => { cleanup(); api.mockReset(); });

describe("A receber", () => {
  it("mostra os tres numeros do alto com o percentual do previsto", async () => {
    api.mockResolvedValue(RESPOSTA);
    render(<AReceberPagina />);
    const resumo = await screen.findByRole("region", { name: "Resumo" });
    expect(api).toHaveBeenCalledWith("/api/a-receber");
    expect(within(resumo).getByText("A receber, na cota").nextSibling?.textContent).toMatch(/R\$\s*15\.000,03/);
    expect(within(resumo).getByText("Previsto em outubro").nextSibling?.textContent).toMatch(/R\$\s*20\.000,00/);
    expect(within(resumo).getByText("Medições recebidas em outubro").nextSibling?.textContent).toMatch(/R\$\s*10\.000,01/);
    expect(within(resumo).getByText(/50% do previsto · até 16\/10\/2026/)).toBeTruthy();
  });

  it("clicar num mes do grafico troca o detalhe; o mes atual vem escolhido e a previsao so' tem previsto", async () => {
    api.mockResolvedValue(RESPOSTA);
    render(<AReceberPagina />);
    const detalhe = (await screen.findAllByRole("status"))[0];
    expect(detalhe.textContent).toMatch(/Outubro de 2026 \(mês atual, até 16\/10\)/);
    fireEvent.click(screen.getByRole("button", { name: /^agosto de 2026: previsto/ }));
    expect(detalhe.textContent).toMatch(/Agosto de 2026: previsto R\$\s*13\.000,00 · recebido R\$\s*12\.500,00 · 96% do previsto/);
    fireEvent.click(screen.getByRole("button", { name: /^dezembro de 2026: previsão/ }));
    expect(detalhe.textContent).toMatch(/Dezembro de 2026 \(previsão\): R\$\s*22\.000,00/);
  });

  it("as setas percorrem os meses do grafico, levando o foco junto", async () => {
    api.mockResolvedValue(RESPOSTA);
    render(<AReceberPagina />);
    const detalhe = (await screen.findAllByRole("status"))[0];
    const set = screen.getByRole("button", { name: /^setembro de 2026: previsto/ });
    fireEvent.keyDown(screen.getByRole("button", { name: /^outubro de 2026: previsto/ }), { key: "ArrowLeft" });
    expect(document.activeElement).toBe(set);
    fireEvent.keyDown(set, { key: "ArrowLeft" });
    expect(detalhe.textContent).toMatch(/^Agosto de 2026/);
  });

  it("clicar numa obra filtra a tabela e o total; clicar de novo ou em Mostrar todas volta", async () => {
    api.mockResolvedValue(RESPOSTA);
    render(<AReceberPagina />);
    const tabela = await screen.findByRole("table", { name: /Cobranças esperando pagamento, na cota/ });
    expect(within(tabela).getAllByRole("row")).toHaveLength(1 + 4 + 1);                    // cabeca, 4 cobrancas, rodape
    fireEvent.click(screen.getByRole("button", { name: /Terminal Norte/ }));
    expect(within(tabela).getAllByRole("row")).toHaveLength(1 + 2 + 1);
    expect(within(tabela).getByText(/Total de Terminal Norte \(2\)/)).toBeTruthy();
    expect(within(tabela).getAllByText(/R\$\s*5\.000,01/).length).toBeGreaterThan(0);
    expect(screen.getByText("Só Terminal Norte")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Mostrar todas" }));
    expect(within(tabela).getAllByRole("row")).toHaveLength(1 + 4 + 1);
  });

  it("a linha leva a etapa de pagamento da medicao; a nota do RM leva a obra", async () => {
    api.mockResolvedValue(RESPOSTA);
    render(<AReceberPagina />);
    const abrir = await screen.findAllByRole("link", { name: /^Abrir/ });
    expect(abrir[0].getAttribute("href")).toContain("/medicoes/");
    expect(abrir[0].getAttribute("href")).toContain("#etapa-5");
    expect(screen.getByText("Nota do RM 900")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Abrir a obra Terminal Norte" })).toBeTruthy();
  });

  it("antes da conciliacao o valor e' tracinho e a tela diz que ha' valores a conciliar", async () => {
    api.mockResolvedValue({
      ...RESPOSTA, total_a_receber_liberado: false, total: { quantidade: 4, obras: 2, valor_centavos: null },
      mes: { ...MESES[5], previsto_centavos: null }, meses: MESES.map(m => ({ ...m, previsto_centavos: null })),
      por_obra: RESPOSTA.por_obra.map(o => ({ ...o, valor_centavos: null })), itens: RESPOSTA.itens.map(i => ({ ...i, valor_centavos: null })),
    });
    render(<AReceberPagina />);
    const resumo = await screen.findByRole("region", { name: "Resumo" });
    expect(within(resumo).getByText("A receber, na cota").nextSibling?.textContent).toBe("—");
    expect(within(resumo).getByText("valores a conciliar com a controladoria")).toBeTruthy();
    expect(within(resumo).getByText("Medições recebidas em outubro").nextSibling?.textContent).toMatch(/R\$\s*10\.000,01/);
  });

  it("erro da API vira mensagem em portugues", async () => {
    api.mockRejectedValue(new Error("falhou"));
    render(<AReceberPagina />);
    expect((await screen.findByRole("alert")).textContent).toMatch(/Recarregue a página/);
  });
});
