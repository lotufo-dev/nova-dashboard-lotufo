import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Medicao } from "./Medicoes";
import PassoAnalise from "./PassoAnalise";

const { api } = vi.hoisted(() => ({ api: vi.fn(async (_caminho: string): Promise<unknown> => ({ processos: [] })) }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

const M = { id: 5, numero: 7, tipo: "execucao", competencia: "2026-07", estado: "boletim_recebido",
  valor_protocolado_centavos: 1234567, valor_protocolado_origem: "manual", valor_atestado_centavos: 1200001,
  valor_atestado_origem: "manual", atestado_em: "2026-08-10", nf_emitida_em: null, recebida_em: null, congelada: 0,
  protocolos: [], boletins: [{ id: 9, tem_arquivo: true, valor_centavos: 1200001, atestado_em: "2026-08-10" }] } as Medicao;
const agir = vi.fn(async () => true);
const abrir = (m: Medicao) => render(<PassoAnalise m={m} planilha={null} podeEditar salvando={false} agir={agir} aoMudarSiga={() => {}} />);
const aprovacao = () => screen.getByLabelText("Aprovação");

describe("Diferença do boletim no passo 2 (issue #288)", () => {
  afterEach(() => cleanup());

  it("aprovado abaixo do pedido: a diferença aparece com o botão de aceitar", () => {
    abrir(M);
    expect(within(aprovacao()).getByText("Diferença")).toBeTruthy();
    expect(aprovacao().textContent).toMatch(/−R\$\s345,66/);
    expect(screen.getByRole("button", { name: "Aceitar a diferença" })).toBeTruthy();
  });

  it("sem diferença abaixo do pedido, ou já aceita, a linha não aparece", () => {
    const { unmount } = abrir({ ...M, valor_atestado_centavos: 1234567 });
    expect(within(aprovacao()).queryByText("Diferença")).toBeNull();
    unmount();
    abrir({ ...M, diferenca_aceita: { atesto_id: 9, justificativa: "glosa de itens", usuario: "Eng",
      criado_em: "2026-11-08 10:00:00", diferenca_centavos: -34566 } });
    expect(within(aprovacao()).queryByText("Diferença")).toBeNull();
    expect(screen.getByText("Diferença aceita")).toBeTruthy();
  });
});

describe("Respostas do órgão por e-mail (issue #644)", () => {
  afterEach(() => { cleanup(); api.mockReset(); api.mockImplementation(async () => ({ processos: [] })); });

  const R = (id: number, recebida_em: string, trecho: string) => ({ id, medicao_id: 5, remetente: "fiscal@orgao-a.exemplo.com.br",
    remetente_nome: id === 1 ? "Fiscal do contrato" : null, recebida_em, assunto: "RES: medição", trecho, anexos: [] });

  it("lista remetente, data e trecho, na ordem que o servidor mandou (da mais nova para a mais antiga)", async () => {
    api.mockImplementation(async (caminho: string) => caminho === "/api/medicoes/5/respostas-orgao"
      ? [R(2, "2026-11-11T13:00:00Z", "Segue o parecer."), R(1, "2026-11-10T14:00:00Z", "Recebido.")] : { processos: [] });
    abrir({ ...M, estado: "planilha_enviada" });
    const itens = within(await screen.findByRole("list", { name: "Respostas do órgão por e-mail" })).getAllByRole("listitem");
    expect(itens).toHaveLength(2);
    expect(itens[0].textContent).toContain("fiscal@orgao-a.exemplo.com.br");
    expect(itens[0].textContent).toContain("11/11");
    expect(itens[0].textContent).toContain("Segue o parecer.");
    expect(itens[1].textContent).toContain("Fiscal do contrato");
    expect(itens[1].textContent).toContain("Recebido.");
  });

  it("sem resposta registrada a lista não aparece; chega uma leitura nova e a lista é relida", async () => {
    abrir({ ...M, estado: "planilha_enviada" });
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/medicoes/5/respostas-orgao"));
    expect(screen.queryByRole("list", { name: "Respostas do órgão por e-mail" })).toBeNull();
    api.mockImplementation(async (caminho: string) => caminho === "/api/medicoes/5/respostas-orgao"
      ? [R(1, "2026-11-10T14:00:00Z", "Recebido.")] : { processos: [] });
    act(() => { window.dispatchEvent(new Event("respostas-orgao-lidas")); });
    expect(await screen.findByText("Recebido.")).toBeTruthy();
  });
});
