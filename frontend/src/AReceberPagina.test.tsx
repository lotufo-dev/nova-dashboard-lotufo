import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import AReceberPagina from "./AReceberPagina";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

const mes = (competencia: string, previsto: number | null, recebido: number | null, atual = false, futuro = false) =>
  ({ competencia, atual, futuro, previsto_centavos: previsto, recebido_centavos: futuro ? null : recebido,
     // o recebido de verdade (baixas do RM): de proposito diferente do das medicoes, para provar qual a tela mostra
     recebido_real_centavos: futuro || recebido === null ? null : recebido + 7 });
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
  recebido_ano_centavos: 8_800_008,
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
  it("mostra tres numeros (a receber, recebido no mes, recebido no ano) e o recebido e' o real do RM", async () => {
    api.mockResolvedValue(RESPOSTA);
    render(<AReceberPagina />);
    const resumo = await screen.findByRole("region", { name: "Resumo" });
    expect(api).toHaveBeenCalledWith("/api/a-receber");
    expect(within(resumo).getAllByRole("listitem").map(li => li.firstChild?.textContent)).toEqual(
      ["A receber, na cota", "Recebido em outubro", "Recebido em 2026"]);
    expect(within(resumo).getByText("A receber, na cota").nextSibling?.textContent).toMatch(/R\$\s*15\.000,03/);
    // 10.000,01 das medicoes + 0,07: a tela mostra o recebido real
    expect(within(resumo).getByText("Recebido em outubro").nextSibling?.textContent).toMatch(/R\$\s*10\.000,08/);
    expect(within(resumo).getByText("Recebido em 2026").nextSibling?.textContent).toMatch(/R\$\s*88\.000,08/);
    // 06/11/2026: sairam o previsto, o medido sem nota, a nota sem protocolo e a lista de cobrancas
    expect(document.body.textContent).not.toMatch(/[Pp]revisto|[Pp]revisão|sem nota|sem protocolo|Cobranças esperando pagamento/);
    expect(screen.queryByRole("table", { name: /Cobranças/ })).toBeNull();
    expect(screen.queryByRole("link", { name: /^Abrir/ })).toBeNull();
  });

  it("issue #583: o baixado no RM sem caixa no ano ganha numero proprio, so' quando existe", async () => {
    api.mockResolvedValue({ ...RESPOSTA, baixado_sem_caixa_ano_centavos: 12_345_679 });
    render(<AReceberPagina />);
    const resumo = await screen.findByRole("region", { name: "Resumo" });
    expect(within(resumo).getAllByRole("listitem").map(li => li.firstChild?.textContent)).toEqual(
      ["A receber, na cota", "Recebido em outubro", "Recebido em 2026", "Baixado sem caixa em 2026"]);
    expect(within(resumo).getByText("Baixado sem caixa em 2026").nextSibling?.textContent).toMatch(/R\$\s*123\.456,79/);
    cleanup();
    api.mockResolvedValue({ ...RESPOSTA, baixado_sem_caixa_ano_centavos: 0 });
    render(<AReceberPagina />);
    const vazio = await screen.findByRole("region", { name: "Resumo" });
    expect(within(vazio).queryByText(/Baixado sem caixa/)).toBeNull();
  });

  it("o grafico e' so' o recebido real dos meses ate' o atual; clicar num mes troca o detalhe", async () => {
    api.mockResolvedValue(RESPOSTA);
    render(<AReceberPagina />);
    const detalhe = (await screen.findAllByRole("status"))[0];
    expect(detalhe.textContent).toMatch(/^Outubro de 2026: recebido R\$\s*10\.000,08$/);
    fireEvent.click(screen.getByRole("button", { name: /^agosto de 2026: recebido/ }));
    expect(detalhe.textContent).toMatch(/^Agosto de 2026: recebido R\$\s*12\.500,07$/);
    // os tres meses futuros nao tem barra nem botao
    expect(screen.getAllByRole("button", { name: /de 202\d: recebido/ })).toHaveLength(6);
    expect(screen.queryByRole("button", { name: /^dezembro de 2026/ })).toBeNull();
  });

  it("#699: a tabela equivalente do grafico fica dentro de um div sr-only (a classe na table alargava a pagina no celular)", async () => {
    api.mockResolvedValue(RESPOSTA);
    const { container } = render(<AReceberPagina />);
    const tabela = await screen.findByRole("table", { name: "Recebido por mês, na cota" });
    expect(tabela.className).toBe("");
    expect(tabela.parentElement?.tagName).toBe("DIV");
    expect(tabela.parentElement?.className).toBe("sr-only");
    expect(container.querySelector("table.sr-only")).toBeNull();
  });

  it("servidor antigo (sem o recebido real) cai no recebido das medicoes e nao mostra o do ano", async () => {
    const { recebido_ano_centavos: _ano, ...sem } = RESPOSTA;
    api.mockResolvedValue({ ...sem, mes: { ...MESES[5], recebido_real_centavos: undefined },
      meses: MESES.map(m => ({ ...m, recebido_real_centavos: undefined })) });
    render(<AReceberPagina />);
    const resumo = await screen.findByRole("region", { name: "Resumo" });
    expect(within(resumo).getByText("Recebido em outubro").nextSibling?.textContent).toMatch(/R\$\s*10\.000,01/);
    expect(within(resumo).queryByText("Recebido em 2026")).toBeNull();
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

  it("o a receber abre por contratante, da maior para a menor, e troca para por obra", async () => {
    api.mockResolvedValue(RESPOSTA);
    render(<AReceberPagina />);
    await screen.findByRole("region", { name: "Resumo" });
    expect(screen.getByRole("button", { name: "Contratante" }).getAttribute("aria-pressed")).toBe("true");
    const nomes = () => [...document.querySelectorAll(".ar-obra__nome")].map(e => e.textContent);
    expect(nomes()).toEqual(["SINFRA", "Prefeitura"]);
    fireEvent.click(screen.getByRole("button", { name: "Obra" }));
    expect(nomes()).toEqual(["Avenida das Palmeiras", "Terminal Norte"]);
    // as linhas so' mostram: sem a tabela de cobrancas nao ha' o que filtrar
    expect(document.querySelector("button.ar-obra")).toBeNull();
  });

  it("antes da conciliacao o valor e' tracinho, sem frase de conciliacao", async () => {
    api.mockResolvedValue({
      ...RESPOSTA, total_a_receber_liberado: false, total: { quantidade: 4, obras: 2, valor_centavos: null },
      mes: { ...MESES[5], previsto_centavos: null }, meses: MESES.map(m => ({ ...m, previsto_centavos: null })),
      por_obra: RESPOSTA.por_obra.map(o => ({ ...o, valor_centavos: null })), itens: RESPOSTA.itens.map(i => ({ ...i, valor_centavos: null })),
      por_orgao: RESPOSTA.por_orgao.map(o => ({ ...o, valor_centavos: null })),
    });
    render(<AReceberPagina />);
    const resumo = await screen.findByRole("region", { name: "Resumo" });
    expect(within(resumo).getByText("A receber, na cota").nextSibling?.textContent).toBe("—");
    expect(screen.queryByText(/a conciliar com a controladoria/)).toBeNull();
    expect(within(resumo).getByText("Recebido em outubro").nextSibling?.textContent).toMatch(/R\$\s*10\.000,08/);
  });

  it("erro da API vira mensagem em portugues", async () => {
    api.mockRejectedValue(new Error("falhou"));
    render(<AReceberPagina />);
    expect((await screen.findByRole("alert")).textContent).toMatch(/Recarregue a página/);
  });
});
