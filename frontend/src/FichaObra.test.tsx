import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import FichaObra, { desvioDaCurva, mesAno, type Ficha } from "./FichaObra";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

const CABECALHO = { id: 3, obra: "Integra BRT", orgao: "SINFRA", instrumento: "041/2025", valor_vigente_centavos: 15516880000,
  percentual_lotufo_bp: 4900, execucao_fim: "2026-11-18", dias_execucao: 12, vigencia_fim: "2027-02-16", dias_vigencia: 102, status: "ativo" };
const CURVA = { curva: [
  { competencia: "2026-08", previsto_centavos: 50, medido_execucao_centavos: 40, atestado_pendente: false },
  { competencia: "2026-09", previsto_centavos: 50, medido_execucao_centavos: 40, atestado_pendente: false },
  { competencia: "2026-10", previsto_centavos: 100, medido_execucao_centavos: 0, atestado_pendente: false }],
saldo: { vigente_centavos: 15516880000, vigente_execucao_centavos: 15516880000, atestado_execucao_centavos: 12624791119, saldo_centavos: 2892088881 } };
const FICHA: Ficha = {
  contrato: { original_centavos: 15516880000, original_igual: true, tas: 2, data_base: "2025-01" },
  ultima_medicao: { id: 15, titulo: "15ª Medição", rotulo: "15ª", competencia: "2026-09", valor_centavos: 787288979,
    recebida_em: "2026-10-16", dias_apos_nota: 14 },
  em_andamento: { id: 16, titulo: "16ª Medição", rotulo: "16ª", competencia: "2026-10", valor_centavos: 990529648,
    etapa: "análise do órgão", desde: "2026-11-05", outras: 0 },
  vencimentos: [
    { chave: "certidao", rotulo: "FGTS Lotufo", data: "2026-11-15", dias: 9, nivel: "atencao" },
    { chave: "execucao", rotulo: "Fim da execução", data: "2026-11-18", dias: 12, nivel: "critico" },
    { chave: "vigencia", rotulo: "Fim da vigência", data: "2027-02-16", dias: 102, nivel: "normal" }],
};

function responder(ficha: Ficha | Error = FICHA) {
  api.mockImplementation(async (url: string) => {
    if (url.endsWith("/cabecalho")) return CABECALHO;
    if (url.endsWith("/curva")) return CURVA;
    if (url.endsWith("/ficha")) { if (ficha instanceof Error) throw ficha; return ficha; }
    return {};
  });
}
const cartao = (nome: string) => screen.getByRole("region", { name: nome });

