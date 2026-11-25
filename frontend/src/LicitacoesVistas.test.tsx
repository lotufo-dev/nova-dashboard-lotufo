import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DiaDoCalendario, PrazoNoCalendario, RespostaCalendario, RespostaFavoritas } from "./licitacoes";
import LicitacoesFavoritas from "./LicitacoesFavoritas";
import { ETAPAS, favorita, HOJE_DO_TESTE, leitura, linha, prazo } from "./licitacoesTeste";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

// As vistas das Favoritas que chegaram na fatia 2 da #906: o quadro por etapa e o calendário dos prazos, cada uma com
// endereço próprio. Licitações inventadas (licitacoesTeste.ts). 24/11/2026, 11h em Cuiabá.

const abas = () => within(screen.getByRole("navigation", { name: "Vistas das Favoritas" })).getAllByRole("link")
  .map(a => [a.textContent, a.getAttribute("href"), a.getAttribute("aria-current")]);

describe("Favoritas: as três vistas em abas", () => {
  afterEach(() => { cleanup(); api.mockReset(); window.history.replaceState(null, "", "/"); });

  it("cada vista é um link com endereço próprio; a atual leva aria-current", async () => {
    api.mockResolvedValue({ leitura: leitura(), decisoes: "radar", pode_decidir: false, etapas: ETAPAS, favoritas: [] });
    const { unmount } = render(<LicitacoesFavoritas />);
    await screen.findByRole("region", { name: "Favoritas em aberto" });
    expect(abas()).toEqual([["Lista", "/licitacoes/favoritas", "page"], ["Quadro", "/licitacoes/favoritas/quadro", null],
      ["Calendário", "/licitacoes/favoritas/calendario", null]]);
    expect(screen.getByRole("link", { name: "Quadro" }).className).toBe("aba");
    fireEvent.click(screen.getByRole("link", { name: "Quadro" }));
    expect(window.location.pathname).toBe("/licitacoes/favoritas/quadro");
    unmount();
    render(<LicitacoesFavoritas vista="quadro" />);
    await screen.findByRole("list", { name: "Favoritas por etapa" });
    expect(abas().map(a => a[2])).toEqual([null, "page", null]);
  });

  it("as abas aparecem também enquanto a leitura não chega", () => {
    api.mockReturnValue(new Promise(() => {}));
    render(<LicitacoesFavoritas vista="calendario" />);
    expect(abas().map(a => a[2])).toEqual([null, null, "page"]);
    expect(screen.getByRole("status").textContent).toBe("Carregando as licitações…");
  });
});

