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
// contrato 1 e' do orgao 10 (SINFRA); contrato 2, do orgao 20 (Prefeitura)
const item = (contrato_id: number, obra: string, medicao_id: number, numero: number, protocolada_em: string, valor_centavos: number | null) =>
  ({ contrato_id, orgao_id: contrato_id === 1 ? 10 : 20, obra, medicao_id, numero, tipo: "execucao", nota_numero: null, competencia: "2026-09",
     protocolada_em, valor_centavos });
const RESPOSTA = {
  hoje: "2026-10-16", total_a_receber_liberado: true,
  total: { quantidade: 4, obras: 2, valor_centavos: 1_500_003 },
  antes_do_protocolo: { medido_esperando_nota: { quantidade: 1, valor_centavos: 700_007 },
                        nota_esperando_protocolo: { quantidade: 2, valor_centavos: 900_009 } },
  mes: MESES[5], meses: MESES,
  por_orgao: [{ orgao_id: 10, orgao: "SINFRA", quantidade: 2, valor_centavos: 1_000_002 },
              { orgao_id: 20, orgao: "Prefeitura", quantidade: 2, valor_centavos: 500_001 }],
  por_obra: [{ contrato_id: 1, obra: "Avenida das Palmeiras", quantidade: 2, valor_centavos: 1_000_002 },
             { contrato_id: 2, obra: "Terminal Norte", quantidade: 2, valor_centavos: 500_001 }],
  itens: [item(1, "Avenida das Palmeiras", 11, 11, "2026-09-05", 400_001), item(2, "Terminal Norte", 21, 6, "2026-09-18", 500_001),
          item(1, "Avenida das Palmeiras", 12, 12, "2026-10-10", 600_001),
          { contrato_id: 2, orgao_id: 20, obra: "Terminal Norte", medicao_id: null, numero: null, tipo: "nota", nota_numero: "900", competencia: null,
            protocolada_em: "2026-06-01", valor_centavos: 0 }],
};

afterEach(() => { cleanup(); api.mockReset(); });

