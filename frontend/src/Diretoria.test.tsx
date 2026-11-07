import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Diretoria from "./Diretoria";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

const g = (quantidade: number, valor_centavos: number | null) => ({ quantidade, valor_centavos });
type ReajusteObra = { contrato_id: number; obra: string; competencias: number; valor_centavos: number };
const PAINEL = {
  hoje: "2026-09-24", total_a_receber_liberado: false,
  dinheiro: {
    medido_esperando_nota: g(2, 150_000), nota_esperando_protocolo: g(0, 0), recebido_mes: g(0, 0),
    protocolado: { ...g(2, null), faixas: { ate_30: g(1, null), de_31_a_60: g(0, null), mais_60: g(1, null) },
                   por_orgao: [{ orgao: "SINFRA", ...g(2, null), maior_dias: 85 }] },
    reajustes_apostilamento: { quantidade: 1, maior_dias: 92, competencias: 0, valor_centavos: 0, obras: [] as ReajusteObra[] } },
  mes_ano: { mes: "2026-09", medido_mes_centavos: 150_000, previsto_mes_centavos: 200_000,
             mesmo_mes_ano_anterior_centavos: 80_000, acumulado_ano_centavos: 1_000_000, previsto_ano_centavos: 2_000_000,
             faturado_mes_centavos: 123_456_789, notas_faturadas_mes: 2,
             serie: [{ competencia: "2026-08", medido_centavos: 100_000, previsto_centavos: 150_000 },
                     { competencia: "2026-09", medido_centavos: 150_000, previsto_centavos: 200_000 }] },
  curva_carteira: [{ competencia: "2026-08", previsto_centavos: 150_000, previsto_anterior_centavos: 300_000, medido_centavos: 100_000 },
                   { competencia: "2026-09", previsto_centavos: 200_000, previsto_anterior_centavos: 200_000, medido_centavos: 150_000 }],
  proximos: [{ competencia: "2026-09", faturamento_previsto_centavos: 200_000 }],
  carteira: { saldo_centavos: 5_000_000, ritmo_mensal_centavos: 100_000, meses_de_producao: 50,
              por_orgao: [{ orgao: "SINFRA", saldo_centavos: 5_000_000, fracao: 1, vigente_centavos: 20_000_000, medido_centavos: 15_000_000, obras: 3 }] },
  obras: [{ contrato_id: 7, seq: 1, obra: "Cavalaria", contratante: "SINFRA", empreita: "PRÓPRIA", direito: 1,
            // #262: faturado (QDOP, com projeto) e saldo (execucao - medido de execucao) nao fecham entre si
            pi_va: 1_000_000, faturados: 450_000, saldo: 600_000, pct_recebido: 0.4, status: "EM ANDAMENTO",
            termino: "2026-12-20", vigencia: "2027-03-20", farol: "vermelho", motivo: "Cavalaria: execução vencida",
            motivos: [{ tipo: "instrumento_pendente", nivel: "critico", dias: -12, valor_centavos: null, texto: "execução vencida" }],
            desvio_pp: -16.7, desvio_base: "anterior" }],
  obras_base: { ativas: 19, encerramento: 2, suspensas: 1, encerradas: 0 },
  avisos: [],
};
const RESPOSTAS: Record<string, unknown> = {
  "/api/diretoria": PAINEL,
  "/api/inicio": { avisos: [], resumo: { mes: "2026-09", obras_protocoladas: 1, obras_ativas: 3 } },
  "/api/contratos": [],
};