describe("Favoritas: quadro por etapa", () => {
  const ACOMPANHANDO = linha(3, { favorita: favorita({ prazos: [prazo("Sessão", "2026-12-10", 12, "breve", { hora: "09:00" })] }) });
  const EM_ANALISE = linha(1, { sigla_orgao: "SEOBRAS-EX", favorita: favorita({ etapa: "em_analise", etapa_rotulo: "Em análise", etapa_do_dossie: true,
    prazos: [prazo("Esclarecimento", "2026-11-27", 3, "critico"), prazo("Sessão", "2026-12-10", 12, "breve")] }) });
  const EM_ANALISE_2 = linha(2, { data_sessao: null, hora_sessao: null, dias_uteis: null, prazo: null,
    favorita: favorita({ etapa: "em_analise", etapa_rotulo: "Em análise" }) });
  // encerrada pelo radar com a sessão ainda por vir: o prazo sai sem os dias, como na lista
  const PERDIDA = linha(9, { prazo: null, encerrada: true,
    favorita: favorita({ etapa: "perdida", etapa_rotulo: "Perdida", prazos: [prazo("Sessão", "2026-12-10", 12, null, { hora: "09:00" })] }) });
  const quadro = (extra: Partial<RespostaFavoritas> = {}): RespostaFavoritas => ({
    leitura: leitura(), decisoes: "dashboard", pode_decidir: true, etapas: ETAPAS,
    favoritas: [EM_ANALISE, ACOMPANHANDO, EM_ANALISE_2, PERDIDA], ...extra });
  const colunas = () => within(screen.getByRole("list", { name: "Favoritas por etapa" })).getAllByRole("heading", { level: 2 })
    .map(h => h.closest<HTMLElement>(".lic-coluna")!);
  const cartoes = (c: HTMLElement) => [...c.querySelectorAll<HTMLElement>(".lic-cartao")];

  beforeEach(() => { vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(HOJE_DO_TESTE); });
  afterEach(() => { cleanup(); api.mockReset(); vi.useRealTimers(); });

  it("lê as mesmas favoritas da lista e mostra uma coluna por etapa, na ordem do servidor, com a contagem", async () => {
    api.mockResolvedValue(quadro());
    render(<LicitacoesFavoritas vista="quadro" />);
    await screen.findByRole("list", { name: "Favoritas por etapa" });
    expect(api).toHaveBeenCalledWith("/api/licitacoes/favoritas");
    expect(colunas().map(c => [c.querySelector("h2")!.textContent, c.querySelector(".contador .sr-only")!.textContent])).toEqual([
      ["Acompanhando", "1 favorita"], ["Em análise", "2 favoritas"], ["Proposta enviada", "0 favoritas"], ["Vencida", "0 favoritas"],
      ["Perdida", "1 favorita"], ["Desistida", "0 favoritas"], ["Encerrada", "0 favoritas"]]);
    // a ordem das colunas é a que o servidor manda, e não a da tela
    cleanup();
    api.mockResolvedValue(quadro({ etapas: [...ETAPAS].reverse() }));
    render(<LicitacoesFavoritas vista="quadro" />);
    await screen.findByRole("list", { name: "Favoritas por etapa" });
    expect(colunas().map(c => c.querySelector("h2")!.textContent)).toEqual([...ETAPAS].reverse().map(e => e.rotulo));
  });

  it("cada cartão tem o órgão com o edital, o objeto e o próximo prazo com a situação do servidor", async () => {
    api.mockResolvedValue(quadro());
    render(<LicitacoesFavoritas vista="quadro" />);
    await screen.findByRole("list", { name: "Favoritas por etapa" });
    const [acompanhando, emAnalise, proposta, , perdida] = colunas();
    // dentro da coluna, a ordem da lista
    expect(cartoes(emAnalise).map(c => c.textContent)).toEqual([
      "SEOBRAS-EX · CE 001/2026 (abre em outra aba)Objeto inventado 1Esclarecimento27/11em 3 dias úteis",
      "PME · CE 002/2026 (abre em outra aba)Objeto inventado 2"]);
    expect(cartoes(emAnalise)[0].querySelector(".selo")!.className).toBe("selo selo--critico lic-dias");
    expect(cartoes(acompanhando)[0].textContent).toBe("PME · CE 003/2026 (abre em outra aba)Objeto inventado 3Sessão10/12 09:00em 12 dias úteis");
    expect(cartoes(acompanhando)[0].querySelector(".selo")!.className).toContain("selo--breve");
    // a encerrada não tem prazo correndo: só o nome e a data, sem cor
    expect(cartoes(perdida)[0].textContent).toBe("PME · CE 009/2026 (abre em outra aba)Objeto inventado 9Sessão10/12 09:00");
    expect(perdida.querySelector("[class*='selo--']")).toBeNull();
    // a etapa sem favorita continua no quadro, com o traço
    expect(cartoes(proposta)).toHaveLength(0);
    expect(proposta.querySelector(".lic-coluna__vazia")!.textContent).toBe("—");
    // o quadro é só de leitura, mesmo para quem decide: a etapa se troca na lista
    expect(screen.queryAllByRole("button")).toHaveLength(0);
    expect(screen.queryAllByRole("combobox")).toHaveLength(0);
  });
});

/** Um mês de mentira, como o servidor o manda: semanas de domingo a sábado a partir de `inicio`, com os prazos por dia. */
function semanas(inicio: string, quantas: number, mes: string, hoje: string, prazos: Record<string, PrazoNoCalendario[]>): DiaDoCalendario[][] {
  const dia = (n: number) => new Date(Date.parse(`${inicio}T00:00:00Z`) + n * 86_400_000).toISOString().slice(0, 10);
  return Array.from({ length: quantas }, (_, s) => Array.from({ length: 7 }, (_, d) => {
    const data = dia(s * 7 + d);
    return { data, do_mes: data.startsWith(mes), hoje: data === hoje, prazos: prazos[data] ?? [] };
  }));
}

