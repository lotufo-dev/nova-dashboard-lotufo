import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import AguardandoPagamento from "./AguardandoPagamento";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

const HOJE = "2026-10-14";
const linha = (extra: Record<string, unknown> = {}) => ({
  medicao_id: 635, contrato_id: 13, obra: "Complexo Xtreme", orgao: "MTPAR", descricao: "15ª medição",
  valor_centavos: 100_000, enviada_em: "2026-10-08", numero_orgao: null, familia: "mtpar", origem: "sistema", ...extra });
// enviadas a 50, 44, 30 e 29 dias de HOJE (45 e 30 sao os limites das faixas) e a 1 dia
const cinco = () => [
  linha({ medicao_id: 1, obra: "Granito", enviada_em: "2026-08-25" }),
  linha({ medicao_id: 2, obra: "MT-402", familia: "sinfra", orgao: "SINFRA", enviada_em: "2026-08-31" }),
  linha({ medicao_id: 3, obra: "Hospital", familia: "ses", orgao: "SES-MT", enviada_em: "2026-09-14", origem: "externo", numero_orgao: "SES-1" }),
  linha({ medicao_id: 4, obra: "MT-388", familia: "sinfra", orgao: "SINFRA", enviada_em: "2026-09-15" }),
  linha({ medicao_id: 5, obra: "Leblon", familia: "sinfra", orgao: "SINFRA", enviada_em: "2026-10-13" }),
];
const faixa = (nome: RegExp) => screen.getByText(nome).closest("tbody") as HTMLElement;

