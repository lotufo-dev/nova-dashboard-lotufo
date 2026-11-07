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
const V2 = { ...V1, id: 32, versao: 2, motivo: "Rev01" };
const ENVIO1 = { planilha_id: 31, versao: 1, numero_oficio: null, enviado_em: "2026-09-02", usuario: null, origem: "externo" };
let versoes = [V1];
let envios = [ENVIO1];
const det = () => ({ id: 5, contrato_id: 1, numero: 4, tipo: "execucao", competencia: "2026-08", estado: "planilha_enviada",
  planilha_enviada_em: "2026-09-02", planilha_envio_origem: "externo", planilhas: versoes, planilha_siga: null,
  envio_planilha: { disponivel: versoes.length > 1, motivo: null,
    envios, reserva: null, pecas: [], pecas_do_orgao: [] } });
const PREVIA = { numero_oficio: "CT-301", versao: 2, para: ["protocolo@exemplo.com.br"], copia: [], assunto: "CT-301 - 4a Medicao",
  corpo: "Encaminho para protocolo.", anexos: [{ nome: "o.pdf", tamanho: 1200, sha256: "a".repeat(64) }], total: 1200, limite: 30_000_000, pendencias: [] };
let falhar = (_n: number) => false;
function responder(falhaDetalhe: (n: number) => boolean) {
  let n = 0;
  falhar = falhaDetalhe;
  api.mockImplementation(async (url: string, opts?: RequestInit) => {
    if (url.endsWith("/cabecalho")) return { obra: "H", orgao: "SES", instrumento: "CT", percentual_lotufo_bp: 10000 };
    if (url === "/api/contratos/1/medicoes") return [MED];
    if (url === "/api/contratos/1/espelho") return { espelhos: [], regra: { situacao: "ativa" } };
    if (url.startsWith("/api/medicoes/andamento")) return [];
    if (url.includes("/planilhas/avisos")) return { avisos: [] };
    if (url === "/api/medicoes/5") { n += 1; if (falhar(n)) throw new Error("rede"); return det(); }
    if (url === "/api/medicoes/5/envio-planilha/previa") return PREVIA;
    if (url === "/api/medicoes/5/envio-planilha" && opts?.method === "POST") return { envio_id: 1 };
    if (url === "/api/contratos/1/protocolos") return { familia: "ses", etapas: [], pecas: [], medicoes: [], protocolos: [] };
    if (url === "/api/notas/a-enviar") return { envios: [], contadores: {} };
    return {};
  });
}

/** O formulario da revisao (o do cartao no passo 1 ou o de "Pediu revisão" no passo 2). */
function preencherRevisao() {
  const form = screen.getByRole("form", { name: /^Registrar revisão Rev/ });
  fireEvent.change(within(form).getByLabelText("Motivo (obrigatório)"), { target: { value: "Ajuste no item 3" } });
  fireEvent.change(within(form).getByLabelText("Ofício assinado (PDF)"), { target: { files: [new File(["%PDF-1.4"], "o.pdf", { type: "application/pdf" })] } });
  fireEvent.change(within(form).getByLabelText("Planilha (.xlsx ou PDF)"), { target: { files: [new File(["PK"], "p.xlsx")] } });
  fireEvent.click(within(form).getByRole("button", { name: "Registrar revisão" }));
}
const semBoletim = () => screen.queryByRole("button", { name: "Gerar o espelho sem o boletim" });
const pagina = () => render(<MedicaoPagina contratoId={1} medicaoId={5} usuario={usuario} origem={null} />);

