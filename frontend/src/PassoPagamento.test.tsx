import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Usuario } from "./Login";
import type { Medicao } from "./Medicoes";
import PassoPagamento, { aReceber, diasEntre } from "./PassoPagamento";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

// bruto = valor nominal da NF; devido = os titulos do RM (liquidos, sem as retencoes); falta = titulo a titulo (servidor)
const nota = (nota_id: number, numero: string, bruto: number, devido: number, recebido = 0, extra: Record<string, unknown> = {}) => ({
  nota_id, coligada: 1, numero, serie: null, emissao: "2026-11-13", valor_centavos: bruto, recebido_centavos: recebido,
  devido_centavos: devido, falta_centavos: Math.max(0, devido - recebido), da_lotufo: true, recebido_em: null, origem: "rm", regra: null, ...extra });
// dados ficticios: consorcio com tres empresas, a Lotufo emite duas notas (Cuiaba e Varzea Grande), com retencao
const MEDICAO = { id: 5, numero: 16, tipo: "execucao", competencia: "2026-10", estado: "protocolada",
  valor_protocolado_centavos: 990529648, valor_protocolado_origem: null, valor_atestado_centavos: 990529648,
  valor_atestado_origem: null, atestado_em: null, nf_emitida_em: null, recebida_em: null, congelada: 1,
  protocolos: [{ id: 9, data: "2026-11-14", numero_oficio: null, numero_processo: "PROC-0001", origem: "manual", protocolo_id: null }],
  notas: [nota(1, "2351", 418330386, 384863955), nota(2, "2352", 67032113, 61669545)], notas_faltam: 0, documentos: [] } as unknown as Medicao;
const admin = { id: 1, nome: "Operação", email: "o@x", perfil: "admin" } as Usuario;
const aqui = { tela: "medicao" as const, obra: 1, id: 5 };
const com = (notas: unknown[], extra: Record<string, unknown> = {}) => ({ ...MEDICAO, notas, ...extra }) as unknown as Medicao;

function montar(extra: Partial<Parameters<typeof PassoPagamento>[0]> = {}) {
  const props = { grupo: [MEDICAO], junta: false, usuario: admin, protocolos: [], aqui, percentualBp: 4900, aoReceber: vi.fn(), ...extra };
  render(<PassoPagamento {...props} />);
  return props;
}

