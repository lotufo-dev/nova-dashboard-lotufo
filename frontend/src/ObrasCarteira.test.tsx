import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ObrasCarteira from "./ObrasCarteira";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

const PAINEL = {
  hoje: "2026-09-24", medido_ano: { ano: "2026", valor_centavos: 1_000_000 },
  curva_carteira: [{ competencia: "2026-08", previsto_centavos: 150_000, previsto_anterior_centavos: 300_000, medido_centavos: 100_000 },
                   { competencia: "2026-09", previsto_centavos: 200_000, previsto_anterior_centavos: 200_000, medido_centavos: 150_000 }],
  carteira: { saldo_centavos: 5_000_000,
              por_orgao: [{ orgao: "SINFRA", saldo_centavos: 5_000_000, vigente_centavos: 20_000_000, medido_centavos: 15_000_000 }] },
  obras: [{ contrato_id: 7, seq: 1, obra: "Cavalaria", contratante: "SINFRA", empreita: "PRÓPRIA", direito: 1,
            // #262: faturado (QDOP, com projeto) e saldo (execucao - medido de execucao) nao fecham entre si
            pi_va: 1_000_000, faturados: 450_000, saldo: 600_000, pct_recebido: 0.4, status: "EM ANDAMENTO",
            termino: "2026-12-20", vigencia: "2027-03-20", farol: "vermelho", motivo: "Cavalaria: execução vencida",
            motivos: [{ tipo: "instrumento_pendente", nivel: "critico", dias: -12, valor_centavos: null, texto: "execução vencida" }] }],
  avisos: [],
};
const RESPOSTAS: Record<string, unknown> = {
  "/api/diretoria": PAINEL,
  "/api/inicio": { avisos: [], resumo: { mes: "2026-09", obras_protocoladas: 1, obras_ativas: 3 } },
  "/api/contratos": [],
};

