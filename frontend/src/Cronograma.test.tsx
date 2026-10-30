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
  // a vigente que /cronograma devolve, coerente com a lista (versao 3, do cadastro)
  const VIGENTE = { numero: 3, criado_em: "2026-10-05 04:00:00", origem: "manual",
    itens: [{ competencia: "2026-10", valor_previsto_centavos: 70001 }] };
  const servir = (vigente: unknown) => api.mockImplementation((c: string) => Promise.resolve(
    c.endsWith("/curva") ? CURVA : c.endsWith("/cronograma") ? vigente : c.endsWith("/versoes") ? VERSOES : null));
  beforeEach(() => { servir(VIGENTE); });
  afterEach(() => { cleanup(); api.mockReset(); });

  it("lista as versões na ordem do servidor, com a data e o documento", async () => {
    render(<Cronograma contratoId={1} podeEditar={false} />);
    const tabela = await screen.findByRole("table", { name: /Versões do cronograma/ });
    // celulas separadas por "|" (o espaco do R$ e' o nao separavel do toLocaleString)
    const linhas = within(tabela).getAllByRole("row").slice(1)
      .map(l => Array.from(l.querySelectorAll("td"), td => (td.textContent ?? "").replace(/\s/g, " ")).join("|"));
    expect(linhas).toEqual([
      "2|11/03/2024|Contrato|6|R$ 10.000.000,01",
      "1|04/09/2026|—|2|R$ 500,00",
      "3 Vigente|05/10/2026|Termo aditivo · ta-01|3|R$ 700,01",
    ]);
    expect(api).toHaveBeenCalledWith("/api/contratos/1/cronograma/versoes");
  });

  it("a dica do cabeçalho é só o número da versão; documento e data ficam na tabela", async () => {
    render(<Cronograma contratoId={1} podeEditar={false} />);
    await screen.findByRole("table", { name: /Versões do cronograma/ });
    const dica = screen.getByText(/^versão 3/);
    expect(dica.textContent).toBe("versão 3");
    expect(dica.getAttribute("title")).toBeNull();
    expect(document.body.innerHTML).not.toMatch(/Origem do cadastro|manual/);
    // os contadores ao lado do summary sairam
    expect(screen.getByText("Versões do cronograma").tagName).toBe("SUMMARY");
  });

  it("a dica casa a versão pelo número, não pela marca de vigente da lista (gate Sol, PR #311)", async () => {
    // as duas leituras sao independentes: /cronograma pode trazer outra versao que a marcada na lista
    servir({ numero: 1, criado_em: "2026-09-04 15:00:00", origem: "manual",
      itens: [{ competencia: "2026-09", valor_previsto_centavos: 50000 }] });
    render(<Cronograma contratoId={1} podeEditar={false} />);
    await screen.findByRole("table", { name: /Versões do cronograma/ });
    expect(screen.getByText(/^versão 1/).textContent).toBe("versão 1");
  });
});

describe("Cronograma: texto na tela", () => {
  afterEach(() => { cleanup(); api.mockReset(); });

  it("o formato de colar fica só no placeholder, sem parágrafo nem aviso fixo; sem a fórmula do saldo", async () => {
    api.mockImplementation((c: string) => Promise.resolve(c.endsWith("/curva") ? CURVA : c.endsWith("/cronograma") ? VERSAO
      : c.endsWith("/versoes") ? [] : null));
    render(<Cronograma contratoId={1} podeEditar />);
    const campo = await screen.findByLabelText("Nova versão do cronograma");
    expect(campo.getAttribute("placeholder")).toContain("2026-09;1.200.000,00");
    expect(screen.queryByText(/no formato/)).toBeNull();
    expect(screen.queryByText(/substitui o cronograma futuro/)).toBeNull();
    expect(screen.queryByText("x")).toBeNull();          // a formula do servidor
    fireEvent.change(campo, { target: { value: "2026-10;900,00" } });
    expect(screen.queryByText(/total previsto/)).toBeNull();
  });

  it("“Medido acima do vigente de execução” só aparece com o saldo negativo", async () => {
    const negativo = { ...CURVA, saldo: { ...CURVA.saldo, atestado_execucao_centavos: 200, saldo_centavos: -100 } };
    api.mockImplementation((c: string) => Promise.resolve(c.endsWith("/curva") ? negativo : c.endsWith("/cronograma") ? VERSAO
      : c.endsWith("/versoes") ? [] : null));
    render(<Cronograma contratoId={1} podeEditar={false} />);
    expect(await screen.findByText("Medido acima do vigente de execução do contrato.")).toBeTruthy();
    cleanup();
    api.mockImplementation((c: string) => Promise.resolve(c.endsWith("/curva") ? CURVA : c.endsWith("/cronograma") ? VERSAO
      : c.endsWith("/versoes") ? [] : null));
    render(<Cronograma contratoId={1} podeEditar={false} />);
    await screen.findByText("Saldo");
    expect(screen.queryByText(/Medido acima/)).toBeNull();
  });
});
