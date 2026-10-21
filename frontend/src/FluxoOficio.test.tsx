import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CartaoPleito, type Pleito } from "./FluxoOficio";
import { ir } from "./rota";

const { api, apiForm } = vi.hoisted(() => ({ api: vi.fn(), apiForm: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api, apiForm }));

const PLEITO: Pleito = {
  id: 4, tipo: "prazo", rotulo: "Pedido de prorrogação", origem: "sistema", numero_oficio: "301/2026",
  data_base_mes: null, ciclo: null, dias: 60, justificativa: null, situacao: "assinado", corpo_carta: "Texto",
  montado_paginas: 3, assinado_arquivo: "pleitos/x.pdf", nome_documento: "Oficio 301.pdf",
  conferencia: { ok: true, avisos: [], paginas_montado: 3, certificado: 0 }, pendencias: [],
  enviado_em: null, envio_justificativa: null, anexos: [], exigidos: [],
};
const PREVIA = { para: ["orgao@exemplo.com"], copia: [], assunto: "Ofício 301/2026", corpo: "Bom dia.",
  anexos: [{ nome: "Oficio 301.pdf", tamanho: 2048 }], total: 2048, limite: 26214400,
  pendencias: [{ codigo: "anexo", mensagem: "Falta o memorial" }] };

// issue #11: o Enviar do ofício com pendência não fica apagado; o clique diz o que falta, junto da justificativa
describe("Ofício", () => {
  afterEach(() => { cleanup(); api.mockReset(); apiForm.mockReset(); });

  it("com pendência na prévia, o clique em Enviar sem justificativa mostra o erro no campo e só envia com 10 caracteres", async () => {
    api.mockImplementation((caminho: string) => Promise.resolve(caminho === "/api/pleitos/4/previa" ? PREVIA : {}));
    render(<CartaoPleito p={PLEITO} podeEditar aoMudar={() => {}} />);
    fireEvent.click(await screen.findByRole("button", { name: "Prévia do e-mail" }));
    const enviar = await screen.findByRole("button", { name: "Enviar" }) as HTMLButtonElement;
    expect(enviar.disabled).toBe(false);
    const campo = screen.getByLabelText(/Justificativa/);
    fireEvent.click(enviar);
    const erro = screen.getByText(/Escreva a justificativa/);
    expect(erro.getAttribute("role")).toBe("alert");
    expect(campo.getAttribute("aria-invalid")).toBe("true");
    expect(document.getElementById(campo.getAttribute("aria-describedby") ?? "")?.contains(erro)).toBe(true);
    expect(api.mock.calls.some(c => c[0] === "/api/pleitos/4/enviar")).toBe(false);
    fireEvent.change(campo, { target: { value: "curta" } });
    fireEvent.click(enviar);
    expect(api.mock.calls.some(c => c[0] === "/api/pleitos/4/enviar")).toBe(false);
    fireEvent.change(campo, { target: { value: "memorial segue amanhã" } });
    expect(screen.queryByText(/Escreva a justificativa/)).toBeNull();
    fireEvent.click(enviar);
    await waitFor(() => expect(api.mock.calls.some(c => c[0] === "/api/pleitos/4/enviar")).toBe(true));
    const [, opcoes] = api.mock.calls.find(c => c[0] === "/api/pleitos/4/enviar")!;
    expect(JSON.parse(opcoes.body).justificativa).toBe("memorial segue amanhã");
  });

  // issue #272: a previsão de reajuste se confere no pleito de reajuste em aberto; no de prazo e no enviado, não
  it("só o pleito de reajuste em aberto oferece a planilha de previsão", () => {
    const reajuste: Pleito = { ...PLEITO, tipo: "reajuste", rotulo: "Pleito de reajuste", data_base_mes: "2024-06", ciclo: 2026 };
    const { rerender } = render(<CartaoPleito p={reajuste} podeEditar aoMudar={() => {}} />);
    expect(screen.getByLabelText("Anexar planilha de previsão")).toBeTruthy();
    rerender(<CartaoPleito p={PLEITO} podeEditar aoMudar={() => {}} />);
    expect(screen.queryByLabelText("Anexar planilha de previsão")).toBeNull();
    rerender(<CartaoPleito p={reajuste} podeEditar={false} aoMudar={() => {}} />);
    expect(screen.queryByLabelText("Anexar planilha de previsão")).toBeNull();
  });

  // issue #27: carta editada pede confirmação; depois de enviada ou descartada, a guarda solta
  it("carta editada pede confirmação ao sair; ofício enviado ou descartado não prende a tela", () => {
    window.history.replaceState(null, "", "/obras/1/prazos");
    const confirmar = vi.spyOn(window, "confirm").mockReturnValue(false);
    const { rerender } = render(<CartaoPleito p={{ ...PLEITO, situacao: "rascunho" }} podeEditar aoMudar={() => {}} />);
    fireEvent.change(document.getElementById("carta-pleito-4")!, { target: { value: "Texto alterado" } });
    ir({ tela: "avisos" });
    expect(confirmar).toHaveBeenCalledTimes(1);
    expect(window.location.pathname).toBe("/obras/1/prazos");
    rerender(<CartaoPleito p={{ ...PLEITO, situacao: "enviado" }} podeEditar aoMudar={() => {}} />);
    rerender(<CartaoPleito p={{ ...PLEITO, situacao: "descartado" }} podeEditar aoMudar={() => {}} />);
    ir({ tela: "avisos" });
    expect(confirmar).toHaveBeenCalledTimes(1);
    expect(window.location.pathname).toBe("/avisos");
    vi.restoreAllMocks();
  });
});