describe("Resumo e QDOP da lista de Obras (#748, vieram da Carteira)", () => {
  afterEach(() => { cleanup(); api.mockReset(); });

  it("Resumo: quatro números (contratado, executado, saldo, medido no ano), curva S e um cartão por contratante", async () => {
    api.mockImplementation((url: string) => Promise.resolve(RESPOSTAS[url]));
    render(<ObrasCarteira ir={() => {}} vista="resumo" />);
    const numeros = await screen.findByRole("list", { name: "Os números da carteira" });
    expect(within(numeros).getAllByRole("listitem")).toHaveLength(4);
    // contratado e executado são a soma dos cartões por contratante (20 e 15 milhões de centavos: 75% executado)
    expect(within(numeros).getByText("Contratado").nextSibling?.textContent).toBe("R$ 200,0 mil");
    expect(within(numeros).getByText("Executado (75%)").nextSibling?.textContent).toBe("R$ 150,0 mil");
    expect(within(numeros).getByText("Saldo a executar").nextSibling?.textContent).toBe("R$ 50,0 mil");
    expect(within(numeros).getByText("Medido em 2026").nextSibling?.textContent).toBe("R$ 10,0 mil");
    expect(within(numeros).queryByText(/Faturado/)).toBeNull();
    expect(within(numeros).queryByText(/medições faturadas/)).toBeNull();
    expect(numeros.querySelector(".cart-numero__apoio")).toBeNull();
    // curva S acumulada: previsto 150.000 + 200.000 e medido 100.000 + 150.000 até 09/2026
    expect(screen.getByRole("img", { name: /Previsto e medido de execução acumulados de 08\/2026 a 09\/2026/ })).toBeTruthy();
    const leitura = (screen.getByRole("status").textContent ?? "").replace(/\s/g, " ");
    expect(leitura).toContain("previsto R$ 3.500,00");
    expect(leitura).toContain("medido de execução R$ 2.500,00");
    expect(leitura).not.toContain("do previsto");
    expect(screen.queryByText("acumulado, na cota da Lotufo")).toBeNull();
    // cartão do contratante: saldo, obras, % executado (15 de 20 milhões) e link para as obras dele
    const cartao = screen.getByRole("link", { name: /SINFRA/ });
    expect(cartao.getAttribute("href")).toContain("orgao=SINFRA");
    expect(within(cartao).getByText("75%")).toBeTruthy();
    expect(within(cartao).queryByText(/obras em execução/)).toBeNull();
    // o que saiu do Resumo não está mais lá
    expect(screen.queryByText(/obras com farol em Ação, Atenção ou Crítico/)).toBeNull();
    expect(screen.queryByText("Onde está o dinheiro")).toBeNull();
    expect(screen.queryByText("Terminam")).toBeNull();
  });

  it("Resumo: a curva S da carteira tem o previsto vigente, o anterior à última repactuação e o medido (#296)", async () => {
    api.mockImplementation((url: string) => Promise.resolve(RESPOSTAS[url]));
    render(<ObrasCarteira ir={() => {}} vista="resumo" />);
    const curva = await screen.findByRole("img", { name: /Previsto e medido de execução acumulados de 08\/2026 a 09\/2026/ });
    // as três linhas: previsto vigente, previsto anterior e medido (vem de curva_carteira)
    expect(curva.querySelector(".cart-c-prev")).toBeTruthy();
    expect(curva.querySelector(".cart-c-ant")).toBeTruthy();
    expect(curva.querySelector(".cart-c-med")).toBeTruthy();
    expect((curva.getAttribute("aria-label") ?? "").replace(/\s/g, " ")).toContain("previsto anterior à última repactuação R$ 5.000,00");
    const leitura = (screen.getByRole("status").textContent ?? "").replace(/\s/g, " ");
    expect(leitura).toContain("previsto anterior R$ 5.000,00");
    expect(screen.getByText("previsto anterior à última repactuação")).toBeTruthy();
    // a curva conta outra regra de medido que o cartão "Medido no ano": o nome diz qual (revisão da PR #326)
    expect(screen.getByText("Previsto e medido de execução acumulados nos últimos 12 meses")).toBeTruthy();
    expect(screen.getByText("medido de execução")).toBeTruthy();
    expect(leitura).toContain("medido de execução R$ 2.500,00");
  });

  it("QDOP: nove colunas, sem o Desvio (p.p.) (06/11/2026; o servidor deixou de mandar na #748)", async () => {
    api.mockImplementation((url: string) => Promise.resolve(RESPOSTAS[url]));
    render(<ObrasCarteira ir={() => {}} vista="qdop" />);
    const tabela = await screen.findByRole("table", { name: /QDOP, na cota da Lotufo/ });
    const cabecas = within(tabela).getAllByRole("columnheader").map(h => h.textContent);
    expect(cabecas).not.toContain("Desvio (p.p.)");
    expect(cabecas).toHaveLength(9);
    // #262: a tabela soma o contratual sem o aditivo de reajuste (a base do saldo); o saldo e' o contratual de
    // execucao menos o medido de execucao, nao menos o faturado
    expect(cabecas).toContain("Contratual de execução (PI+VA)");
    expect(cabecas).toContain("Saldo (contratual de execução − medido)");
    expect(cabecas).not.toContain("Saldo (contratual − faturado)");
    expect(tabela.textContent).not.toMatch(/−16,7|anterior/);
    // cada linha tem uma célula por coluna
    within(tabela).getAllByRole("row").slice(1, -1).forEach(l => expect(l.children).toHaveLength(9));
  });

  it("QDOP: o farol de Ação e o de Atenção têm rótulos diferentes (D10), o filtro recorta e o total acompanha", async () => {
    const outra = { ...PAINEL.obras[0], contrato_id: 8, seq: 2, obra: "Outra", farol: "atencao", pi_va: 500_000, faturados: 150_000, saldo: 400_000 };
    const verde = { ...PAINEL.obras[0], contrato_id: 9, seq: 3, obra: "Tranquila", farol: "verde", motivos: [] };
    const respostas: Record<string, unknown> = { ...RESPOSTAS, "/api/diretoria": { ...PAINEL, obras: [{ ...PAINEL.obras[0], farol: "acao" }, outra, verde] } };
    api.mockImplementation((url: string) => Promise.resolve(respostas[url]));
    render(<ObrasCarteira ir={() => {}} vista="qdop" />);
    const tabela = await screen.findByRole("table", { name: /QDOP, na cota da Lotufo/ });
    expect(within(tabela).getByText("Ação")).toBeTruthy();
    expect(within(tabela).getByText("Atenção")).toBeTruthy();
    expect(within(tabela).getByText("Total")).toBeTruthy();
    expect(screen.queryByText(/com farol em Ação, Atenção ou Crítico/)).toBeNull();
    // os botoes do farol so' com o rotulo, sem contagem
    expect(screen.getByRole("button", { name: "Atenção" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /^Atenção/ }));
    expect(within(tabela).queryByText("Cavalaria")).toBeNull();
    // total do recorte: só a "Outra" (contratual 5.000,00; faturado 1.500,00; saldo do servidor 4.000,00)
    const total = within(tabela).getByText("Total").closest("tr") as HTMLElement;
    const txt = (total.textContent ?? "").replace(/\s/g, " ");
    expect(txt).toContain("R$ 5.000,00");
    expect(txt).toContain("R$ 1.500,00");
    expect(txt).toContain("R$ 4.000,00");
  });

  it("QDOP: a obra com problema e o painel do farol traz o que termina e os avisos", async () => {
    api.mockImplementation((url: string) => Promise.resolve(RESPOSTAS[url]));
    render(<ObrasCarteira ir={() => {}} vista="qdop" />);
    expect(await screen.findByText("Crítico", { selector: ".selo__texto, .selo" })).toBeTruthy();
    expect(screen.getByText("Obras pelo farol")).toBeTruthy();
    expect(screen.getByText("Terminam")).toBeTruthy();
    expect(await screen.findByText("0 obras terminam em 90 dias")).toBeTruthy();
    expect(screen.getByText("Avisos da diretoria")).toBeTruthy();
    expect(screen.getByText("Avisos da diretoria").nextElementSibling?.textContent).toBe("0 avisos");
    expect(screen.queryByText(/A execução ou a vigência/)).toBeNull();
  });

  it("QDOP: exporta a planilha (só no QDOP) e mostra os motivos da obra", async () => {
    api.mockImplementation((url: string) => Promise.resolve(RESPOSTAS[url]));
    render(<ObrasCarteira ir={() => {}} vista="qdop" />);
    expect((await screen.findByRole("link", { name: /Exportar QDOP/ })).getAttribute("href")).toBe("/api/diretoria/qdop.xlsx");
    expect(screen.getByText("execução vencida")).toBeTruthy();
    cleanup();
    render(<ObrasCarteira ir={() => {}} vista="resumo" />);
    await screen.findByRole("list", { name: "Os números da carteira" });
    expect(screen.queryByRole("link", { name: /Exportar QDOP/ })).toBeNull();
    expect(api.mock.calls.every(c => c[0] !== "/api/diretoria/custo")).toBe(true);
  });

});