describe("A receber", () => {
  it("mostra os quatro passos do dinheiro, na ordem do ciclo, sem frase de apoio", async () => {
    api.mockResolvedValue(RESPOSTA);
    render(<AReceberPagina />);
    const caminho = await screen.findByRole("region", { name: "Onde está o dinheiro, na cota" });
    expect(api).toHaveBeenCalledWith("/api/a-receber");
    expect(within(caminho).getAllByRole("listitem").map(li => li.firstChild?.textContent)).toEqual(
      ["Medido, sem nota", "Nota emitida, sem protocolo", "Protocolado, a receber", "Recebido em outubro"]);
    expect(within(caminho).getByText("Medido, sem nota").nextSibling?.textContent).toMatch(/R\$\s*7\.000,07/);
    expect(within(caminho).getByText("Nota emitida, sem protocolo").nextSibling?.textContent).toMatch(/R\$\s*9\.000,09/);
    expect(within(caminho).getByText("Protocolado, a receber").nextSibling?.textContent).toMatch(/R\$\s*15\.000,03/);
    expect(within(caminho).getByText("Recebido em outubro").nextSibling?.textContent).toMatch(/R\$\s*10\.000,01/);
    // 06/11/2026: o "previsto" por vencimento estimado saiu da tela
    expect(document.body.textContent).not.toMatch(/[Pp]revisto|[Pp]revisão|do previsto|até 16\/10|cobranças em/);
  });

  it("o grafico e' so' o recebido dos meses ate' o atual; clicar num mes troca o detalhe", async () => {
    api.mockResolvedValue(RESPOSTA);
    render(<AReceberPagina />);
    const detalhe = (await screen.findAllByRole("status"))[0];
    expect(detalhe.textContent).toMatch(/^Outubro de 2026: recebido R\$\s*10\.000,01$/);
    fireEvent.click(screen.getByRole("button", { name: /^agosto de 2026: recebido/ }));
    expect(detalhe.textContent).toMatch(/^Agosto de 2026: recebido R\$\s*12\.500,00$/);
    // os tres meses futuros nao tem barra nem botao
    expect(screen.getAllByRole("button", { name: /de 202\d: recebido/ })).toHaveLength(6);
    expect(screen.queryByRole("button", { name: /^dezembro de 2026/ })).toBeNull();
  });

  it("cada mes tem um rotulo so', centrado na propria barra (sem sobreposicao com o vizinho)", async () => {
    api.mockResolvedValue(RESPOSTA);
    render(<AReceberPagina />);
    await screen.findAllByRole("status");
    const grupos = [...document.querySelectorAll<SVGGElement>(".ar-grafico .g-grupo")];
    expect(grupos).toHaveLength(6);
    const centros = grupos.map(g => {
      const valores = g.querySelectorAll("text.g-valor");
      expect(valores).toHaveLength(1);
      return Number(valores[0].getAttribute("x"));
    });
    // o passo entre rotulos vizinhos e' a largura do mes: 9 caracteres de 11px (~60px) cabem com folga
    const passos = centros.slice(1).map((x, i) => x - centros[i]);
    passos.forEach(d => expect(d).toBeGreaterThan(90));
  });

  it("as setas percorrem os meses do grafico, levando o foco junto", async () => {
    api.mockResolvedValue(RESPOSTA);
    render(<AReceberPagina />);
    const detalhe = (await screen.findAllByRole("status"))[0];
    const set = screen.getByRole("button", { name: /^setembro de 2026: recebido/ });
    fireEvent.keyDown(screen.getByRole("button", { name: /^outubro de 2026: recebido/ }), { key: "ArrowLeft" });
    expect(document.activeElement).toBe(set);
    fireEvent.keyDown(set, { key: "ArrowLeft" });
    expect(detalhe.textContent).toMatch(/^Agosto de 2026/);
  });

  it("o a receber abre por contratante; clicar num contratante filtra a tabela e o total", async () => {
    api.mockResolvedValue(RESPOSTA);
    render(<AReceberPagina />);
    const tabela = await screen.findByRole("table", { name: /Cobranças esperando pagamento, na cota/ });
    expect(screen.getByRole("button", { name: "Contratante" }).getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: /Prefeitura/ }));
    expect(within(tabela).getAllByRole("row")).toHaveLength(1 + 2 + 1);
    expect(within(tabela).getByText("Total de Prefeitura")).toBeTruthy();
    // trocar o corte para obra limpa o filtro
    fireEvent.click(screen.getByRole("button", { name: "Obra" }));
    expect(within(tabela).getAllByRole("row")).toHaveLength(1 + 4 + 1);
    expect(screen.getByRole("button", { name: /Avenida das Palmeiras/ })).toBeTruthy();
  });

  it("a lista vem da maior cobranca para a menor", async () => {
    api.mockResolvedValue(RESPOSTA);
    render(<AReceberPagina />);
    const tabela = await screen.findByRole("table", { name: /Cobranças esperando pagamento, na cota/ });
    const valores = within(tabela).getAllByRole("row").slice(1, 5).map(l => within(l).getAllByRole("cell")[3].textContent ?? "");
    expect(valores.map(v => v.replace(/\s/g, " "))).toEqual(["R$ 6.000,01", "R$ 5.000,01", "R$ 4.000,01", "R$ 0,00"]);
  });

  it("clicar numa obra filtra a tabela e o total; clicar de novo ou em Mostrar todas volta", async () => {
    api.mockResolvedValue(RESPOSTA);
    render(<AReceberPagina />);
    const tabela = await screen.findByRole("table", { name: /Cobranças esperando pagamento, na cota/ });
    expect(within(tabela).getAllByRole("row")).toHaveLength(1 + 4 + 1);                    // cabeca, 4 cobrancas, rodape
    fireEvent.click(screen.getByRole("button", { name: "Obra" }));
    fireEvent.click(screen.getByRole("button", { name: /Terminal Norte/ }));
    expect(within(tabela).getAllByRole("row")).toHaveLength(1 + 2 + 1);
    expect(within(tabela).getByText("Total de Terminal Norte")).toBeTruthy();
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

  it("antes da conciliacao o valor e' tracinho, sem frase de conciliacao", async () => {
    api.mockResolvedValue({
      ...RESPOSTA, total_a_receber_liberado: false, total: { quantidade: 4, obras: 2, valor_centavos: null },
      mes: { ...MESES[5], previsto_centavos: null }, meses: MESES.map(m => ({ ...m, previsto_centavos: null })),
      por_obra: RESPOSTA.por_obra.map(o => ({ ...o, valor_centavos: null })), itens: RESPOSTA.itens.map(i => ({ ...i, valor_centavos: null })),
      por_orgao: RESPOSTA.por_orgao.map(o => ({ ...o, valor_centavos: null })),
    });
    render(<AReceberPagina />);
    const caminho = await screen.findByRole("region", { name: "Onde está o dinheiro, na cota" });
    expect(within(caminho).getByText("Protocolado, a receber").nextSibling?.textContent).toBe("—");
    expect(screen.queryByText(/a conciliar com a controladoria/)).toBeNull();
    expect(within(caminho).getByText("Recebido em outubro").nextSibling?.textContent).toMatch(/R\$\s*10\.000,01/);
  });

  it("erro da API vira mensagem em portugues", async () => {
    api.mockRejectedValue(new Error("falhou"));
    render(<AReceberPagina />);
    expect((await screen.findByRole("alert")).textContent).toMatch(/Recarregue a página/);
  });
});
