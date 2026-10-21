import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
    api.mockImplementation((c: string) => Promise.resolve(c.endsWith("/curva") ? CURVA : c.endsWith("/cronograma") ? VERSAO
      : c.endsWith("/versoes") ? [] : { versao: 3 }));
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

// issue #256: uma linha por versao, com a data do documento quando veio do cadastro
describe("Cronograma: versões", () => {
  const VERSOES = [
    { numero: 2, criado_em: "2024-03-11 04:00:00", chave: "contratual", origem_documento: "contratual",
      data_documento: "2024-03-11", instrumento: null, competencias: 6, total_centavos: 1000000001, vigente: false },
    { numero: 1, criado_em: "2026-09-04 15:00:00", chave: null, origem_documento: null,
      data_documento: null, instrumento: null, competencias: 2, total_centavos: 50000, vigente: false },
    { numero: 3, criado_em: "2026-10-05 04:00:00", chave: "ta-01", origem_documento: "aditivo",
      data_documento: "2026-10-05", instrumento: "ta-01", competencias: 3, total_centavos: 70001, vigente: true },
  ];
  beforeEach(() => {
    api.mockImplementation((c: string) => Promise.resolve(c.endsWith("/curva") ? CURVA : c.endsWith("/cronograma") ? VERSAO
      : c.endsWith("/versoes") ? VERSOES : null));
  });
  afterEach(() => { cleanup(); api.mockReset(); });

  it("lista as versões na ordem do servidor, com a data e o documento", async () => {
    render(<Cronograma contratoId={1} podeEditar={false} />);
    const tabela = await screen.findByRole("table", { name: /Versões do cronograma/ });
    // celulas separadas por "|" (o espaco do R$ e' o nao separavel do toLocaleString)
    const linhas = within(tabela).getAllByRole("row").slice(1)
      .map(l => Array.from(l.querySelectorAll("td"), td => (td.textContent ?? "").replace(/\s/g, " ")).join("|"));
    expect(linhas).toEqual([
      "2|11/03/2024|Contrato|6|R$ 10.000.000,01",
      "1|04/09/2026|Sem documento no cadastro|2|R$ 500,00",
      "3 · vigente|05/10/2026|Termo aditivo · ta-01|3|R$ 700,01",
    ]);
    expect(api).toHaveBeenCalledWith("/api/contratos/1/cronograma/versoes");
  });
});
