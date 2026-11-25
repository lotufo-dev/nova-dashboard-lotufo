import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { RespostaTriagem } from "./licitacoes";
import { favorita, HOJE_DO_TESTE, leitura, linha, MOTIVOS, mudanca, prazo, recomendada } from "./licitacoesTeste";
import LicitacoesTriagem from "./LicitacoesTriagem";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

// Licitações inventadas (licitacoesTeste.ts). 24/11/2026, 11h em Cuiabá.
const triagem = (extra: Partial<RespostaTriagem> = {}): RespostaTriagem => ({
  leitura: leitura(),
  contagens: { recomendadas: 0, favoritas: 0, novas: 0, novas_desde: null, por_orgao: [] },
  favoritas: [], recomendadas: [], decisoes: "radar", pode_decidir: false, motivos_descarte: MOTIVOS, ...extra });

const FAVORITA_COM_DOSSIE = linha(1, {
  sigla_orgao: "SEOBRAS-EX", favorita: favorita({
    etapa: "em_analise", etapa_rotulo: "Em análise", etapa_do_dossie: true, dossie: "2026-CE-001-exemplo-pavimentacao", selos: ["Diretoria: interesse"],
    prazos: [prazo("Esclarecimento", "2026-11-27", 3, "critico"), prazo("Sessão", "2026-12-10", 12, "breve", { hora: "09:00" })],
    mudancas: [mudanca("2026-11-20", "Sessão adiada"), mudanca("2026-11-18", "Novo anexo")] }) });
const FAVORITA_SEM_PRAZO = linha(2, {
  sigla_orgao: "", orgao: "Departamento de Estradas de Exemplo", data_sessao: null, hora_sessao: null, dias_uteis: null, prazo: null,
  favorita: favorita({ mudancas: [mudanca("2026-11-22", "Licitação suspensa")] }) });
const FAVORITA_LONGE = linha(3, {
  data_sessao: "2027-03-01", hora_sessao: null, dias_uteis: 65, prazo: null,
  favorita: favorita({ etapa: "proposta_enviada", etapa_rotulo: "Proposta enviada", prazos: [prazo("Sessão", "2027-03-01", 65, null)] }) });

const mostrar = (dados: RespostaTriagem) => { api.mockResolvedValue(dados); return render(<LicitacoesTriagem />); };
const numeros = () => [...screen.getByLabelText("Licitações na triagem").querySelectorAll(".lic-numero")].map(n => [
  n.querySelector("dt")?.textContent, n.querySelector(".lic-numero__valor")?.textContent, n.querySelector(".lic-numero__apoio")?.textContent ?? null]);
const bloco = (nome: string) => screen.getByRole("region", { name: nome });
const linhasDe = (nome: string) => within(bloco(nome)).getAllByRole("row").slice(1);
const cabecalhos = (nome: string) => within(bloco(nome)).getAllByRole("columnheader").map(c => c.textContent);
const celula = (l: HTMLElement, rotulo: string) => l.querySelector<HTMLElement>(`td[data-rotulo="${rotulo}"]`)!;

