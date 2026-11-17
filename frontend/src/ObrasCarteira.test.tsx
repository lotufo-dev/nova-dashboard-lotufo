import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CurvaDaCarteira, Qdop, Reajustes, SeloFarol, type Painel } from "./ObrasCarteira";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

const PAINEL: Painel = {
  hoje: "2026-09-24", medido_ano: { ano: "2026", valor_centavos: 1_000_000 },
  curva_carteira: [{ competencia: "2026-08", previsto_centavos: 150_000, previsto_anterior_centavos: 300_000, medido_centavos: 100_000 },
                   { competencia: "2026-09", previsto_centavos: 200_000, previsto_anterior_centavos: 200_000, medido_centavos: 150_000 }],
  reajustes_apostilamento: { competencias: 0, valor_centavos: 0, obras: [] },
  obras: [{ contrato_id: 7, seq: 1, obra: "Obra Própria", contratante: "Secretaria de Exemplo", empreita: "PRÓPRIA", direito: 1,
            // #262: faturado (QDOP, com projeto) e saldo (execucao - medido de execucao) nao fecham entre si
            pi_va: 1_000_000, faturados: 450_000, saldo: 600_000, status: "EM ANDAMENTO",
            termino: "2026-12-20", vigencia: "2027-03-20", farol: "vermelho", motivo: "Obra Própria: execução vencida",
            motivos: [{ tipo: "instrumento_pendente", nivel: "critico", dias: -12, valor_centavos: null, texto: "execução vencida" }] }],
  avisos: [],
};