describe("Passo Pagamento (#514)", () => {
  beforeEach(() => { vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(new Date("2026-11-22T15:00:00Z")); api.mockResolvedValue({ processos: [] }); });
  afterEach(() => { cleanup(); api.mockReset(); vi.useRealTimers(); });

  it("em consórcio: a receber é o que falta dos títulos das notas da Lotufo, ao lado do total cheio e dos dias aguardando", () => {
    montar();
    expect(screen.getByText("A receber · cota da Lotufo")).toBeTruthy();
    expect(screen.getByLabelText("A receber: R$ 4.465.335,00")).toBeTruthy();       // 3.848.639,55 + 616.695,45
    expect(screen.getByText("R$ 9.905.296,48")).toBeTruthy();
    expect(screen.getByText(/^8\sdias$/)).toBeTruthy();
    expect(screen.getByText("nota enviada em 14/11/2026")).toBeTruthy();
    expect(screen.getByText("R$ 0,00 recebido de R$ 4.465.335,00")).toBeTruthy();
    // a NF aparece pelo valor nominal (bruto)
    expect(screen.getByText("R$ 4.183.303,86")).toBeTruthy();
    expect(screen.getAllByText("em aberto")).toHaveLength(2);
  });

  it("título com retenção baixado inteiro: a nota fica “paga” e a receber é R$ 0,00 (revisor e Sol, PR #555)", () => {
    // NF de R$ 1.000,01 com R$ 76,00 de retencao: titulo de R$ 924,01 baixado inteiro
    montar({ grupo: [com([nota(1, "2351", 100001, 92401, 92401)], { valor_atestado_centavos: 100001 })], percentualBp: 10000 });
    expect(screen.getByLabelText("A receber: R$ 0,00")).toBeTruthy();
    expect(screen.getByText("paga")).toBeTruthy();
    expect(screen.queryByText("paga em parte")).toBeNull();
    expect(screen.getByText("100%")).toBeTruthy();
  });

  it("juros num título não cobrem o outro aberto: a barra usa o recebido título a título (Sol, rodada 2)", () => {
    // dois titulos de R$ 100,00: um recebeu R$ 110,00 (juros), o outro R$ 90,00 -> falta R$ 10,00
    const n = nota(1, "2351", 21739, 20000, 20000, { falta_centavos: 1000 });
    montar({ grupo: [com([n], { valor_atestado_centavos: 21739 })], percentualBp: 10000 });
    expect(screen.getByLabelText("A receber: R$ 10,00")).toBeTruthy();
    expect(screen.getByText("R$ 190,00 recebido de R$ 200,00")).toBeTruthy();
    expect(screen.getByText("95%")).toBeTruthy();
    expect(screen.getByText("paga em parte")).toBeTruthy();
  });

  it("consórcio com uma das notas municipais da Lotufo ainda sem casar: a cota fica “—” (Sol, rodada 2)", () => {
    montar({ grupo: [com([nota(1, "2351", 418330386, 384863955)], { notas_faltam: 1 })] });
    expect(screen.getByText("A receber · cota da Lotufo")).toBeTruthy();
    expect(screen.getByLabelText("A receber: —")).toBeTruthy();
    expect(screen.queryByText(/recebido de/)).toBeNull();
    expect(screen.queryByText(/%$/)).toBeNull();
  });

  it("cabeçalho ainda não lido, com as notas completas: “—” (sem saber se é consórcio, nada se confere) (revisor e Sol, rodada 2)", () => {
    montar({ percentualBp: null });
    expect(screen.getByLabelText("A receber: —")).toBeTruthy();
  });

  it("nota sem título ao lado de outra já paga: a receber “—”, mas o selo diz que já houve recebimento (Sol, rodada 2)", () => {
    montar({ grupo: [com([nota(1, "2351", 418330386, 384863955, 384863955), nota(2, "2352", 67032113, 0)])] });
    expect(screen.getByLabelText("A receber: —")).toBeTruthy();
    expect(screen.getByText("Recebido em parte")).toBeTruthy();
    expect(screen.queryByText("Aguardando o órgão")).toBeNull();
  });

  it("consórcio com a fatura integral do consórcio e a nota da Lotufo: só a da Lotufo entra na cota (Sol, PR #555)", () => {
    const fatura = nota(3, "21", 990529648, 911287276, 0, { coligada: 90, da_lotufo: false });
    montar({ grupo: [com([fatura, nota(1, "2351", 400000001, 368000001)])] });
    expect(screen.getByLabelText("A receber: R$ 3.680.000,01")).toBeTruthy();
    expect(screen.getByText(/fatura do consórcio/)).toBeTruthy();
  });

  it("nota sem título no RM: a linha mostra “—” e a receber fica “—”", () => {
    montar({ grupo: [com([nota(1, "2351", 418330386, 0), nota(2, "2352", 67032113, 61669545)])] });
    expect(screen.getByLabelText("A receber: —")).toBeTruthy();
    expect(screen.getAllByText("em aberto")).toHaveLength(1);
  });

  it("obra só da Lotufo: o rótulo não fala de cota", () => {
    montar({ percentualBp: 10000, grupo: [com([nota(1, "2351", 990529648, 911287276)])] });
    expect(screen.getByText("A receber")).toBeTruthy();
    expect(screen.queryByText(/cota/)).toBeNull();
    expect(screen.getByLabelText("A receber: R$ 9.112.872,76")).toBeTruthy();
  });

  it("recebimento em parte: o que falta é título a título, centavo a centavo", () => {
    montar({ grupo: [com([nota(1, "2351", 418330386, 384863955, 384863955), nota(2, "2352", 67032113, 61669545, 1)])] });
    expect(screen.getByLabelText("A receber: R$ 616.695,44")).toBeTruthy();
    expect(screen.getByText("paga")).toBeTruthy();
    expect(screen.getByText("paga em parte")).toBeTruthy();
    expect(screen.getByText("Recebido em parte")).toBeTruthy();
  });

  it("processo no órgão: o nº e a data do envio; o admin registra o recebimento à mão", () => {
    const props = montar();
    const proc = screen.getByRole("region", { name: "Processo no órgão" });
    expect(within(proc).getByText("PROC-0001")).toBeTruthy();
    expect(within(proc).getByText("14/11/2026")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Registrar recebimento" }));
    expect(props.aoReceber).toHaveBeenCalledWith(MEDICAO);
  });

  it("cabeçalho ainda não lido: sem nota, nada de mostrar o cheio como da Lotufo (code-review)", () => {
    montar({ grupo: [com([])], percentualBp: null });
    expect(screen.getByText("A receber")).toBeTruthy();
    expect(screen.getByLabelText("A receber: —")).toBeTruthy();
  });

  it("a engenharia não vê o botão de recebimento (sem botão no passo)", () => {
    montar({ usuario: { ...admin, perfil: "engenharia" } });
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("contas do pagamento", () => {
  it("dias corridos entre datas puras, sem fuso", () => {
    expect(diasEntre("2026-11-14", "2026-11-22")).toBe(8);
    expect(diasEntre("2026-02-28", "2026-03-01")).toBe(1);
    expect(diasEntre("x", "2026-03-01")).toBeNull();
  });

  it("medição sem nota da Lotufo ainda: a receber não se sabe (—), em consórcio ou não", () => {
    expect(aReceber([com([])], true).falta).toBeNull();
    expect(aReceber([com([])], false).falta).toBeNull();
  });

  it("par com uma metade ainda sem nota: “—” (code-review)", () => {
    const paga = com([nota(1, "2351", 100001, 92401, 92401)], { valor_atestado_centavos: 100001 });
    const semNota = com([], { id: 6, tipo: "reajuste" });
    expect(aReceber([paga, semNota], false).falta).toBeNull();
    expect(aReceber([paga, semNota], true).falta).toBeNull();
  });

  it("obra própria com só uma das notas casada (as notas não fecham com o valor da medição): “—” (revisor, PR #555)", () => {
    const metade = com([nota(1, "2351", 418330386, 384863955)]);       // medicao de 9.905.296,48
    expect(aReceber([metade], false).falta).toBeNull();
    const inteira = com([nota(1, "2351", 990529647, 911287276), nota(2, "2352", 1, 1)]);
    expect(aReceber([inteira], false)).toEqual({ falta: 911287277, recebido: 0, total: 911287277, algumRecebido: false });
  });

  it("detalhe sem a contagem das notas que faltam (servidor antigo) não soma: “—”", () => {
    expect(aReceber([com(MEDICAO.notas!, { notas_faltam: undefined })], true).falta).toBeNull();
    expect(aReceber([MEDICAO], null).falta).toBeNull();
    expect(aReceber([MEDICAO], true).falta).toBe(446533500);
  });
});
