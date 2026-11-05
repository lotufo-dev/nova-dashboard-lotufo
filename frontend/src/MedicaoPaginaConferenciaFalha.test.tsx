// issue #384: Tentar de novo e releitura que falha depois de gravar, com o CartaoPlanilha de verdade
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Usuario } from "./Login";
import MedicaoPagina from "./MedicaoPagina";

const { api, apiForm } = vi.hoisted(() => ({ api: vi.fn(), apiForm: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api, apiForm }));
vi.mock("./Espelho", () => ({ default: ({ parte }: { parte?: string }) => <div data-espelho={parte} /> }));
vi.mock("./Frc", () => ({ FrcConsorcio: () => <div /> }));
vi.mock("./Notas", () => ({ Notas: () => <div /> }));

const usuario = { id: 1, nome: "X", email: "x@x", perfil: "admin" } as Usuario;
const MED = { id: 5, numero: 4, tipo: "execucao", competencia: "2026-08", estado: "planilha_enviada",
  valor_protocolado_centavos: 1000000, valor_protocolado_origem: null, valor_atestado_centavos: null,
  valor_atestado_origem: null, atestado_em: null, nf_emitida_em: null, recebida_em: null, congelada: 0,
  protocolos: [], notas: [], documentos: [] };
const V1 = { id: 31, versao: 1, periodo_inicio: "2026-08-01", periodo_fim: "2026-08-31", valor_pedido_centavos: 1234567,
  acumulado_anterior_centavos: 0, motivo: null as string | null, criado_em: "2026-09-01 12:00:00", usuario: "Op" };
let versoes = [V1];
const det = () => ({ id: 5, contrato_id: 1, numero: 4, tipo: "execucao", competencia: "2026-08", estado: "planilha_enviada",
  planilha_enviada_em: "2026-09-02", planilha_envio_origem: "externo", planilhas: versoes, planilha_siga: null,
  envio_planilha: { disponivel: versoes.length > 1, motivo: null,
    envios: [{ planilha_id: 31, versao: 1, numero_oficio: null, enviado_em: "2026-09-02", usuario: null, origem: "externo" }],
    reserva: null, pecas: [], pecas_do_orgao: [] } });
function responder(falhaDetalhe: (n: number) => boolean) {
  let n = 0;
  api.mockImplementation(async (url: string) => {
    if (url.endsWith("/cabecalho")) return { obra: "H", orgao: "SES", instrumento: "CT", percentual_lotufo_bp: 10000 };
    if (url === "/api/contratos/1/medicoes") return [MED];
    if (url === "/api/contratos/1/espelho") return { espelhos: [], regra: { situacao: "ativa" } };
    if (url.startsWith("/api/medicoes/andamento")) return [];
    if (url.includes("/planilhas/avisos")) return { avisos: [] };
    if (url === "/api/medicoes/5") { n += 1; if (falhaDetalhe(n)) throw new Error("rede"); return det(); }
    if (url === "/api/contratos/1/protocolos") return { familia: "ses", etapas: [], pecas: [], medicoes: [], protocolos: [] };
    if (url === "/api/notas/a-enviar") return { envios: [], contadores: {} };
    return {};
  });
}

describe("Página da medição: falhas na conferência da revisão (cartão real)", () => {
  afterEach(() => { cleanup(); api.mockReset(); apiForm.mockReset(); versoes = [V1]; });

  it("cartao real: falha na 1a leitura, Tentar de novo rele e o espelho aparece", async () => {
    window.history.replaceState(null, "", "/obras/1/medicoes/5");
    responder(n => n === 1);
    const { container } = render(<MedicaoPagina contratoId={1} medicaoId={5} usuario={usuario} origem={null} />);
    fireEvent.click(await screen.findByRole("button", { name: "Tentar de novo" }));
    await waitFor(() => expect(container.querySelector("[data-espelho='espelho']")).not.toBeNull(), { timeout: 3000 });
  });

  it("revisão registrada e a releitura falha: o espelho some e a tela avisa que não conseguiu conferir", async () => {
    window.history.replaceState(null, "", "/obras/1/medicoes/5");
    responder(n => n >= 2);
    apiForm.mockImplementation(async () => { versoes = [V1, { ...V1, id: 32, versao: 2, motivo: "Rev01" }]; return { ok: true }; });
    const { container } = render(<MedicaoPagina contratoId={1} medicaoId={5} usuario={usuario} origem={null} />);
    await waitFor(() => expect(container.querySelector("[data-espelho='espelho']")).not.toBeNull());
    fireEvent.click(await screen.findByRole("button", { name: "Registrar revisão" }));
    const form = screen.getByRole("form", { name: "Registrar revisão Rev01" });
    fireEvent.change(within(form).getByLabelText("Motivo (obrigatório)"), { target: { value: "Ajuste no item 3" } });
    fireEvent.change(within(form).getByLabelText("Ofício assinado (PDF)"), { target: { files: [new File(["%PDF-1.4"], "o.pdf", { type: "application/pdf" })] } });
    fireEvent.change(within(form).getByLabelText("Planilha (.xlsx ou PDF)"), { target: { files: [new File(["PK"], "p.xlsx")] } });
    fireEvent.click(within(form).getByRole("button", { name: "Registrar revisão" }));
    expect(await screen.findByText("Revisão registrada.")).toBeTruthy();
    expect(await screen.findByText(/Não foi possível conferir a planilha\/carta/)).toBeTruthy();
    expect(container.querySelector("[data-espelho]")).toBeNull();
  });
});