describe("Ficha executiva da obra", () => {
  beforeEach(() => { window.history.replaceState(null, "", "/obras/3"); });
  afterEach(() => { cleanup(); api.mockReset(); });

  it("mostra os seis cartões com os valores da API", async () => {
    responder();
    render(<FichaObra contratoId={3} origem={null} />);
    expect(await screen.findByRole("heading", { level: 1, name: "Integra BRT" })).toBeTruthy();
    expect(screen.getByText("SINFRA · Contrato 041/2025 · Consórcio, cota Lotufo 49%")).toBeTruthy();
    const contrato = await within(await screen.findByRole("region", { name: "Contrato" })).findByText(/original igual/);
    expect(contrato.textContent).toContain("2 TAs");
    expect(contrato.textContent).toContain("data-base jan/2025");
    expect(within(cartao("Contrato")).getByText(/155\.168\.800,00/)).toBeTruthy();
    expect(within(cartao("Execução")).getByText("81%").className).toContain("info--feito");
    expect(within(cartao("Execução")).getByText(/126\.247\.911,19/)).toBeTruthy();
    expect(within(cartao("Execução")).getByText(/28\.920\.888,81/)).toBeTruthy();
    expect(within(cartao("Última medição")).getByRole("link").textContent).toMatch(/^15ª · set\/2026 · R\$.*7\.872\.889,79$/);
    expect(within(cartao("Última medição")).getByText(/recebida em 16\/10\/2026, 14 dias após a nota/)).toBeTruthy();
    expect(within(cartao("Em andamento")).getByRole("link").textContent).toMatch(/^16ª · out\/2026 · R\$.*9\.905\.296,48$/);
    expect(within(cartao("Em andamento")).getByText("análise do órgão desde 05/11")).toBeTruthy();
  });

  it("prazo em vermelho quando crítico e preto quando não; vencimentos pelo nível do servidor", async () => {
    responder();
    render(<FichaObra contratoId={3} origem={null} />);
    await screen.findByRole("heading", { level: 1, name: "Integra BRT" });
    const dias = await within(cartao("Prazo")).findByText("12 dias");
    expect(dias.className).toContain("info--critico");
    expect(within(cartao("Prazo")).getByText(/execução até 18\/11\/2026 · vigência até 16\/02\/2027/)).toBeTruthy();
    const venc = cartao("Próximos vencimentos");
    expect((await within(venc).findByText("15/11/2026")).className).toContain("info--breve");
    expect(within(venc).getByText("18/11/2026").className).toContain("info--critico");
    expect(within(venc).getByText("16/02/2027").className).not.toContain("info-");
  });

  it("prazo longe do fim não fica vermelho", async () => {
    api.mockImplementation(async (url: string) => url.endsWith("/ficha")
      ? { ...FICHA, vencimentos: FICHA.vencimentos.map(v => ({ ...v, dias: 200, nivel: "normal" })) } : url.endsWith("/curva") ? CURVA : CABECALHO);
    render(<FichaObra contratoId={3} origem={null} />);
    await screen.findByRole("heading", { level: 1, name: "Integra BRT" });
    expect((await within(cartao("Prazo")).findByText("200 dias")).className).not.toContain("info--critico");
  });

  it("curva S com as duas séries e a pílula do desvio", async () => {
    responder();
    const { container } = render(<FichaObra contratoId={3} origem={null} />);
    await screen.findByRole("img", { name: /Curva S/ });
    expect(container.querySelector("path.ficha__previsto")).toBeTruthy();
    expect(container.querySelector("path.ficha__medido")).toBeTruthy();
    // medido 80 de 200 previstos no total; previsto acumulado até a última medição: 100 → 10 pontos abaixo
    expect(screen.getByText(/medido/, { selector: ".pilula-info" }).textContent).toBe("medido 10% abaixo do previsto");
  });

  it("falha da ficha mostra indisponível sem derrubar a página", async () => {
    responder(new Error("falhou"));
    render(<FichaObra contratoId={3} origem={null} />);
    await screen.findByRole("heading", { level: 1, name: "Integra BRT" });
    expect(await within(cartao("Última medição")).findByRole("alert")).toBeTruthy();
    expect(within(cartao("Execução")).getByText("81%")).toBeTruthy();
  });
});

describe("regras puras da ficha", () => {
  it("desvio: acima, abaixo e sem medição", () => {
    const p = (competencia: string, previsto: number, medido: number) => ({ competencia, previsto_centavos: previsto, medido_execucao_centavos: medido, atestado_pendente: false });
    expect(desvioDaCurva([p("2026-01", 50, 60), p("2026-02", 50, 0)], null)!.pp).toBeCloseTo(10);
    expect(desvioDaCurva([p("2026-01", 50, 40), p("2026-02", 50, 0)], null)!.pp).toBeCloseTo(-10);
    expect(desvioDaCurva([p("2026-01", 50, 0)], null)).toBeNull();
  });
  it("mês e ano", () => expect(mesAno("2026-09")).toBe("set/2026"));
});

describe("execução com aditivo de reajuste", () => {
  afterEach(() => { cleanup(); api.mockReset(); });
  it("o percentual divide pelo vigente a preços iniciais, não pelo vigente com reajuste", async () => {
    api.mockImplementation(async (url: string) => url.endsWith("/cabecalho") ? CABECALHO : url.endsWith("/ficha") ? FICHA
      : { ...CURVA, saldo: { vigente_centavos: 110_000_000_00, vigente_execucao_centavos: 100_000_000_00,
        atestado_execucao_centavos: 90_000_000_00, saldo_centavos: 10_000_000_00 } });
    render(<FichaObra contratoId={3} origem={null} />);
    await screen.findByRole("heading", { level: 1, name: "Integra BRT" });
    expect((await within(await screen.findByRole("region", { name: "Execução" })).findByText("90%")).className).toContain("info--feito");
  });
});