// #508: com a planilha/carta enviada a vez e' do passo 2; a pagina confere a revisao lendo o detalhe da medicao, e o
// cartao (passo 1) confere tambem quando aberto. O espelho sem o boletim so' se oferece com a conferencia certa.
describe("Página da medição: falhas na conferência da revisão (cartão real)", () => {
  afterEach(() => { cleanup(); api.mockReset(); apiForm.mockReset(); versoes = [V1]; envios = [ENVIO1]; });

  it("falha na 1a leitura: a tela avisa, Tentar de novo relê e o espelho sem o boletim aparece", async () => {
    window.history.replaceState(null, "", "/obras/1/medicoes/5");
    responder(n => n === 1);
    const { container } = pagina();
    expect(await screen.findByText(/Não foi possível conferir a planilha\/carta/)).toBeTruthy();
    expect(semBoletim()).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Tentar de novo" }));
    fireEvent.click(await screen.findByRole("button", { name: "Gerar o espelho sem o boletim" }, { timeout: 3000 }));
    expect(container.querySelector("[data-espelho='espelho']")).not.toBeNull();
  });

  it("“Pediu revisão” registrada e a releitura falha: o espelho some e a tela avisa que não conseguiu conferir", async () => {
    window.history.replaceState(null, "", "/obras/1/medicoes/5");
    responder(n => n >= 2);
    apiForm.mockImplementation(async () => { versoes = [V1, V2]; return { ok: true }; });
    pagina();
    await screen.findByRole("button", { name: "Gerar o espelho sem o boletim" });
    fireEvent.click(screen.getByRole("button", { name: /^Pediu revisão/ }));
    preencherRevisao();
    expect(await screen.findByText("Revisão registrada.")).toBeTruthy();
    expect(apiForm.mock.calls[0][0]).toBe("/api/medicoes/5/planilhas");
    expect(await screen.findByText(/Não foi possível conferir a planilha\/carta/)).toBeTruthy();
    expect(semBoletim()).toBeNull();
  });

  it("revisão registrada (releitura certa) devolve a vez ao passo 1; enviada por fora, a vez volta ao passo 2", async () => {
    window.history.replaceState(null, "", "/obras/1/medicoes/5");
    responder(() => false);
    apiForm.mockImplementation(async (url: string) => {
      if (url.endsWith("/planilhas")) versoes = [V1, V2];
      else if (url.endsWith("/planilhas/envio-externo")) envios = [ENVIO1, { ...ENVIO1, planilha_id: 32, versao: 2 }];
      return { ok: true };
    });
    const { container } = pagina();
    await screen.findByRole("button", { name: "Gerar o espelho sem o boletim" });
    fireEvent.click(screen.getByRole("button", { name: /^Pediu revisão/ }));
    preencherRevisao();
    expect(await screen.findByText("Revisão registrada.")).toBeTruthy();
    const barra = screen.getByRole("navigation", { name: "Passos da medição" });
    await waitFor(() => expect(barra.querySelector("[aria-current='step']")!.textContent).toContain("Planilha e carta"));
    expect(container.querySelector("[data-espelho]")).toBeNull();
    expect(screen.queryByText(/Não foi possível conferir/)).toBeNull();
    fireEvent.click(await screen.findByRole("button", { name: "Já enviei por fora" }));
    fireEvent.change(screen.getByLabelText("Meio"), { target: { value: "Outlook" } });
    fireEvent.click(screen.getByRole("button", { name: "Registrar envio" }));
    await waitFor(() => expect(barra.querySelector("[aria-current='step']")!.textContent).toContain("Análise do órgão"));
    expect(await screen.findByRole("button", { name: "Gerar o espelho sem o boletim" })).toBeTruthy();
  });

  it("revisão enviada pelo sistema e a releitura cai: a tela diz que não conseguiu conferir e oferece Tentar de novo", async () => {
    window.history.replaceState(null, "", "/obras/1/medicoes/5");
    versoes = [V1, V2];
    let enviou = false;
    responder(() => enviou);
    api.mockImplementation(((impl) => async (url: string, opts?: RequestInit) => {
      if (url === "/api/medicoes/5/envio-planilha" && opts?.method === "POST") enviou = true;
      return impl(url, opts);
    })(api.getMockImplementation()!));
    const { container } = pagina();
    // a revisao pendente e' a vez do passo 1: e' la' que ela sai
    fireEvent.click(await screen.findByRole("button", { name: "Enviar ao órgão" }));
    expect(container.querySelector("[data-espelho]")).toBeNull();
    fireEvent.change(screen.getByLabelText("Nº do ofício (CT)"), { target: { value: "301" } });
    fireEvent.click(screen.getByRole("button", { name: "Prévia do e-mail" }));
    await screen.findByLabelText("Assunto");
    fireEvent.click(screen.getByRole("button", { name: "Enviar ao órgão" }));
    expect(await screen.findByText(/Não foi possível conferir a planilha\/carta\./)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Tentar de novo" })).toBeTruthy();
    expect(container.querySelector("[data-espelho]")).toBeNull();
    expect(semBoletim()).toBeNull();
  });

  it("com a falha na tela, outra revisão que relê com sucesso limpa a falha", async () => {
    window.history.replaceState(null, "", "/obras/1/medicoes/5");
    responder(n => n === 2);
    apiForm.mockImplementation(async () => ({ ok: true })); // a releitura devolve o mesmo (sem revisão pendente)
    pagina();
    await screen.findByRole("button", { name: "Gerar o espelho sem o boletim" });
    fireEvent.click(screen.getByRole("button", { name: /^Pediu revisão/ }));
    preencherRevisao();
    expect(await screen.findByText(/Não foi possível conferir a planilha\/carta\./)).toBeTruthy();
    expect(semBoletim()).toBeNull();
    await waitFor(() => expect(screen.queryByRole("form", { name: /^Registrar revisão Rev/ })).toBeNull());
    fireEvent.click(screen.getByRole("button", { name: /^Pediu revisão/ }));
    preencherRevisao();
    await waitFor(() => expect(screen.queryByText(/Não foi possível conferir/)).toBeNull());
    expect(await screen.findByRole("button", { name: "Gerar o espelho sem o boletim" })).toBeTruthy();
  });
});
