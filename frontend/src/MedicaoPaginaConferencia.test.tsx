// issue #384: a conferencia da revisao pendente na pagina, com o CartaoPlanilha de verdade (Espelho, Frc e Notas falsos)
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Usuario } from "./Login";
import MedicaoPagina from "./MedicaoPagina";

const { api, apiForm } = vi.hoisted(() => ({ api: vi.fn(), apiForm: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api, apiForm }));
vi.mock("./Espelho", () => ({ default: ({ parte }: { parte?: string }) => <div data-espelho={parte} /> }));
vi.mock("./Frc", () => ({ FrcConsorcio: () => <div /> }));
vi.mock("./Notas", () => ({ Notas: () => <div /> }));

const usuario = { id: 1, nome: "X", email: "x@x", perfil: "admin" } as Usuario;
const MED = { id: 5, numero: 4, tipo: "execucao", competencia: "2026-08", estado: "planilha_gerada",
  valor_protocolado_centavos: 1000000, valor_protocolado_origem: null, valor_atestado_centavos: null,
  valor_atestado_origem: null, atestado_em: null, nf_emitida_em: null, recebida_em: null, congelada: 0,
  protocolos: [], notas: [], documentos: [] };
const V1 = { id: 31, versao: 1, periodo_inicio: "2026-08-01", periodo_fim: "2026-08-31", valor_pedido_centavos: 1234567,
  acumulado_anterior_centavos: 0, motivo: null, criado_em: "2026-09-01 12:00:00", usuario: "Op" };
let estado = "planilha_gerada";
const det = () => ({ id: 5, contrato_id: 1, numero: 4, tipo: "execucao", competencia: "2026-08", estado,
  planilha_enviada_em: estado === "planilha_enviada" ? "2026-09-02" : null, planilha_envio_origem: estado === "planilha_enviada" ? "externo" : null,
  planilhas: [V1], planilha_siga: null,
  envio_planilha: { disponivel: estado === "planilha_gerada", motivo: null,
    envios: estado === "planilha_enviada" ? [{ planilha_id: 31, versao: 1, numero_oficio: null, enviado_em: "2026-09-02", usuario: null, origem: "externo" }] : [],
    reserva: null, pecas: [], pecas_do_orgao: [] } });
function responder(travarReleitura = false) {
  let leituras = 0;
  api.mockImplementation(async (url: string) => {
    if (url.endsWith("/cabecalho")) return { obra: "H", orgao: "SES", instrumento: "CT", percentual_lotufo_bp: 10000 };
    if (url === "/api/contratos/1/medicoes") return [{ ...MED, estado }];
    if (url === "/api/contratos/1/espelho") return { espelhos: [], regra: { situacao: "ativa" } };
    if (url.startsWith("/api/medicoes/andamento")) return [];
    if (url === "/api/medicoes/5") {
      if (travarReleitura && estado === "planilha_enviada" && ++leituras > 1) return new Promise(() => {});
      return det();
    }
    if (url === "/api/contratos/1/protocolos") return { familia: "ses", etapas: [], pecas: [], medicoes: [], protocolos: [] };
    if (url === "/api/notas/a-enviar") return { envios: [], contadores: {} };
    return {};
  });
  apiForm.mockImplementation(async () => { estado = "planilha_enviada"; return { ok: true }; });
  return () => leituras;
}
async function enviarPorFora() {
  fireEvent.click(await screen.findByRole("button", { name: "Registrar envio por fora" }));
  fireEvent.change(screen.getByLabelText("Meio"), { target: { value: "Outlook" } });
  fireEvent.click(screen.getByRole("button", { name: "Registrar envio" }));
}

describe("Página da medição: conferência da revisão pendente (cartão real)", () => {
  afterEach(() => { cleanup(); api.mockReset(); apiForm.mockReset(); estado = "planilha_gerada"; });
    it("gerada -> enviada pelo cartao: o espelho aparece depois da conferencia", async () => {
    window.history.replaceState(null, "", "/obras/1/medicoes/5");
    responder();
    const { container } = render(<MedicaoPagina contratoId={1} medicaoId={5} usuario={usuario} origem={null} />);
    await enviarPorFora();
    await waitFor(() => expect(container.querySelector("[data-espelho='espelho']")).not.toBeNull(), { timeout: 3000 });
  });
    it("gerada -> enviada: enquanto o cartao rele, o espelho nao aparece", async () => {
    window.history.replaceState(null, "", "/obras/1/medicoes/5");
    const leituras = responder(true);
    const { container } = render(<MedicaoPagina contratoId={1} medicaoId={5} usuario={usuario} origem={null} />);
    await enviarPorFora();
    await waitFor(() => expect(leituras()).toBeGreaterThanOrEqual(2));
    await new Promise(r => setTimeout(r, 50));
    expect(container.querySelector("[data-espelho]")).toBeNull();
  });
});
