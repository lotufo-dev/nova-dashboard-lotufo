import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiErro } from "./api";
import type { RespostaFavoritas, RespostaTriagem } from "./licitacoes";
import LicitacoesFavoritas from "./LicitacoesFavoritas";
import { ETAPAS, favorita, HOJE_DO_TESTE, leitura, linha, MOTIVOS, mudanca, prazo, recomendada } from "./licitacoesTeste";
import LicitacoesTriagem from "./LicitacoesTriagem";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

// As decisões pela tela (fatia 2 da #906). Licitações inventadas (licitacoesTeste.ts). 24/11/2026, 11h em Cuiabá.
// Depois do corte o servidor manda `pode_decidir` a quem decide; a tela só mostra botão com ele.

/** Um servidor de mentira: cada leitura devolve a próxima resposta da fila (a última se repete); o POST devolve o que
 *  `respostas` tem para o caminho, ou falha com o erro que estiver lá. */
function servidor<T>(leituras: T[], respostas: Record<string, unknown> = {}) {
  let n = 0;
  api.mockImplementation(async (caminho: string, opcoes?: RequestInit) => {
    if (opcoes?.method !== "POST") return leituras[Math.min(n++, leituras.length - 1)];
    const r = respostas[caminho];
    if (r instanceof Error) throw r;
    return r ?? { id: 0 };
  });
}
const gravados = () => api.mock.calls.filter(c => c[1]?.method === "POST").map(c => [c[0], JSON.parse(c[1].body)]);
const leituras = () => api.mock.calls.filter(c => c[1]?.method !== "POST").length;
const bloco = (nome: string) => screen.getByRole("region", { name: nome });
const linhasDe = (nome: string) => within(bloco(nome)).getAllByRole("row").slice(1);
const botoes = (l: HTMLElement) => within(l).queryAllByRole("button").map(b => b.textContent);