describe("As peças da lista de Obras que vieram da Carteira (#748, redesenho #774)", () => {
  afterEach(() => { cleanup(); api.mockReset(); });

  it("a curva da carteira tem o previsto vigente, o anterior à última repactuação e o medido (#296)", () => {
    render(<CurvaDaCarteira serie={PAINEL.curva_carteira} />);
    // curva acumulada: previsto 150.000 + 200.000 e medido 100.000 + 150.000 até 09/2026
    const curva = screen.getByRole("img", { name: /Previsto e medido de execução acumulados de 08\/2026 a 09\/2026/ });
    expect(curva.querySelector(".cart-c-prev")).toBeTruthy();
    expect(curva.querySelector(".cart-c-ant")).toBeTruthy();
    expect(curva.querySelector(".cart-c-med")).toBeTruthy();
    expect((curva.getAttribute("aria-label") ?? "").replace(/\s/g, " ")).toContain("previsto anterior à última repactuação R$ 5.000,00");
    const leitura = (screen.getByRole("status").textContent ?? "").replace(/\s/g, " ");
    expect(leitura).toContain("previsto R$ 3.500,00");
    expect(leitura).toContain("previsto anterior R$ 5.000,00");
    expect(leitura).toContain("medido de execução R$ 2.500,00");
    expect(leitura).not.toContain("do previsto");
    expect(screen.getByText("previsto anterior à última repactuação")).toBeTruthy();
    // a curva conta outra regra de medido que o "Medido em <ano>": o nome diz qual (revisão da PR #326)
    expect(screen.getByText("Previsto e medido de execução acumulados nos últimos 12 meses")).toBeTruthy();
    expect(screen.getByText("medido de execução")).toBeTruthy();
  });

  it("sem série, a curva não desenha painel vazio", () => {
    const { container } = render(<CurvaDaCarteira serie={[]} />);
    expect(container.textContent).toBe("");
  });

  it("o farol vira selo com glifo e palavra; Ação e Atenção se separam pela palavra (D10)", () => {
    const { container } = render(<><SeloFarol farol="vermelho" /><SeloFarol farol="acao" /><SeloFarol farol="atencao" /><SeloFarol farol="verde" /></>);
    const selos = [...container.querySelectorAll(".selo")];
    expect(selos.map(s => s.textContent)).toEqual(["Crítico", "Ação", "Atenção", "Em dia"]);
    expect(selos.map(s => s.className)).toEqual(["selo selo--critico", "selo selo--breve", "selo selo--breve", "selo selo--feito"]);
    // forma alem da cor: todo selo de farol leva o glifo da situacao
    expect(selos.every(s => s.querySelector(".glifo"))).toBe(true);
  });

  it("QDOP: seis colunas, sem o Desvio (p.p.); empreita e status sob o nome, a vigência sob o término, os motivos sob o farol", () => {
    api.mockResolvedValue([]);
    render(<Qdop p={PAINEL} ir={() => {}} />);
    const tabela = screen.getByRole("table", { name: /QDOP, na cota da Lotufo/ });
    const cabecas = within(tabela).getAllByRole("columnheader").map(h => h.textContent);
    // #262: a tabela soma o contratual sem o aditivo de reajuste (a base do saldo)
    expect(cabecas).toEqual(["Obra", "Contratual de execução (PI+VA)", "Faturado", "Saldo", "Término", "Farol"]);
    expect(tabela.textContent).not.toMatch(/−16,7|anterior/);
    const [, linha] = within(tabela).getAllByRole("row");
    expect(linha.children).toHaveLength(6);
    const celulas = within(linha).getAllByRole("cell").map(c => (c.textContent ?? "").replace(/\s/g, " "));
    expect(celulas[0]).toBe("Obra PrópriaPRÓPRIA · EM ANDAMENTO");
    expect(celulas[4]).toBe("20/12/2026vigência 20/03/2027");
    expect(celulas[5]).toBe("Críticoexecução vencida");
    expect(within(linha).getByRole("link", { name: "Obra Própria" }).getAttribute("href")).toBe("/obras/7/medicoes");
  });

  it("QDOP: o filtro do farol traz a contagem, recorta a tabela e o total acompanha", () => {
    api.mockResolvedValue([]);
    const outra = { ...PAINEL.obras[0], contrato_id: 8, seq: 2, obra: "Outra", farol: "atencao" as const, pi_va: 500_000, faturados: 150_000, saldo: 400_000 };
    const verde = { ...PAINEL.obras[0], contrato_id: 9, seq: 3, obra: "Tranquila", farol: "verde" as const, motivos: [] };
    render(<Qdop p={{ ...PAINEL, obras: [{ ...PAINEL.obras[0], farol: "acao" }, outra, verde] }} ir={() => {}} />);
    const tabela = screen.getByRole("table", { name: /QDOP, na cota da Lotufo/ });
    expect(within(tabela).getByText("Ação")).toBeTruthy();
    expect(within(tabela).getByText("Atenção")).toBeTruthy();
    const filtros = screen.getByRole("group", { name: "Filtrar o QDOP pelo farol" });
    expect(within(filtros).getAllByRole("button").map(b => (b.textContent ?? "").replace(/\s+/g, " ")))
      .toEqual(["Todas 3", "Com problema 2", "Crítico 0", "Ação 1", "Atenção 1", "Em dia 1"]);
    fireEvent.click(within(filtros).getByRole("button", { name: /^Atenção/ }));
    expect(within(filtros).getByRole("button", { name: /^Atenção/ }).getAttribute("aria-pressed")).toBe("true");
    expect(within(tabela).queryByText("Obra Própria")).toBeNull();
    // total do recorte: só a "Outra" (contratual 5.000,00; faturado 1.500,00; saldo do servidor 4.000,00)
    const total = within(tabela).getByText("Total").closest("tr") as HTMLElement;
    const txt = (total.textContent ?? "").replace(/\s/g, " ");
    expect(txt).toContain("R$ 5.000,00");
    expect(txt).toContain("R$ 1.500,00");
    expect(txt).toContain("R$ 4.000,00");
    fireEvent.click(within(filtros).getByRole("button", { name: /^Crítico/ }));
    expect(within(tabela).getByText("Nenhuma obra neste farol.")).toBeTruthy();
  });

  it("QDOP: exporta a planilha e, no rodapé, o que termina e os avisos da diretoria são links", async () => {
    api.mockResolvedValue([]);
    render(<Qdop p={PAINEL} ir={() => {}} />);
    expect(screen.getByRole("link", { name: /Exportar QDOP/ }).getAttribute("href")).toBe("/api/diretoria/qdop.xlsx");
    expect((await screen.findByRole("link", { name: /^0 obras terminam em 90.dias$/ })).getAttribute("href")).toBe("/obras?termina=90");
    expect(screen.getByRole("link", { name: "0 obras terminam em 6 meses" }).getAttribute("href")).toBe("/obras?termina=180");
    expect(screen.getByRole("link", { name: "0 avisos da diretoria" }).getAttribute("href")).toBe("/avisos");
    // o painel "Obras pelo farol" saiu: o filtro, a tabela e o rodape' moram num painel so'
    expect(screen.queryByText("Obras pelo farol")).toBeNull();
    expect(screen.queryByText("Terminam")).toBeNull();
    expect(screen.queryByText(/A execução ou a vigência/)).toBeNull();
    expect(api.mock.calls.every(c => c[0] !== "/api/diretoria/custo")).toBe(true);
  });

  it("os reajustes esperando apostilamento listam por obra as competências e o medido, com o total (#279)", () => {
    const reajustes = { competencias: 5, valor_centavos: 750_004,
      obras: [{ contrato_id: 7, obra: "Obra Própria", competencias: 3, valor_centavos: 650_003 },
              { contrato_id: 8, obra: "Obra Consórcio", competencias: 2, valor_centavos: 100_001 }] };
    render(<Reajustes r={reajustes} ir={() => {}} />);
    expect(screen.getByRole("heading", { name: "Reajustes esperando apostilamento" })).toBeTruthy();
    const tabela = screen.getByRole("table", { name: /Reajustes esperando apostilamento/ });
    expect(within(tabela).getAllByRole("columnheader").map(h => h.textContent)).toEqual(["Obra", "Competências", "Medido"]);
    const texto = (l: HTMLElement) => within(l).getAllByRole("cell").map(c => (c.textContent ?? "").replace(/\s/g, " "));
    const [, primeira, segunda, total] = within(tabela).getAllByRole("row");
    expect(texto(primeira)).toEqual(["Obra Própria", "3", "R$ 6.500,03"]);
    expect(texto(segunda)).toEqual(["Obra Consórcio", "2", "R$ 1.000,01"]);
    expect((total.textContent ?? "").replace(/\s/g, " ")).toBe("Total5R$ 7.500,04");
    expect(within(tabela).getByRole("link", { name: "Obra Própria" }).getAttribute("href")).toBe("/obras/7/reajuste");
  });
});
