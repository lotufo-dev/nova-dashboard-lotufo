import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { RespostaFavoritas } from "./licitacoes";
import LicitacoesFavoritas from "./LicitacoesFavoritas";
import { ETAPAS, favorita, HOJE_DO_TESTE, leitura, linha, mudanca, prazo } from "./licitacoesTeste";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

// Licitações inventadas (licitacoesTeste.ts). 24/11/2026, 11h em Cuiabá.
const EM_ANALISE = linha(1, {
  sigla_orgao: "SEOBRAS-EX", valor_centavos: 4875000000, favorita: favorita({
    etapa: "em_analise", etapa_rotulo: "Em análise", etapa_do_dossie: true, dossie: "2026-CE-001-exemplo-pavimentacao", selos: ["Diretoria: interesse"],
    prazos: [prazo("Esclarecimento", "2026-11-27", 3, "critico"), prazo("Impugnação", "2026-12-02", 6, "breve"),
      prazo("Sessão", "2026-12-10", 12, "breve", { hora: "09:00", aviso: "dossiê diz 11/12/2026, conferir" })],
    mudancas: [mudanca("2026-11-20", "Sessão adiada"), mudanca("2026-11-18", "Novo anexo"), mudanca("2026-11-17", "Esclarecimento publicado"),
      mudanca("2026-11-14", "Edital retificado"), mudanca("2026-11-13", "Novo anexo")] }) });
const PROPOSTA_ENVIADA = linha(2, {
  valor_centavos: null, valor_rotulo: "sigiloso", data_sessao: "2027-03-01", hora_sessao: null, dias_uteis: 65, prazo: null,
  favorita: favorita({ etapa: "proposta_enviada", etapa_rotulo: "Proposta enviada", prazos: [prazo("Sessão", "2027-03-01", 65, null)] }) });
const SEM_DATA = linha(3, {
  valor_centavos: 234567890, valor_rotulo: "valor do lote 2", data_sessao: null, hora_sessao: null, dias_uteis: null, prazo: null,
  favorita: favorita({ selos: ["Suspensa", "Diretoria: interesse"] }) });
// encerradas: o servidor manda os prazos sem situação; uma pela sessão que passou, outra pela situação, com a sessão ainda por vir
const VENCIDA = linha(8, {
  data_sessao: "2026-11-05", dias_uteis: -13, prazo: null, encerrada: true,
  favorita: favorita({ etapa: "vencida", etapa_rotulo: "Vencida", prazos: [prazo("Sessão", "2026-11-05", -13, null, { hora: "09:00", passado: true })],
    mudancas: [mudanca("2026-11-19", "Resultado publicado")] }) });
const REVOGADA = linha(9, {
  dias_uteis: 12, prazo: null, encerrada: true,
  favorita: favorita({ etapa: "encerrada", etapa_rotulo: "Encerrada",
    prazos: [prazo("Sessão", "2026-12-10", 12, null, { hora: "09:00", aviso: "dossiê diz 11/12/2026, conferir" })] }) });

const favoritas = (linhas = [EM_ANALISE, PROPOSTA_ENVIADA, SEM_DATA, VENCIDA, REVOGADA], extra: Partial<RespostaFavoritas> = {}): RespostaFavoritas => ({
  leitura: leitura(), decisoes: "radar", pode_decidir: false, etapas: ETAPAS, favoritas: linhas, ...extra });
const mostrar = (dados: RespostaFavoritas) => { api.mockResolvedValue(dados); return render(<LicitacoesFavoritas />); };
const bloco = (nome: string) => screen.getByRole("region", { name: nome });
const linhasDe = (nome: string) => within(bloco(nome)).getAllByRole("row").slice(1);
const celula = (l: HTMLElement, rotulo: string) => l.querySelector<HTMLElement>(`td[data-rotulo="${rotulo}"]`)!;
const itens = (c: HTMLElement) => [...c.querySelectorAll("li")].map(li => li.textContent);

