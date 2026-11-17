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
const medicao = (id: number, numero: number, comp: string, x: ReturnType<typeof n>,
    notas: { id: number; numero: string; v: number; ok: boolean; parte?: boolean }[]) => ({
  ...x, medicao_id: id, contrato_id: 7, obra: "Obra Alfa", numero, tipo: "execucao", estado: "protocolada", competencia: comp,
  protocolo_em: `${comp}-28`,
  notas: notas.map(t => ({ nota_id: t.id, numero: t.numero, valor_centavos: t.v, recebida: t.ok, paga_em_parte: !!t.parte })),
});
// o total do ano, com as tres partes do em aberto: (a) notas, (a') repasse sem baixa e (b) medicoes sem nota ligada
const ano = (x: ReturnType<typeof n>, meses: number, semNota = 0, repasse = 0) => ({
  ...x, em_aberto_centavos: x.em_aberto_centavos + semNota, em_aberto_notas_centavos: x.em_aberto_centavos - repasse,
  em_aberto_repasse_centavos: repasse, sem_nota_centavos: semNota, meses,
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
  por_ano: { "2025": ano(n(900_000, 900_000, 900_000, 900_000), 1), "2026": ano(n(1_700_001, 1_400_001, 1_400_001, 1_000_000), 2) },
  acumulado: { ate_mes: "05", "2025": n(900_000, 900_000, 900_000, 900_000), "2026": n(1_700_001, 1_400_001, 1_400_001, 1_000_000) },
  em_aberto: [{ tipo_aberto: "nota", nota_id: 22, numero: "602", contrato_id: 7, obra: "Obra Alfa", medicao_id: 2, medicao_numero: 15,
    tipo: "execucao", competencia: "2026-03", protocolo_em: "2026-03-28", valor_centavos: 400_001, paga_em_parte: false }],
  em_aberto_anteriores: { quantidade: 0, valor_centavos: 0 },
  notas_sem_medicao: { em_aberto: [], em_aberto_centavos: 0, pagas: { quantidade: 2, valor_centavos: 700_002 } },
  cobertura: {
    "2025": { aprovado_centavos: 900_000, com_nota_centavos: 900_000, sem_nota_centavos: 0, medicoes_sem_nota: 0, percentual: 100 },
    "2026": { aprovado_centavos: 1_400_001, com_nota_centavos: 1_400_001, sem_nota_centavos: 0, medicoes_sem_nota: 0, percentual: 100 },
  },
  notas_diferem: [],
  total_a_receber_liberado: true,
};
// as tres partes do em aberto: (a) nota nao paga, (b) medicao protocolada sem nota ligada e (c) nota solta, a' parte
const TRES_PARTES: RespostaFechamento = {
  ...FECHAMENTO,
  em_aberto: [...FECHAMENTO.em_aberto, { tipo_aberto: "sem_nota", nota_id: null, numero: null, contrato_id: 7, obra: "Obra Alfa",
    medicao_id: 4, medicao_numero: 17, tipo: "execucao", competencia: "2026-05", protocolo_em: "2026-06-02", valor_centavos: 200_000,
    paga_em_parte: false }],
  por_ano: { ...FECHAMENTO.por_ano, "2026": ano(n(1_700_001, 1_400_001, 1_400_001, 1_000_000), 2, 200_000) },
  notas_sem_medicao: { em_aberto: [{ nota_id: 31, numero: "777", contrato_id: 7, obra: "Obra Alfa", emissao: "2026-06-01", valor_centavos: 200_000,
    paga_em_parte: false }],
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
    const tabela = await screen.findByRole("table", { name: /notas protocoladas não pagas, notas da empresa de medições que o órgão já pagou ao consórcio .* e medições protocoladas sem nota ligada/ });
    const [, grupo, linha, total] = within(tabela).getAllByRole("row");
    expect(texto(grupo)).toBe("Nota protocolada não pagaR$ 4.000,01");
    expect(texto(linha)).toBe("28/03/2026Obra Alfa15ª Medição03/2026602R$ 4.000,01");
    expect(texto(total)).toBe("Total em aberto de 2026R$ 4.000,01");
    expect(valorDe("Em aberto")).toBe("R$ 4.000,01");                 // o total do painel é o número do alto
    expect(texto(screen.getByText("Notas pagas sem medição ligada (2025 e 2026)").nextElementSibling)).toBe("2 notas · R$ 7.000,02");
    expect(screen.queryByText(/anteriores a 2025/)).toBeNull();
    expect(screen.queryByText(/não dependem do ano escolhido/)).toBeNull();
    expect(screen.queryByText("Nota sem medição ligada")).toBeNull();
    expect(screen.queryByText(/podem ser a mesma cobrança/)).toBeNull();
  });

  it("as três partes do em aberto: nota não paga e medição sem nota somam o total; a nota sem medição é subtotal à parte", async () => {
    api.mockResolvedValue(TRES_PARTES);
    render(<Fechamento ir={() => {}} />);
    const tabela = await screen.findByRole("table", { name: /notas protocoladas não pagas, notas da empresa de medições que o órgão já pagou ao consórcio .* e medições protocoladas sem nota ligada/ });
    const linhas = within(tabela).getAllByRole("row").map(l => texto(l));
    expect(linhas).toEqual(["ProtocoloObraMediçãoNotaValor", "Nota protocolada não pagaR$ 4.000,01",
      "28/03/2026Obra Alfa15ª Medição03/2026602R$ 4.000,01", "Medição protocolada sem nota ligadaR$ 2.000,00",
      "02/06/2026Obra Alfa17ª Medição05/2026sem nota ligadaR$ 2.000,00", "Total em aberto de 2026R$ 6.000,01"]);
    const soltas = screen.getByRole("table", { name: "Nota sem medição ligada" });
    expect(within(soltas).getAllByRole("row").map(l => texto(l))).toEqual(
      ["EmissãoObraNotaValor", "01/06/2026Obra Alfa777R$ 2.000,00", "Subtotal à parteR$ 2.000,00"]);
    // a mesma cobrança pode estar nas duas listas: uma frase diz, e o total não soma a nota solta
    expect(screen.getByText(/Medição sem nota ligada e nota sem medição ligada podem ser a mesma cobrança/)).toBeTruthy();
    // um total só de em aberto na tela: o do painel é o do alto e o da linha "Total de 2026" da tabela do mês
    expect(valorDe("Em aberto")).toBe("R$ 6.000,01");
    const meses = screen.getByRole("table", { name: /por mês de competência de 2026/ });
    expect(texto(meses.querySelector("tfoot"))).toBe("Total de 2026R$ 17.000,01R$ 14.000,01R$ 14.000,01R$ 10.000,00R$ 6.000,01");
  });

  it("o painel Em aberto segue o ano escolhido; nota sem medição e em aberto anterior a 2025 não, e a tela diz", async () => {
    const dois: RespostaFechamento = {
      ...TRES_PARTES,
      em_aberto: [...TRES_PARTES.em_aberto, { tipo_aberto: "nota", nota_id: 12, numero: "502", contrato_id: 7, obra: "Obra Alfa",
        medicao_id: 5, medicao_numero: 9, tipo: "execucao", competencia: "2025-11", protocolo_em: "2025-12-15", valor_centavos: 30_003,
        paga_em_parte: false }],
      por_ano: { ...TRES_PARTES.por_ano, "2025": ano(n(930_003, 930_003, 930_003, 900_000), 2) },
      em_aberto_anteriores: { quantidade: 1, valor_centavos: 50_000 },
    };
    api.mockResolvedValue(dois);
    render(<Fechamento ir={() => {}} />);
    const linhasDe = (t: HTMLElement) => within(t).getAllByRole("row").map(l => texto(l));
    const de2026 = await screen.findByRole("table", { name: /Em aberto de 2026/ });
    expect(screen.getByRole("heading", { name: "Em aberto de 2026" })).toBeTruthy();
    expect(linhasDe(de2026).at(-1)).toBe("Total em aberto de 2026R$ 6.000,01");
    expect(linhasDe(de2026).join(" ")).not.toContain("502");
    const soltas = linhasDe(screen.getByRole("table", { name: "Nota sem medição ligada" }));
    fireEvent.click(screen.getByRole("button", { name: "2025" }));
    const de2025 = screen.getByRole("table", { name: /Em aberto de 2025/ });
    expect(linhasDe(de2025)).toEqual(["ProtocoloObraMediçãoNotaValor", "Nota protocolada não pagaR$ 300,03",
      "15/12/2025Obra Alfa9ª Medição11/2025502R$ 300,03", "Total em aberto de 2025R$ 300,03"]);
    expect(valorDe("Em aberto")).toBe("R$ 300,03");
    expect(screen.getByText("1 linha", { selector: ".contador .sr-only" })).toBeTruthy();     // o contador é do ano
    // as duas listas à parte são as mesmas nos dois anos
    expect(linhasDe(screen.getByRole("table", { name: "Nota sem medição ligada" }))).toEqual(soltas);
    expect(texto(screen.getByText("Em aberto de competências anteriores a 2025").nextElementSibling)).toBe("1 linha · R$ 500,00");
    expect(screen.getByText("Nota sem medição ligada e em aberto de competência anterior a 2025 não dependem do ano escolhido.")).toBeTruthy();
  });

  it("nota paga em parte: selo na medição, na linha do em aberto e na nota sem medição, com o que falta", async () => {
    const emParte: RespostaFechamento = {
      ...FECHAMENTO,
      meses: FECHAMENTO.meses.map(m => m.competencia !== "2026-03" ? m : { ...m, obras: [{ ...m.obras[0],
        medicoes: [medicao(2, 15, "2026-03", MAR26, [{ id: 21, numero: "601", v: 1_000_000, ok: true },
          { id: 22, numero: "602", v: 800_002, ok: false, parte: true }])] }] }),
      em_aberto: FECHAMENTO.em_aberto.map(e => ({ ...e, paga_em_parte: true })),
      notas_sem_medicao: { em_aberto: [{ nota_id: 31, numero: "777", contrato_id: 7, obra: "Obra Alfa", emissao: "2024-08-20",
        valor_centavos: 5_001, paga_em_parte: true }], em_aberto_centavos: 5_001, pagas: { quantidade: 0, valor_centavos: 0 } },
    };
    api.mockResolvedValue(emParte);
    render(<Fechamento ir={() => {}} />);
    const aberto = await screen.findByRole("table", { name: /Em aberto de 2026/ });
    expect(within(aberto).getAllByRole("row").map(l => texto(l))[2]).toBe("28/03/2026Obra Alfa15ª Medição03/2026602paga em parteR$ 4.000,01");
    const soltas = screen.getByRole("table", { name: "Nota sem medição ligada" });
    expect(within(soltas).getAllByRole("row").map(l => texto(l))[1]).toBe("20/08/2024Obra Alfa777paga em parteR$ 50,01");
    const meses = screen.getByRole("table", { name: /por mês de competência de 2026/ });
    fireEvent.click(within(meses).getByRole("button", { name: /Março de 2026, por obra/ }));
    fireEvent.click(within(meses).getByRole("button", { name: /Obra Alfa, medições de 03\/2026/ }));
    const linha = within(meses).getByRole("link", { name: "15ª Medição" }).closest("tr") as HTMLElement;
    expect(texto(linha)).toContain("Nota 602paga em parte");
    expect(within(linha).queryByText("em aberto")).toBeNull();
  });

  it("consórcio com a nota da empresa ligada: a fatura do consórcio aparece na medição, sem selo de situação e sem valor (#756)", async () => {
    const consorcio: RespostaFechamento = {
      ...FECHAMENTO,
      meses: FECHAMENTO.meses.map(m => m.competencia !== "2026-03" ? m : { ...m, obras: [{ ...m.obras[0],
        medicoes: [{ ...medicao(2, 15, "2026-03", MAR26, [{ id: 21, numero: "601", v: 1_400_001, ok: false }]),
          notas_fora_da_conta: [{ nota_id: 23, numero: "88" }] }] }] }),
    };
    api.mockResolvedValue(consorcio);
    render(<Fechamento ir={() => {}} />);
    const meses = await screen.findByRole("table", { name: /por mês de competência de 2026/ });
    fireEvent.click(within(meses).getByRole("button", { name: /Março de 2026, por obra/ }));
    fireEvent.click(within(meses).getByRole("button", { name: /Obra Alfa, medições de 03\/2026/ }));
    const linha = within(meses).getByRole("link", { name: "15ª Medição" }).closest("tr") as HTMLElement;
    const itens = [...linha.querySelectorAll(".fch-notas li")].map(li => texto(li));
    expect(itens).toEqual(["Nota 601em aberto", "Nota 88fatura do consórcio, não entra na conta"]);
    expect(texto(linha)).not.toContain("88R$");                 // a fatura fora da conta não leva valor
  });

  it("linha sem nota ligada e sem data de protocolo: diz que não há data, em vez de traço", async () => {
    api.mockResolvedValue({ ...TRES_PARTES, em_aberto: TRES_PARTES.em_aberto.map(e => e.tipo_aberto === "sem_nota" ? { ...e, protocolo_em: null } : e) });
    render(<Fechamento ir={() => {}} />);
    const tabela = await screen.findByRole("table", { name: /Em aberto de 2026/ });
    expect(within(tabela).getAllByRole("row").map(l => texto(l))[4]).toBe("sem data de protocoloObra Alfa17ª Medição05/2026sem nota ligadaR$ 2.000,00");
  });

  it("aviso de cobertura do vínculo: só quando falta nota ligada, com valor e percentual", async () => {
    api.mockResolvedValue(TRES_PARTES);
    render(<Fechamento ir={() => {}} />);
    const aviso = await screen.findByRole("status");
    expect(texto(aviso)).toContain("Em 2026, só R$ 14.000,01 (87,5%) dos R$ 16.000,01 aprovados com nota emitida têm nota ligada; 1 medição aparece sem protocolado nem recebido.");
    fireEvent.click(screen.getByRole("button", { name: "2025" }));
    expect(screen.queryByRole("status")).toBeNull();                    // 2025 com cobertura total: some
  });

  it("aviso da nota da empresa ao consórcio diferente da cota: só no ano em que existe, com o link e a diferença (#756)", async () => {
    const difere = (id: number, numero: number, tipo: string, comp: string, notas: number, cota: number) => ({
      contrato_id: 9, obra: "Obra Consórcio", medicao_id: id, medicao_numero: numero, tipo, competencia: comp,
      notas_centavos: notas, cota_centavos: cota, diferenca_centavos: notas - cota });
    api.mockResolvedValue({ ...FECHAMENTO, notas_diferem: [
      difere(41, 5, "execucao", "2026-03", 700_001, 1_000_001), difere(42, 5, "reajuste", "2026-04", 300_102, 300_001)] });
    const ir = vi.fn();
    render(<Fechamento ir={ir} />);
    const aviso = await screen.findByRole("status");
    expect(texto(aviso)).toContain("Em 2026, a nota da empresa ao consórcio difere da cota da medição: "
      + "Obra Consórcio, 5ª Medição (R$ 3.000,00 a menos); Obra Consórcio, Reajuste da 5ª Medição (R$ 1,01 a mais).");
    fireEvent.click(within(aviso).getByRole("link", { name: "Obra Consórcio, Reajuste da 5ª Medição" }));
    expect(ir.mock.calls[0][0]).toEqual({ tela: "medicao", obra: 9, id: 42 });
    fireEvent.click(screen.getByRole("button", { name: "2025" }));
    expect(screen.queryByRole("status")).toBeNull();                    // 2025 sem divergência: some
  });

  it("aviso do par misto: a medição que ainda conta pela fatura do consórcio, com o link, só no ano em que existe (#756)", async () => {
    api.mockResolvedValue({ ...FECHAMENTO, pares_mistos: [
      { contrato_id: 9, obra: "Obra Consórcio", medicao_id: 51, medicao_numero: 5, tipo: "execucao", competencia: "2026-03",
        par_medicao_id: 52, par_tipo: "reajuste" },
      { contrato_id: 9, obra: "Obra Consórcio", medicao_id: 54, medicao_numero: 6, tipo: "reajuste", competencia: "2026-04",
        par_medicao_id: 53, par_tipo: "execucao" }] });
    const ir = vi.fn();
    render(<Fechamento ir={ir} />);
    const aviso = await screen.findByRole("status");
    expect(texto(aviso)).toContain("Em 2026, falta ligar a nota da empresa ao consórcio, e a cobrança pode estar somada duas vezes: "
      + "Obra Consórcio, 5ª Medição; Obra Consórcio, Reajuste da 6ª Medição.");
    fireEvent.click(within(aviso).getByRole("link", { name: "Obra Consórcio, 5ª Medição" }));
    expect(ir.mock.calls[0][0]).toEqual({ tela: "medicao", obra: 9, id: 51 });
    fireEvent.click(screen.getByRole("button", { name: "2025" }));
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("repasse sem baixa: grupo próprio no em aberto, com subtotal, fora de nota protocolada não paga, e os grupos somam o total", async () => {
    // 2026-03: a nota 602 (R$ 4.000,01) passa a ser de medição que o órgão já pagou ao consórcio; entra a 603, que o órgão não pagou
    const linha = (tipo: "nota" | "repasse", nota: number, numero: string, medicao: number, num: number, v: number, parte = false) => ({
      tipo_aberto: tipo, nota_id: nota, numero, contrato_id: 7, obra: "Obra Alfa", medicao_id: medicao, medicao_numero: num,
      tipo: "execucao", competencia: "2026-03", protocolo_em: "2026-03-28", valor_centavos: v, paga_em_parte: parte });
    const total = n(1_700_001, 1_400_001, 1_400_001, 700_000);          // em aberto das notas: 7.000,01
    api.mockResolvedValue({ ...FECHAMENTO,
      meses: FECHAMENTO.meses.map(m => m.competencia !== "2026-03" ? m : { ...m, obras: [{ ...m.obras[0], medicoes: [
        { ...medicao(2, 15, "2026-03", MAR26, [{ id: 22, numero: "602", v: 400_001, ok: false }]), estado: "recebida",
          notas: [{ nota_id: 22, numero: "602", valor_centavos: 400_001, recebida: false, paga_em_parte: false, aguarda_repasse: true }] }] }] }),
      em_aberto: [linha("nota", 23, "603", 5, 18, 300_000), linha("repasse", 22, "602", 2, 15, 400_001)],
      por_ano: { ...FECHAMENTO.por_ano, "2026": ano(total, 2, 0, 400_001) } });
    render(<Fechamento ir={() => {}} />);
    const tabela = await screen.findByRole("table", { name: /Em aberto de 2026/ });
    expect(within(tabela).getAllByRole("row").map(l => texto(l))).toEqual([
      "ProtocoloObraMediçãoNotaValor",
      "Nota protocolada não pagaR$ 3.000,00",
      "28/03/2026Obra Alfa18ª Medição03/2026603R$ 3.000,00",
      "Órgão pagou o consórcio, repasse sem baixa no RMR$ 4.000,01",
      "28/03/2026Obra Alfa15ª Medição03/2026602R$ 4.000,01",
      "Total em aberto de 2026R$ 7.000,01",
    ]);
    expect(texto(tabela.querySelector("caption"))).toContain("que o órgão já pagou ao consórcio e seguem sem baixa do repasse no RM");
    expect(valorDe("Em aberto")).toBe("R$ 7.000,01");                   // o número do alto é a soma dos grupos
    // na linha da medição, a nota leva o mesmo nome do grupo, em vez de "em aberto"
    const meses = screen.getByRole("table", { name: /por mês de competência de 2026/ });
    fireEvent.click(within(meses).getByRole("button", { name: /Março de 2026, por obra/ }));
    fireEvent.click(within(meses).getByRole("button", { name: /Obra Alfa, medições de 03\/2026/ }));
    const med = within(meses).getByRole("link", { name: "15ª Medição" }).closest("tr") as HTMLElement;
    expect([...med.querySelectorAll(".fch-notas li")].map(li => texto(li))).toEqual(["Nota 602repasse sem baixa"]);
  });

  it("diz a base dos números: valor bruto da nota e mês de competência", async () => {
    api.mockResolvedValue(FECHAMENTO);
    render(<Fechamento ir={() => {}} />);
    expect(await screen.findByText(/Protocolado e recebido pelo valor bruto da nota; cada número no mês de competência da medição/)).toBeTruthy();
  });

  it("sem o total a receber liberado: a tela diz, e não mostra o em aberto nem o recebido que deixaria deduzi-lo", async () => {
    // o que o servidor manda com a trava: recebido e em aberto nulos em todo nível, notas sem marca e listas vazias
    const semValor = <T extends object>(x: T) => ({ ...x, recebido_centavos: null, em_aberto_centavos: null });
    const travado: RespostaFechamento = {
      ...TRES_PARTES, total_a_receber_liberado: false,
      meses: TRES_PARTES.meses.map(m => ({ ...semValor(m), obras: m.obras.map(o => ({ ...semValor(o),
        medicoes: o.medicoes.map(md => ({ ...semValor(md), notas: md.notas.map(t => ({ ...t, recebida: null, paga_em_parte: null })) })) })) })),
      por_ano: Object.fromEntries(Object.entries(TRES_PARTES.por_ano).map(([a, t]) =>
        [a, { ...semValor(t), em_aberto_notas_centavos: null, sem_nota_centavos: null }])),
      acumulado: { ate_mes: "05", "2025": semValor(n(900_000, 900_000, 900_000, 0)), "2026": semValor(n(1_700_001, 1_400_001, 1_400_001, 0)) },
      em_aberto: [], em_aberto_anteriores: { quantidade: 0, valor_centavos: null },
      notas_sem_medicao: { em_aberto: [], em_aberto_centavos: null, pagas: { quantidade: 0, valor_centavos: null } },
    };
    api.mockResolvedValue(travado);
    render(<Fechamento ir={() => {}} />);
    expect(await screen.findByText("O total a receber ainda não está liberado: recebido e em aberto ficam sem valor.")).toBeTruthy();
    expect(valorDe("Protocolado")).toBe("R$ 14.000,01");
    expect(valorDe("Recebido")).toBe("—");
    expect(valorDe("Em aberto")).toBe("—");
    expect(screen.queryByRole("heading", { name: /Em aberto de/ })).toBeNull();
    expect(screen.queryByRole("table", { name: /Em aberto de/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Recebido" })).toBeNull();     // a comparação não oferece o recebido
    const meses = screen.getByRole("table", { name: /por mês de competência de 2026/ });
    expect(texto(meses.querySelector("tfoot"))).toBe("Total de 2026R$ 17.000,01R$ 14.000,01R$ 14.000,01——");
    fireEvent.click(within(meses).getByRole("button", { name: /Março de 2026, por obra/ }));
    fireEvent.click(within(meses).getByRole("button", { name: /Obra Alfa, medições de 03\/2026/ }));
    const linha = within(meses).getByRole("link", { name: "15ª Medição" }).closest("tr") as HTMLElement;
    expect(texto(linha)).toContain("Nota 601");
    expect(within(linha).queryByText("recebida")).toBeNull();                   // nem o selo da nota
    expect(within(linha).queryByText("em aberto")).toBeNull();
    expect(document.body.textContent).not.toMatch(/R\$ 10\.000,00|R\$ 4\.000,01|R\$ 6\.000,01/);
  });

  it("com o total liberado a frase da trava não aparece", async () => {
    api.mockResolvedValue(FECHAMENTO);
    render(<Fechamento ir={() => {}} />);
    await screen.findByText("Cota da Lotufo");
    expect(screen.queryByText(/não está liberado/)).toBeNull();
  });

  it("no celular a tabela do mês fica com medido e recebido (as outras colunas são opcionais)", async () => {
    api.mockResolvedValue(FECHAMENTO);
    render(<Fechamento ir={() => {}} />);
    const tabela = await screen.findByRole("table", { name: /por mês de competência de 2026/ });
    const cab = within(tabela).getAllByRole("columnheader");
    expect(cab.filter(h => !h.classList.contains("fch-col-opcional")).map(h => h.textContent)).toEqual(["Mês", "Medido", "Recebido"]);
  });

  it("comparação em painel próprio: 2026 × 2025 mês a mês, com o acumulado até o último mês e o ano", async () => {
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

  it("sem lançamento: uma linha curta no lugar de cada tabela, sem zero disfarçado", async () => {
    api.mockResolvedValue({ ...FECHAMENTO, meses: [], em_aberto: [],
      por_ano: { "2025": ano(n(0, 0, 0, 0), 0), "2026": ano(n(0, 0, 0, 0), 0) },
      acumulado: { ate_mes: null, "2025": n(0, 0, 0, 0), "2026": n(0, 0, 0, 0) },
      notas_sem_medicao: { em_aberto: [], em_aberto_centavos: 0, pagas: { quantidade: 0, valor_centavos: 0 } } });
    render(<Fechamento ir={() => {}} />);
    expect(await screen.findByText("Nenhum lançamento em 2026.")).toBeTruthy();
    expect(screen.getByText("Nada em aberto em 2026.")).toBeTruthy();
    expect(valorDe("Medido")).toBe("—");
  });

  it("a falha da leitura vira uma frase, com o que fazer", async () => {
    api.mockRejectedValue(new Error("Servidor fora do ar"));
    render(<Fechamento ir={() => {}} />);
    expect((await screen.findByRole("alert")).textContent).toContain("Não foi possível carregar o fechamento");
  });
});
