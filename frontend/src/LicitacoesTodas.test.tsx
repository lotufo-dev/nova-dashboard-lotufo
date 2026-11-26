import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { pedidoDeTodas, temFiltro, type FiltroDeTodas, type LinhaDeTodas, type RespostaTodas } from "./licitacoes";
import { favorita, HOJE_DO_TESTE, leitura, linha, recomendada } from "./licitacoesTeste";
import LicitacoesTodas from "./LicitacoesTodas";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

// Todas e Grande vulto (fatia 3 da #906). Licitações inventadas (licitacoesTeste.ts). 24/11/2026, 11h em Cuiabá.

const todas = (n: number, extra: Partial<LinhaDeTodas> = {}): LinhaDeTodas => ({ ...linha(n), descarte: null, ...extra });
const FILTROS: FiltroDeTodas[] = [
  { filtro: "tipo", rotulo: "Tipo de obra", escolhido: null, opcoes: [{ valor: "Rodovia", rotulo: "Rodovia", n: 2 }, { valor: "Urbanização", rotulo: "Urbanização", n: 0 }] },
  { filtro: "decisao", rotulo: "Decisão", escolhido: null, opcoes: [
    { valor: "favorita", rotulo: "Favorita", n: 1 }, { valor: "descartada", rotulo: "Descartada", n: 1 }, { valor: "sem-decisao", rotulo: "Sem decisão", n: 2 }] },
];
const resposta = (extra: Partial<RespostaTodas> = {}): RespostaTodas => ({
  leitura: leitura(), decisoes: "radar", pode_decidir: false, vista: "novas", total: 4, ordem: "padrao",
  ordens: [{ ordem: "padrao", rotulo: "Padrão" }, { ordem: "prazo", rotulo: "Prazo" }, { ordem: "publicacao", rotulo: "Publicação" },
    { ordem: "valor", rotulo: "Valor" }],
  filtros: FILTROS, linhas: [], ...extra });

const NOVA = todas(1, { recomendada: recomendada(8) });
const FAVORITA = todas(2, { favorita: favorita({ etapa: "em_analise", etapa_rotulo: "Em análise" }) });
const DESCARTADA = todas(3, { descarte: { motivo: "local", rotulo: "Local", quando: "2026-11-23T14:00:00+00:00" } });
const ENCERRADA = todas(4, { encerrada: true, prazo: null, data_sessao: "2026-11-20", dias_uteis: -2 });
const QUATRO = [NOVA, FAVORITA, DESCARTADA, ENCERRADA];

function servidor(leituras: RespostaTodas[]) {
  let n = 0;
  api.mockImplementation(async (_caminho: string, opcoes?: RequestInit) =>
    opcoes?.method === "POST" ? { id: 0 } : leituras[Math.min(n++, leituras.length - 1)]);
}
const linhas = () => within(screen.getByRole("region", { name: "Licitações novas" })).getAllByRole("row").slice(1);
const botoes = (l: HTMLElement) => within(l).queryAllByRole("button").map(b => b.textContent);

