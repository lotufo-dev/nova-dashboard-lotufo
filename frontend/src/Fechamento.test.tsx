import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Fechamento, { type RespostaFechamento } from "./Fechamento";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

// Dados sinteticos. Os numeros ja' vem somados do servidor; a tela so' mostra.
const n = (medido: number, aprovado: number, protocolado: number, recebido: number) => ({
  medido_centavos: medido, aprovado_centavos: aprovado, protocolado_centavos: protocolado, recebido_centavos: recebido,
  em_aberto_centavos: protocolado - recebido,
});
const medicao = (id: number, numero: number, comp: string, x: ReturnType<typeof n>, notas: { id: number; numero: string; v: number; ok: boolean }[]) => ({
  ...x, medicao_id: id, contrato_id: 7, obra: "Obra Alfa", numero, tipo: "execucao", estado: "protocolada", competencia: comp,
  protocolo_em: `${comp}-28`, notas: notas.map(t => ({ nota_id: t.id, numero: t.numero, valor_centavos: t.v, recebida: t.ok })),
});
const MAR26 = n(1_500_001, 1_400_001, 1_400_001, 1_000_000);
const FECHAMENTO: RespostaFechamento = {
  anos: ["2025", "2026"],
  meses: [
    { competencia: "2025-03", ...n(900_000, 900_000, 900_000, 900_000),
      obras: [{ contrato_id: 7, obra: "Obra Alfa", ...n(900_000, 900_000, 900_000, 900_000),
        medicoes: [medicao(1, 3, "2025-03", n(900_000, 900_000, 900_000, 900_000), [{ id: 11, numero: "501", v: 900_000, ok: true }])] }] },
    { competencia: "2026-03", ...MAR26,
      obras: [{ contrato_id: 7, obra: "Obra Alfa", ...MAR26,
        medicoes: [medicao(2, 15, "2026-03", MAR26, [{ id: 21, numero: "601", v: 1_000_000, ok: true }, { id: 22, numero: "602", v: 400_001, ok: false }])] }] },
    { competencia: "2026-05", ...n(200_000, 0, 0, 0),
      obras: [{ contrato_id: 7, obra: "Obra Alfa", ...n(200_000, 0, 0, 0), medicoes: [medicao(3, 16, "2026-05", n(200_000, 0, 0, 0), [])] }] },
  ],
  por_ano: { "2025": { ...n(900_000, 900_000, 900_000, 900_000), meses: 1 }, "2026": { ...n(1_700_001, 1_400_001, 1_400_001, 1_000_000), meses: 2 } },
  acumulado: { ate_mes: "05", "2025": n(900_000, 900_000, 900_000, 900_000), "2026": n(1_700_001, 1_400_001, 1_400_001, 1_000_000) },
  em_aberto: [{ tipo_aberto: "nota", nota_id: 22, numero: "602", contrato_id: 7, obra: "Obra Alfa", medicao_id: 2, medicao_numero: 15,
    tipo: "execucao", competencia: "2026-03", protocolo_em: "2026-03-28", valor_centavos: 400_001 }],
  em_aberto_centavos: 400_001, em_aberto_notas_centavos: 400_001, em_aberto_sem_nota_centavos: 0,
  em_aberto_anteriores: { quantidade: 0, valor_centavos: 0 },
  notas_sem_medicao: { em_aberto: [], em_aberto_centavos: 0, pagas: { quantidade: 2, valor_centavos: 700_002 } },
  cobertura: {
    "2025": { aprovado_centavos: 900_000, com_nota_centavos: 900_000, sem_nota_centavos: 0, medicoes_sem_nota: 0, percentual: 100 },
    "2026": { aprovado_centavos: 1_400_001, com_nota_centavos: 1_400_001, sem_nota_centavos: 0, medicoes_sem_nota: 0, percentual: 100 },
  },
  total_a_receber_liberado: true,
};
// as tres partes do em aberto: (a) nota nao paga, (b) medicao protocolada sem nota ligada e (c) nota solta, a' parte
const TRES_PARTES: RespostaFechamento = {
  ...FECHAMENTO,
  em_aberto: [...FECHAMENTO.em_aberto, { tipo_aberto: "sem_nota", nota_id: null, numero: null, contrato_id: 7, obra: "Obra Alfa",
    medicao_id: 4, medicao_numero: 17, tipo: "execucao", competencia: "2026-05", protocolo_em: "2026-06-02", valor_centavos: 200_000 }],
  em_aberto_centavos: 600_001, em_aberto_sem_nota_centavos: 200_000,
  notas_sem_medicao: { em_aberto: [{ nota_id: 31, numero: "777", contrato_id: 7, obra: "Obra Alfa", emissao: "2026-06-01", valor_centavos: 200_000 }],
    em_aberto_centavos: 200_000, pagas: { quantidade: 2, valor_centavos: 700_002 } },
  cobertura: { ...FECHAMENTO.cobertura,
    "2026": { aprovado_centavos: 1_600_001, com_nota_centavos: 1_400_001, sem_nota_centavos: 200_000, medicoes_sem_nota: 1, percentual: 87.5 } },
};

