import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Prazos from "./Prazos";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

const situacao = (extra: Record<string, unknown> = {}) => ({
  execucao_fim: "2026-12-31", dias_execucao: 66, vigencia_fim: "2027-01-31", dias_vigencia: 97, vigencia_automatica: true,
  folga: { exigida: 30, real: 31, quebrada: false }, paralisacao: null, pedido: null, endosso: null, encerramento: null,
  instrumentos: [], ...extra });

// texto na tela (26/10/2026): data, valor e selo; quanto falta, a regra do orgao e as contagens sairam
describe("Prazos", () => {
  afterEach(() => { cleanup(); api.mockReset(); });

  it("prazo em dia: só as datas, sem \"faltam N dias\" nem a regra da vigência", async () => {
    api.mockResolvedValue({ situacao: situacao(), historico: "", pleitos: [] });
    render(<Prazos contratoId={1} podeEditar={false} />);
    expect(await screen.findByText("31/12/2026")).toBeTruthy();
    expect(screen.queryByText(/faltam|vencida/)).toBeNull();
    expect(screen.queryByText(/prorroga a vigência junto|o órgão pede/)).toBeNull();
    expect(screen.queryByText(/nenhum ofício ainda/)).toBeNull();
    expect(screen.getByRole("link", { name: "Abrir os instrumentos" })).toBeTruthy();
  });

  it("prazo vencido vira selo, só quando vence", async () => {
    api.mockResolvedValue({ situacao: situacao({ dias_execucao: -5 }), historico: "", pleitos: [] });
    render(<Prazos contratoId={1} podeEditar={false} />);
    expect(await screen.findByText("vencida")).toBeTruthy();
    expect(screen.getAllByText("vencida")).toHaveLength(1);    // a vigencia segue em dia
  });

  it("prazo perto do fim vira selo com os dias, nos limites do aviso (60 em Atenção, 30 em Crítico)", async () => {
    api.mockResolvedValue({ situacao: situacao({ dias_execucao: 45, dias_vigencia: 10, vigencia_automatica: false }), historico: "", pleitos: [] });
    render(<Prazos contratoId={1} podeEditar={false} />);
    expect((await screen.findByText("vence em 45 dias")).closest(".selo")?.className).toContain("selo--atencao");
    expect(screen.getByText("vence em 10 dias").closest(".selo")?.className).toContain("selo--acao");
  });

  it("vigência que o órgão prorroga junto e obra em encerramento não levam selo (o servidor não avisa)", async () => {
    api.mockResolvedValue({ situacao: situacao({ dias_vigencia: -10 }), historico: "", pleitos: [] });
    const r = render(<Prazos contratoId={1} podeEditar={false} />);
    expect(await screen.findByText("31/01/2027")).toBeTruthy();
    expect(screen.queryByText(/vencida|vence /)).toBeNull();
    r.unmount();
    api.mockResolvedValue({ situacao: situacao({ dias_execucao: -5, vigencia_automatica: false, dias_vigencia: -5,
      encerramento: { desde: "2026-10-01", marcos: {}, conclusao_comunicada: false } }), historico: "", pleitos: [] });
    render(<Prazos contratoId={1} podeEditar={false} />);
    expect(await screen.findByText("31/01/2027")).toBeTruthy();
    expect(screen.queryByText(/vencida|vence /)).toBeNull();
  });

  it("obra paralisada não leva selo de vencimento da execução (D16)", async () => {
    api.mockResolvedValue({ situacao: situacao({ dias_execucao: -5, paralisacao: { desde: "2026-09-01", numero: null } }),
      historico: "", pleitos: [] });
    render(<Prazos contratoId={1} podeEditar={false} />);
    expect(await screen.findByText(/paralisada desde/)).toBeTruthy();
    expect(screen.queryByText("vencida")).toBeNull();
  });

  // issue #292: a carta de prazo sugere os dias pelo ritmo dos ultimos 6 meses; a pessoa confirma ou muda
  const sugestao = (extra: Record<string, unknown> = {}) => ({
    saldo_centavos: 20000000, medido_periodo_centavos: 30000001, ritmo_centavos: 5000000, meses: 6, de: "2026-04",
    ate: "2026-09", execucao_fim: "2026-10-20", novo_fim: "2027-02-15", dias: 123, motivo: null, ...extra });

  it("pedir prorrogação mostra a sugestão com a conta e o campo de dias preenchido e editável", async () => {
    api.mockResolvedValue({ situacao: situacao(), historico: "", sugestao: sugestao(), pleitos: [] });
    render(<Prazos contratoId={1} podeEditar={true} />);
    fireEvent.click(await screen.findByRole("button", { name: "Pedir prorrogação" }));
    expect(screen.getByText(/^Sugestão: 123 dias \(saldo R\$\s200\.000,00, ritmo R\$\s50\.000,00\/mês de 04\/2026 a 09\/2026\)$/)).toBeTruthy();
    // a conta cabe numa linha: sem frase de apoio explicando a regra (texto-na-tela.md)
    expect(screen.queryByText(/Confira e mude|contado a partir/)).toBeNull();
    const campo = screen.getByLabelText("Dias de prorrogação") as HTMLInputElement;
    expect(campo.value).toBe("123");
    fireEvent.change(campo, { target: { value: "150" } });
    expect(campo.value).toBe("150");
  });

  it("obra sem medição recente não sugere, diz por quê e deixa o campo vazio", async () => {
    const motivo = "Sem medição de execução de 04/2026 a 09/2026: sem ritmo para sugerir os dias.";
    api.mockResolvedValue({ situacao: situacao(), historico: "",
      sugestao: sugestao({ dias: null, ritmo_centavos: null, medido_periodo_centavos: 0, novo_fim: null, motivo }), pleitos: [] });
    render(<Prazos contratoId={1} podeEditar={true} />);
    fireEvent.click(await screen.findByRole("button", { name: "Pedir prorrogação" }));
    expect(screen.getByText(`Sem sugestão de dias. ${motivo}`)).toBeTruthy();
    expect(screen.queryByText(/^Sugestão:/)).toBeNull();
    expect((screen.getByLabelText("Dias de prorrogação") as HTMLInputElement).value).toBe("");
  });

  it("sugestão de 1 dia no singular, e o campo tem o teto do pedido", async () => {
    api.mockResolvedValue({ situacao: situacao(), historico: "", sugestao: sugestao({ dias: 1 }), pleitos: [] });
    render(<Prazos contratoId={1} podeEditar={true} />);
    fireEvent.click(await screen.findByRole("button", { name: "Pedir prorrogação" }));
    expect(screen.getByText(/^Sugestão: 1 dia \(/)).toBeTruthy();
    expect((screen.getByLabelText("Dias de prorrogação") as HTMLInputElement).max).toBe("3650");
  });
});