describe("Todas e Grande vulto", () => {
  beforeEach(() => { vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(HOJE_DO_TESTE); window.history.replaceState(null, "", "/licitacoes/todas"); });
  afterEach(() => { cleanup(); api.mockReset(); vi.useRealTimers(); });

  it("pede a vista com o que está no endereço, e deixa de fora o que o servidor recusaria", () => {
    expect(pedidoDeTodas("novas", {})).toBe("/api/licitacoes/todas?vista=novas");
    expect(pedidoDeTodas("grande-vulto", { tipo: "Rodovia", q: " ponte ", ordem: "valor", sessao_de: "2026-12-01", outro: "x" }))
      .toBe("/api/licitacoes/todas?vista=grande-vulto&q=ponte&tipo=Rodovia&sessao_de=2026-12-01&ordem=valor");
    // data fora do formato e ordem desconhecida: o link estragado abre a lista
    expect(pedidoDeTodas("novas", { sessao_ate: "01/12/2026", ordem: "nota" })).toBe("/api/licitacoes/todas?vista=novas");
    expect(pedidoDeTodas("novas", { q: "x".repeat(300) })).toBe(`/api/licitacoes/todas?vista=novas&q=${"x".repeat(200)}`);
    expect([temFiltro({}), temFiltro({ ordem: "padrao" }), temFiltro({ ordem: "prazo" }), temFiltro({ km: "ate-100" })])
      .toEqual([false, false, true, true]);
  });

  it("a tabela, as abas e cada filtro com as quantidades que o servidor contou", async () => {
    servidor([resposta({ linhas: QUATRO })]);
    render(<LicitacoesTodas vista="novas" busca={{}} />);
    await screen.findByRole("region", { name: "Licitações novas" });
    expect(api).toHaveBeenCalledWith("/api/licitacoes/todas?vista=novas");
    expect(screen.getByRole("link", { name: "Todas" }).getAttribute("aria-current")).toBe("page");
    expect(screen.getByRole("link", { name: "Grande vulto" }).getAttribute("href")).toBe("/licitacoes/grande-vulto");
    expect(within(screen.getByRole("region", { name: "Licitações novas" })).getAllByRole("columnheader").map(c => c.textContent))
      .toEqual(["Nota", "Licitação", "Tipo de obra", "Local", "Valor", "Sessão", "Decisão"]);
    expect(screen.getByRole("status").textContent).toBe("4 licitações");
    const tipo = screen.getByLabelText("Tipo de obra") as HTMLSelectElement;
    expect([...tipo.options].map(o => o.textContent)).toEqual(["Todos", "Rodovia (2)", "Urbanização (0)"]);
    // a decisao em vigor, sem botao (antes do corte)
    const [nova, fav, desc, enc] = linhas();
    expect(within(fav).getByText("Favorita")).toBeTruthy();
    expect(within(fav).getByText("Em análise")).toBeTruthy();
    expect(within(desc).getByText("Descartada")).toBeTruthy();
    expect(within(desc).getByText("Local")).toBeTruthy();
    expect([nova, fav, desc, enc].map(botoes)).toEqual([[], [], [], []]);
    expect(within(nova).getAllByRole("cell")[0].textContent).toBe("8");
    // nada filtrado: sem o link de limpar
    expect(screen.queryByRole("link", { name: "Limpar os filtros" })).toBeNull();
  });

  it("escolher um filtro, a ordem ou uma data troca a busca do endereço", async () => {
    servidor([resposta({ linhas: QUATRO })]);
    render(<LicitacoesTodas vista="novas" busca={{}} />);
    await screen.findByRole("region", { name: "Licitações novas" });
    fireEvent.change(screen.getByLabelText("Tipo de obra"), { target: { value: "Rodovia" } });
    expect(window.location.search).toBe("?tipo=Rodovia");
    fireEvent.change(screen.getByLabelText("Ordem"), { target: { value: "valor" } });
    fireEvent.change(screen.getByLabelText("Sessão de"), { target: { value: "2026-12-01" } });
    expect(new URLSearchParams(window.location.search).toString()).toBe("tipo=Rodovia&ordem=valor&sessao_de=2026-12-01");
    fireEvent.change(screen.getByLabelText("Ordem"), { target: { value: "padrao" } });
    fireEvent.change(screen.getByLabelText("Tipo de obra"), { target: { value: "" } });
    expect(window.location.search).toBe("?sessao_de=2026-12-01");
  });

  it("a busca vai para o endereço quando a pessoa para de digitar", async () => {
    servidor([resposta({ linhas: QUATRO })]);
    render(<LicitacoesTodas vista="novas" busca={{}} />);
    await screen.findByRole("region", { name: "Licitações novas" });
    const campo = screen.getByLabelText("Buscar");
    fireEvent.change(campo, { target: { value: "pon" } });
    fireEvent.change(campo, { target: { value: "ponte" } });
    expect(window.location.search).toBe("");
    await waitFor(() => expect(window.location.search).toBe("?q=ponte"));
  });

  it("filtrado: quantas de quantas, o link de limpar e a linha curta quando nada acha", async () => {
    servidor([resposta({ linhas: [NOVA] })]);
    const { unmount } = render(<LicitacoesTodas vista="novas" busca={{ tipo: "Rodovia" }} />);
    await screen.findByRole("region", { name: "Licitações novas" });
    expect(api).toHaveBeenCalledWith("/api/licitacoes/todas?vista=novas&tipo=Rodovia");
    expect(screen.getByRole("status").textContent).toBe("1 de 4 licitações");
    expect(screen.getByRole("link", { name: "Limpar os filtros" }).getAttribute("href")).toBe("/licitacoes/todas");
    unmount();
    servidor([resposta({ linhas: [] })]);
    render(<LicitacoesTodas vista="novas" busca={{ q: "inexistente" }} />);
    expect(await screen.findByText("Nenhuma licitação com esses filtros.")).toBeTruthy();
  });

  it("a lista vazia e a leitura atrasada", async () => {
    servidor([resposta({ vista: "grande-vulto", total: 0, leitura: leitura({ atrasada: true, lido_em: "2026-11-20T13:00:00+00:00" }) })]);
    render(<LicitacoesTodas vista="grande-vulto" busca={{}} />);
    expect(await screen.findByText("Nenhuma licitação.")).toBeTruthy();
    expect(screen.getByText(/O radar não lê desde 20\/11/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Grande vulto" }).getAttribute("aria-current")).toBe("page");
  });

  it("depois do corte: Favoritar a que não tem decisão e Desfazer o descarte; a encerrada e a favorita sem botão", async () => {
    const corte = { decisoes: "dashboard" as const, pode_decidir: true };
    servidor([resposta({ ...corte, linhas: QUATRO }), resposta({ ...corte, linhas: [NOVA, FAVORITA, todas(3), ENCERRADA] })]);
    render(<LicitacoesTodas vista="novas" busca={{}} />);
    await screen.findByRole("region", { name: "Licitações novas" });
    const [nova, fav, desc, enc] = linhas();
    expect([nova, fav, desc, enc].map(botoes)).toEqual([["Favoritar"], [], ["Desfazer o descarte"], []]);
    expect(within(nova).getByRole("button").className).toBe("btn btn--pequeno btn--primario");
    fireEvent.click(within(desc).getByRole("button", { name: /Desfazer o descarte: PME · CE 003\/2026/ }));
    await waitFor(() => expect(botoes(linhas()[2])).toEqual(["Favoritar"]));
    expect(api.mock.calls.filter(c => c[1]?.method === "POST").map(c => c[0])).toEqual(["/api/licitacoes/3/descarte/desfazer"]);
  });
});
