import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Cronograma from "./Cronograma";
import { ir } from "./rota";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", () => ({ api, ApiErro: class ApiErro extends Error { status = 0; } }));

const VERSAO = { numero: 2, criado_em: "2026-09-01T12:00:00", origem: "sistema",
  itens: [{ competencia: "2026-09", valor_previsto_centavos: 120000000 }] };
const CURVA = { curva: [], saldo: { vigente_centavos: 100, atestado_execucao_centavos: 0, saldo_centavos: 100, formula: "x" } };

// guarda de rascunho (issue #27): cronograma digitado e nao publicado
describe("Cronograma: guarda de rascunho", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/obras/1/contrato");
    api.mockImplementation((c: string) => Promise.resolve(c.endsWith("/curva") ? CURVA : c.endsWith("/cronograma") ? VERSAO : { versao: 3 }));
  });
  afterEach(() => { cleanup(); api.mockReset(); vi.restoreAllMocks(); });

  it("digitar pergunta ao sair; copiar a versão vigente sem editar não; publicar limpa", async () => {
    const confirmar = vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<Cronograma contratoId={1} podeEditar />);
    const campo = await screen.findByLabelText("Nova versão do cronograma");
    fireEvent.click(screen.getByRole("button", { name: "Copiar versão vigente" }));
    ir({ tela: "avisos" });
    expect(confirmar).not.toHaveBeenCalled();
    window.history.replaceState(null, "", "/obras/1/contrato");
    fireEvent.change(campo, { target: { value: "2026-10;900,00" } });
    ir({ tela: "avisos" });
    expect(confirmar).toHaveBeenCalledTimes(1);
    expect(window.location.pathname).toBe("/obras/1/contrato");
    // publicar com sucesso limpa o campo e solta a guarda
    fireEvent.click(screen.getByRole("button", { name: /Publicar/ }));
    await waitFor(() => expect((campo as HTMLTextAreaElement).value).toBe(""));
    ir({ tela: "avisos" });
    expect(confirmar).toHaveBeenCalledTimes(1);
    expect(window.location.pathname).toBe("/avisos");
  });
});

// #262 (spec 2026-10-20 §3.2): saldo a precos iniciais; o aditivo de reajuste aparece a parte, fora da conta
describe("Cronograma: saldo e reajuste contratado", () => {
  afterEach(() => { cleanup(); api.mockReset(); });
  const comSaldo = (saldo: object) => api.mockImplementation((c: string) =>
    Promise.resolve(c.endsWith("/curva") ? { curva: [], saldo } : VERSAO));

  it("com aditivo de reajuste: a conta usa o vigente de execução e o reajuste fica à parte", async () => {
    comSaldo({ vigente_centavos: 133301, vigente_execucao_centavos: 120001, reajuste_contratado_centavos: 13300,
      atestado_execucao_centavos: 24000, saldo_centavos: 96001, formula: "f" });
    render(<Cronograma contratoId={1} podeEditar={false} />);
    expect(await screen.findByText("Vigente de execução")).toBeTruthy();
    expect(screen.getByText("R$ 1.200,01")).toBeTruthy();
    expect(screen.getByText("R$ 960,01")).toBeTruthy();
    expect(screen.getByText("Reajuste contratado (fora do saldo)")).toBeTruthy();
    expect(screen.getByText("R$ 133,00")).toBeTruthy();
    expect(screen.queryByText("R$ 1.333,01")).toBeNull();
  });

  it("sem aditivo de reajuste: sem a linha do reajuste", async () => {
    comSaldo({ vigente_centavos: 100000, vigente_execucao_centavos: 100000, reajuste_contratado_centavos: 0,
      atestado_execucao_centavos: 0, saldo_centavos: 100000, formula: "f" });
    render(<Cronograma contratoId={1} podeEditar={false} />);
    expect(await screen.findByText("Vigente de execução")).toBeTruthy();
    expect(screen.queryByText("Reajuste contratado (fora do saldo)")).toBeNull();
  });
});
