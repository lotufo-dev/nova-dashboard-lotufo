import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import AbrirEnvio from "./AbrirEnvio";
import { ApiErro } from "./api";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

// 16/10/2026: a página avulsa "Enviar a nota" saiu; o endereço antigo cai na etapa 4 da medição
describe("Endereço antigo /notas/envio/:id", () => {
  afterEach(() => { cleanup(); api.mockReset(); });

  it("troca o endereço pela etapa 4 da medição do protocolo, sem empilhar histórico", async () => {
    window.history.replaceState(null, "", "/notas/envio/3?x=1");
    const antes = window.history.length;
    api.mockResolvedValue({ envio: { contrato_id: 20, medicao_ids: [631, 632] } });
    render(<AbrirEnvio protocoloId={3} />);
    await waitFor(() => expect(window.location.pathname).toBe("/obras/20/medicoes/631"));
    expect(window.location.hash).toBe("#etapa-4");
    expect(window.location.search).toBe("");
    expect(window.history.length).toBe(antes);
  });

  it("protocolo que não existe: diz o que houve e leva à lista de notas a enviar", async () => {
    api.mockRejectedValue(new ApiErro(404, "Protocolo não encontrado"));
    render(<AbrirEnvio protocoloId={99} />);
    expect((await screen.findByRole("alert")).textContent).toContain("Protocolo não encontrado");
    expect(screen.getByRole("link", { name: "Ver as notas a enviar" }).getAttribute("href")).toBe("/medicoes/enviar-nota");
  });
});
