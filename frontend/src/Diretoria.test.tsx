import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Diretoria from "./Diretoria";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

const g = (quantidade: number, valor_centavos: number | null) => ({ quantidade, valor_centavos });
const PAINEL = {
  hoje: "2026-09-24", total_a_receber_liberado: false,
  dinheiro: {
    medido_esperando_nota: g(2, 150_000), nota_esperando_protocolo: g(0, 0), recebido_mes: g(0, 0),
    protocolado: { ...g(2, null), faixas: { ate_30: g(1, null), de_31_a_60: g(0, null), mais_60: g(1, null) },
                   por_orgao: [{ orgao: "SINFRA", ...g(2, null), maior_dias: 85 }] },
    reajustes_apostilamento: { quantidade: 1, maior_dias: 92 } },
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
            pi_va: 1_000_000, faturados: 400_000, saldo: 600_000, pct_recebido: 0.4, status: "EM ANDAMENTO",
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

  it("Resumo: três números, curva S e um cartão por contratante, sem o que foi para as outras abas", async () => {
    api.mockImplementation((url: string) => Promise.resolve(RESPOSTAS[url]));
    render(<Diretoria ir={() => {}} />);
    const numeros = await screen.findByRole("list", { name: "Os números da carteira" });
    expect(within(numeros).getAllByRole("listitem")).toHaveLength(3);
    expect(within(numeros).getByText("Saldo a executar")).toBeTruthy();
    expect(within(numeros).getByText("Medido no ano")).toBeTruthy();
    expect(within(numeros).getByText("Faturado no mês")).toBeTruthy();
    // o faturado do mês vem do servidor, em milhões, com o valor exato no title e sem linha de apoio
    expect(within(numeros).getByText("R$ 1,2 mi")).toBeTruthy();
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

  it("QDOP: a coluna Desvio (p.p.) mostra o número com sinal e a linha de base, e — sem cronograma (#296)", async () => {
    const semCronograma = { ...PAINEL.obras[0], contrato_id: 8, seq: 2, obra: "Sem cronograma", desvio_pp: null, desvio_base: null };
    const adiantada = { ...PAINEL.obras[0], contrato_id: 9, seq: 3, obra: "Adiantada", desvio_pp: 2.9, desvio_base: "vigente" };
    const respostas: Record<string, unknown> = { ...RESPOSTAS, "/api/diretoria": { ...PAINEL, obras: [PAINEL.obras[0], semCronograma, adiantada] } };
    api.mockImplementation((url: string) => Promise.resolve(respostas[url]));
    render(<Diretoria ir={() => {}} aba="qdop" />);
    const tabela = await screen.findByRole("table", { name: /QDOP, na cota da Lotufo/ });
    const cabecalho = within(tabela).getAllByRole("columnheader").map(h => h.textContent);
    expect(cabecalho).toContain("Desvio (p.p.)");
    const coluna = cabecalho.indexOf("Desvio (p.p.)");
    const celula = (obra: string) => {
      const linha = within(tabela).getByText(obra).closest("tr") as HTMLElement;
      return within(linha).getAllByRole("cell")[coluna];
    };
    expect(celula("Cavalaria").textContent).toBe("−16,7anterior");
    expect(celula("Cavalaria").className).toContain("negativo");
    // só a palavra da base, sem frase de apoio no ponteiro (texto-na-tela)
    expect(celula("Cavalaria").querySelector("[title]")).toBeNull();
    expect(celula("Adiantada").textContent).toBe("+2,9vigente");
    expect(celula("Sem cronograma").textContent).toBe("—");
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
    const outra = { ...PAINEL.obras[0], contrato_id: 8, seq: 2, obra: "Outra", farol: "atencao", pi_va: 500_000, faturados: 100_000, saldo: 400_000 };
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
    // total do recorte: só a "Outra" (contratual 5.000,00; faturado 1.000,00; saldo 4.000,00)
    const total = within(tabela).getByText("Total").closest("tr") as HTMLElement;
    const txt = (total.textContent ?? "").replace(/\s/g, " ");
    expect(txt).toContain("R$ 5.000,00");
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

  it("Produção: o mês, quantas obras protocolaram, onde está o dinheiro (a conciliar) e o saldo por órgão", async () => {
    api.mockImplementation((url: string) => Promise.resolve(RESPOSTAS[url]));
    render(<Diretoria ir={() => {}} aba="producao" />);
    expect(await screen.findByText("Onde está o dinheiro (cota)")).toBeTruthy();
    // protocolado sem conciliar: "—", sem frase
    expect(screen.getByText("protocolado esperando pagamento").previousElementSibling?.textContent).toBe("—");
    expect(screen.queryByText("a conciliar")).toBeNull();
    expect(screen.queryByText(/a conciliar com a controladoria/)).toBeNull();
    expect(await screen.findByText("1 de 3")).toBeTruthy();
    expect(screen.getByText("obras ativas protocolaram")).toBeTruthy();
    expect(screen.queryByText(/mesmo mês do ano anterior/)).toBeNull();
    expect(screen.getByText("medido esperando nota")).toBeTruthy();
    expect(screen.getByText("Próximos meses")).toBeTruthy();
    // #255: os próximos meses só trazem o faturamento previsto; o recebimento previsto saiu
    expect(screen.getByText("Faturamento previsto")).toBeTruthy();
    expect(screen.queryByText("Recebimento previsto")).toBeNull();
    const saldo = screen.getByRole("table", { name: /Saldo a executar por órgão/ });
    expect(within(saldo).getByText("SINFRA")).toBeTruthy();
    expect(within(saldo).getByText("Total")).toBeTruthy();
    ["Onde está o dinheiro", "O mês"].forEach(n => expect(screen.getByRole("list", { name: n }).tagName).toBe("UL"));
    const kpis = screen.getAllByRole("listitem").filter(i => i.classList.contains("kpi"));
    expect(kpis.length).toBe(10);
    kpis.forEach(i => { expect(i.parentElement?.tagName).toBe("UL"); expect(i.hasAttribute("role")).toBe(false); });
  });

  it("QDOP: exporta a planilha e mostra os motivos da obra", async () => {
    api.mockImplementation((url: string) => Promise.resolve(RESPOSTAS[url]));
    render(<Diretoria ir={() => {}} aba="qdop" />);
    expect((await screen.findByRole("link", { name: /Exportar QDOP/ })).getAttribute("href")).toBe("/api/diretoria/qdop.xlsx");
    expect(screen.getByText("execução vencida")).toBeTruthy();
  });

  it("Produção: o gráfico de 12 meses tem a tabela com mês, previsto e medido, e o gráfico aponta para ela", async () => {
    const serie = Array.from({ length: 12 }, (_, i) => ({
      competencia: `2025-${String(i + 1).padStart(2, "0")}`, previsto_centavos: (i + 1) * 100_000, medido_centavos: (i + 1) * 50_000,
    }));
    const painel = { ...PAINEL, mes_ano: { ...PAINEL.mes_ano, serie } };
    api.mockImplementation((url: string) => Promise.resolve(url === "/api/diretoria" ? painel : RESPOSTAS[url]));
    render(<Diretoria ir={() => {}} aba="producao" />);
    const tabela = (await screen.findByRole("table", { name: /Previsto e medido nos últimos 12 meses/, hidden: true }));
    const linhas = within(tabela).getAllByRole("row", { hidden: true }).slice(1, -1);          // sem o cabeçalho e sem a linha de total
    expect(linhas).toHaveLength(12);
    const texto = (l: HTMLElement) => within(l).getAllByRole("cell", { hidden: true }).map(c => (c.textContent ?? "").replace(/\s/g, " "));
    linhas.forEach((l, i) => {
      const reais = (c: number) => `R$ ${(c / 100).toLocaleString("pt-BR", { minimumFractionDigits: 2 })}`;
      expect(texto(l)).toEqual([`${String(i + 1).padStart(2, "0")}/2025`, reais((i + 1) * 100_000), reais((i + 1) * 50_000)]);
    });
    // a tabela mora no "Tabela por competência", recolhido, que o aviso do gráfico cita
    expect(tabela.closest("details")?.querySelector("summary")?.textContent).toBe("Tabela por competência");
    // o gráfico (role="img") manda o leitor de tela para a tabela, que fica logo abaixo
    const grafico = screen.getByRole("img", { name: /Tabela por competência/ });
    expect(grafico.getAttribute("aria-label")).toContain("nos últimos 12 meses");
    expect(screen.getByText("Tabela por competência").tagName).toBe("SUMMARY");
  });
});
