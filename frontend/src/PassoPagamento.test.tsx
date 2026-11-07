import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Usuario } from "./Login";
import type { Medicao } from "./Medicoes";
import PassoPagamento, { aReceber, diasEntre } from "./PassoPagamento";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

// bruto = valor nominal da NF; devido = os titulos do RM (liquidos); falta = titulo a titulo (servidor)
const nota = (nota_id: number, numero: string, bruto: number, devido: number, recebido = 0, extra: Record<string, unknown> = {}) => ({
  nota_id, coligada: 1, numero, serie: null, emissao: "2026-11-13", valor_centavos: bruto, recebido_centavos: recebido,
  devido_centavos: devido, falta_centavos: Math.max(0, devido - recebido), da_lotufo: true, da_cota: true, recebido_em: null,
  origem: "rm", regra: null, ...extra });
// o resumo pronto do servidor (sincronizacao_rm.pagamento_cota)
const cota = (total: number | null, recebido: number | null, falta: number | null, parcial = false, extra: Record<string, unknown> = {}) =>
  ({ notas_faltam: 0, completo: total !== null, total_centavos: total, recebido_centavos: recebido, falta_centavos: falta, parcial, ...extra });
// dados ficticios: consorcio com tres empresas, a Lotufo emite duas notas (Cuiaba e Varzea Grande), com retencao
const MEDICAO = { id: 5, numero: 16, tipo: "execucao", competencia: "2026-10", estado: "protocolada",
  valor_protocolado_centavos: 990529648, valor_protocolado_origem: null, valor_atestado_centavos: 990529648,
  valor_atestado_origem: null, atestado_em: null, nf_emitida_em: null, recebida_em: null, congelada: 1,
  protocolos: [{ id: 9, data: "2026-11-14", numero_oficio: null, numero_processo: "PROC-0001", origem: "manual", protocolo_id: null }],
  notas: [nota(1, "2351", 418330386, 384863955), nota(2, "2352", 67032113, 61669545)], notas_faltam: 0,
  pagamento_cota: cota(446533500, 0, 446533500), documentos: [] } as unknown as Medicao;
const admin = { id: 1, nome: "Operação", email: "o@x", perfil: "admin" } as Usuario;
const aqui = { tela: "medicao" as const, obra: 1, id: 5 };
const com = (extra: Record<string, unknown>) => ({ ...MEDICAO, ...extra }) as unknown as Medicao;

function montar(extra: Partial<Parameters<typeof PassoPagamento>[0]> = {}) {
  const props = { grupo: [MEDICAO], junta: false, usuario: admin, protocolos: [], aqui, percentualBp: 4900 as number | null,
    total: 990529648 as number | null, aoReceber: vi.fn(), ...extra };
  render(<PassoPagamento {...props} />);
  return props;
}