describe("Favoritas: calendário dos prazos", () => {
  const licitacao = (n: number, extra: Partial<PrazoNoCalendario["licitacao"]> = {}): PrazoNoCalendario["licitacao"] => {
    const l = linha(n);
    return { id: l.id, chave: l.chave, orgao: l.orgao, sigla_orgao: l.sigla_orgao, edital: l.edital, modalidade: l.modalidade, objeto: l.objeto,
      link: l.link, encerrada: false, ...extra };
  };
  const calendario = (extra: Partial<RespostaCalendario> = {}): RespostaCalendario => ({
    leitura: leitura(), decisoes: "radar", pode_decidir: false, mes: "2026-12", anterior: "2026-11", proximo: "2027-01", mes_atual: false, prazos: 4,
    semanas: semanas("2026-11-29", 5, "2026-12", "2026-11-24", {
      "2026-12-02": [{ ...prazo("Impugnação", "2026-12-02", 6, "breve"), licitacao: licitacao(1, { sigla_orgao: "SEOBRAS-EX" }) }],
      "2026-12-10": [{ ...prazo("Sessão", "2026-12-10", 12, "breve", { hora: "09:00" }), licitacao: licitacao(1, { sigla_orgao: "SEOBRAS-EX" }) },
        // a encerrada pelo radar: o prazo aparece no dia, sem os dias e sem cor
        { ...prazo("Sessão", "2026-12-10", 12, null, { hora: "14:00" }), licitacao: licitacao(9, { encerrada: true, link: "" }) }],
      "2026-12-30": [{ ...prazo("Visita técnica", "2026-12-30", 25, null), licitacao: licitacao(2) }] }),
    ...extra });
  const celula = (data: string) => screen.getByRole("table").querySelector<HTMLElement>(`td[data-dia="${data}"]`)!;

  beforeEach(() => { vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(HOJE_DO_TESTE); });
  afterEach(() => { cleanup(); api.mockReset(); vi.useRealTimers(); window.history.replaceState(null, "", "/"); });

  it("pede o mês da busca ao servidor; sem mês, ou com mês fora do formato, o de hoje", async () => {
    api.mockResolvedValue(calendario());
    const { unmount } = render(<LicitacoesFavoritas vista="calendario" busca={{ mes: "2026-12" }} />);
    await screen.findByRole("table");
    expect(api).toHaveBeenLastCalledWith("/api/licitacoes/calendario?mes=2026-12");
    unmount();
    for (const busca of [{}, { mes: "2026-13" }, { mes: "dezembro" }, { mes: "2026-12&x=1" }] as Record<string, string>[]) {
      const tela = render(<LicitacoesFavoritas vista="calendario" busca={busca} />);
      await screen.findByRole("table");
      expect(api).toHaveBeenLastCalledWith("/api/licitacoes/calendario");
      tela.unmount();
    }
  });

  it("o mês por extenso e os links para o mês anterior, o próximo e o atual, que o servidor manda", async () => {
    api.mockResolvedValue(calendario());
    const { unmount } = render(<LicitacoesFavoritas vista="calendario" busca={{ mes: "2026-12" }} />);
    expect((await screen.findByRole("heading", { level: 2 })).textContent).toBe("dezembro de 2026");
    const troca = screen.getByRole("navigation", { name: "Trocar o mês" });
    expect(within(troca).getAllByRole("link").map(a => [a.textContent, a.getAttribute("href")])).toEqual([
      ["Mês anterior", "/licitacoes/favoritas/calendario?mes=2026-11"], ["Mês atual", "/licitacoes/favoritas/calendario"],
      ["Próximo mês", "/licitacoes/favoritas/calendario?mes=2027-01"]]);
    fireEvent.click(within(troca).getByRole("link", { name: "Próximo mês" }));
    expect(window.location.pathname + window.location.search).toBe("/licitacoes/favoritas/calendario?mes=2027-01");
    unmount();
    // no mês de hoje (quem diz é o servidor), o link "Mês atual" não aparece
    api.mockResolvedValue(calendario({ mes: "2026-11", anterior: "2026-10", proximo: "2026-12", mes_atual: true,
      semanas: semanas("2026-11-01", 5, "2026-11", "2026-11-24", {}) , prazos: 1 }));
    render(<LicitacoesFavoritas vista="calendario" />);
    expect((await screen.findByRole("heading", { level: 2 })).textContent).toBe("novembro de 2026");
    expect(within(screen.getByRole("navigation", { name: "Trocar o mês" })).getAllByRole("link").map(a => a.textContent)).toEqual(
      ["Mês anterior", "Próximo mês"]);
    // hoje é o dia que o servidor marcou
    expect([...screen.getByRole("table").querySelectorAll("td[aria-current='date']")].map(td => td.getAttribute("data-dia"))).toEqual(["2026-11-24"]);
    expect(celula("2026-11-24").querySelector(".lic-dia__data")!.textContent).toBe("24ter 24/11 hoje");
  });

  it("a grade tem os sete dias da semana, de domingo a sábado, e uma célula por dia das semanas do servidor", async () => {
    api.mockResolvedValue(calendario());
    render(<LicitacoesFavoritas vista="calendario" busca={{ mes: "2026-12" }} />);
    const tabela = await screen.findByRole("table");
    expect(within(tabela).getAllByRole("columnheader").map(c => c.textContent)).toEqual(["dom", "seg", "ter", "qua", "qui", "sex", "sáb"]);
    expect(within(tabela).getAllByRole("row")).toHaveLength(6);
    expect(tabela.querySelectorAll("td")).toHaveLength(35);
    // os dias de fora do mês vêm marcados pelo servidor
    expect([...tabela.querySelectorAll("td.lic-dia--fora")].map(td => td.getAttribute("data-dia"))).toEqual(
      ["2026-11-29", "2026-11-30", "2027-01-01", "2027-01-02"]);
    expect(tabela.querySelector("td[aria-current]")).toBeNull();
  });

  it("cada prazo no dia dele, com o nome, a hora, a situação do servidor e a licitação", async () => {
    api.mockResolvedValue(calendario());
    render(<LicitacoesFavoritas vista="calendario" busca={{ mes: "2026-12" }} />);
    await screen.findByRole("table");
    const itens = (data: string) => [...celula(data).querySelectorAll("li")].map(li => li.textContent);
    expect(itens("2026-12-02")).toEqual(["Impugnaçãoem 6 dias úteisSEOBRAS-EX · CE 001/2026 (abre em outra aba)"]);
    expect(itens("2026-12-10")).toEqual(["Sessão 09:00em 12 dias úteisSEOBRAS-EX · CE 001/2026 (abre em outra aba)", "Sessão 14:00PME · CE 009/2026"]);
    // sem situação, só o nome e a licitação; o dia sem prazo fica só com o número
    expect(itens("2026-12-30")).toEqual(["Visita técnicaPME · CE 002/2026 (abre em outra aba)"]);
    expect(itens("2026-12-03")).toEqual([]);
    expect(celula("2026-12-03").className).toBe("lic-dia lic-dia--vazio");
    expect(celula("2026-12-03").querySelector(".lic-dia__data")!.textContent).toBe("3qui 03/12");
    // a situação é a do servidor, no selo, com o símbolo dela
    expect([...celula("2026-12-10").querySelectorAll(".selo")].map(s => s.className)).toEqual(["selo selo--breve lic-dias"]);
    expect(celula("2026-12-30").querySelector(".selo")).toBeNull();
    // a licitação leva ao edital, em outra aba; o objeto não entra na célula
    const edital = within(celula("2026-12-02")).getByRole("link");
    expect([edital.getAttribute("href"), edital.getAttribute("target")]).toEqual(["https://exemplo.com.br/editais/1", "_blank"]);
    expect(screen.queryByText(/Objeto inventado/)).toBeNull();
  });

  it("mês sem prazo: uma linha curta no lugar da grade, com a troca de mês", async () => {
    api.mockResolvedValue(calendario({ mes: "2026-02", anterior: "2026-01", proximo: "2026-03", prazos: 0,
      semanas: semanas("2026-02-01", 4, "2026-02", "2026-11-24", {}) }));
    render(<LicitacoesFavoritas vista="calendario" busca={{ mes: "2026-02" }} />);
    expect(await screen.findByText("Nenhum prazo em fevereiro de 2026.")).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
    expect(within(screen.getByRole("navigation", { name: "Trocar o mês" })).getAllByRole("link")).toHaveLength(3);
  });

  it("a leitura atrasada avisa; a falha de leitura diz o que aconteceu e deixa tentar de novo", async () => {
    api.mockResolvedValue(calendario({ leitura: leitura({ lido_em: "2026-11-20T13:05:00+00:00", atrasada: true }) }));
    const { unmount } = render(<LicitacoesFavoritas vista="calendario" />);
    await screen.findByRole("table");
    expect(screen.getByRole("status").textContent).toBe("Atenção: O radar não lê desde 20/11 às 09:05.");
    unmount();
    api.mockReset();
    api.mockRejectedValueOnce(new Error("rede"));
    const erro = vi.spyOn(console, "error").mockImplementation(() => {});
    render(<LicitacoesFavoritas vista="calendario" />);
    expect((await screen.findByRole("alert")).textContent).toBe("Não foi possível ler as licitações: Algo deu errado. Tente de novo.");
    erro.mockRestore();
    api.mockResolvedValue(calendario());
    fireEvent.click(screen.getByRole("button", { name: "Tentar de novo" }));
    expect(await screen.findByRole("table")).toBeTruthy();
  });
});