describe("Aguardando pagamento", () => {
  afterEach(() => { cleanup(); api.mockReset(); });

  it("divide em Atrasadas (45+), Atenção (30 a 44) e Em dia, com o total; a faixa é só o rótulo", async () => {
    api.mockResolvedValue(cinco());
    render(<AguardandoPagamento hoje={HOJE} />);
    await screen.findByText(/Atrasadas \(45 dias ou mais\)/);
    const atrasadas = faixa(/Atrasadas \(45 dias ou mais\)/);
    expect(within(atrasadas).getByText(/Granito/)).toBeTruthy();
    expect(within(atrasadas).queryByText(/MT-402/)).toBeNull();
    const atencao = faixa(/Atenção \(30 a 44 dias\)/);
    expect(within(atencao).getByText(/MT-402/)).toBeTruthy();   // 44 dias
    expect(within(atencao).getByText(/Hospital/)).toBeTruthy();  // 30 dias
    const emDia = faixa(/Em dia/);
    expect(within(emDia).getByText(/MT-388/)).toBeTruthy();      // 29 dias
    expect(within(emDia).getByText(/Leblon/)).toBeTruthy();
    expect(atencao.querySelector(".ap__faixa-rotulo")?.textContent).toBe("Atenção (30 a 44 dias)");
    expect(screen.getByText("Total").textContent).toMatch(/^Total R\$\s5\.000,00$/);
    expect(screen.queryByText(/5 notas|em notas aguardando pagamento/)).toBeNull();
  });

  it("Parada há: âmbar a partir de 30 dias, vermelho a partir de 45", async () => {
    api.mockResolvedValue(cinco());
    render(<AguardandoPagamento hoje={HOJE} />);
    expect((await screen.findByText("50 dias")).className).toContain("parada--acao");
    expect(screen.getByText("44 dias").className).toContain("parada--atencao");
    expect(screen.getByText("30 dias").className).toContain("parada--atencao");
    expect(screen.getByText("29 dias").className).not.toContain("parada--");
  });

  it("escolher uma nota abre o painel com valor, protocolo e links da medição e da obra", async () => {
    api.mockResolvedValue(cinco());
    render(<AguardandoPagamento hoje={HOJE} />);
    fireEvent.click(await screen.findByRole("row", { name: /MT-402/ }));
    const painel = screen.getByRole("complementary", { name: "Detalhe da nota" });
    expect(within(painel).getByRole("heading", { name: /MT-402/ })).toBeTruthy();
    expect(within(painel).getByText("Nº do protocolo no órgão")).toBeTruthy();
    expect(within(painel).getByRole("link", { name: /Abrir a medição/ })).toBeTruthy();
    expect(within(painel).getByRole("link", { name: "Abrir a obra" })).toBeTruthy();
  });

  // 16/10/2026: o nº do protocolo no órgão só se digita na etapa 4 da medição; aqui a marca leva até lá
  it("MTPAR: a marca 'sem protocolo SIGA' leva à etapa 4; nos outros órgãos, sem marca e sem campo", async () => {
    api.mockResolvedValue([cinco()[0], cinco()[1]]);
    render(<AguardandoPagamento hoje={HOJE} />);
    const painel = await screen.findByRole("complementary", { name: "Detalhe da nota" });   // 1ª da lista: Granito, MTPAR
    expect(within(painel).getByText("Nº do protocolo no SIGA")).toBeTruthy();
    expect(screen.getAllByText("sem protocolo SIGA")).toHaveLength(2);   // linha + painel
    for (const marca of screen.getAllByText("sem protocolo SIGA")) {
      expect(marca.closest("a")!.getAttribute("href")).toBe("/obras/13/medicoes/1#etapa-4");
    }
    // a marca ja' e' o link: sem o link de texto repetido ao lado, nem title explicando
    expect(within(painel).queryByRole("link", { name: /Registrar o número/ })).toBeNull();
    expect(painel.querySelector("a[title]")).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
    fireEvent.click(screen.getByRole("row", { name: /MT-402/ }));
    const outro = screen.getByRole("complementary", { name: "Detalhe da nota" });
    expect(within(outro).getByText("Nº do protocolo no órgão")).toBeTruthy();
    // fora da MTPAR nao ha' marca: o link curto leva a' etapa 4
    expect(within(outro).getByRole("link", { name: "Registrar o número →" }).getAttribute("href")).toBe("/obras/13/medicoes/2#etapa-4");
    expect(screen.getAllByText("sem protocolo SIGA")).toHaveLength(1);   // so' a linha da Granito
  });

  it("quem só consulta vê a marca, mas sem o caminho para registrar o número", async () => {
    api.mockResolvedValue([cinco()[0]]);
    render(<AguardandoPagamento hoje={HOJE} podeEditar={false} />);
    expect((await screen.findAllByText("sem protocolo SIGA")).length).toBe(2);
    expect(screen.queryByRole("link", { name: /Registrar o número/ })).toBeNull();
    expect(screen.getAllByText("sem protocolo SIGA").some(x => x.closest("a"))).toBe(false);
  });

  it("diretoria vê o número do órgão sem o formulário de registrar (B-09, 10/10/2026)", async () => {
    api.mockResolvedValue([linha({ familia: "sinfra", orgao: "SINFRA", numero_orgao: "SEI 123" })]);
    render(<AguardandoPagamento hoje={HOJE} />);
    const painel = await screen.findByRole("complementary", { name: "Detalhe da nota" });
    expect(within(painel).getByText("SEI 123")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Registrar" })).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("sem notas, mostra o estado vazio", async () => {
    api.mockResolvedValue([]);
    render(<AguardandoPagamento hoje={HOJE} />);
    expect(await screen.findByText("Nenhuma nota esperando pagamento.")).toBeTruthy();
  });

  it("em tela estreita (até 1180 px), escolher uma nota rola até o painel; em tela larga, não", async () => {
    api.mockResolvedValue(cinco());
    const rolar = vi.fn();
    Element.prototype.scrollIntoView = rolar;
    window.matchMedia = ((q: string) => ({ matches: q === "(max-width: 1180px)" })) as unknown as typeof window.matchMedia;
    render(<AguardandoPagamento hoje={HOJE} />);
    fireEvent.click(await screen.findByRole("row", { name: /MT-402/ }));
    expect(rolar).toHaveBeenCalledTimes(1);
    window.matchMedia = (() => ({ matches: false })) as unknown as typeof window.matchMedia;
    fireEvent.click(screen.getByRole("row", { name: /Leblon/ }));
    expect(rolar).toHaveBeenCalledTimes(1);
  });
});