describe("Carteira", () => {
  afterEach(() => { cleanup(); api.mockReset(); });

  it("Resumo: quatro números (contratado, executado, saldo, medido no ano), curva S e um cartão por contratante", async () => {
    api.mockImplementation((url: string) => Promise.resolve(RESPOSTAS[url]));
    render(<Diretoria ir={() => {}} />);
    const numeros = await screen.findByRole("list", { name: "Os números da carteira" });
    expect(within(numeros).getAllByRole("listitem")).toHaveLength(4);
    // contratado e executado são a soma dos cartões por contratante (20 e 15 milhões de centavos: 75% executado)
    expect(within(numeros).getByText("Contratado").nextSibling?.textContent).toBe("R$ 200,0 mil");
    expect(within(numeros).getByText("Executado (75%)").nextSibling?.textContent).toBe("R$ 150,0 mil");
    expect(within(numeros).getByText("Saldo a executar").nextSibling?.textContent).toBe("R$ 50,0 mil");
    expect(within(numeros).getByText("Medido em 2026").nextSibling?.textContent).toBe("R$ 10,0 mil");
    // o faturado do mês (zerado no começo de todo mês) saiu do Resumo: mora na Produção
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
    // sem a linha "N de M obras com farol…" (as abas já levam ao QDOP e à Produção); o que saiu do Resumo não está mais lá
    expect(screen.queryByText(/obras com farol em Ação, Atenção ou Crítico/)).toBeNull();
    expect(screen.queryByText("Onde está o dinheiro")).toBeNull();
    expect(screen.queryByText("Terminam")).toBeNull();
  });

  it("Resumo: a curva S da carteira tem o previsto vigente, o anterior à última repactuação e o medido (#296)", async () => {
    api.mockImplementation((url: string) => Promise.resolve(RESPOSTAS[url]));
    render(<Diretoria ir={() => {}} />);
    const curva = await screen.findByRole("img", { name: /Previsto e medido de execução acumulados de 08\/2026 a 09\/2026/ });
    // as três linhas: previsto vigente, previsto anterior e medido (vem de curva_carteira, não da série da Produção)
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

  it("QDOP: a coluna Desvio (p.p.) saiu da tela, mesmo com o servidor mandando o desvio (06/11/2026)", async () => {
    const obras = [{ ...PAINEL.obras[0], desvio_pp: -16.7, desvio_base: "anterior" as const }];
    api.mockImplementation((url: string) => Promise.resolve(url === "/api/diretoria" ? { ...PAINEL, obras } : RESPOSTAS[url]));
    render(<Diretoria ir={() => {}} aba="qdop" />);
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

  it("o Exportar QDOP aparece nas três abas", async () => {
    api.mockImplementation((url: string) => Promise.resolve(RESPOSTAS[url]));
    for (const aba of ["resumo", "qdop", "producao"] as const) {
      render(<Diretoria ir={() => {}} aba={aba} />);
      expect((await screen.findByRole("link", { name: /Exportar QDOP/ })).getAttribute("href")).toBe("/api/diretoria/qdop.xlsx");
      cleanup();
    }
  });

  it("QDOP: o farol de Ação e o de Atenção têm rótulos diferentes (D10), o filtro recorta e o total acompanha", async () => {
    const outra = { ...PAINEL.obras[0], contrato_id: 8, seq: 2, obra: "Outra", farol: "atencao", pi_va: 500_000, faturados: 150_000, saldo: 400_000 };
    const verde = { ...PAINEL.obras[0], contrato_id: 9, seq: 3, obra: "Tranquila", farol: "verde", motivos: [] };
    const respostas: Record<string, unknown> = { ...RESPOSTAS, "/api/diretoria": { ...PAINEL, obras: [{ ...PAINEL.obras[0], farol: "acao" }, outra, verde] } };
    api.mockImplementation((url: string) => Promise.resolve(respostas[url]));
    render(<Diretoria ir={() => {}} aba="qdop" />);
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

  it("QDOP: a obra com problema, o 'a conciliar' fica na Produção, e o painel do farol traz o que termina e os avisos", async () => {
    api.mockImplementation((url: string) => Promise.resolve(RESPOSTAS[url]));
    render(<Diretoria ir={() => {}} aba="qdop" />);
    expect(await screen.findByText("Crítico", { selector: ".selo__texto, .selo" })).toBeTruthy();
    expect(screen.getByText("Obras pelo farol")).toBeTruthy();
    expect(screen.getByText("Terminam")).toBeTruthy();
    expect(await screen.findByText("0 obras terminam em 90 dias")).toBeTruthy();
    expect(screen.getByText("Avisos da diretoria")).toBeTruthy();
    expect(screen.getByText("Avisos da diretoria").nextElementSibling?.textContent).toBe("0 avisos");
    expect(screen.queryByText(/A execução ou a vigência/)).toBeNull();
  });

  it("Produção: o faturado real (notas do RM) do último mês fechado e do ano, ao lado do ano anterior", async () => {
    const faturado_rm = {
      serie: [{ competencia: "2026-07", faturado_centavos: 300_000, ano_anterior_centavos: 250_000 },
              { competencia: "2026-08", faturado_centavos: 400_004, ano_anterior_centavos: 350_003 }],
      ate: "2026-08", ano_centavos: 2_000_002, ano_anterior_centavos: 1_500_001 };
    api.mockImplementation((url: string) => Promise.resolve(url === "/api/diretoria" ? { ...PAINEL, faturado_rm } : RESPOSTAS[url]));
    render(<Diretoria ir={() => {}} aba="producao" />);
    const kpis = await screen.findByRole("list", { name: "Faturado" });
    expect(kpis.tagName).toBe("UL");
    const numero = (rotulo: string) => (within(kpis).getByText(rotulo).previousElementSibling?.textContent ?? "").replace(/\s/g, " ");
    expect(numero("faturado em agosto de 2026")).toBe("R$ 4.000,04");
    expect(numero("agosto de 2025")).toBe("R$ 3.500,03");
    expect(numero("faturado em 2026, até agosto")).toBe("R$ 20.000,02");
    expect(numero("2025, até agosto")).toBe("R$ 15.000,01");
    // o mês a mês contra o mesmo mês do ano anterior, com a tabela para teclado e leitor de tela
    expect(screen.getByRole("img", { name: /Faturado nos últimos 12 meses fechados e no mesmo mês do ano anterior/ })).toBeTruthy();
    const tabela = screen.getByRole("table", { name: /Faturado por mês e no mesmo mês do ano anterior/, hidden: true });
    expect(within(tabela).getAllByRole("columnheader", { hidden: true }).map(h => h.textContent)).toEqual(
      ["Mês", "Faturado", "Mesmo mês do ano anterior"]);
    expect(screen.getByText("Reajustes esperando apostilamento (cota)")).toBeTruthy();
    // 06/11/2026: o medido por competência, o caminho do dinheiro, o saldo por órgão e as projeções saíram da Produção
    for (const fora of [/Onde está o dinheiro/, /Próximos meses/, /Faturamento previsto/, /obras ativas protocolaram/,
      /ritmo mensal/, /de produção/, /medido esperando nota/, /medido em/, /^previsto$/]) {
      expect(screen.queryByText(fora)).toBeNull();
    }
    expect(screen.queryByRole("table", { name: /Saldo a executar por órgão/ })).toBeNull();
    expect(api.mock.calls.map(c => c[0])).toEqual(["/api/diretoria"]);
  });

  it("Produção: servidor antigo, sem o faturado do RM, mostra só os reajustes", async () => {
    api.mockImplementation((url: string) => Promise.resolve(RESPOSTAS[url]));
    render(<Diretoria ir={() => {}} aba="producao" />);
    expect(await screen.findByText("Reajustes esperando apostilamento (cota)")).toBeTruthy();
    expect(screen.queryByRole("list", { name: "Faturado" })).toBeNull();
  });

  it("Produção: os reajustes esperando apostilamento listam por obra as competências e o medido, com o total (#279)", async () => {
    const reajustes = { quantidade: 2, maior_dias: 120, competencias: 5, valor_centavos: 750_004,
      obras: [{ contrato_id: 7, obra: "Cavalaria", competencias: 3, valor_centavos: 650_003 },
              { contrato_id: 8, obra: "Consórcio Sul", competencias: 2, valor_centavos: 100_001 }] };
    const painel = { ...PAINEL, dinheiro: { ...PAINEL.dinheiro, reajustes_apostilamento: reajustes } };
    api.mockImplementation((url: string) => Promise.resolve(url === "/api/diretoria" ? painel : RESPOSTAS[url]));
    render(<Diretoria ir={() => {}} aba="producao" />);
    const tabela = await screen.findByRole("table", { name: /Reajustes esperando apostilamento/ });
    expect(within(tabela).getAllByRole("columnheader").map(h => h.textContent)).toEqual(["Obra", "Competências", "Medido"]);
    const texto = (l: HTMLElement) => within(l).getAllByRole("cell").map(c => (c.textContent ?? "").replace(/\s/g, " "));
    const [, primeira, segunda, total] = within(tabela).getAllByRole("row");
    expect(texto(primeira)).toEqual(["Cavalaria", "3", "R$ 6.500,03"]);
    expect(texto(segunda)).toEqual(["Consórcio Sul", "2", "R$ 1.000,01"]);
    expect((total.textContent ?? "").replace(/\s/g, " ")).toBe("Total5R$ 7.500,04");
    // a obra leva ao reajuste dela
    expect(within(tabela).getByRole("link", { name: "Cavalaria" }).getAttribute("href")).toBe("/obras/7/reajuste");
    // so' o rotulo e o valor: sem os dias nem a contagem de ciclos
    expect(screen.queryByText(/120/)).toBeNull();
  });

  it("Produção: sem reajuste esperando apostilamento, uma linha no lugar da tabela", async () => {
    api.mockImplementation((url: string) => Promise.resolve(RESPOSTAS[url]));
    render(<Diretoria ir={() => {}} aba="producao" />);
    expect(await screen.findByText("Reajustes esperando apostilamento (cota)")).toBeTruthy();
    expect(screen.getByText("Nenhum reajuste esperando apostilamento.")).toBeTruthy();
    expect(screen.queryByRole("table", { name: /Reajustes esperando apostilamento/ })).toBeNull();
  });

  it("QDOP: exporta a planilha e mostra os motivos da obra", async () => {
    api.mockImplementation((url: string) => Promise.resolve(RESPOSTAS[url]));
    render(<Diretoria ir={() => {}} aba="qdop" />);
    expect((await screen.findByRole("link", { name: /Exportar QDOP/ })).getAttribute("href")).toBe("/api/diretoria/qdop.xlsx");
    expect(screen.getByText("execução vencida")).toBeTruthy();
  });

  it("Produção: o gráfico de 12 meses tem a tabela com mês, faturado e ano anterior, e o gráfico aponta para ela", async () => {
    const serie = Array.from({ length: 12 }, (_, i) => ({
      competencia: `2025-${String(i + 1).padStart(2, "0")}`, faturado_centavos: (i + 1) * 100_000, ano_anterior_centavos: (i + 1) * 50_000,
    }));
    const painel = { ...PAINEL, faturado_rm: { serie, ate: "2025-12", ano_centavos: 7_800_000, ano_anterior_centavos: 3_900_000 } };
    api.mockImplementation((url: string) => Promise.resolve(url === "/api/diretoria" ? painel : RESPOSTAS[url]));
    render(<Diretoria ir={() => {}} aba="producao" />);
    const tabela = (await screen.findByRole("table", { name: /Faturado por mês e no mesmo mês do ano anterior/, hidden: true }));
    const linhas = within(tabela).getAllByRole("row", { hidden: true }).slice(1, -1);          // sem o cabeçalho e sem a linha de total
    expect(linhas).toHaveLength(12);
    const texto = (l: HTMLElement) => within(l).getAllByRole("cell", { hidden: true }).map(c => (c.textContent ?? "").replace(/\s/g, " "));
    linhas.forEach((l, i) => {
      const reais = (c: number) => `R$ ${(c / 100).toLocaleString("pt-BR", { minimumFractionDigits: 2 })}`;
      expect(texto(l)).toEqual([`${String(i + 1).padStart(2, "0")}/2025`, reais((i + 1) * 100_000), reais((i + 1) * 50_000)]);
    });
    // a tabela mora no "Tabela por mês", recolhido, logo abaixo do gráfico, que manda o leitor de tela para ela
    expect(tabela.closest("details")?.querySelector("summary")?.textContent).toBe("Tabela por mês");
    const grafico = screen.getByRole("img", { name: /tabela recolhida logo abaixo/ });
    expect(grafico.getAttribute("aria-label")).toContain("12 meses");
  });

  it("#491: a aba Custo aparece entre as da Carteira e abre sem esperar o painel", async () => {
    api.mockImplementation((url: string) => url === "/api/diretoria/custo" ? Promise.resolve([]) : new Promise(() => {}));
    render(<Diretoria ir={() => {}} aba="custo" />);
    expect(screen.getByRole("link", { name: "Custo" }).getAttribute("href")).toBe("/carteira/custo");
    expect(await screen.findByText("Nenhuma obra com cadastro de custo.")).toBeTruthy();
    expect(api).not.toHaveBeenCalledWith("/api/diretoria");
  });
});
