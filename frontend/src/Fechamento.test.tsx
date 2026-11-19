import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Fechamento, { type RespostaFechamento } from "./Fechamento";
import { caminhoDe, hrefDe, ir as irDoRoteador, parseRota } from "./rota";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

// Dados sinteticos. Os numeros ja' vem somados do servidor; a tela so' mostra.
const n = (medido: number, aprovado: number, protocolado: number, recebido: number) => ({
  medido_centavos: medido, aprovado_centavos: aprovado, protocolado_centavos: protocolado, recebido_centavos: recebido,
  em_aberto_centavos: protocolado - recebido,
});
const medicao = (id: number, numero: number, comp: string, x: ReturnType<typeof n>,
    notas: { id: number; numero: string; v: number; ok: boolean; parte?: boolean }[]) => ({
  ...x, medicao_id: id, contrato_id: 7, obra: "Obra Alfa", numero, tipo: "execucao", competencia: comp,
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
// a aba e o ano saem do endereco (#815): cada teste abre a pagina num endereco e a limpeza volta ao padrao
const abrirEm = (endereco: string) => window.history.replaceState(null, "", endereco);
const limpar = () => { cleanup(); api.mockReset(); abrirEm("/fechamento"); };
const endereco = () => `${window.location.pathname}${window.location.search}`;

describe("Fechamento (#748)", () => {
  afterEach(limpar);

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

  it("o em aberto nota a nota saiu da página: fica o total do ano, com o link para A receber (#815)", async () => {
    // o servidor continua mandando as linhas do em aberto, as notas sem medição e o em aberto anterior a 2025 (a
    // página A receber usa): aqui nada disso é desenhado, em aba nenhuma
    const dois: RespostaFechamento = {
      ...TRES_PARTES,
      em_aberto: [...TRES_PARTES.em_aberto, { tipo_aberto: "nota", nota_id: 12, numero: "502", contrato_id: 7, obra: "Obra Alfa",
        medicao_id: 5, medicao_numero: 9, tipo: "execucao", competencia: "2025-11", protocolo_em: "2025-12-15", valor_centavos: 30_003,
        paga_em_parte: false }],
      por_ano: { ...TRES_PARTES.por_ano, "2025": ano(n(930_003, 930_003, 930_003, 900_000), 2) },
      em_aberto_anteriores: { quantidade: 1, valor_centavos: 50_000 },
    };
    api.mockResolvedValue(dois);
    for (const caminho of ["/fechamento", "/fechamento/comparacao", "/fechamento/contratantes"]) {
      abrirEm(caminho);
      render(<Fechamento ir={() => {}} />);
      await screen.findByText("Cota da Lotufo");
      expect(screen.queryByRole("heading", { name: /Em aberto de/ })).toBeNull();
      expect(screen.queryByRole("table", { name: /Em aberto de|Nota sem medição ligada/ })).toBeNull();
      expect(document.querySelector(".fch-tabela--aberto, .fch-soltas, .fch-aparte")).toBeNull();
      expect(document.body.textContent).not.toMatch(/Nota protocolada não paga|Subtotal à parte|anteriores a 2025|Notas pagas sem medição|podem ser a mesma cobrança/);
      expect(document.body.textContent).not.toMatch(/28\/03\/2026|02\/06\/2026|01\/06\/2026|R\$ 500,00|R\$ 7\.000,02/);
      cleanup();
    }
    abrirEm("/fechamento");
    render(<Fechamento ir={() => {}} />);
    await screen.findByText("Cota da Lotufo");
    // o total do em aberto do ano: o número do alto, o mesmo do "Total de 2026" da tabela do mês
    expect(valorDe("Em aberto")).toBe("R$ 6.000,01");
    const meses = screen.getByRole("table", { name: /por mês de competência de 2026/ });
    expect(texto(meses.querySelector("tfoot"))).toBe("Total de 2026R$ 17.000,01R$ 14.000,01R$ 14.000,01R$ 10.000,00R$ 6.000,01");
    const porta = screen.getByRole("link", { name: "Em aberto nota a nota, na página A receber" });
    expect(porta.getAttribute("href")).toBe("/a-receber");
    expect(porta.textContent?.trim()).toBe("nota a nota");            // ao lado do rótulo "Em aberto"
    expect(porta.closest(".fch-numero")?.querySelector("dt")?.textContent).toBe("Em aberto");
    // o total segue o ano escolhido, e o link continua lá
    fireEvent.click(screen.getByRole("button", { name: "2025" }));
    expect(valorDe("Em aberto")).toBe("R$ 300,03");
    expect(screen.getByRole("link", { name: /na página A receber/ }).getAttribute("href")).toBe("/a-receber");
  });

  it("nota paga em parte: o selo na linha da medição", async () => {
    const emParte: RespostaFechamento = {
      ...FECHAMENTO,
      meses: FECHAMENTO.meses.map(m => m.competencia !== "2026-03" ? m : { ...m, obras: [{ ...m.obras[0],
        medicoes: [medicao(2, 15, "2026-03", MAR26, [{ id: 21, numero: "601", v: 1_000_000, ok: true },
          { id: 22, numero: "602", v: 800_002, ok: false, parte: true }])] }] }),
    };
    api.mockResolvedValue(emParte);
    render(<Fechamento ir={() => {}} />);
    const meses = await screen.findByRole("table", { name: /por mês de competência de 2026/ });
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

  it("medição protocolada sem nota ligada: o selo na linha da medição", async () => {
    api.mockResolvedValue({ ...FECHAMENTO,
      meses: FECHAMENTO.meses.map(m => m.competencia !== "2026-05" ? m : { ...m, obras: [{ ...m.obras[0],
        medicoes: [{ ...m.obras[0].medicoes[0], sem_nota: true }] }] }) });
    render(<Fechamento ir={() => {}} />);
    const meses = await screen.findByRole("table", { name: /por mês de competência de 2026/ });
    fireEvent.click(within(meses).getByRole("button", { name: /Maio de 2026, por obra/ }));
    fireEvent.click(within(meses).getByRole("button", { name: /Obra Alfa, medições de 05\/2026/ }));
    const linha = within(meses).getByRole("link", { name: "16ª Medição" }).closest("tr") as HTMLElement;
    expect([...linha.querySelectorAll(".fch-notas li")].map(li => texto(li))).toEqual(["sem nota ligada"]);
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

  it("repasse sem baixa: entra no total do em aberto do ano, e a nota diz isso na linha da medição", async () => {
    // 2026-03: a nota 602 (R$ 4.000,01) é de medição que o órgão já pagou ao consórcio; a 603 (R$ 3.000,00), o órgão não pagou
    const total = n(1_700_001, 1_400_001, 1_400_001, 700_000);          // em aberto das notas: 7.000,01
    api.mockResolvedValue({ ...FECHAMENTO,
      meses: FECHAMENTO.meses.map(m => m.competencia !== "2026-03" ? m : { ...m, obras: [{ ...m.obras[0], medicoes: [
        { ...medicao(2, 15, "2026-03", MAR26, [{ id: 22, numero: "602", v: 400_001, ok: false }]),
          notas: [{ nota_id: 22, numero: "602", valor_centavos: 400_001, recebida: false, paga_em_parte: false, aguarda_repasse: true }] }] }] }),
      por_ano: { ...FECHAMENTO.por_ano, "2026": ano(total, 2, 0, 400_001) } });
    render(<Fechamento ir={() => {}} />);
    const meses = await screen.findByRole("table", { name: /por mês de competência de 2026/ });
    expect(valorDe("Em aberto")).toBe("R$ 7.000,01");                   // o número que o servidor manda para o ano
    // na linha da medição, a nota leva o nome do repasse, em vez de "em aberto"
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
    expect(screen.queryByRole("link", { name: /A receber/ })).toBeNull();      // sem valor, não há o que abrir
    const meses = screen.getByRole("table", { name: /por mês de competência de 2026/ });
    expect(texto(meses.querySelector("tfoot"))).toBe("Total de 2026R$ 17.000,01R$ 14.000,01R$ 14.000,01——");
    fireEvent.click(within(meses).getByRole("button", { name: /Março de 2026, por obra/ }));
    fireEvent.click(within(meses).getByRole("button", { name: /Obra Alfa, medições de 03\/2026/ }));
    const linha = within(meses).getByRole("link", { name: "15ª Medição" }).closest("tr") as HTMLElement;
    expect(texto(linha)).toContain("Nota 601");
    expect(within(linha).queryByText("recebida")).toBeNull();                   // nem o selo da nota
    expect(within(linha).queryByText("em aberto")).toBeNull();
    expect(document.body.textContent).not.toMatch(/R\$ 10\.000,00|R\$ 4\.000,01|R\$ 6\.000,01/);
    // nas outras duas abas também: a comparação não oferece o recebido, e a frase da trava continua
    cleanup();
    abrirEm("/fechamento/comparacao");
    render(<Fechamento ir={() => {}} />);
    expect(await screen.findByText("O total a receber ainda não está liberado: recebido e em aberto ficam sem valor.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Protocolado" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Recebido" })).toBeNull();
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

  it("comparação na aba própria: 2026 × 2025 mês a mês, com o acumulado até o último mês e o ano", async () => {
    api.mockResolvedValue(FECHAMENTO);
    abrirEm("/fechamento/comparacao");
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
    expect(valorDe("Medido")).toBe("—");
    expect(screen.queryByRole("table")).toBeNull();
    for (const [caminho, frase] of [["/fechamento/comparacao", "Nenhum lançamento em 2025 nem em 2026."],
      ["/fechamento/contratantes", "Nenhum lançamento em 2026."]]) {
      cleanup();
      abrirEm(caminho);
      render(<Fechamento ir={() => {}} />);
      expect(await screen.findByText(frase)).toBeTruthy();
      expect(screen.queryByRole("table")).toBeNull();
    }
  });

  it("a falha da leitura vira uma frase, com o que fazer", async () => {
    api.mockRejectedValue(new Error("Servidor fora do ar"));
    render(<Fechamento ir={() => {}} />);
    expect((await screen.findByRole("alert")).textContent).toContain("Não foi possível carregar o fechamento");
  });
});

// #805: as familias de valor na tabela do mes. Valores inventados; as referencias e o limite vem do servidor.
describe("Fechamento: famílias de valor (#805)", () => {
  afterEach(limpar);

  // marco: aprovado R$ 30,00 abaixo do pedido das medicoes comparaveis (0,2%: pequena), medido 66,7% acima de 03/2025;
  // maio: em analise, sem aprovado; o total do ano leva a mesma diferenca
  // os dois lados comparaveis e o corte, como o servidor manda: o corte e' so' o que ficou abaixo do pedido
  const par = (aprovado: number, pedido: number, abaixo = Math.max(0, pedido - aprovado)) => ({
    aprovado_com_pedido_centavos: aprovado, pedido_do_aprovado_centavos: pedido, abaixo_do_pedido_centavos: abaixo });
  const MAR = { ...MAR26, ...par(1_400_001, 1_403_001) };
  const VALORES: RespostaFechamento = {
    ...FECHAMENTO,
    diferenca_critica_por_mil: 5,
    meses: [
      { ...FECHAMENTO.meses[0], ...par(900_000, 900_000), medido_ano_anterior_centavos: null },
      { ...FECHAMENTO.meses[1], ...MAR, medido_ano_anterior_centavos: 900_000,
        obras: [{ ...FECHAMENTO.meses[1].obras[0], ...MAR,
          medicoes: [{ ...FECHAMENTO.meses[1].obras[0].medicoes[0], ...MAR }] }] },
      { ...FECHAMENTO.meses[2], ...par(0, 0), medido_ano_anterior_centavos: null },
    ],
    por_ano: { "2025": { ...FECHAMENTO.por_ano["2025"], ...par(900_000, 900_000) }, "2026": { ...FECHAMENTO.por_ano["2026"], ...MAR } },
  };
  const tabelaDe = async (anoDaTabela = "2026") =>
    screen.findByRole("table", { name: new RegExp(`por mês de competência de ${anoDaTabela}`) });
  const etiquetas = (el: Element, classe: string) =>
    [...el.querySelectorAll(`.${classe}`)].map(e => [e.className, [...e.querySelectorAll(`.${classe}__parte`)].map(x => texto(x)).join(" ")]);

  it("o cabeçalho de cada coluna leva a marca da etapa do dinheiro; o medido, que junta etapas, não", async () => {
    api.mockResolvedValue(VALORES);
    render(<Fechamento ir={() => {}} />);
    const cabecalho = within(await tabelaDe()).getAllByRole("columnheader");
    expect(cabecalho.map(th => [texto(th), th.querySelector(".marca-etapa__cor")?.className ?? null])).toEqual([
      ["Mês", null], ["Medido", null], ["Aprovado", "marca-etapa__cor marca-etapa__cor--boletim"],
      ["Protocolado", "marca-etapa__cor marca-etapa__cor--protocolado"], ["Recebido", "marca-etapa__cor marca-etapa__cor--recebido"],
      ["Em aberto", "marca-etapa__cor marca-etapa__cor--em_aberto"]]);
  });

  it("medido: a variação contra o mesmo mês do ano anterior, só no mês que tem a referência", async () => {
    api.mockResolvedValue(VALORES);
    render(<Fechamento ir={() => {}} />);
    const [, marco, maio, total] = within(await tabelaDe()).getAllByRole("row");
    expect(etiquetas(marco, "variacao")).toEqual([["variacao variacao--bom", "▲ +66,7% × mar/25"]]);
    expect(texto(marco.querySelector(".variacao .sr-only"))).toBe("subiu 66,7% em relação a março de 2025");
    expect(etiquetas(maio, "variacao")).toEqual([]);
    expect(etiquetas(total, "variacao")).toEqual([]);                  // o total do ano não compara com o ano inteiro anterior
    // o valor continua lá, em tinta, acima da etiqueta
    expect(texto(within(marco).getAllByRole("cell")[0].querySelector(".fch-cel > span"))).toBe("R$ 15.000,01");
  });

  it("aprovado: a diferença contra o pedido, do mês até a medição; sem os dois lados, nada", async () => {
    api.mockResolvedValue(VALORES);
    render(<Fechamento ir={() => {}} />);
    const tabela = await tabelaDe();
    const [, marco, maio, total] = within(tabela).getAllByRole("row");
    const pequena = [["diferenca diferenca--leve", "\u2212 R$ 30,00 (\u22120,2%)"]];
    expect(etiquetas(marco, "diferenca")).toEqual(pequena);
    expect(etiquetas(total, "diferenca")).toEqual(pequena);
    expect(texto(marco.querySelector(".diferenca .sr-only"))).toBe("R$ 30,00 abaixo do pedido, 0,2%");
    // maio so' tem medicao em analise: nao e' diferenca, e' etapa nao alcancada
    expect(etiquetas(maio, "diferenca")).toEqual([]);
    expect(within(maio).getAllByRole("cell").map(c => texto(c))).toEqual(["R$ 2.000,00", "—", "—", "—", "—"]);
    // a diferenca fica na coluna Aprovado; protocolado e recebido nao levam etiqueta
    const celulas = within(marco).getAllByRole("cell");
    expect(celulas.map(c => c.querySelector(".diferenca") !== null)).toEqual([false, true, false, false, false]);
    fireEvent.click(within(tabela).getByRole("button", { name: /Março de 2026, por obra/ }));
    fireEvent.click(within(tabela).getByRole("button", { name: /Obra Alfa, medições de 03\/2026/ }));
    const medicao = within(tabela).getByRole("link", { name: "15ª Medição" }).closest("tr") as HTMLElement;
    expect(etiquetas(medicao, "diferenca")).toEqual(pequena);
    expect(etiquetas(medicao, "variacao")).toEqual([]);                // a referencia e' do mes
  });

  it("aprovado igual ao pedido leva o sinal de igual; acima do limite do servidor, o tom do crítico", async () => {
    api.mockResolvedValue(VALORES);
    render(<Fechamento ir={() => {}} />);
    await tabelaDe();
    fireEvent.click(screen.getByRole("button", { name: "2025" }));
    const [, marco25] = within(await tabelaDe("2025")).getAllByRole("row");
    expect(etiquetas(marco25, "diferenca")).toEqual([["diferenca diferenca--igual", "= igual ao pedido"]]);
    cleanup();
    abrirEm("/fechamento");                                            // o ano escolhido tinha ido para o endereco
    // a mesma diferenca de 0,2% com o limite em 1 por mil passa a ser critica: quem decide e' o servidor
    api.mockResolvedValue({ ...VALORES, diferenca_critica_por_mil: 1 });
    render(<Fechamento ir={() => {}} />);
    const [, marco] = within(await tabelaDe()).getAllByRole("row");
    expect(etiquetas(marco, "diferenca")).toEqual([["diferenca diferenca--ruim", "\u2212 R$ 30,00 (\u22120,2%)"]]);
  });

  it("no mês, na obra e no total a diferença é só o corte; o aprovado acima do pedido aparece só na medição e não o anula", async () => {
    // a 15ª teve corte de R$ 1.000,00; a 16ª tem o pedido gravado errado (aprovado R$ 5.500,00 acima). Somadas, o mes
    // daria "+ R$ 4.500,00": o servidor manda so' o corte, e o percentual e' sobre o pedido das duas
    const corte = { ...n(1_900_001, 1_900_001, 0, 0), ...par(1_900_001, 2_000_001) };
    const errado = { ...n(600_001, 600_001, 0, 0), ...par(600_001, 50_001), acima_do_pedido_centavos: 550_000 };
    const soma = { ...n(2_500_002, 2_500_002, 0, 0), ...par(2_500_002, 2_050_002, 100_000) };
    api.mockResolvedValue({ ...VALORES,
      meses: [{ competencia: "2026-03", ...soma, medido_ano_anterior_centavos: null,
        obras: [{ contrato_id: 7, obra: "Obra Alfa", ...soma,
          medicoes: [medicao(2, 15, "2026-03", corte, []), medicao(5, 16, "2026-03", errado, [])] }] }],
      por_ano: { ...VALORES.por_ano, "2026": { ...VALORES.por_ano["2026"], ...soma } } });
    render(<Fechamento ir={() => {}} />);
    const tabela = await tabelaDe();
    const [, marco, total] = within(tabela).getAllByRole("row");
    const doMes = [["diferenca diferenca--ruim", "\u2212 R$ 1.000,00 (\u22124,9%)"]];
    expect(etiquetas(marco, "diferenca")).toEqual(doMes);
    expect(etiquetas(total, "diferenca")).toEqual(doMes);
    fireEvent.click(within(tabela).getByRole("button", { name: /Março de 2026, por obra/ }));
    const obra = within(tabela).getByRole("button", { name: /Obra Alfa, medições de 03\/2026/ });
    expect(etiquetas(obra.closest("tr") as HTMLElement, "diferenca")).toEqual(doMes);
    fireEvent.click(obra);
    const linha = (nome: string) => within(tabela).getByRole("link", { name: nome }).closest("tr") as HTMLElement;
    expect(etiquetas(linha("15ª Medição"), "diferenca")).toEqual([["diferenca diferenca--ruim", "\u2212 R$ 1.000,00 (\u22125,0%)"]]);
    // acima do pedido: diz o sentido, no tom da atenção, nunca crítico, e só aqui
    expect(etiquetas(linha("16ª Medição"), "diferenca")).toEqual([["diferenca diferenca--leve", "+ R$ 5.500,00 acima do pedido"]]);
    expect(tabela.querySelectorAll(".diferenca--leve")).toHaveLength(1);
  });

  it("diferença que o servidor conta como arredondamento (sem corte e sem acima) é igual ao pedido, do mês à medição", async () => {
    // aprovado R$ 0,02 abaixo do pedido: dentro da tolerancia do servidor, que manda corte zero
    const quase = { ...n(900_000, 900_000, 0, 0), ...par(900_000, 900_002, 0) };
    api.mockResolvedValue({ ...VALORES,
      meses: [{ competencia: "2026-03", ...quase, medido_ano_anterior_centavos: null,
        obras: [{ contrato_id: 7, obra: "Obra Alfa", ...quase,
          medicoes: [{ ...medicao(2, 15, "2026-03", quase, []), acima_do_pedido_centavos: 0 }] }] }],
      por_ano: { ...VALORES.por_ano, "2026": { ...VALORES.por_ano["2026"], ...quase } } });
    render(<Fechamento ir={() => {}} />);
    const tabela = await tabelaDe();
    fireEvent.click(within(tabela).getByRole("button", { name: /Março de 2026, por obra/ }));
    fireEvent.click(within(tabela).getByRole("button", { name: /Obra Alfa, medições de 03\/2026/ }));
    const igual = [["diferenca diferenca--igual", "= igual ao pedido"]];
    expect(within(tabela).getAllByRole("row").slice(1).map(l => etiquetas(l, "diferenca"))).toEqual([igual, igual, igual, igual]);
  });

  it("em aberto no tom do “vence em breve”, só onde há valor; sem o limite do servidor, nenhuma diferença", async () => {
    api.mockResolvedValue({ ...VALORES, diferenca_critica_por_mil: undefined });
    render(<Fechamento ir={() => {}} />);
    const tabela = await tabelaDe();
    const [, marco, maio, total] = within(tabela).getAllByRole("row");
    const emAberto = (linha: HTMLElement) => within(linha).getAllByRole("cell").map(c => c.classList.contains("fch-em-aberto"));
    expect(emAberto(marco)).toEqual([false, false, false, false, true]);
    expect(emAberto(maio)).toEqual([false, false, false, false, false]);        // "—" fica em tinta
    expect(emAberto(total)).toEqual([false, false, false, false, true]);
    expect(tabela.querySelector(".diferenca")).toBeNull();
    expect(tabela.querySelector(".variacao")).not.toBeNull();
  });

  it("a resposta sem os campos novos desenha a tabela de antes, sem etiqueta", async () => {
    api.mockResolvedValue(FECHAMENTO);
    render(<Fechamento ir={() => {}} />);
    const tabela = await tabelaDe();
    expect(tabela.querySelector(".variacao, .diferenca, .fch-cel")).toBeNull();
  });
});

// #815: as tres abas, com a aba e o ano no endereco, e a aba Por contratante. Valores inventados: as linhas por
// contratante ja' vem somadas do servidor, e aqui somam o total do ano coluna a coluna, como la'.
describe("Fechamento em abas (#815)", () => {
  afterEach(limpar);

  const par = (aprovado: number, pedido: number) => ({
    aprovado_com_pedido_centavos: aprovado, pedido_do_aprovado_centavos: pedido, abaixo_do_pedido_centavos: Math.max(0, pedido - aprovado) });
  const linha = (contratante: string, chave: string | null, x: ReturnType<typeof n>, parte: number | null) => ({
    contratante, contratante_chave: chave, ...x, participacao_medido_por_mil: parte });
  // 2026: 12.000,01 + 4.000,00 + 1.000,00 = 17.000,01 de medido; 70,6% + 23,5% + 5,9% = 100%
  const ABAS: RespostaFechamento = {
    ...FECHAMENTO,
    diferenca_critica_por_mil: 5,
    meses: FECHAMENTO.meses.map(m => (m.competencia === "2026-03" ? { ...m, medido_ano_anterior_centavos: 900_000 } : m)),
    por_ano: { ...FECHAMENTO.por_ano, "2026": { ...FECHAMENTO.por_ano["2026"], ...par(1_000_001, 1_003_001) } },
    por_contratante: {
      "2025": [linha("SINFRA", "sinfra", n(900_000, 900_000, 900_000, 900_000), 1000)],
      "2026": [
        linha("SINFRA", "sinfra", { ...n(1_200_001, 1_000_001, 1_000_001, 1_000_000), ...par(1_000_001, 1_003_001) }, 706),
        linha("Secretaria X", "orgao-x", n(400_000, 400_000, 400_000, 0), 235),
        linha("ÓRGÃO ANTIGO", null, n(100_000, 0, 0, 0), 59),
      ],
    },
  };
  const abas = () => within(screen.getByRole("navigation", { name: "Fechamento" })).getAllByRole("link");
  const tabelas = () => screen.queryAllByRole("table").map(t => [...t.classList].find(c => /^fch-tabela--(meses|comparacao|contratantes)$/.test(c)));
  const linhasDe = (t: HTMLElement) => within(t).getAllByRole("row");

  it("cada aba tem o seu endereço, e o endereço antigo de uma aba só continua abrindo a primeira", () => {
    expect(parseRota("/fechamento")).toEqual({ tela: "fechamento" });
    expect(parseRota("/fechamento/comparacao")).toEqual({ tela: "fechamento", aba: "comparacao" });
    expect(parseRota("/fechamento/contratantes")).toEqual({ tela: "fechamento", aba: "contratantes" });
    expect(parseRota("/fechamento/meses")).toEqual({ tela: "fechamento" });            // a padrão não entra na URL
    expect(parseRota("/fechamento/outra")).toEqual({ tela: "raiz" });
    expect(parseRota("/fechamento/contratantes/sinfra")).toEqual({ tela: "raiz" });
    expect(caminhoDe({ tela: "fechamento" })).toBe("/fechamento");
    expect(caminhoDe({ tela: "fechamento", aba: "meses" })).toBe("/fechamento");
    expect(caminhoDe({ tela: "fechamento", aba: "comparacao" })).toBe("/fechamento/comparacao");
    expect(hrefDe({ tela: "fechamento", aba: "contratantes" }, { ano: "2025" })).toBe("/fechamento/contratantes?ano=2025");
    expect(parseRota("/carteira/producao")).toEqual({ tela: "fechamento" });           // o endereço de antes da #748
  });

  it("o link direto abre a aba certa, e cada aba mostra só a tabela dela", async () => {
    api.mockResolvedValue(ABAS);
    const casos: [string, string, string, boolean][] = [
      ["/fechamento", "Mês a mês", "fch-tabela--meses", true],
      ["/fechamento/comparacao", "2026 × 2025", "fch-tabela--comparacao", false],
      ["/fechamento/contratantes", "Por contratante", "fch-tabela--contratantes", true],
    ];
    for (const [caminho, rotulo, tabela, doAno] of casos) {
      abrirEm(caminho);
      render(<Fechamento ir={() => {}} />);
      await screen.findByText("Cota da Lotufo");
      expect(abas().map(a => [a.textContent, a.getAttribute("href")])).toEqual([
        ["Mês a mês", "/fechamento"], ["2026 × 2025", "/fechamento/comparacao"], ["Por contratante", "/fechamento/contratantes"]]);
      expect(abas().filter(a => a.getAttribute("aria-current") === "page").map(a => a.textContent)).toEqual([rotulo]);
      expect(tabelas()).toEqual([tabela]);
      // o painel leva o nome da aba para o leitor de tela e não o repete como título
      expect(screen.getByRole("region", { name: rotulo }).querySelector("table")?.classList.contains(tabela)).toBe(true);
      expect(screen.getAllByRole("heading").map(h => h.textContent)).toEqual(["Cota da Lotufo"]);
      // o ano e os cinco números do ano só nas abas de um ano; a comparação mostra os dois
      expect(screen.queryByRole("group", { name: "Ano" }) !== null).toBe(doAno);
      expect(document.querySelector(".fch-numeros") !== null).toBe(doAno);
      cleanup();
    }
  });

  it("trocar de aba muda o endereço e o que a página mostra", async () => {
    api.mockResolvedValue(ABAS);
    window.scrollTo = vi.fn();                                  // o roteador leva a tela nova ao topo; o jsdom não rola
    render(<Fechamento ir={irDoRoteador} />);
    await screen.findByText("Cota da Lotufo");
    expect(tabelas()).toEqual(["fch-tabela--meses"]);
    fireEvent.click(screen.getByRole("link", { name: "Por contratante" }));
    expect(endereco()).toBe("/fechamento/contratantes");
    expect(tabelas()).toEqual(["fch-tabela--contratantes"]);
    fireEvent.click(screen.getByRole("link", { name: "2026 × 2025" }));
    expect(endereco()).toBe("/fechamento/comparacao");
    expect(tabelas()).toEqual(["fch-tabela--comparacao"]);
    fireEvent.click(screen.getByRole("link", { name: "Mês a mês" }));
    expect(endereco()).toBe("/fechamento");
    expect(tabelas()).toEqual(["fch-tabela--meses"]);
    expect(api).toHaveBeenCalledTimes(1);                       // a troca de aba não lê o servidor de novo
  });

  it("o ano escolhido vai no endereço, acompanha a troca de aba, e o mais novo não entra na URL", async () => {
    api.mockResolvedValue(ABAS);
    window.scrollTo = vi.fn();
    abrirEm("/fechamento?ano=2025");
    render(<Fechamento ir={irDoRoteador} />);
    await screen.findByText("Cota da Lotufo");
    expect(screen.getByRole("button", { name: "2025" }).getAttribute("aria-pressed")).toBe("true");
    expect(valorDe("Medido")).toBe("R$ 9.000,00");
    expect(screen.getByRole("table", { name: /por mês de competência de 2025/ })).toBeTruthy();
    expect(abas().map(a => a.getAttribute("href"))).toEqual(["/fechamento?ano=2025", "/fechamento/comparacao?ano=2025", "/fechamento/contratantes?ano=2025"]);
    fireEvent.click(screen.getByRole("link", { name: "Por contratante" }));
    expect(endereco()).toBe("/fechamento/contratantes?ano=2025");
    expect(screen.getByRole("table", { name: /cada contratante em 2025/ })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "2026" }));
    expect(endereco()).toBe("/fechamento/contratantes");
    expect(screen.getByRole("table", { name: /cada contratante em 2026/ })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "2025" }));
    expect(endereco()).toBe("/fechamento/contratantes?ano=2025");
  });

  it("ano que não é da página no endereço: vale o mais novo", async () => {
    api.mockResolvedValue(ABAS);
    abrirEm("/fechamento?ano=1999");
    render(<Fechamento ir={() => {}} />);
    await screen.findByText("Cota da Lotufo");
    expect(screen.getByRole("button", { name: "2026" }).getAttribute("aria-pressed")).toBe("true");
    expect(valorDe("Medido")).toBe("R$ 17.000,01");
  });

  it("?mes= abre a página no ano do mês, com ele aberto por obra; a obra abre a medição", async () => {
    api.mockResolvedValue(ABAS);
    const rolou = vi.fn();
    Element.prototype.scrollIntoView = rolou;
    abrirEm("/fechamento?mes=2025-03");
    render(<Fechamento ir={() => {}} />);
    const tabela = await screen.findByRole("table", { name: /por mês de competência de 2025/ });
    expect(screen.getByRole("button", { name: "2025" }).getAttribute("aria-pressed")).toBe("true");
    expect(within(tabela).getByRole("button", { name: /Março de 2025, por obra/ }).getAttribute("aria-expanded")).toBe("true");
    // a vista vai até a linha do mês aberto (19/11/2026), uma vez, ao abrir
    const linhaDoMes = within(tabela).getByRole("button", { name: /Março de 2025, por obra/ }).closest("tr")!;
    expect(rolou).toHaveBeenCalledTimes(1);
    expect(rolou.mock.contexts[0]).toBe(linhaDoMes);
    fireEvent.click(within(tabela).getByRole("button", { name: /Obra Alfa, medições de 03\/2025/ }));
    expect(within(tabela).getByRole("link", { name: "3ª Medição" }).getAttribute("href")).toBe("/obras/7/medicoes/1");
    expect(rolou).toHaveBeenCalledTimes(1);
    // escolher o outro ano tira o mês do endereço
    fireEvent.click(screen.getByRole("button", { name: "2026" }));
    expect(endereco()).toBe("/fechamento");
    const de2026 = screen.getByRole("table", { name: /por mês de competência de 2026/ });
    expect(within(de2026).getByRole("button", { name: /Março de 2026, por obra/ }).getAttribute("aria-expanded")).toBe("false");
    cleanup();
    // mês mal escrito ou de ano fora da página: a página abre como sempre, sem mês aberto
    for (const ruim of ["2026-13", "2024-03", "março"]) {
      abrirEm(`/fechamento?mes=${encodeURIComponent(ruim)}`);
      render(<Fechamento ir={() => {}} />);
      const t = await screen.findByRole("table", { name: /por mês de competência de 2026/ });
      expect(t.querySelector('[aria-expanded="true"]')).toBeNull();
      cleanup();
    }
    // sem mês aberto, a vista fica no alto
    expect(rolou).toHaveBeenCalledTimes(1);
  });

  it("por contratante: os cinco números de cada um, a participação no medido e o total do ano na última linha", async () => {
    api.mockResolvedValue(ABAS);
    abrirEm("/fechamento/contratantes");
    render(<Fechamento ir={() => {}} />);
    const tabela = await screen.findByRole("table", { name: /cada contratante em 2026, na cota da Lotufo, com a participação no medido do ano/ });
    expect(within(tabela).getAllByRole("columnheader").map(th => [texto(th), th.querySelector(".marca-etapa__cor")?.className ?? null])).toEqual([
      ["Contratante", null], ["Medido", null], ["Aprovado", "marca-etapa__cor marca-etapa__cor--boletim"],
      ["Protocolado", "marca-etapa__cor marca-etapa__cor--protocolado"], ["Recebido", "marca-etapa__cor marca-etapa__cor--recebido"],
      ["Em aberto", "marca-etapa__cor marca-etapa__cor--em_aberto"]]);
    const [, sinfra, secretaria, antigo, total] = linhasDe(tabela);
    const valores = (l: HTMLElement) => within(l).getAllByRole("cell").map(c => texto(c.querySelector(".fch-cel > span") ?? c));
    expect([sinfra, secretaria, antigo, total].map(l => texto(l.querySelector("th")))).toEqual(["SINFRA", "Secretaria X", "ÓRGÃO ANTIGO", "Total de 2026"]);
    expect(valores(sinfra)).toEqual(["R$ 12.000,01", "R$ 10.000,01", "R$ 10.000,01", "R$ 10.000,00", "R$ 0,01"]);
    expect(valores(secretaria)).toEqual(["R$ 4.000,00", "R$ 4.000,00", "R$ 4.000,00", "—", "R$ 4.000,00"]);
    expect(valores(antigo)).toEqual(["R$ 1.000,00", "—", "—", "—", "—"]);
    // a última linha é o total do ano que o servidor manda: o mesmo dos cinco números do alto
    expect(valores(total)).toEqual(["R$ 17.000,01", "R$ 14.000,01", "R$ 14.000,01", "R$ 10.000,00", "R$ 4.000,01"]);
    expect(["Medido", "Aprovado", "Protocolado", "Recebido", "Em aberto"].map(valorDe)).toEqual(valores(total));
    // a participação de cada um no medido do ano, sob o medido; o total não leva
    expect([sinfra, secretaria, antigo, total].map(l => texto(l.querySelector(".fch-parte")))).toEqual(
      ["70,6% do total", "23,5% do total", "5,9% do total", ""]);
    expect(sinfra.querySelector(".fch-parte")?.closest("td")?.getAttribute("data-rotulo")).toBe("Medido");
    // as famílias de valor da tabela do mês valem aqui: a diferença contra o pedido e o tom do em aberto
    expect(texto(sinfra.querySelector(".diferenca .sr-only"))).toBe("R$ 30,00 abaixo do pedido, 0,3%");
    expect(sinfra.querySelector(".diferenca")?.className).toBe("diferenca diferenca--leve");
    expect(secretaria.querySelector(".diferenca")).toBeNull();          // sem os dois lados, nada
    expect(texto(total.querySelector(".diferenca .sr-only"))).toBe("R$ 30,00 abaixo do pedido, 0,3%");
    expect(tabela.querySelector(".variacao")).toBeNull();               // a variação é do mês
    expect([sinfra, secretaria, antigo].map(l => within(l).getAllByRole("cell")[4].classList.contains("fch-em-aberto"))).toEqual([true, true, false]);
    // o rótulo da coluna vai em cada célula, para o bloco do celular
    expect(within(secretaria).getAllByRole("cell").map(c => c.getAttribute("data-rotulo"))).toEqual(["Medido", "Aprovado", "Protocolado", "Recebido", "Em aberto"]);
    // o contratante abre a página dele; sem órgão no cadastro não há página, e o nome fica em texto
    expect(within(sinfra).getByRole("link", { name: "SINFRA" }).getAttribute("href")).toBe("/obras/contratante/sinfra");
    expect(within(secretaria).getByRole("link", { name: "Secretaria X" }).getAttribute("href")).toBe("/obras/contratante/orgao-x");
    expect(within(antigo).queryByRole("link")).toBeNull();
    // o outro ano
    fireEvent.click(screen.getByRole("button", { name: "2025" }));
    const de2025 = screen.getByRole("table", { name: /cada contratante em 2025/ });
    expect(linhasDe(de2025).slice(1).map(l => texto(l))).toEqual([
      "SINFRAR$ 9.000,00100,0% do totalR$ 9.000,00R$ 9.000,00R$ 9.000,00—", "Total de 2025R$ 9.000,00R$ 9.000,00R$ 9.000,00R$ 9.000,00—"]);
  });

  it("por contratante sem participação (ano sem medido que se reparta): só os valores", async () => {
    api.mockResolvedValue({ ...ABAS, por_contratante: { ...ABAS.por_contratante,
      "2026": (ABAS.por_contratante?.["2026"] ?? []).map(g => ({ ...g, participacao_medido_por_mil: null })) } });
    abrirEm("/fechamento/contratantes");
    render(<Fechamento ir={() => {}} />);
    const tabela = await screen.findByRole("table", { name: /cada contratante em 2026/ });
    expect(tabela.querySelector(".fch-parte")).toBeNull();
    expect(texto(linhasDe(tabela)[2])).toBe("Secretaria XR$ 4.000,00R$ 4.000,00R$ 4.000,00—R$ 4.000,00");
  });

  it("por contratante com a trava do total a receber: recebido e em aberto sem valor em toda linha", async () => {
    const semValor = <T extends object>(x: T) => ({ ...x, recebido_centavos: null, em_aberto_centavos: null });
    api.mockResolvedValue({ ...ABAS, total_a_receber_liberado: false,
      por_ano: Object.fromEntries(Object.entries(ABAS.por_ano).map(([a, t]) => [a, semValor(t)])),
      por_contratante: Object.fromEntries(Object.entries(ABAS.por_contratante ?? {}).map(([a, gs]) => [a, gs.map(semValor)])) });
    abrirEm("/fechamento/contratantes");
    render(<Fechamento ir={() => {}} />);
    const tabela = await screen.findByRole("table", { name: /cada contratante em 2026/ });
    expect(screen.getByText("O total a receber ainda não está liberado: recebido e em aberto ficam sem valor.")).toBeTruthy();
    for (const l of linhasDe(tabela).slice(1)) {
      expect(within(l).getAllByRole("cell").slice(3).map(c => texto(c))).toEqual(["—", "—"]);
    }
    expect(texto(linhasDe(tabela)[1])).toContain("R$ 12.000,0170,6% do total");   // o medido e a participação ficam
    expect(tabela.querySelector(".fch-em-aberto")).toBeNull();
    expect(document.body.textContent).not.toMatch(/R\$ 10\.000,00|R\$ 4\.000,01|R\$ 0,01/);
  });

  it("2026 × 2025: no medido, o mês encerrado leva a variação contra o mesmo mês do ano anterior; nos outros números, não", async () => {
    api.mockResolvedValue(ABAS);
    abrirEm("/fechamento/comparacao");
    render(<Fechamento ir={() => {}} />);
    const tabela = await screen.findByRole("table", { name: /Medido por mês de competência, 2025 e 2026/ });
    const [, marco, maio, ate, doAno] = linhasDe(tabela);
    expect([...marco.querySelectorAll(".variacao__parte")].map(x => texto(x))).toEqual(["▲ +66,7%", "× mar/25"]);
    expect(marco.querySelector(".variacao")?.closest("td")).toBe(within(marco).getAllByRole("cell")[1]);   // na coluna do ano mais novo
    expect(texto(marco.querySelector(".variacao .sr-only"))).toBe("subiu 66,7% em relação a março de 2025");
    expect(texto(marco.querySelector(".fch-cel > span"))).toBe("R$ 15.000,01");
    // maio não tem referência (o servidor manda nula); o acumulado e o ano não comparam
    expect([maio, ate, doAno].map(l => l.querySelector(".variacao"))).toEqual([null, null, null]);
    fireEvent.click(screen.getByRole("button", { name: "Aprovado" }));
    const aprovado = screen.getByRole("table", { name: /Aprovado por mês de competência/ });
    expect(aprovado.querySelector(".variacao")).toBeNull();
    expect(texto(linhasDe(aprovado)[1])).toBe("MarçoR$ 9.000,00R$ 14.000,01");
  });

  it("a resposta sem as linhas por contratante: a aba diz que não há lançamento, sem quebrar", async () => {
    api.mockResolvedValue(FECHAMENTO);
    abrirEm("/fechamento/contratantes");
    render(<Fechamento ir={() => {}} />);
    expect(await screen.findByText("Nenhum lançamento em 2026.")).toBeTruthy();
  });
});