describe("LicitacoesTriagem", () => {
  beforeEach(() => { vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(HOJE_DO_TESTE); });
  afterEach(() => { cleanup(); api.mockReset(); vi.useRealTimers(); window.history.replaceState(null, "", "/"); });

  it("lê GET /api/licitacoes/triagem e mostra os números do alto como o servidor os conta", async () => {
    mostrar(triagem({
      leitura: leitura({ fontes_com_problema: 2 }),
      contagens: { recomendadas: 3, favoritas: 8, novas: 1506, novas_desde: { desde: "2026-11-23", quantas: 12 }, por_orgao: [] } }));
    await screen.findByLabelText("Licitações na triagem");
    expect(api).toHaveBeenCalledWith("/api/licitacoes/triagem");
    expect(numeros()).toEqual([
      ["Recomendadas a decidir", "3", null], ["Favoritas", "8", null], ["Novas", "1.506", "+12 desde 23/11"], ["Fontes com problema", "2", null]]);
    // as fontes com problema pedem atenção e não travam nada (como os não lidos do SIGA): o símbolo ao lado do rótulo;
    // os outros números ficam em tinta, sem símbolo
    const glifos = [...screen.getByLabelText("Licitações na triagem").querySelectorAll(".lic-numero")].map(n => n.querySelector("dt .glifo")?.className ?? null);
    expect(glifos).toEqual([null, null, null, "glifo glifo--breve"]);
  });

  it("o número de favoritas é a porta para a página delas, com cara de número", async () => {
    mostrar(triagem({ contagens: { recomendadas: 0, favoritas: 8, novas: 0, novas_desde: null, por_orgao: [] } }));
    const porta = await screen.findByRole("link", { name: "8" });
    expect(porta.getAttribute("href")).toBe("/licitacoes/favoritas");
    expect(porta.className).toBe("lic-porta");
    expect(porta.closest(".lic-numero__valor")).not.toBeNull();
    fireEvent.click(porta);
    expect(window.location.pathname).toBe("/licitacoes/favoritas");
  });

  it("sem fonte com problema o número não aparece; sem leitura anterior, as novas ficam sem o “desde”", async () => {
    mostrar(triagem({ contagens: { recomendadas: 1, favoritas: 2, novas: 30, novas_desde: null, por_orgao: [] } }));
    await screen.findByLabelText("Licitações na triagem");
    expect(numeros()).toEqual([["Recomendadas a decidir", "1", null], ["Favoritas", "2", null], ["Novas", "30", null]]);
    expect(screen.queryByText("Fontes com problema")).toBeNull();
    expect(screen.queryByText("Novas por órgão")).toBeNull();
  });

  it("as novas por órgão de interesse, na ordem do servidor, quando ele manda", async () => {
    mostrar(triagem({ contagens: { recomendadas: 0, favoritas: 0, novas: 6, novas_desde: null,
      por_orgao: [{ orgao: "DER-EX", novas: 2 }, { orgao: "SEOBRAS-EX", novas: 1 }] } }));
    const lista = await screen.findByRole("list", { name: "Novas por órgão" });
    expect(within(lista).getAllByRole("listitem").map(li => li.textContent)).toEqual(["DER-EX 22 novas", "SEOBRAS-EX 11 nova"]);
    // o número desenhado sai da leitura; o leitor de tela diz "2 novas"
    expect(lista.querySelector(".contador [aria-hidden='true']")!.textContent).toBe("2");
  });

  it("leitura em dia: diz quando o radar leu, na hora de Cuiabá, sem aviso", async () => {
    mostrar(triagem());
    expect((await screen.findByText(/Última leitura do radar/)).textContent).toBe("Última leitura do radar: 24/11 às 09:05");
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("leitura atrasada: avisa desde quando o radar não lê; sem leitura nenhuma, que ele ainda não entregou", async () => {
    const { unmount } = mostrar(triagem({ leitura: leitura({ lido_em: "2026-11-20T13:05:00+00:00", atrasada: true }) }));
    await screen.findByLabelText("Licitações na triagem");
    const aviso = screen.getByRole("status");
    expect(aviso.textContent).toBe("Atenção: O radar não lê desde 20/11 às 09:05.");
    expect(aviso.className).toBe("aviso");                       // o mesmo nível do aviso do monitor do SIGA
    expect(screen.queryByText(/Última leitura do radar/)).toBeNull();
    unmount();
    mostrar(triagem({ leitura: leitura({ lido_em: null, atrasada: true }) }));
    await screen.findByLabelText("Licitações na triagem");
    expect(screen.getByRole("status").textContent).toBe("Atenção: O radar ainda não entregou leitura.");
  });

  it("favoritas que pedem atenção: tabela na ordem do servidor, com a etapa, o próximo prazo e a mudança mais recente", async () => {
    mostrar(triagem({ favoritas: [FAVORITA_SEM_PRAZO, FAVORITA_COM_DOSSIE, FAVORITA_LONGE] }));
    await screen.findByRole("region", { name: "Favoritas que pedem atenção" });
    expect(cabecalhos("Favoritas que pedem atenção")).toEqual(["Licitação", "Etapa", "Próximo prazo", "Mudança"]);
    const [semPrazo, comDossie, longe] = linhasDe("Favoritas que pedem atenção");
    // a tela não reordena: a primeira linha é a que o servidor mandou primeiro
    expect(within(semPrazo).getByRole("rowheader").textContent).toBe("Departamento de Estradas de Exemplo · CE 002/2026 (abre em outra aba)Objeto inventado 2");
    expect(within(comDossie).getByRole("rowheader").textContent).toBe("SEOBRAS-EX · CE 001/2026 (abre em outra aba)Objeto inventado 1");

    // a etapa é o rótulo do servidor, em selo neutro (etapa não é situação); ao lado, o que o dossiê diz além dela
    const selos = [...celula(comDossie, "Etapa").querySelectorAll(".selo")];
    expect(selos.map(s => [s.textContent, s.className])).toEqual([["Em análise", "selo"], ["Diretoria: interesse", "selo"]]);
    expect(celula(comDossie, "Etapa").querySelector(".glifo")).toBeNull();
    expect(celula(semPrazo, "Etapa").textContent).toBe("Acompanhando");

    // o próximo prazo: o nome, a data e os dias úteis no selo da situação que o servidor mandou
    const proximo = celula(comDossie, "Próximo prazo");
    expect(proximo.textContent).toBe("Esclarecimento27/11em 3 dias úteis");
    expect(within(proximo).getByText("em 3 dias úteis").closest(".selo")!.className).toBe("selo selo--critico lic-dias");
    // sem situação, só o texto, em tinta; a data de outro ano leva o ano
    expect(celula(longe, "Próximo prazo").textContent).toBe("Sessão01/03/2027em 65 dias úteis");
    expect(celula(longe, "Próximo prazo").querySelector(".selo")).toBeNull();
    expect(celula(semPrazo, "Próximo prazo").textContent).toBe("—");

    // a mudança: só a mais recente, o rótulo e o dia
    expect(celula(comDossie, "Mudança").textContent).toBe("Sessão adiada 20/11");
    expect(celula(semPrazo, "Mudança").textContent).toBe("Licitação suspensa 22/11");
    expect(celula(longe, "Mudança").textContent).toBe("—");
    // o contador do bloco conta as linhas do bloco
    expect(bloco("Favoritas que pedem atenção").querySelector(".contador .sr-only")!.textContent).toBe("3 favoritas");
  });

  it("a situação do prazo é a do servidor: a tela não compara os dias com limite nenhum", async () => {
    mostrar(triagem({ favoritas: [
      linha(1, { favorita: favorita({ prazos: [prazo("Sessão", "2026-11-25", 1, null)] }) }),
      linha(2, { favorita: favorita({ prazos: [prazo("Sessão", "2026-12-30", 25, "critico")] }) }),
      linha(3, { favorita: favorita({ prazos: [prazo("Sessão", "2026-11-24", 0, "breve", { hora: "14:30" })] }) })] }));
    await screen.findByRole("region", { name: "Favoritas que pedem atenção" });
    const [um, vinteECinco, hoje] = linhasDe("Favoritas que pedem atenção").map(l => celula(l, "Próximo prazo"));
    expect(um.textContent).toBe("Sessão25/11em 1 dia útil");
    expect(um.querySelector(".selo")).toBeNull();
    expect(vinteECinco.querySelector(".selo")!.className).toContain("selo--critico");
    expect(hoje.textContent).toBe("Sessão24/11 14:30hoje");
    expect(hoje.querySelector(".selo")!.className).toContain("selo--breve");
  });

  it("zero dias úteis não quer dizer hoje: a sessão de sábado vista na sexta não diz “hoje”", async () => {
    mostrar(triagem({ recomendadas: [
      linha(1, { recomendada: recomendada(9), data_sessao: "2026-11-28", hora_sessao: null, dias_uteis: 0, prazo: "critico" }),
      linha(2, { recomendada: recomendada(8), data_sessao: "2026-11-24", hora_sessao: "14:30", dias_uteis: 0, prazo: "critico" })] }));
    await screen.findByRole("region", { name: "Recomendadas a decidir" });
    expect(linhasDe("Recomendadas a decidir").map(l => celula(l, "Sessão").textContent)).toEqual(
      ["28/11antes do próximo dia útil", "24/11 14:30hoje"]);
  });

  it("recomendadas a decidir: a nota, a licitação com o motivo, o tipo de obra, o local, o valor e a sessão", async () => {
    mostrar(triagem({ recomendadas: [
      linha(4, { recomendada: recomendada(9, { cidade: "Porto Modelo", km: 1250 }), cidade: "Outra Cidade", km: 900, dias_uteis: 3, prazo: "critico" }),
      linha(5, { recomendada: recomendada(7, { cidade: "Vila Exemplo", km: null, motivo: "concorrência · 1 atestado" }), valor_centavos: null,
        valor_rotulo: "sigiloso", tipo_obra: "", data_sessao: null, hora_sessao: null, dias_uteis: null, prazo: null }),
      linha(6, { recomendada: recomendada(5, { cidade: "", km: null }), valor_centavos: null, valor_rotulo: "", hora_sessao: null,
        dias_uteis: 28, prazo: null })] }));
    await screen.findByRole("region", { name: "Recomendadas a decidir" });
    expect(cabecalhos("Recomendadas a decidir")).toEqual(["Nota", "Licitação", "Tipo de obra", "Local", "Valor", "Sessão"]);
    const [nove, sete, cinco] = linhasDe("Recomendadas a decidir");
    expect([nove, sete, cinco].map(l => celula(l, "Nota").textContent)).toEqual(["9", "7", "5"]);
    // o motivo da recomendação vai sob o objeto; o leitor de tela ouve "Motivo:"
    expect(within(nove).getByRole("rowheader").textContent).toBe(
      "PME · CE 004/2026 (abre em outra aba)Objeto inventado 4Motivo: concorrência · R$ 123,4 mi · Exemplo · 120 km · 2 atestados");
    expect(celula(nove, "Tipo de obra").textContent).toBe("Urbanização");
    expect(celula(sete, "Tipo de obra").textContent).toBe("—");
    // o local é o da obra, que o radar mandou com a recomendação, e não a cidade e a distância da licitação
    expect([...celula(nove, "Local").children].map(c => c.textContent)).toEqual(["Porto Modelo", "1.250 km"]);
    expect(celula(sete, "Local").textContent).toBe("Vila Exemplo");
    expect(celula(cinco, "Local").textContent).toBe("—");
    // o valor pelos centavos, na coluna de número; sem valor, o que o radar diz no lugar, ou o traço
    expect(celula(nove, "Valor").textContent).toBe("R$ 1.234.567,89");
    expect(celula(nove, "Valor").className).toContain("col-num");
    expect(celula(sete, "Valor").textContent).toBe("sigiloso");
    expect(celula(cinco, "Valor").textContent).toBe("—");
    // a sessão: a data com a hora e os dias úteis, com a situação que o servidor mandou em `prazo`
    expect(celula(nove, "Sessão").textContent).toBe("10/12 09:00em 3 dias úteis");
    expect(celula(nove, "Sessão").querySelector(".selo")!.className).toContain("selo--critico");
    expect(celula(sete, "Sessão").textContent).toBe("—");
    expect(celula(cinco, "Sessão").textContent).toBe("10/12em 28 dias úteis");
    expect(celula(cinco, "Sessão").querySelector(".selo")).toBeNull();
  });

  it("o edital só vira link quando o endereço é http ou https, e abre em outra aba", async () => {
    mostrar(triagem({ recomendadas: [
      linha(1, { recomendada: recomendada(9), link: "https://exemplo.com.br/editais/1" }),
      linha(2, { recomendada: recomendada(8), link: "javascript:alert(1)" }),
      linha(3, { recomendada: recomendada(7), link: "" }),
      linha(4, { recomendada: recomendada(6), link: "http://exemplo.com.br/editais/4", edital: "" })] }));
    await screen.findByRole("region", { name: "Recomendadas a decidir" });
    const links = within(bloco("Recomendadas a decidir")).getAllByRole("link");
    expect(links.map(a => [a.textContent, a.getAttribute("href"), a.getAttribute("target"), a.getAttribute("rel")])).toEqual([
      ["CE 001/2026 (abre em outra aba)", "https://exemplo.com.br/editais/1", "_blank", "noopener noreferrer"],
      // sem número de edital, o link leva o nome da modalidade
      ["Concorrência (abre em outra aba)", "http://exemplo.com.br/editais/4", "_blank", "noopener noreferrer"]]);
    const [, perigoso, semLink] = linhasDe("Recomendadas a decidir");
    expect(within(perigoso).getByRole("rowheader").textContent).toContain("PME · CE 002/2026");
    expect(within(perigoso).queryByRole("link")).toBeNull();
    expect(within(semLink).queryByRole("link")).toBeNull();
  });

  it("lista vazia: uma linha curta no lugar da tabela", async () => {
    mostrar(triagem());
    expect(await screen.findByText("Nenhuma favorita pede atenção.")).toBeTruthy();
    expect(screen.getByText("Nenhuma recomendada a decidir.")).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("só leitura: nenhum botão de decisão na página", async () => {
    mostrar(triagem({ favoritas: [FAVORITA_COM_DOSSIE], recomendadas: [linha(4, { recomendada: recomendada(9) })] }));
    await screen.findByRole("region", { name: "Recomendadas a decidir" });
    expect(screen.queryAllByRole("button")).toHaveLength(0);
    // a pasta do dossiê não aparece na tela
    expect(screen.queryByText(/2026-CE-001-exemplo-pavimentacao/)).toBeNull();
  });

  it("falha de leitura: diz o que aconteceu e deixa tentar de novo", async () => {
    api.mockRejectedValueOnce(new Error("rede"));
    const erro = vi.spyOn(console, "error").mockImplementation(() => {});
    render(<LicitacoesTriagem />);
    expect((await screen.findByRole("alert")).textContent).toBe("Não foi possível ler as licitações: Algo deu errado. Tente de novo.");
    erro.mockRestore();
    api.mockResolvedValue(triagem());
    fireEvent.click(screen.getByRole("button", { name: "Tentar de novo" }));
    expect(await screen.findByText("Nenhuma recomendada a decidir.")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(api).toHaveBeenCalledTimes(2);
  });
});
