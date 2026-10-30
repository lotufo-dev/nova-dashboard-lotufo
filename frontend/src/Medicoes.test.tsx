import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Medicoes from "./Medicoes";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

const medicao = (extra: Record<string, unknown> = {}) => ({
  id: 70, numero: 7, tipo: "execucao", competencia: "2026-09", estado: "nota_emitida", valor_protocolado_centavos: 100,
  valor_protocolado_origem: null, valor_atestado_centavos: null, valor_atestado_origem: null, atestado_em: null,
  nf_emitida_em: null, recebida_em: null, congelada: 0, protocolos: [], notas: [], ...extra });

function responder(rm: { configurado: boolean; ultima_sincronizacao: string | null; ultimo_erro: string | null }) {
  api.mockImplementation(async (url: string) => {
    if (url.startsWith("/api/medicoes/andamento")) return [{ id: 70, proximo_passo: "protocolar", desde: "2026-10-01" }];
    if (url === "/api/rm/status") return rm;
    return [medicao(), medicao({ id: 60, numero: 6, estado: "recebida", recebida_em: "2026-09-20",
      notas: [{ nota_id: 1, numero: "0002322", serie: null, emissao: null, valor_centavos: 1, coligada: 1,
        recebido_centavos: 1, recebido_em: null, origem: "rm", regra: null }] })];
  });
}

// texto na tela (26/10/2026): sem contador ao lado dos titulos, sem "desde" nem carimbo de sincronizacao do RM
describe("Medições da obra", () => {
  afterEach(() => { cleanup(); api.mockReset(); });

  it("sem frase de apoio: contador, 'desde' e sincronização do RM saem; a coluna Notas traz os números", async () => {
    responder({ configurado: true, ultima_sincronizacao: "2026-10-26T08:00:00-04:00", ultimo_erro: null });
    render(<Medicoes contratoId={3} busca={{}} />);
    expect(await screen.findByRole("heading", { name: "Em andamento" })).toBeTruthy();
    expect(screen.getByText("Enviar a nota")).toBeTruthy();
    expect(screen.queryByText(/desde|sincronizado|1 medição|recebidas, canceladas/)).toBeNull();
    expect(screen.queryByText(/Sincronização com o RM falhou/)).toBeNull();
    expect(screen.getByText("NF 2322")).toBeTruthy();
  });

  it("a falha da última sincronização do RM vira selo, só quando acontece", async () => {
    responder({ configurado: true, ultima_sincronizacao: null, ultimo_erro: "tempo esgotado" });
    render(<Medicoes contratoId={3} busca={{}} />);
    const selo = await screen.findByText("Sincronização com o RM falhou");
    expect(selo.closest(".selo")?.className).toContain("selo--atencao");
  });
});