describe("LicitacoesFavoritas", () => {
  beforeEach(() => { vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(HOJE_DO_TESTE); });
  afterEach(() => { cleanup(); api.mockReset(); vi.useRealTimers(); });

  it("lê GET /api/licitacoes/favoritas e mostra as em aberto numa tabela, na ordem do servidor", async () => {
    mostrar(favoritas());
    await screen.findByRole("region", { name: "Favoritas em aberto" });
    expect(api).toHaveBeenCalledWith("/api/licitacoes/favoritas");
    expect(within(bloco("Favoritas em aberto")).getAllByRole("columnheader").map(c => c.textContent)).toEqual(
      ["Licitação", "Etapa", "Prazos", "Valor", "Mudanças"]);
    expect(linhasDe("Favoritas em aberto").map(l => within(l).getByRole("rowheader").textContent)).toEqual([
      "SEOBRAS-EX · CE 001/2026 (abre em outra aba)Objeto inventado 1", "PME · CE 002/2026 (abre em outra aba)Objeto inventado 2",
      "PME · CE 003/2026 (abre em outra aba)Objeto inventado 3"]);
    // o nome da página já está no alto: o painel não o repete como título
    expect(within(bloco("Favoritas em aberto")).queryByRole("heading")).toBeNull();
  });

  it("a etapa é o rótulo do servidor, em selo neutro, com o que o dossiê diz além dela; a pasta do dossiê não aparece", async () => {
    mostrar(favoritas());
    await screen.findByRole("region", { name: "Favoritas em aberto" });
    const [emAnalise, proposta, semData] = linhasDe("Favoritas em aberto").map(l => celula(l, "Etapa"));
    expect([...emAnalise.querySelectorAll(".selo")].map(s => [s.textContent, s.className])).toEqual([["Em análise", "selo"], ["Diretoria: interesse", "selo"]]);
    expect(proposta.textContent).toBe("Proposta enviada");
    expect([...semData.querySelectorAll(".selo")].map(s => s.textContent)).toEqual(["Acompanhando", "Suspensa", "Diretoria: interesse"]);
    expect(bloco("Favoritas em aberto").querySelector("td[data-rotulo='Etapa'] .glifo")).toBeNull();
    expect(screen.queryByText(/2026-CE-001-exemplo-pavimentacao/)).toBeNull();
  });

  it("todos os prazos, cada um com o nome, a data e a situação que o servidor mandou; o aviso do prazo aparece", async () => {
    mostrar(favoritas());
    await screen.findByRole("region", { name: "Favoritas em aberto" });
    const [emAnalise, proposta, semData] = linhasDe("Favoritas em aberto").map(l => celula(l, "Prazos"));
    expect(itens(emAnalise)).toEqual(["Esclarecimento27/11em 3 dias úteis", "Impugnação02/12em 6 dias úteis",
      "Sessão10/12 09:00em 12 dias úteisdossiê diz 11/12/2026, conferir"]);
    expect([...emAnalise.querySelectorAll(".selo")].map(s => s.className)).toEqual(
      ["selo selo--critico lic-dias", "selo selo--breve lic-dias", "selo selo--breve lic-dias"]);
    // o aviso do prazo leva o triângulo de atenção, com o texto ao lado
    expect(emAnalise.querySelector(".lic-prazo__aviso .glifo")!.className).toBe("glifo glifo--breve");
    // sem situação, só o texto; sem prazo nenhum, o traço
    expect(itens(proposta)).toEqual(["Sessão01/03/2027em 65 dias úteis"]);
    expect(proposta.querySelector(".selo")).toBeNull();
    expect(semData.textContent).toBe("—");
  });

  it("o prazo que passou é o que o servidor diz em `passado`, e não o sinal dos dias úteis", async () => {
    mostrar(favoritas([linha(1, { favorita: favorita({ prazos: [
      // de sexta para sábado não há dia útil: o prazo de ontem pode vir com zero dias úteis
      prazo("Esclarecimento", "2026-11-23", 0, null, { passado: true }),
      // o de hoje, e o de um dia sem expediente que ainda não chegou (zero dias úteis não quer dizer hoje)
      prazo("Impugnação", "2026-11-24", 0, "critico"), prazo("Visita técnica", "2026-11-28", 0, "critico"),
      prazo("Sessão", "2026-12-10", 12, "breve")] }) })]));
    await screen.findByRole("region", { name: "Favoritas em aberto" });
    const prazos = celula(linhasDe("Favoritas em aberto")[0], "Prazos");
    expect(itens(prazos)).toEqual(["Esclarecimento23/11", "Impugnação24/11hoje", "Visita técnica28/11antes do próximo dia útil",
      "Sessão10/12em 12 dias úteis"]);
    expect([...prazos.querySelectorAll("li")].map(li => li.querySelector(".selo")?.className ?? null)).toEqual(
      [null, "selo selo--critico lic-dias", "selo selo--critico lic-dias", "selo selo--breve lic-dias"]);
  });

  it("o valor pelos centavos, com o rótulo de onde veio; sem valor, o que o radar diz no lugar", async () => {
    mostrar(favoritas());
    await screen.findByRole("region", { name: "Favoritas em aberto" });
    const [emAnalise, proposta, semData] = linhasDe("Favoritas em aberto").map(l => celula(l, "Valor"));
    expect(emAnalise.textContent).toBe("R$ 48.750.000,00");
    expect(emAnalise.className).toContain("col-num");
    expect(proposta.textContent).toBe("sigiloso");
    expect([...semData.childNodes].map(n => n.textContent)).toEqual(["R$ 2.345.678,90", "valor do lote 2"]);
  });

  it("as mudanças, da mais recente para a mais antiga: as três primeiras e a contagem do resto", async () => {
    mostrar(favoritas());
    await screen.findByRole("region", { name: "Favoritas em aberto" });
    const [emAnalise, proposta] = linhasDe("Favoritas em aberto").map(l => celula(l, "Mudanças"));
    expect(itens(emAnalise)).toEqual(["Sessão adiada 20/11", "Novo anexo 18/11", "Esclarecimento publicado 17/11", "e mais 2"]);
    expect(proposta.textContent).toBe("—");
  });

  it("as encerradas ficam num grupo recolhido no fim, só com o nome e a data do prazo, sem cor de situação", async () => {
    mostrar(favoritas());
    await screen.findByRole("region", { name: "Favoritas em aberto" });
    const grupo = screen.getByText("Encerradas").closest("details")!;
    expect(grupo.open).toBe(false);
    expect(within(grupo).getByText("2 favoritas encerradas")).toBeTruthy();
    // fora da tabela das em aberto
    expect(within(bloco("Favoritas em aberto")).queryByText(/CE 008\/2026/)).toBeNull();
    const tabela = grupo.querySelector("table")!;
    const linhas = within(tabela).getAllByRole("row", { hidden: true }).slice(1);
    expect(linhas.map(l => l.querySelector("th")!.textContent)).toEqual([
      "PME · CE 008/2026 (abre em outra aba)Objeto inventado 8", "PME · CE 009/2026 (abre em outra aba)Objeto inventado 9"]);
    expect(linhas.map(l => celula(l, "Etapa").textContent)).toEqual(["Vencida", "Encerrada"]);
    // nem os dias úteis da sessão que ainda viria: a licitação encerrada não tem prazo correndo
    expect(linhas.map(l => itens(celula(l, "Prazos")))).toEqual([["Sessão05/11 09:00"], ["Sessão10/12 09:00dossiê diz 11/12/2026, conferir"]]);
    expect(tabela.querySelector("[class*='selo--']")).toBeNull();
    expect(tabela.querySelector(".glifo")).toBeNull();
    expect(celula(linhas[0], "Mudanças").textContent).toBe("Resultado publicado 19/11");
  });

  it("a leitura do radar: em dia, quando leu; atrasada, o aviso", async () => {
    const { unmount } = mostrar(favoritas());
    expect((await screen.findByText(/Última leitura do radar/)).textContent).toBe("Última leitura do radar: 24/11 às 09:05");
    expect(screen.queryByRole("status")).toBeNull();
    unmount();
    mostrar(favoritas(undefined, { leitura: leitura({ lido_em: "2026-11-20T13:05:00+00:00", atrasada: true }) }));
    await screen.findByRole("region", { name: "Favoritas em aberto" });
    expect(screen.getByRole("status").textContent).toBe("Atenção: O radar não lê desde 20/11 às 09:05.");
    unmount();
    cleanup();
    mostrar(favoritas([], { leitura: leitura({ lido_em: null, atrasada: true }) }));
    await screen.findByRole("region", { name: "Favoritas em aberto" });
    expect(screen.getByRole("status").textContent).toBe("Atenção: O radar ainda não entregou leitura.");
  });

  it("lista vazia: uma linha curta no lugar da tabela; só com encerradas, diz que nenhuma está em aberto", async () => {
    const { unmount } = mostrar(favoritas([]));
    expect(await screen.findByText("Nenhuma favorita.")).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByText("Encerradas")).toBeNull();
    unmount();
    mostrar(favoritas([VENCIDA]));
    expect(await screen.findByText("Nenhuma favorita em aberto.")).toBeTruthy();
    expect(screen.getByText("1 favorita encerrada")).toBeTruthy();
  });

  it("o edital só vira link quando o endereço é http ou https, e abre em outra aba; só leitura, sem botão", async () => {
    mostrar(favoritas([EM_ANALISE, { ...PROPOSTA_ENVIADA, link: "ftp://exemplo.com.br/edital" }, { ...SEM_DATA, link: "" }]));
    await screen.findByRole("region", { name: "Favoritas em aberto" });
    const links = within(bloco("Favoritas em aberto")).getAllByRole("link");
    expect(links.map(a => [a.getAttribute("href"), a.getAttribute("target"), a.getAttribute("rel")])).toEqual([
      ["https://exemplo.com.br/editais/1", "_blank", "noopener noreferrer"]]);
    expect(screen.queryAllByRole("button")).toHaveLength(0);
  });

  it("falha de leitura: diz o que aconteceu e deixa tentar de novo", async () => {
    api.mockRejectedValueOnce(new Error("rede"));
    const erro = vi.spyOn(console, "error").mockImplementation(() => {});
    render(<LicitacoesFavoritas />);
    expect((await screen.findByRole("alert")).textContent).toBe("Não foi possível ler as licitações: Algo deu errado. Tente de novo.");
    erro.mockRestore();
    api.mockResolvedValue(favoritas([]));
    fireEvent.click(screen.getByRole("button", { name: "Tentar de novo" }));
    expect(await screen.findByText("Nenhuma favorita.")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
