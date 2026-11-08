import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Medicao } from "./Medicoes";
import PassoAnalise from "./PassoAnalise";

const { api } = vi.hoisted(() => ({ api: vi.fn(async () => ({ processos: [] })) }));
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