describe("Passo Pagamento (#514)", () => {
  beforeEach(() => { vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(new Date("2026-11-22T15:00:00Z")); api.mockResolvedValue({ processos: [] }); });
  afterEach(() => { cleanup(); api.mockReset(); vi.useRealTimers(); });

  it("em consórcio: exibe o resumo do servidor (a receber, recebido de, barra) ao lado do total cheio e dos dias aguardando", () => {
    montar();
    expect(screen.getByText("A receber · cota da Lotufo")).toBeTruthy();
    expect(screen.getByLabelText("A receber: R$ 4.465.335,00")).toBeTruthy();
    expect(screen.getByText("R$ 9.905.296,48")).toBeTruthy();
    expect(screen.getByText(/^8\sdias$/)).toBeTruthy();
    expect(screen.getByText("nota enviada em 14/11/2026")).toBeTruthy();
    expect(screen.getByText("R$ 0,00 recebido de R$ 4.465.335,00")).toBeTruthy();
    expect(screen.getByText("0%")).toBeTruthy();
    // a NF aparece pelo valor nominal (bruto); a situacao de cada nota continua na linha dela
    expect(screen.getByText("R$ 4.183.303,86")).toBeTruthy();
    expect(screen.getAllByText("em aberto")).toHaveLength(2);
    expect(screen.getByText("Aguardando o órgão")).toBeTruthy();
  });

  it("a tela não soma as notas: com notas que somariam outro valor, mostra o que o servidor mandou", () => {
    montar({ grupo: [com({ notas: [nota(1, "2351", 100, 100, 100), nota(9, "2399", 999, 999, 999, { da_cota: false })],
      pagamento_cota: cota(30001, 10000, 20001, true) })] });
    expect(screen.getByLabelText("A receber: R$ 200,01")).toBeTruthy();
    expect(screen.getByText("R$ 100,00 recebido de R$ 300,01")).toBeTruthy();
    expect(screen.getByText("33%")).toBeTruthy();
    expect(screen.getByText("Recebido em parte")).toBeTruthy();
  });

  it("resumo incompleto (nota faltando ou sem título): “—”, sem barra, com o “Recebido em parte” do servidor", () => {
    montar({ grupo: [com({ pagamento_cota: cota(null, null, null, true, { notas_faltam: 1 }) })] });
    expect(screen.getByLabelText("A receber: —")).toBeTruthy();
    expect(screen.queryByText(/recebido de/)).toBeNull();
    expect(screen.queryByText(/%$/)).toBeNull();
    expect(screen.getByText("Recebido em parte")).toBeTruthy();
  });

  it("sem espelho (resumo nulo): “—” e “Aguardando o órgão”", () => {
    montar({ grupo: [com({ pagamento_cota: null })] });
    expect(screen.getByLabelText("A receber: —")).toBeTruthy();
    expect(screen.getByText("Aguardando o órgão")).toBeTruthy();
  });

  it("parcial falso do servidor (nota extra paga, cota em aberto) não vira “Recebido em parte”", () => {
    montar({ grupo: [com({ notas: [...MEDICAO.notas!, nota(9, "2399", 12345, 11000, 11000, { da_cota: false })] })] });
    expect(screen.getByText("Aguardando o órgão")).toBeTruthy();
    expect(screen.queryByText("Recebido em parte")).toBeNull();
  });

  it("cota quitada nos títulos: a receber R$ 0,00, barra cheia e “Recebido”", () => {
    montar({ grupo: [com({ notas: [nota(1, "2351", 100001, 92401, 92401)], pagamento_cota: cota(92401, 92401, 0) })], percentualBp: 10000 });
    expect(screen.getByLabelText("A receber: R$ 0,00")).toBeTruthy();
    expect(screen.getByText("paga")).toBeTruthy();
    expect(screen.getByText("100%")).toBeTruthy();
    expect(screen.getByText("Recebido")).toBeTruthy();
  });

  it("nota sem título no RM: a linha mostra “—”; a nota de outra coligada é marcada na tabela, sem dizer que é a fatura", () => {
    montar({ grupo: [com({ notas: [nota(1, "2351", 418330386, 0), nota(3, "21", 990529648, 911287276, 0, { coligada: 90, da_lotufo: false, da_cota: false })],
      pagamento_cota: cota(null, null, null) })] });
    expect(screen.getByLabelText("A receber: —")).toBeTruthy();
    expect(screen.getByText(/outra coligada/)).toBeTruthy();
    expect(screen.queryByText(/fatura do consórcio/)).toBeNull();
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("espelho sem saída da Lotufo (cota zero, completa): A receber R$ 0,00, sem barra, sem “Recebido” nem “Aguardando o órgão”", () => {
    montar({ grupo: [com({ notas: [nota(3, "21", 990529648, 911287276, 911287276, { coligada: 90, da_lotufo: false, da_cota: false })],
      pagamento_cota: cota(0, 0, 0) })] });
    expect(screen.getByLabelText("A receber: R$ 0,00")).toBeTruthy();
    expect(screen.queryByText("Recebido")).toBeNull();
    expect(screen.queryByText("Aguardando o órgão")).toBeNull();
    expect(screen.queryByText("Recebido em parte")).toBeNull();
    expect(screen.queryByLabelText("Recebido")).toBeNull();          // sem barra
    expect(screen.getByText("paga")).toBeTruthy();                   // a situacao da nota continua na linha dela
  });

  it("par recebido em dias diferentes: “Recebida” com a data da última metade", () => {
    montar({ grupo: [com({ estado: "recebida", recebida_em: "2026-11-10T12:00:00", pagamento_cota: cota(100, 100, 0) }),
      com({ id: 6, tipo: "reajuste", estado: "recebida", recebida_em: "2026-11-20T12:00:00", notas: [], pagamento_cota: cota(100, 100, 0) })] });
    expect(screen.getByText("Recebida", { selector: "p" })).toBeTruthy();
    expect(screen.getByText("20/11/2026")).toBeTruthy();
    expect(screen.queryByText("10/11/2026")).toBeNull();
  });

  it("obra só da Lotufo e cabeçalho ainda não lido: o rótulo não fala de cota", () => {
    montar({ percentualBp: 10000 });
    expect(screen.getByText("A receber")).toBeTruthy();
    expect(screen.queryByText(/cota/)).toBeNull();
    cleanup();
    montar({ percentualBp: null });
    expect(screen.getByText("A receber")).toBeTruthy();
  });

  it("processo no órgão: o nº e a data do envio; o admin registra o recebimento à mão", () => {
    const props = montar();
    const proc = screen.getByRole("region", { name: "Processo no órgão" });
    expect(within(proc).getByText("PROC-0001")).toBeTruthy();
    expect(within(proc).getByText("14/11/2026")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Registrar recebimento" }));
    expect(props.aoReceber).toHaveBeenCalledWith(MEDICAO);
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

  it("aReceber só repassa o bloco do servidor; incompleto ou ausente vira null", () => {
    expect(aReceber([MEDICAO])).toEqual({ falta: 446533500, recebido: 0, total: 446533500, parcial: false, completo: true });
    expect(aReceber([com({ pagamento_cota: cota(null, null, null, true) })])).toEqual({ falta: null, recebido: null, total: null, parcial: true, completo: false });
    expect(aReceber([com({ pagamento_cota: cota(0, 0, 0) })])).toEqual({ falta: 0, recebido: 0, total: 0, parcial: false, completo: true });
    expect(aReceber([com({ pagamento_cota: undefined })]).falta).toBeNull();
    expect(aReceber([]).falta).toBeNull();
  });
});
