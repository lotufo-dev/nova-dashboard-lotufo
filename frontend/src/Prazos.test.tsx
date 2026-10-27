import { cleanup, render, screen } from "@testing-library/react";
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
});
