import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Usuario } from "./Login";
import type { Medicao } from "./Medicoes";
import PassoPagamento, { aReceber, diasEntre } from "./PassoPagamento";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

const nota = (nota_id: number, numero: string, valor: number, recebido = 0) => ({ nota_id, coligada: 1, numero, serie: null,
  emissao: "2026-11-13", valor_centavos: valor, recebido_centavos: recebido, recebido_em: null, origem: "rm", regra: null });
// dados ficticios: consorcio com tres empresas, a Lotufo emite duas notas (Cuiaba e Varzea Grande)
const MEDICAO = { id: 5, numero: 16, tipo: "execucao", competencia: "2026-10", estado: "protocolada",
  valor_protocolado_centavos: 990529648, valor_protocolado_origem: null, valor_atestado_centavos: 990529648,
  valor_atestado_origem: null, atestado_em: null, nf_emitida_em: null, recebida_em: null, congelada: 1,
  protocolos: [{ id: 9, data: "2026-11-14", numero_oficio: null, numero_processo: "PROC-0001", origem: "manual", protocolo_id: null }],
  notas: [nota(1, "2351", 418330386), nota(2, "2352", 67032113)], documentos: [] } as unknown as Medicao;
const admin = { id: 1, nome: "Operação", email: "o@x", perfil: "admin" } as Usuario;
const aqui = { tela: "medicao" as const, obra: 1, id: 5 };

function montar(extra: Partial<Parameters<typeof PassoPagamento>[0]> = {}) {
  const props = { grupo: [MEDICAO], junta: false, usuario: admin, protocolos: [], aqui, percentualBp: 4900, aoReceber: vi.fn(), ...extra };
  render(<PassoPagamento {...props} />);
  return props;
}

describe("Passo Pagamento (#514)", () => {
  beforeEach(() => { vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(new Date("2026-11-22T15:00:00Z")); api.mockResolvedValue({ processos: [] }); });
  afterEach(() => { cleanup(); api.mockReset(); vi.useRealTimers(); });

  it("em consórcio: a receber é a cota da Lotufo (as notas dela), ao lado do total da medição e dos dias aguardando", () => {
    montar();
    expect(screen.getByText("A receber · cota da Lotufo")).toBeTruthy();
    expect(screen.getByLabelText("A receber: R$ 4.853.624,99")).toBeTruthy();
    expect(screen.getByText("R$ 9.905.296,48")).toBeTruthy();
    expect(screen.getByText(/^8\sdias$/)).toBeTruthy();
    expect(screen.getByText("nota enviada em 14/11/2026")).toBeTruthy();
    expect(screen.getByText("R$ 0,00 recebido de R$ 4.853.624,99")).toBeTruthy();
    expect(screen.getAllByText("em aberto")).toHaveLength(2);
  });

  it("obra só da Lotufo: o rótulo não fala de cota", () => {
    montar({ percentualBp: 10000 });
    expect(screen.getByText("A receber")).toBeTruthy();
    expect(screen.queryByText(/cota/)).toBeNull();
  });

  it("recebimento em parte: o que falta desconta o recebido, centavo a centavo", () => {
    const parcial = { ...MEDICAO, notas: [nota(1, "2351", 418330386, 418330386), nota(2, "2352", 67032113, 1)] } as Medicao;
    montar({ grupo: [parcial] });
    expect(screen.getByLabelText("A receber: R$ 670.321,12")).toBeTruthy();
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
  it("consórcio sem nota ainda: a cota não se sabe (—); obra própria usa o valor cheio", () => {
    const sem = { ...MEDICAO, notas: [] } as unknown as Medicao;
    expect(aReceber([sem], true).falta).toBeNull();
    expect(aReceber([sem], false).falta).toBe(990529648);
  });
});