const texto = (el: Element | null) => (el?.textContent ?? "").replace(/\s/g, " ");
const valorDe = (rotulo: string) => texto(screen.getByText(rotulo, { selector: "dt" }).nextElementSibling);

describe("Fechamento (#748)", () => {
  afterEach(() => { cleanup(); api.mockReset(); });

  it("os cinco números do ano mais novo, na cota, e o ano anterior pelo botão", async () => {
    api.mockResolvedValue(FECHAMENTO);
    render(<Fechamento ir={() => {}} />);
    expect(await screen.findByText("Cota da Lotufo")).toBeTruthy();
    expect(api).toHaveBeenCalledWith("/api/fechamento");
    expect(screen.getByRole("button", { name: "2026" }).getAttribute("aria-pressed")).toBe("true");
    expect(valorDe("Medido")).toBe("R$ 17.000,01");
    expect(valorDe("Aprovado")).toBe("R$ 14.000,01");
    expect(valorDe("Protocolado")).toBe("R$ 14.000,01");
    expect(valorDe("Recebido")).toBe("R$ 10.000,00");
    expect(valorDe("Em aberto")).toBe("R$ 4.000,01");
    fireEvent.click(screen.getByRole("button", { name: "2025" }));
    expect(valorDe("Medido")).toBe("R$ 9.000,00");
    expect(valorDe("Em aberto")).toBe("—");                     // zero em ano com lançamento não vira número
    // sem faixa de dias em lugar nenhum
    expect(document.body.textContent).not.toMatch(/dias|até 30|mais de 60/);
  });

  it("a tabela do mês só tem os meses com lançamento, fecha com o total do ano e abre por obra e por medição", async () => {
    api.mockResolvedValue(FECHAMENTO);
    render(<Fechamento ir={() => {}} />);
    const tabela = await screen.findByRole("table", { name: /por mês de competência de 2026/ });
    const linhas = within(tabela).getAllByRole("row");
    expect(linhas.map(l => texto(l.querySelector(".fch-mes-longo") ?? l.querySelector("th")))).toEqual(["Mês", "Março", "Maio", "Total de 2026"]);
    expect(linhas.slice(1, 3).map(l => texto(l.querySelector(".fch-mes-curto")))).toEqual(["Mar", "Mai"]);   // a 390 px
    expect(texto(linhas[3])).toContain("R$ 17.000,01");
    // maio: medido sem aprovado nem nota; o zero vira "—"
    expect(within(linhas[2]).getAllByRole("cell").map(c => texto(c))).toEqual(["R$ 2.000,00", "—", "—", "—", "—"]);
    const mes = within(tabela).getByRole("button", { name: /Março de 2026, por obra/ });
    expect(mes.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(mes);
    expect(mes.getAttribute("aria-expanded")).toBe("true");
    const obra = within(tabela).getByRole("button", { name: /Obra Alfa, medições de 03\/2026/ });
    fireEvent.click(obra);
    const link = within(tabela).getByRole("link", { name: "15ª Medição" });
    expect(link.getAttribute("href")).toBe("/obras/7/medicoes/2");
    const linhaMedicao = link.closest("tr") as HTMLElement;
    expect(texto(linhaMedicao)).toContain("Nota 601");
    expect(within(linhaMedicao).getByText("recebida")).toBeTruthy();
    expect(within(linhaMedicao).getByText("em aberto")).toBeTruthy();
    expect(texto(linhaMedicao)).toContain("R$ 4.000,01");
  });

  it("em aberto nota a nota, com a data do protocolo e o total; as notas pagas sem medição só contadas à parte", async () => {
    api.mockResolvedValue(FECHAMENTO);
    render(<Fechamento ir={() => {}} />);
    const tabela = await screen.findByRole("table", { name: /notas protocoladas não pagas e medições protocoladas sem nota ligada/ });
    const [, grupo, linha, total] = within(tabela).getAllByRole("row");
    expect(texto(grupo)).toBe("Nota protocolada não pagaR$ 4.000,01");
    expect(texto(linha)).toBe("28/03/2026Obra Alfa15ª Medição03/2026602R$ 4.000,01");
    expect(texto(total)).toBe("Total em abertoR$ 4.000,01");
    expect(texto(screen.getByText("Notas pagas sem medição ligada (2025 e 2026)").nextElementSibling)).toBe("2 notas · R$ 7.000,02");
    expect(screen.queryByText(/anteriores a 2025/)).toBeNull();
    expect(screen.queryByText("Nota sem medição ligada")).toBeNull();
    expect(screen.queryByText(/podem ser a mesma cobrança/)).toBeNull();
  });

  it("as três partes do em aberto: nota não paga e medição sem nota somam o total; a nota sem medição é subtotal à parte", async () => {
    api.mockResolvedValue(TRES_PARTES);
    render(<Fechamento ir={() => {}} />);
    const tabela = await screen.findByRole("table", { name: /notas protocoladas não pagas e medições protocoladas sem nota ligada/ });
    const linhas = within(tabela).getAllByRole("row").map(l => texto(l));
    expect(linhas).toEqual(["ProtocoloObraMediçãoNotaValor", "Nota protocolada não pagaR$ 4.000,01",
      "28/03/2026Obra Alfa15ª Medição03/2026602R$ 4.000,01", "Medição protocolada sem nota ligadaR$ 2.000,00",
      "02/06/2026Obra Alfa17ª Medição05/2026sem nota ligadaR$ 2.000,00", "Total em abertoR$ 6.000,01"]);
    const soltas = screen.getByRole("table", { name: "Nota sem medição ligada" });
    expect(within(soltas).getAllByRole("row").map(l => texto(l))).toEqual(
      ["EmissãoObraNotaValor", "01/06/2026Obra Alfa777R$ 2.000,00", "Subtotal à parteR$ 2.000,00"]);
    // a mesma cobrança pode estar nas duas listas: uma frase diz, e o total não soma a nota solta
    expect(screen.getByText(/Medição sem nota ligada e nota sem medição ligada podem ser a mesma cobrança/)).toBeTruthy();
    expect(valorDe("Em aberto")).toBe("R$ 4.000,01");                 // o do ano vem do servidor, não da tela
  });

  it("aviso de cobertura do vínculo: só quando falta nota ligada, com valor e percentual", async () => {
    api.mockResolvedValue(TRES_PARTES);
    render(<Fechamento ir={() => {}} />);
    const aviso = await screen.findByRole("status");
    expect(texto(aviso)).toContain("Em 2026, só R$ 14.000,01 (87,5%) dos R$ 16.000,01 aprovados com nota emitida têm nota ligada; 1 medição aparece sem protocolado nem recebido.");
    fireEvent.click(screen.getByRole("button", { name: "2025" }));
    expect(screen.queryByRole("status")).toBeNull();                    // 2025 com cobertura total: some
  });

  it("diz a base dos números: valor bruto da nota e mês de competência", async () => {
    api.mockResolvedValue(FECHAMENTO);
    render(<Fechamento ir={() => {}} />);
    expect(await screen.findByText(/Protocolado e recebido pelo valor bruto da nota; cada número no mês de competência da medição/)).toBeTruthy();
  });

  it("sem o total a receber liberado, o em aberto mostra as linhas sem valor", async () => {
    const nulos = { ...TRES_PARTES, total_a_receber_liberado: false, em_aberto_centavos: null, em_aberto_notas_centavos: null,
      em_aberto_sem_nota_centavos: null, em_aberto: TRES_PARTES.em_aberto.map(e => ({ ...e, valor_centavos: null })),
      por_ano: { ...TRES_PARTES.por_ano, "2026": { ...TRES_PARTES.por_ano["2026"], em_aberto_centavos: null } },
      notas_sem_medicao: { ...TRES_PARTES.notas_sem_medicao, em_aberto_centavos: null,
        em_aberto: TRES_PARTES.notas_sem_medicao.em_aberto.map(e => ({ ...e, valor_centavos: null })) } };
    api.mockResolvedValue(nulos);
    render(<Fechamento ir={() => {}} />);
    const tabela = await screen.findByRole("table", { name: /notas protocoladas não pagas/ });
    expect(texto(tabela.querySelector("tfoot"))).toBe("Total em aberto—");
    expect(valorDe("Em aberto")).toBe("—");
    expect(document.body.textContent).not.toContain("R$ 4.000,01");
  });

  it("no celular a tabela do mês fica com medido e recebido (as outras colunas são opcionais)", async () => {
    api.mockResolvedValue(FECHAMENTO);
    render(<Fechamento ir={() => {}} />);
    const tabela = await screen.findByRole("table", { name: /por mês de competência de 2026/ });
    const cab = within(tabela).getAllByRole("columnheader");
    expect(cab.filter(h => !h.classList.contains("fch-col-opcional")).map(h => h.textContent)).toEqual(["Mês", "Medido", "Recebido"]);
  });

  it("variante A da comparação: 2026 × 2025 mês a mês, com o acumulado até o último mês e o ano", async () => {
    api.mockResolvedValue(FECHAMENTO);
    render(<Fechamento ir={() => {}} />);
    const tabela = await screen.findByRole("table", { name: /Medido por mês de competência, 2025 e 2026/ });
    expect(within(tabela).getAllByRole("row").map(l => texto(l))).toEqual([
      "Mês20252026", "MarçoR$ 9.000,00R$ 15.000,01", "Maio—R$ 2.000,00", "Até maioR$ 9.000,00R$ 17.000,01",
      "AnoR$ 9.000,00R$ 17.000,01"]);
    fireEvent.click(screen.getByRole("button", { name: "Recebido" }));
    const recebido = screen.getByRole("table", { name: /Recebido por mês de competência/ });
    expect(texto(within(recebido).getAllByRole("row")[1])).toBe("MarçoR$ 9.000,00R$ 10.000,00");
  });

  it("variante B (?variante=b): o mesmo mês do outro ano embaixo do valor, o mês abre um quadro por obra, sem o painel da comparação", async () => {
    api.mockResolvedValue(FECHAMENTO);
    render(<Fechamento ir={() => {}} busca={{ variante: "b" }} />);
    const tabela = await screen.findByRole("table", { name: /por mês de competência de 2026/ });
    expect(screen.queryByRole("heading", { name: "2026 × 2025" })).toBeNull();
    const marco = within(tabela).getByRole("button", { name: /Março de 2026/ }).closest("tr") as HTMLElement;
    expect(texto(marco)).toContain("R$ 15.000,01mesmo mês de 2025: R$ 9.000,00");
    expect(texto(tabela.querySelector("tfoot"))).toContain("2025, até maio");
    fireEvent.click(within(tabela).getByRole("button", { name: /Março de 2026/ }));
    const quadro = screen.getByRole("table", { name: /Medições de Obra Alfa em 03\/2026/ });
    expect(within(quadro).getByRole("link", { name: "15ª Medição" })).toBeTruthy();
  });

  it("sem lançamento: uma linha curta no lugar de cada tabela, sem zero disfarçado", async () => {
    api.mockResolvedValue({ ...FECHAMENTO, meses: [], em_aberto: [], em_aberto_centavos: 0,
      por_ano: { "2025": { ...n(0, 0, 0, 0), meses: 0 }, "2026": { ...n(0, 0, 0, 0), meses: 0 } },
      acumulado: { ate_mes: null, "2025": n(0, 0, 0, 0), "2026": n(0, 0, 0, 0) },
      notas_sem_medicao: { em_aberto: [], em_aberto_centavos: 0, pagas: { quantidade: 0, valor_centavos: 0 } } });
    render(<Fechamento ir={() => {}} />);
    expect(await screen.findByText("Nenhum lançamento em 2026.")).toBeTruthy();
    expect(screen.getByText("Nada em aberto.")).toBeTruthy();
    expect(valorDe("Medido")).toBe("—");
  });

  it("a falha da leitura vira uma frase, com o que fazer", async () => {
    api.mockRejectedValue(new Error("Servidor fora do ar"));
    render(<Fechamento ir={() => {}} />);
    expect((await screen.findByRole("alert")).textContent).toContain("Não foi possível carregar o fechamento");
  });
});