describe("Triagem: decidir pela tela", () => {
  const triagem = (extra: Partial<RespostaTriagem> = {}): RespostaTriagem => ({
    leitura: leitura(), decisoes: "dashboard", pode_decidir: true, motivos_descarte: MOTIVOS,
    contagens: { recomendadas: 0, favoritas: 0, novas: 0, novas_desde: null, por_orgao: [] }, favoritas: [], recomendadas: [], ...extra });
  const NOVE = linha(4, { recomendada: recomendada(9) });
  const SETE = linha(5, { recomendada: recomendada(7), link: "" });
  // longe do prazo, com uma mudança que ninguém viu e outra já vista
  const COM_MUDANCA = linha(1, { favorita: favorita({
    prazos: [prazo("Sessão", "2027-03-01", 65, null)], mudancas: [mudanca("2026-11-20", "Sessão adiada"), mudanca("2026-11-18", "Novo anexo", true)] }) });
  // só o prazo a traz: a mudança dela já foi vista
  const SO_PRAZO = linha(2, { favorita: favorita({
    prazos: [prazo("Sessão", "2026-11-27", 3, "critico")], mudancas: [mudanca("2026-11-18", "Novo anexo", true)] }) });

  beforeEach(() => { vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(HOJE_DO_TESTE); });
  afterEach(() => { cleanup(); api.mockReset(); vi.useRealTimers(); vi.unstubAllGlobals(); });

  it("com `pode_decidir`, cada recomendada tem Favoritar (a ação principal), Analisar o edital e Descartar", async () => {
    servidor([triagem({ recomendadas: [NOVE, SETE] })]);
    render(<LicitacoesTriagem />);
    await screen.findByRole("region", { name: "Recomendadas a decidir" });
    expect(within(bloco("Recomendadas a decidir")).getAllByRole("columnheader").map(c => c.textContent)).toEqual(
      ["Nota", "Licitação", "Tipo de obra", "Local", "Valor", "Sessão", "Decisão"]);
    const [nove, sete] = linhasDe("Recomendadas a decidir");
    expect(botoes(nove)).toEqual(["Favoritar", "Analisar o edital", "Descartar"]);
    // botão de linha de tabela; um só principal por linha; o nome diz de qual licitação é
    expect(within(nove).getAllByRole("button").map(b => b.className)).toEqual(
      ["btn btn--pequeno btn--primario", "btn btn--pequeno", "btn btn--pequeno"]);
    expect(within(sete).getByRole("button", { name: "Favoritar: PME · CE 005/2026" })).toBeTruthy();
    expect(within(nove).getByRole("button", { name: "Descartar: PME · CE 004/2026" })).toBeTruthy();
  });

  it("depois do corte, quem só vê não tem botão nem a coluna das decisões", async () => {
    servidor([triagem({ pode_decidir: false, favoritas: [COM_MUDANCA], recomendadas: [NOVE] })]);
    render(<LicitacoesTriagem />);
    await screen.findByRole("region", { name: "Recomendadas a decidir" });
    expect(screen.queryAllByRole("button")).toHaveLength(0);
    expect(screen.queryByRole("columnheader", { name: "Decisão" })).toBeNull();
  });

  it("Favoritar grava e a linha sai pelo que o servidor diz na leitura seguinte", async () => {
    servidor([triagem({ recomendadas: [NOVE, SETE] }), triagem({ recomendadas: [SETE] })]);
    render(<LicitacoesTriagem />);
    fireEvent.click(await screen.findByRole("button", { name: "Favoritar: PME · CE 004/2026" }));
    await waitFor(() => expect(linhasDe("Recomendadas a decidir")).toHaveLength(1));
    expect(gravados()).toEqual([["/api/licitacoes/4/favorita", {}]]);
    expect(leituras()).toBe(2);
    expect(within(linhasDe("Recomendadas a decidir")[0]).getByRole("rowheader").textContent).toContain("CE 005/2026");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("a recusa do servidor aparece junto da linha, nas palavras dele, e a lista não muda", async () => {
    servidor([triagem({ recomendadas: [NOVE, SETE] })],
      { "/api/licitacoes/4/favorita": new ApiErro(409, "Esta licitação acabou de ser decidida por outra pessoa: atualize a página") });
    render(<LicitacoesTriagem />);
    fireEvent.click(await screen.findByRole("button", { name: "Favoritar: PME · CE 004/2026" }));
    const [nove, sete] = linhasDe("Recomendadas a decidir");
    expect((await within(nove).findByRole("alert")).textContent).toBe("Esta licitação acabou de ser decidida por outra pessoa: atualize a página");
    expect(within(sete).queryByRole("alert")).toBeNull();
    expect(leituras()).toBe(1);
    // o botão volta a valer depois da recusa
    expect((within(nove).getByRole("button", { name: /^Favoritar/ }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("Descartar abre a janela com os motivos do servidor, grava o escolhido e a linha sai", async () => {
    servidor([triagem({ recomendadas: [NOVE, SETE] }), triagem({ recomendadas: [SETE] })]);
    render(<LicitacoesTriagem />);
    fireEvent.click(await screen.findByRole("button", { name: "Descartar: PME · CE 004/2026" }));
    const janela = screen.getByRole("dialog", { name: "Descartar a licitação" });
    expect(janela.querySelector(".lic-janela__nome")!.textContent).toBe("PME · CE 004/2026Objeto inventado 4");
    // os motivos são os que o servidor mandou, na ordem dele
    expect(within(janela).getAllByRole("radio").map(r => r.closest("label")!.textContent!.trim())).toEqual(
      ["Tipo de obra", "Local", "Valor", "Órgão", "Outro"]);
    expect(gravados()).toEqual([]);
    fireEvent.click(within(janela).getByRole("radio", { name: "Órgão" }));
    fireEvent.click(within(janela).getByRole("button", { name: "Descartar" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(gravados()).toEqual([["/api/licitacoes/4/descarte", { motivo: "órgão" }]]);
    expect(linhasDe("Recomendadas a decidir")).toHaveLength(1);
  });

  it("a recusa do descarte aparece dentro da janela, que continua aberta; Cancelar fecha sem gravar mais nada", async () => {
    servidor([triagem({ recomendadas: [NOVE] })], { "/api/licitacoes/4/descarte": new ApiErro(422, "Escolha o motivo do descarte") });
    render(<LicitacoesTriagem />);
    fireEvent.click(await screen.findByRole("button", { name: "Descartar: PME · CE 004/2026" }));
    const janela = screen.getByRole("dialog");
    // sem motivo escolhido, quem diz é o servidor
    fireEvent.click(within(janela).getByRole("button", { name: "Descartar" }));
    expect((await within(janela).findByRole("alert")).textContent).toBe("Escolha o motivo do descarte");
    expect(gravados()).toEqual([["/api/licitacoes/4/descarte", { motivo: "" }]]);
    // a recusa é da janela: não se repete na linha
    expect(within(linhasDe("Recomendadas a decidir")[0]).queryByRole("alert")).toBeNull();
    fireEvent.click(within(janela).getByRole("button", { name: "Cancelar" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(leituras()).toBe(1);
  });

  it("Analisar o edital grava, lê de novo e mostra o comando que o servidor devolveu, com o botão de copiar", async () => {
    const copiar = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText: copiar } });
    servidor([triagem({ recomendadas: [NOVE, SETE] }), triagem({ recomendadas: [SETE] })],
      { "/api/licitacoes/4/analise": { id: 4, favoritou: true, comando: "/analisar-edital https://exemplo.com.br/editais/4", aviso: null } });
    render(<LicitacoesTriagem />);
    fireEvent.click(await screen.findByRole("button", { name: "Analisar o edital: PME · CE 004/2026" }));
    const janela = await screen.findByRole("dialog", { name: "Analisar o edital" });
    expect(gravados()).toEqual([["/api/licitacoes/4/analise", {}]]);
    // a linha já saiu da fila (virou favorita), e a janela continua aberta
    expect(linhasDe("Recomendadas a decidir")).toHaveLength(1);
    const comando = within(janela).getByLabelText("Comando para a sessão de análise") as HTMLInputElement;
    expect([comando.value, comando.readOnly]).toEqual(["/analisar-edital https://exemplo.com.br/editais/4", true]);
    expect(within(janela).getByRole("status").textContent).toBe("A licitação agora é favorita.");
    expect(janela.querySelector(".aviso")).toBeNull();
    fireEvent.click(within(janela).getByRole("button", { name: "Copiar" }));
    await waitFor(() => expect(within(janela).getByRole("status").textContent).toBe("Comando copiado."));
    expect(copiar).toHaveBeenCalledWith("/analisar-edital https://exemplo.com.br/editais/4");
    // a janela fecha pelo botão de fechar dela (ou pelo Esc)
    fireEvent.click(within(janela).getByRole("button", { name: "Fechar" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("sem link de edital o comando vem sem ele, com o aviso do servidor", async () => {
    servidor([triagem({ recomendadas: [SETE] }), triagem()], { "/api/licitacoes/5/analise": {
      id: 5, favoritou: false, comando: "/analisar-edital", aviso: "Esta licitação não tem link de edital: baixe o edital e passe o arquivo ao comando" } });
    render(<LicitacoesTriagem />);
    fireEvent.click(await screen.findByRole("button", { name: "Analisar o edital: PME · CE 005/2026" }));
    const janela = await screen.findByRole("dialog", { name: "Analisar o edital" });
    expect((within(janela).getByLabelText("Comando para a sessão de análise") as HTMLInputElement).value).toBe("/analisar-edital");
    expect(janela.querySelector(".aviso")!.textContent).toBe("Atenção: Esta licitação não tem link de edital: baixe o edital e passe o arquivo ao comando.");
    expect(janela.querySelector(".aviso")!.className).toBe("aviso");
    // já era favorita: nada a dizer além do comando
    expect(within(janela).getByRole("status").textContent).toBe("");
  });

  it("Marcar como vista só existe na favorita com mudança que ninguém viu; grava e lê de novo", async () => {
    const vista = { ...COM_MUDANCA, favorita: { ...COM_MUDANCA.favorita!, mudancas_novas: 0, mudancas: COM_MUDANCA.favorita!.mudancas.map(m => ({ ...m, vista: true })) } };
    servidor([triagem({ favoritas: [SO_PRAZO, COM_MUDANCA] }), triagem({ favoritas: [SO_PRAZO, vista] })]);
    render(<LicitacoesTriagem />);
    await screen.findByRole("region", { name: "Favoritas que pedem atenção" });
    const [soPrazo, comMudanca] = linhasDe("Favoritas que pedem atenção");
    expect(botoes(soPrazo)).toEqual([]);
    expect(botoes(comMudanca)).toEqual(["Marcar como vista"]);
    // a mudança já vista fica na letra de apoio, e o leitor de tela ouve que foi vista
    expect(soPrazo.querySelector("td[data-rotulo='Mudança']")!.textContent).toBe("Novo anexo 18/11 (vista)");
    expect(soPrazo.querySelector("td[data-rotulo='Mudança'] > .lic-fraco")).not.toBeNull();
    expect(comMudanca.querySelector("td[data-rotulo='Mudança']")!.textContent).toBe("Sessão adiada 20/11");
    fireEvent.click(within(comMudanca).getByRole("button", { name: "Marcar como vista: PME · CE 001/2026" }));
    // sem mudança nova em linha nenhuma, a coluna das decisões some
    await waitFor(() => expect(screen.queryByRole("columnheader", { name: "Decisão" })).toBeNull());
    // o pedido leva as chaves das mudanças não vistas que a linha mostrou
    expect(gravados()).toEqual([["/api/licitacoes/1/mudancas-vistas", { chaves: ["2026-11-20-Sessão adiada"] }]]);
    expect(screen.queryAllByRole("button")).toHaveLength(0);
  });

  it("a mudança da linha são as que ninguém viu, mesmo com a mais recente já vista; o botão manda as chaves delas", async () => {
    // o radar trouxe depois uma mudança do mesmo dia da que já foi vista e outra de um dia anterior
    const VOLTOU = linha(3, { favorita: favorita({ prazos: [prazo("Sessão", "2027-03-01", 65, null)], mudancas: [
      mudanca("2026-11-23", "Sessão adiada", true), mudanca("2026-11-23", "Retificada"), mudanca("2026-11-21", "Suspensa")] }) });
    servidor([triagem({ favoritas: [VOLTOU] }), triagem()]);
    render(<LicitacoesTriagem />);
    await screen.findByRole("region", { name: "Favoritas que pedem atenção" });
    const [voltou] = linhasDe("Favoritas que pedem atenção");
    expect([...voltou.querySelectorAll("td[data-rotulo='Mudança'] li")].map(li => li.textContent)).toEqual(["Retificada 23/11", "Suspensa 21/11"]);
    fireEvent.click(within(voltou).getByRole("button", { name: "Marcar como vistas: PME · CE 003/2026" }));
    await waitFor(() => expect(leituras()).toBe(2));
    expect(gravados()).toEqual([["/api/licitacoes/3/mudancas-vistas", { chaves: ["2026-11-23-Retificada", "2026-11-21-Suspensa"] }]]);
  });

  it("antes do corte ninguém marca nada: a linha mostra só a mudança mais recente", async () => {
    servidor([triagem({ decisoes: "radar", pode_decidir: false, favoritas: [linha(3, { favorita: favorita({ mudancas: [
      mudanca("2026-11-23", "Sessão adiada"), mudanca("2026-11-21", "Suspensa")] }) })] })]);
    render(<LicitacoesTriagem />);
    await screen.findByRole("region", { name: "Favoritas que pedem atenção" });
    expect(linhasDe("Favoritas que pedem atenção")[0].querySelector("td[data-rotulo='Mudança']")!.textContent).toBe("Sessão adiada 23/11");
  });

  it("a leitura que falha depois da decisão é dita, e a página continua com o que tinha", async () => {
    let n = 0;
    api.mockImplementation(async (_caminho: string, opcoes?: RequestInit) => {
      if (opcoes?.method === "POST") return { id: 4 };
      if (n++ === 0) return triagem({ recomendadas: [NOVE] });
      throw new ApiErro(0, "Sem conexão com o servidor.");
    });
    render(<LicitacoesTriagem />);
    fireEvent.click(await screen.findByRole("button", { name: "Favoritar: PME · CE 004/2026" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Não foi possível atualizar as licitações: Sem conexão com o servidor.");
    expect(linhasDe("Recomendadas a decidir")).toHaveLength(1);
  });
});

describe("Favoritas: decidir pela tela", () => {
  const SEM_DOSSIE = linha(2, { favorita: favorita({ prazos: [prazo("Sessão", "2026-12-10", 12, "breve")] }) });
  const COM_DOSSIE = linha(1, { sigla_orgao: "SEOBRAS-EX", favorita: favorita({
    etapa: "em_analise", etapa_rotulo: "Em análise", etapa_do_dossie: true, dossie: "2026-CE-001-exemplo-pavimentacao", selos: ["Diretoria: interesse"] }) });
  // pasta de dossiê sem etapa nele: a etapa é a escolhida na tela, e o que o dossiê diz continua ao lado
  const DOSSIE_SEM_ETAPA = linha(3, { favorita: favorita({ dossie: "2026-CE-003-exemplo-terminal", selos: ["Suspensa"] }) });
  const ENCERRADA = linha(8, { data_sessao: "2026-11-05", dias_uteis: -13, prazo: null, encerrada: true,
    favorita: favorita({ prazos: [prazo("Sessão", "2026-11-05", -13, null, { passado: true })] }) });
  const favoritas = (linhas = [COM_DOSSIE, SEM_DOSSIE, DOSSIE_SEM_ETAPA, ENCERRADA], extra: Partial<RespostaFavoritas> = {}): RespostaFavoritas => ({
    leitura: leitura(), decisoes: "dashboard", pode_decidir: true, etapas: ETAPAS, favoritas: linhas, ...extra });
  const etapa = (l: HTMLElement) => l.querySelector<HTMLElement>("td[data-rotulo='Etapa']")!;

  beforeEach(() => { vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(HOJE_DO_TESTE); });
  afterEach(() => { cleanup(); api.mockReset(); vi.useRealTimers(); });

  it("a etapa troca num controle com as etapas do servidor, só na favorita sem etapa de dossiê", async () => {
    servidor([favoritas()]);
    render(<LicitacoesFavoritas />);
    await screen.findByRole("region", { name: "Favoritas em aberto" });
    expect(within(bloco("Favoritas em aberto")).getAllByRole("columnheader").map(c => c.textContent)).toEqual(
      ["Licitação", "Etapa", "Prazos", "Valor", "Mudanças", "Decisão"]);
    const [comDossie, semDossie, dossieSemEtapa] = linhasDe("Favoritas em aberto");
    // com etapa de dossiê: só mostra, e diz de onde vem
    expect(within(comDossie).queryByRole("combobox")).toBeNull();
    expect(etapa(comDossie).textContent).toBe("Em análiseDiretoria: interessedo dossiê");
    // sem: o controle, com a etapa de hoje escolhida e as opções na ordem do servidor
    const escolha = within(semDossie).getByRole("combobox", { name: "Etapa: PME · CE 002/2026" }) as HTMLSelectElement;
    expect(escolha.value).toBe("acompanhando");
    expect([...escolha.options].map(o => [o.value, o.textContent])).toEqual(ETAPAS.map(e => [e.etapa, e.rotulo]));
    expect(within(dossieSemEtapa).getByRole("combobox")).toBeTruthy();
    expect([...etapa(dossieSemEtapa).querySelectorAll(".selo")].map(s => s.textContent)).toEqual(["Suspensa"]);
  });

  it("trocar a etapa grava a escolhida e lê de novo; a recusa aparece junto da linha", async () => {
    const depois = { ...SEM_DOSSIE, favorita: { ...SEM_DOSSIE.favorita!, etapa: "proposta_enviada", etapa_rotulo: "Proposta enviada" } };
    servidor([favoritas(), favoritas([COM_DOSSIE, depois, DOSSIE_SEM_ETAPA])],
      { "/api/licitacoes/3/etapa": new ApiErro(409, "A etapa desta licitação vem do dossiê e não se muda pela tela") });
    render(<LicitacoesFavoritas />);
    await screen.findByRole("region", { name: "Favoritas em aberto" });
    fireEvent.change(within(linhasDe("Favoritas em aberto")[1]).getByRole("combobox"), { target: { value: "proposta_enviada" } });
    await waitFor(() => expect(leituras()).toBe(2));
    expect(gravados()).toEqual([["/api/licitacoes/2/etapa", { etapa: "proposta_enviada" }]]);
    await waitFor(() => expect((within(linhasDe("Favoritas em aberto")[1]).getByRole("combobox") as HTMLSelectElement).value).toBe("proposta_enviada"));

    fireEvent.change(within(linhasDe("Favoritas em aberto")[2]).getByRole("combobox"), { target: { value: "vencida" } });
    expect((await within(linhasDe("Favoritas em aberto")[2]).findByRole("alert")).textContent).toBe(
      "A etapa desta licitação vem do dossiê e não se muda pela tela");
    // a etapa mostrada continua a do servidor
    expect((within(linhasDe("Favoritas em aberto")[2]).getByRole("combobox") as HTMLSelectElement).value).toBe("acompanhando");
    expect(leituras()).toBe(2);
  });

  it("Tirar a favorita pede confirmação: Cancelar não grava; confirmar grava, lê de novo e a linha sai", async () => {
    servidor([favoritas(), favoritas([COM_DOSSIE, DOSSIE_SEM_ETAPA, ENCERRADA])]);
    render(<LicitacoesFavoritas />);
    fireEvent.click(await screen.findByRole("button", { name: "Tirar a favorita: PME · CE 002/2026" }));
    let janela = screen.getByRole("dialog", { name: "Tirar a favorita" });
    expect(janela.querySelector(".lic-janela__nome")!.textContent).toBe("PME · CE 002/2026Objeto inventado 2");
    fireEvent.click(within(janela).getByRole("button", { name: "Cancelar" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(gravados()).toEqual([]);

    fireEvent.click(screen.getByRole("button", { name: "Tirar a favorita: PME · CE 002/2026" }));
    janela = screen.getByRole("dialog", { name: "Tirar a favorita" });
    fireEvent.click(within(janela).getByRole("button", { name: "Tirar a favorita" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(gravados()).toEqual([["/api/licitacoes/2/favorita/remover", {}]]);
    expect(linhasDe("Favoritas em aberto")).toHaveLength(2);
  });

  it("a recusa de tirar a favorita aparece na janela; a encerrada também se decide", async () => {
    servidor([favoritas()], { "/api/licitacoes/8/favorita/remover": new ApiErro(409, "Esta licitação não é favorita") });
    render(<LicitacoesFavoritas />);
    await screen.findByRole("region", { name: "Favoritas em aberto" });
    const encerradas = screen.getByText("Encerradas").closest("details")!;
    fireEvent.click(within(encerradas).getByRole("button", { name: "Tirar a favorita: PME · CE 008/2026", hidden: true }));
    const janela = screen.getByRole("dialog", { name: "Tirar a favorita" });
    fireEvent.click(within(janela).getByRole("button", { name: "Tirar a favorita" }));
    expect((await within(janela).findByRole("alert")).textContent).toBe("Esta licitação não é favorita");
    expect(within(encerradas).queryByRole("alert", { hidden: true })).toBeNull();
    expect(within(encerradas).getByRole("combobox", { hidden: true })).toBeTruthy();
  });

  it("antes do corte, ou sem poder decidir, a lista é só de leitura", async () => {
    servidor([favoritas(undefined, { pode_decidir: false })]);
    render(<LicitacoesFavoritas />);
    await screen.findByRole("region", { name: "Favoritas em aberto" });
    expect(screen.queryAllByRole("button", { hidden: true })).toHaveLength(0);
    expect(screen.queryAllByRole("combobox", { hidden: true })).toHaveLength(0);
    expect(etapa(linhasDe("Favoritas em aberto")[0]).textContent).toBe("Em análiseDiretoria: interesse");
  });
});
