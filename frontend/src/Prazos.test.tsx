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
});
