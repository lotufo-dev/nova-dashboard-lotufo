/// <reference types="node" />
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import SigaPagina from "./SigaPagina";
import type { Movimentacao, PainelSiga, ProcessoSiga, Robo, TipoMovimentacao } from "./siga";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

// 28/10/2026, 11h30 em Cuiaba. Pessoas, obras e processos fictícios.
const tipoDe = (evento: string): TipoMovimentacao => {
  const e = evento.toLowerCase();
  return e.startsWith("transfer") ? "transferencia" : e.startsWith("recebimento") ? "recebimento"
    : e.startsWith("juntada") ? "juntada" : e.startsWith("marca") ? "marcacao" : "outras";
};
const AGORA = new Date("2026-10-28T15:30:00Z");
const mov = (data: string, evento: string, extra: Partial<Movimentacao> = {}): Movimentacao => ({
  data, evento, tipo: tipoDe(evento), cad_lotacao: "PROTOC/ORGAO", cad_pessoa: "Beltrano", at_lotacao: "COFIN/ORGAO", at_pessoa: "Fulano", ...extra });
const processo = (extra: Partial<ProcessoSiga>): ProcessoSiga => ({
  id: 1, codigo: null, link: null, numero: null, nome: null, contrato_id: null, obra: null, medicao_id: null,
  categoria: extra.medicao_id ? "medicoes" : "outros", complemento: null, o_que_e: extra.medicao_titulo ?? "Outro",
  medicao_titulo: null, protocolo_id: null, situacao: "1º Volume - Aguardando Andamento [COFIN, [X]]", encerrado: null, setor: "COFIN",
  caixa_entrada: false, com_quem: "Fulano", desde: "2026-10-20T10:00:00-04:00", dias_uteis: 6, hoje: 0,
  ultima: mov("2026-10-20T10:00:00-04:00", "Recebimento"), protocolado_em: "2026-10-01T08:00:00-04:00",
  movimentacoes: [mov("2026-10-20T10:00:00-04:00", "Recebimento")], ...extra });

const ALFA = processo({
  id: 1, codigo: "ABC123", link: "https://siga.exemplo.com.br/acompanhar?n=ABC123", numero: "ORGAO-PRO-2026/00001",
  nome: "Processo Alfa", contrato_id: 7, obra: "Obra Alfa", medicao_id: 31, medicao_titulo: "7ª Medição", protocolo_id: 5,
  desde: "2026-10-28T08:00:00-04:00", dias_uteis: 0, hoje: 1,
  ultima: mov("2026-10-28T09:30:00-04:00", "Recebimento | texto do órgão"),
  movimentacoes: [
    mov("2026-10-20T10:00:00-04:00", "Cadastro", { at_pessoa: "Beltrano", at_lotacao: "PROTOC/ORGAO" }),
    mov("2026-10-28T08:00:00-04:00", "Recebimento", { cad_lotacao: "COFIN/ORGAO", cad_pessoa: "Fulano" }),
    mov("2026-10-25T08:00:00-04:00", "Transferência", { cad_pessoa: "Sicrana", cad_lotacao: "PROTOC/ORGAO", at_lotacao: "GABIN/ORGAO", at_pessoa: "" }),
    mov("2026-10-26T14:10:00-04:00", "Juntada | documento ORGAO-DIC-2026/96012-A", { cad_lotacao: "COFIN/ORGAO", cad_pessoa: "Bruna", at_lotacao: "", at_pessoa: "" }),
    mov("2026-10-27T09:00:00-04:00", "Marcação", { cad_lotacao: "COFIN/ORGAO", cad_pessoa: "Camila", at_lotacao: "GSAGPM/ORGAO", at_pessoa: "Helia" }),
  ] });
const EPSILON = processo({
  id: 2, nome: "Processo Epsilon", contrato_id: 8, obra: "Obra Épsilon", medicao_id: 32, medicao_titulo: "2ª Medição",
  desde: "2026-10-28T11:00:00-04:00", dias_uteis: 0, hoje: 2, ultima: mov("2026-10-28T11:00:00-04:00", "Recebimento") });
const DELTA = processo({
  id: 3, nome: "Processo Delta", contrato_id: 9, obra: "Obra Delta", medicao_id: 33, medicao_titulo: "4ª Medição", dias_uteis: 3 });
const BETA = processo({
  id: 4, nome: "Processo Beta", numero: "ORGAO-PRO-2026/00011", situacao: "2º Volume - Caixa de Entrada [GABIN, [X]]",
  setor: "GABIN", caixa_entrada: true, com_quem: "", dias_uteis: 6 });
const GAMA = processo({ id: 5, nome: "Processo Gama", dias_uteis: 12, setor: "COFIN" });
// 40 movimentações: 20 transferências, 10 recebimentos, 6 juntadas, 3 marcações e 1 anotação; o último recebimento é o do setor atual
const MUITOS = processo({
  id: 6, nome: "Processo Mu", numero: "ORGAO-PRO-2026/00020", setor: "CCONT", desde: "2026-10-23T17:05:00-04:00", dias_uteis: 3,
  movimentacoes: [
    ...Array.from({ length: 20 }, (_, i) => mov(`2026-10-${String(1 + (i % 20)).padStart(2, "0")}T09:00:00-04:00`, "Transferência")),
    ...Array.from({ length: 9 }, (_, i) => mov(`2026-10-${String(2 + i).padStart(2, "0")}T10:00:00-04:00`, "Recebimento")),
    mov("2026-10-23T17:05:00-04:00", "Recebimento", { cad_lotacao: "CCONT/ORGAO", cad_pessoa: "Athayde", at_lotacao: "CCONT/ORGAO", at_pessoa: "Athayde" }),
    ...Array.from({ length: 6 }, (_, i) => mov(`2026-10-${String(5 + i).padStart(2, "0")}T11:00:00-04:00`, "Juntada | documento DOC-0" + i)),
    ...Array.from({ length: 3 }, (_, i) => mov(`2026-10-${String(12 + i).padStart(2, "0")}T12:00:00-04:00`, "Marcação")),
    mov("2026-10-22T08:00:00-04:00", "Anotação"),
  ] });

const PARADO: Robo = { estado: "parado", rodada: null, pedidos: [], avisos: [] };
const painel = (processos: ProcessoSiga[], extra: Partial<PainelSiga> = {}): PainelSiga =>
  ({ lido_em: "2026-10-28T15:00:00+00:00", atrasado: false, processos, pode_atualizar: false, robo: PARADO, ...extra });
const mostrar = (dados: PainelSiga, busca: Record<string, string> = {}) => {
  api.mockResolvedValue(dados);
  return render(<SigaPagina busca={busca} agora={AGORA} />);
};
const linhasDe = (onde: HTMLElement) => within(onde).getAllByRole("row").filter(l => l.classList.contains("sg__linha"));
const nomesEm = (onde: HTMLElement) => linhasDe(onde).map(l => l.getAttribute("aria-label"));
const nomesNaTabela = () => nomesEm(document.body);
const ADITIVO = processo({ id: 21, nome: "Nome do robô", contrato_id: 7, obra: "Obra Alfa", categoria: "aditivos", complemento: "de prazo",
  o_que_e: "Aditivo de prazo", dias_uteis: 2 });
const ADITIVO_PARADO = processo({ id: 22, contrato_id: 9, obra: "Obra Delta", categoria: "aditivos", o_que_e: "Aditivo", dias_uteis: 8 });
const INDENIZATORIO = processo({ id: 23, contrato_id: 8, obra: "Obra Épsilon", categoria: "indenizatorios", o_que_e: "Indenizatório", dias_uteis: 20 });

describe("SigaPagina", () => {
  afterEach(() => { cleanup(); api.mockReset(); window.history.replaceState(null, "", "/"); });

  it("uma tabela só, com uma seção por categoria na ordem fixa, cada uma do mais parado ao menos; sem coluna Hoje nem painel lateral (#663)", async () => {
    mostrar(painel([ALFA, ADITIVO, INDENIZATORIO, DELTA, EPSILON, BETA, GAMA, ADITIVO_PARADO]));
    const grade = await screen.findByRole("grid");
    expect(screen.getAllByRole("grid")).toHaveLength(1);
    const secoes = within(grade).getAllByRole("rowgroup").filter(g => g.tagName === "TBODY");
    expect(secoes.map(s => s.getAttribute("aria-label"))).toEqual(["Medições", "Aditivos", "Indenizatórios", "Outros"]);
    expect(secoes.map(s => s.querySelector(".sg__secao th")?.textContent)).toEqual(["Medições", "Aditivos", "Indenizatórios", "Outros"]);
    expect(secoes.map(nomesEm)).toEqual([
      ["Obra Delta · 4ª Medição", "Obra Alfa · 7ª Medição", "Obra Épsilon · 2ª Medição"],
      ["Obra Delta · Aditivo", "Obra Alfa · Aditivo de prazo"],
      ["Obra Épsilon · Indenizatório"],
      ["Processo Gama", "Processo Beta"]]);
    expect(within(grade.querySelector("thead") as HTMLElement).getAllByRole("columnheader").map(c => c.textContent)).toEqual(
      ["Processo", "Onde está", "Com quem", "No setor há", "Última movimentação", "Protocolado em", "Abrir"]);
    expect(screen.queryByRole("complementary")).toBeNull();
  });

  it("seção vazia não aparece (#663)", async () => {
    mostrar(painel([ALFA, GAMA]));
    const grade = await screen.findByRole("grid");
    expect(within(grade).getAllByRole("rowgroup").filter(g => g.tagName === "TBODY").map(s => s.getAttribute("aria-label"))).toEqual(["Medições", "Outros"]);
    expect(screen.queryByText("Aditivos")).toBeNull();
    expect(screen.queryByText("Indenizatórios")).toBeNull();
  });

  it("subtítulo com o número de processos e a hora da última leitura; legenda da cor", async () => {
    mostrar(painel([ALFA, BETA]));
    await screen.findByRole("grid");
    expect(screen.getByText("2 processos · última leitura 11:00")).toBeTruthy();
    const legenda = screen.getByRole("list", { name: "Cor do tempo no setor" });
    expect(within(legenda).getAllByRole("listitem").map(li => li.textContent)).toEqual(
      ["andou hoje", "parado há 5 dias úteis ou mais", "10 dias úteis ou mais"]);
  });

  it("Processo: obra em negrito e o que é embaixo (título da medição, 'Aditivo de prazo'); o nome do robô só sem obra; o número não entra no nome (#663)", async () => {
    mostrar(painel([ALFA, BETA, ADITIVO]));
    const alfa = await screen.findByRole("row", { name: "Obra Alfa · 7ª Medição" });
    expect(within(alfa).getByText("Obra Alfa").className).toContain("sg__nome");
    expect(within(alfa).getByText("7ª Medição").className).toContain("sg__fraco");
    expect(within(alfa).queryByRole("link")).toBeNull();
    expect(alfa.textContent).not.toContain("ORGAO-PRO-2026/00001");
    const aditivo = screen.getByRole("row", { name: "Obra Alfa · Aditivo de prazo" });
    expect(within(aditivo).getByText("Aditivo de prazo").className).toContain("sg__fraco");
    expect(aditivo.textContent).not.toContain("Nome do robô");
    const beta = screen.getByRole("row", { name: "Processo Beta" });
    expect(within(beta).getByText("Processo Beta").className).toContain("sg__nome");
  });

  it("cor do tempo no setor: âmbar a partir de 5 dias úteis, vermelho a partir de 10, nenhuma antes; verde 'hoje' quando andou hoje", async () => {
    mostrar(painel([ALFA, DELTA, BETA, GAMA]));
    await screen.findByRole("grid");
    expect(screen.getByText("12 dias úteis").className).toContain("sg__dias--acao");
    expect(screen.getByText("6 dias úteis").className).toContain("sg__dias--atencao");
    expect(screen.getByText("3 dias úteis").className).not.toMatch(/sg__dias--(atencao|acao)/);
    const hoje = screen.getByText("hoje");
    expect(hoje.className).toContain("sg__dias--hoje");
    expect(within(screen.getByRole("row", { name: /Obra Alfa/ })).getByText("hoje")).toBe(hoje);
  });

  it("No setor há: minutos e horas antes de um dia útil, para quem não andou hoje", async () => {
    mostrar(painel([processo({ id: 7, nome: "Mi", dias_uteis: 0, hoje: 0, desde: "2026-10-28T11:00:00-04:00" }),
      processo({ id: 8, nome: "Ho", dias_uteis: 0, hoje: 0, desde: "2026-10-28T08:00:00-04:00" })]));
    await screen.findByRole("grid");
    expect(screen.getByText("3 h")).toBeTruthy();       // desde 08h00, agora 11h30
    expect(screen.getByText("30 min")).toBeTruthy();    // desde 11h00
  });

  it("Onde está: setor, caixa de entrada e volume; Última movimentação com dia/mês e o evento sem o texto depois de ' |'; Protocolado em", async () => {
    mostrar(painel([ALFA, BETA]));
    const beta = await screen.findByRole("row", { name: /Processo Beta/ });
    expect(within(beta).getByText("GABIN")).toBeTruthy();
    expect(within(beta).getByText("caixa de entrada")).toBeTruthy();
    expect(within(beta).getByText("(2º Volume)")).toBeTruthy();
    const alfa = screen.getByRole("row", { name: /Obra Alfa/ });
    expect(within(alfa).getByText("28/10")).toBeTruthy();
    expect(within(alfa).getByText("Recebimento")).toBeTruthy();
    expect(within(alfa).queryByText(/texto do órgão/)).toBeNull();
    expect(within(alfa).getByText("Fulano")).toBeTruthy();                // Com quem
    expect(within(alfa).getByText("01/10/2026")).toBeTruthy();            // Protocolado em
  });

  it("a 1024 px o cabeçalho quebra entre palavras em vez de invadir a coluna vizinha e a data não quebra (#650)", async () => {
    // o jsdom nao mede layout: aqui so' a presenca das regras e das classes; a medida foi conferida no navegador
    const css = readFileSync(join(process.cwd(), "src", "siga.css"), "utf8").split("@media")[0];
    expect(css).not.toMatch(/\.sg__tabela th\s*\{[^}]*white-space:\s*nowrap/);
    expect(css).toMatch(/\.sg__tabela td\.num\s*\{[^}]*white-space:\s*nowrap/);
    const largura = (col: string) => Number(new RegExp(`\\.sg__c-${col}\\s*\\{\\s*width:\\s*(\\d+)%`).exec(css)?.[1]);
    const colunas = ["proc", "onde", "quem", "setor", "ultima", "prot", "seta"];
    expect(colunas.reduce((soma, c) => soma + largura(c), 0)).toBe(100);
    expect(largura("prot")).toBeGreaterThanOrEqual(16);       // "DD/MM/AAAA" numa linha na tabela de ~718 px
    mostrar(painel([ALFA]));
    const alfa = await screen.findByRole("row", { name: /Obra Alfa/ });
    expect(within(alfa).getByText("01/10/2026").className).toBe("num");
    expect(document.querySelectorAll("colgroup col")).toHaveLength(7);
  });

  it("clicar na linha, ou Enter nela, abre o histórico do processo (?processo=)", async () => {
    mostrar(painel([ALFA, BETA]));
    fireEvent.click(await screen.findByRole("row", { name: /Processo Beta/ }));
    expect(window.location.pathname + window.location.search).toBe("/siga?processo=4");
    window.history.replaceState(null, "", "/");
    fireEvent.keyDown(screen.getByRole("row", { name: /Obra Alfa/ }), { key: "Enter" });
    expect(window.location.search).toBe("?processo=1");
  });

  it("?processo= abre o histórico desse processo; id que não existe cai na tabela", async () => {
    const { unmount } = mostrar(painel([ALFA, DELTA]), { processo: String(DELTA.id) });
    expect((await screen.findByRole("heading", { level: 1 })).textContent).toBe("Histórico · Obra Delta · 4ª Medição");
    expect(screen.queryByRole("table", { name: /Processos/ })).toBeNull();
    unmount();
    window.history.replaceState(null, "", "/siga?processo=999");
    mostrar(painel([ALFA, DELTA]), { processo: "999" });
    expect(await screen.findByRole("grid")).toBeTruthy();
    expect(window.location.search).toBe("");   // sai o ?processo= que nao existe
  });

  it("sem nenhum processo: só a linha 'Nenhum processo acompanhado.'", async () => {
    mostrar(painel([], { lido_em: null }));
    expect(await screen.findByText("Nenhum processo acompanhado.")).toBeTruthy();
    expect(screen.getByText("0 processos")).toBeTruthy();
    expect(screen.queryByRole("grid")).toBeNull();
  });

  it("atrasado avisa desde quando; em dia não avisa", async () => {
    const { unmount } = mostrar(painel([ALFA], { atrasado: true, lido_em: "2026-10-28T12:00:00+00:00" }));
    expect(await screen.findByText("1 processo · última leitura 08:00")).toBeTruthy();
    expect(screen.getByText("O monitor do SIGA não lê desde 28/10 08:00.")).toBeTruthy();
    unmount();
    mostrar(painel([ALFA]));
    await screen.findByRole("grid");
    expect(screen.queryByText(/O monitor do SIGA não lê/)).toBeNull();
  });

  it("rele de hora em hora (#657); o aviso de atraso aparece quando a resposta nova o traz; ao sair, para", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      mostrar(painel([ALFA, BETA]));
      await screen.findByRole("grid");
      expect(api).toHaveBeenCalledTimes(1);
      expect(screen.queryByText(/O monitor do SIGA não lê/)).toBeNull();
      api.mockResolvedValue(painel([ALFA, BETA], { atrasado: true, lido_em: "2026-10-28T12:00:00+00:00" }));
      await vi.advanceTimersByTimeAsync(45 * 60_000);
      expect(api).toHaveBeenCalledTimes(1);
      await vi.advanceTimersByTimeAsync(15 * 60_000);
      expect(api).toHaveBeenCalledTimes(2);
      expect(await screen.findByText("O monitor do SIGA não lê desde 28/10 08:00.")).toBeTruthy();
      cleanup();
      await vi.advanceTimersByTimeAsync(120 * 60_000);
      expect(api).toHaveBeenCalledTimes(2);
    } finally { vi.useRealTimers(); }
  });

  // issue #512: histórico do processo
  const chipsDe = () => within(screen.getByRole("group", { name: "Tipo de movimentação" })).getAllByRole("button").map(b => b.textContent);
  const linhasDoHistorico = () => within(screen.getByRole("table")).getAllByRole("row").slice(1);

  it("histórico: trilha, título, número, total e período, Abrir no SIGA e a medição", async () => {
    mostrar(painel([ALFA]), { processo: "1" });
    const h1 = await screen.findByRole("heading", { level: 1 });
    expect(h1.textContent).toBe("Histórico · Obra Alfa · 7ª Medição");
    const trilha = screen.getByRole("navigation", { name: "Você está em" });
    expect(within(trilha).getByRole("link", { name: "SIGA" }).getAttribute("href")).toBe("/siga");
    expect(trilha.textContent).toContain("Obra Alfa · 7ª Medição");
    expect(within(trilha).getByText("Histórico").getAttribute("aria-current")).toBe("page");
    expect(screen.getByText("ORGAO-PRO-2026/00001 · 5 movimentações · 20/10/2026 a 28/10/2026")).toBeTruthy();
    expect(screen.getByRole("link", { name: /Abrir no SIGA/ }).getAttribute("href")).toBe("https://siga.exemplo.com.br/acompanhar?n=ABC123");
    expect(screen.getByRole("link", { name: "Ver a medição" }).getAttribute("href")).toBe("/obras/7/medicoes/31#passo-5");
  });

  it("histórico: tabela De/Para, a mais recente primeiro, documento na juntada", async () => {
    mostrar(painel([ALFA]), { processo: "1" });
    await screen.findByRole("heading", { level: 1 });
    expect(screen.getAllByRole("columnheader").map(c => c.textContent)).toEqual(["Data e hora", "Evento", "De (setor · pessoa)", "Para (setor · pessoa)"]);
    const linhas = linhasDoHistorico();
    expect(linhas.map(l => within(l).getAllByRole("cell")[1].textContent)).toEqual([
      "Recebimento", "Marcação", "Juntadadocumento ORGAO-DIC-2026/96012-A", "Transferência", "Cadastro"]);
    const transf = linhas[3];
    expect(within(transf).getAllByRole("cell")[2].textContent).toBe("PROTOC · Sicrana");
    expect(within(transf).getAllByRole("cell")[3].textContent).toBe("GABIN");
    expect(within(linhas[1]).getAllByRole("cell")[3].textContent).toBe("GSAGPM · Helia");
    expect(within(linhas[0]).getAllByRole("cell")[0].textContent).toBe("28/10/2026 às 08:00");
  });

  it("histórico: quando a entrada no setor é a transferência, é ela a linha destacada (#650)", async () => {
    const entrada = mov("2026-10-21T09:00:00-04:00", "Transferência");
    const p = processo({ id: 9, nome: "Processo Pi", desde: entrada.data,
      movimentacoes: [entrada, mov("2026-10-22T10:00:00-04:00", "Recebimento"), mov("2026-10-26T10:00:00-04:00", "Recebimento")] });
    mostrar(painel([p]), { processo: "9" });
    await screen.findByRole("heading", { name: /Histórico/ });
    const destacadas = screen.getAllByRole("row").filter(l => l.getAttribute("aria-current") === "true");
    expect(destacadas).toHaveLength(1);
    expect(within(destacadas[0]).getAllByRole("cell")[0].textContent).toBe("21/10/2026 às 09:00");
  });

  it("histórico: traz TODAS as movimentações (não só 30), 15 por vez com 'Ver mais', e a linha do recebimento no setor atual destacada", async () => {
    mostrar(painel([MUITOS]), { processo: "6" });
    await screen.findByRole("heading", { level: 1 });
    expect(screen.getByText("40 movimentações", { exact: false })).toBeTruthy();
    expect(linhasDoHistorico()).toHaveLength(15);
    expect(screen.getByText(/Mostrando 15 de 40/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Ver mais" }));
    expect(linhasDoHistorico()).toHaveLength(40);
    expect(screen.getByText(/Mostrando 40 de 40/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Ver mais" })).toBeNull();
    const destacadas = linhasDoHistorico().filter(l => l.getAttribute("aria-current") === "true");
    expect(destacadas).toHaveLength(1);
    expect(destacadas[0].className).toContain("sg__mov--atual");
    expect(within(destacadas[0]).getAllByRole("cell")[0].textContent).toBe("23/10/2026 às 17:05");
  });

  it("histórico: chips por tipo contam certo e filtram; Todas volta", async () => {
    mostrar(painel([MUITOS]), { processo: "6" });
    await screen.findByRole("heading", { level: 1 });
    expect(chipsDe()).toEqual(["Todas 40", "Transferências 20", "Recebimentos 10", "Juntadas 6", "Marcações 3", "Outras 1"]);
    fireEvent.click(screen.getByRole("button", { name: /Juntadas/ }));
    expect(screen.getByRole("button", { name: /Juntadas/ }).getAttribute("aria-pressed")).toBe("true");
    expect(linhasDoHistorico()).toHaveLength(6);
    expect(screen.getByText(/Mostrando 6 de 6/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Outras/ }));
    expect(linhasDoHistorico().map(l => within(l).getAllByRole("cell")[1].textContent)).toEqual(["Anotação"]);
    fireEvent.click(screen.getByRole("button", { name: /Todas/ }));
    expect(linhasDoHistorico()).toHaveLength(15);
  });

  it("histórico: busca por setor, pessoa ou documento, sem maiúscula nem acento, junto com o tipo", async () => {
    mostrar(painel([MUITOS]), { processo: "6" });
    await screen.findByRole("heading", { level: 1 });
    const busca = screen.getByRole("searchbox", { name: "Buscar setor, pessoa ou documento" });
    fireEvent.change(busca, { target: { value: "ATHAYDE" } });
    expect(linhasDoHistorico()).toHaveLength(1);
    fireEvent.change(busca, { target: { value: "doc-03" } });
    expect(linhasDoHistorico()).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: /Marcações/ }));
    expect(screen.getByText("Nenhuma movimentação encontrada.")).toBeTruthy();
    expect(chipsDe()[0]).toBe("Todas 40");   // a contagem dos chips é do processo, não da busca
  });

  it("histórico: Pedir leitura do processo pede com processo_id", async () => {
    const chamadas: { caminho: string; opts?: RequestInit }[] = [];
    api.mockImplementation(async (caminho: string, opts?: RequestInit) => {
      chamadas.push({ caminho, opts });
      return caminho === "/api/siga" ? painel([ALFA], { pode_atualizar: true }) : { id: 9 };
    });
    render(<SigaPagina busca={{ processo: "1" }} agora={AGORA} />);
    fireEvent.click(await screen.findByRole("button", { name: "Pedir leitura" }));
    await vi.waitFor(() => expect(chamadas.filter(c => c.caminho === "/api/siga")).toHaveLength(2));
    expect(JSON.parse(chamadas.find(c => c.caminho === "/api/siga/atualizar")?.opts?.body as string)).toEqual({ processo_id: ALFA.id });
  });

  // issue #339: link colado na tela SIGA
  const OBRAS = [{ id: 9, orgao: "ORGAO", numero_instrumento: "IC 9/2026", nome_curto: "Obra Zeta", estado: "em_andamento" },
                 { id: 7, orgao: "ORGAO", numero_instrumento: "IC 7/2026", nome_curto: "Obra Alfa", estado: "em_andamento" }];
  const MEDICOES_DA_OBRA = [{ id: 31, numero: 7, tipo: "execucao", estado: "protocolada" }, { id: 30, numero: 6, tipo: "execucao", estado: "recebida" },
                            { id: 32, numero: 7, tipo: "reajuste", estado: "nota_emitida" }, { id: 29, numero: 5, tipo: "execucao", estado: "cancelada" }];
  const NOVO = processo({ id: 8, codigo: "XyZ98765", nome: "Obra Alfa · Aditivo de prazo", contrato_id: 7, obra: "Obra Alfa",
    categoria: "aditivos", complemento: "de prazo", o_que_e: "Aditivo de prazo",
    situacao: null, setor: "", com_quem: "", desde: null, dias_uteis: null, ultima: null, protocolado_em: null, movimentacoes: [] });
  const comFormulario = (antes: ProcessoSiga[], depois: ProcessoSiga[], resposta: () => Promise<unknown>) => {
    const chamadas: { caminho: string; opts?: RequestInit }[] = [];
    let gravado = false;
    api.mockImplementation(async (caminho: string, opts?: RequestInit) => {
      chamadas.push({ caminho, opts });
      if (caminho === "/api/contratos") return OBRAS;
      if (caminho === "/api/contratos/7/medicoes") return MEDICOES_DA_OBRA;
      if (caminho === "/api/siga/processos-avulsos") { const r = await resposta(); gravado = true; return r; }
      return painel(gravado ? depois : antes);
    });
    render(<SigaPagina busca={{}} agora={AGORA} />);
    return chamadas;
  };
  const preencher = async () => {
    fireEvent.click(await screen.findByRole("button", { name: "Acompanhar processo" }));
    const form = screen.getByRole("form", { name: "Acompanhar processo" });
    fireEvent.change(within(form).getByLabelText("Link do SIGA"), { target: { value: "https://siga.exemplo.com.br/acompanhar?n=XyZ98765" } });
    fireEvent.change(within(form).getByLabelText("Categoria"), { target: { value: "aditivos" } });
    await within(form).findByRole("option", { name: "Obra Alfa" });
    fireEvent.change(within(form).getByLabelText("Obra"), { target: { value: "7" } });
    fireEvent.change(within(form).getByLabelText("Complemento"), { target: { value: " de prazo " } });
    fireEvent.click(within(form).getByRole("button", { name: "Acompanhar" }));
    return form;
  };

  it("Acompanhar processo: o formulário pede Categoria, Obra, Complemento e Link, sem campo Nome; envia, a lista recarrega e o novo aparece com o nome montado (#663)", async () => {
    const chamadas = comFormulario([BETA], [BETA, NOVO], async () => ({ id: 8 }));
    const form = await preencher();
    expect(within(form).queryByLabelText("Nome")).toBeNull();
    expect(within(form).queryByLabelText("Medição")).toBeNull();
    expect(Array.from(form.querySelectorAll("#siga-categoria option")).map(o => o.textContent)).toEqual(
      ["Escolha", "Medições", "Aditivos", "Indenizatórios", "Outros"]);
    const linha = await screen.findByRole("row", { name: "Obra Alfa · Aditivo de prazo" });
    expect(linha.closest("tbody")?.getAttribute("aria-label")).toBe("Aditivos");
    expect(screen.queryByRole("form", { name: "Acompanhar processo" })).toBeNull();
    const envio = chamadas.find(c => c.caminho === "/api/siga/processos-avulsos");
    expect(envio?.opts?.method).toBe("POST");
    expect(JSON.parse(envio?.opts?.body as string)).toEqual({
      link: "https://siga.exemplo.com.br/acompanhar?n=XyZ98765", categoria: "aditivos", contrato_id: 7, medicao_id: null, complemento: "de prazo" });
    const opcoes = Array.from(document.querySelectorAll("#siga-obra option")).map(o => o.textContent);
    expect(opcoes).toEqual([]);   // formulario fechado depois de gravar
  });

  it("Medição só aparece na categoria Medições, com as medições abertas da obra, e vai no envio no lugar do complemento (#663)", async () => {
    const chamadas = comFormulario([BETA], [BETA], async () => ({ id: 8 }));
    fireEvent.click(await screen.findByRole("button", { name: "Acompanhar processo" }));
    const form = screen.getByRole("form", { name: "Acompanhar processo" });
    expect(within(form).queryByLabelText("Medição")).toBeNull();
    fireEvent.change(within(form).getByLabelText("Categoria"), { target: { value: "medicoes" } });
    expect(within(form).queryByLabelText("Complemento")).toBeNull();
    await within(form).findByRole("option", { name: "Obra Alfa" });
    fireEvent.change(within(form).getByLabelText("Obra"), { target: { value: "7" } });
    await within(form).findByRole("option", { name: "7ª Medição" });
    expect(Array.from(form.querySelectorAll("#siga-medicao option")).map(o => o.textContent)).toEqual(["Escolha", "7ª Medição", "Reajuste da 7ª Medição"]);
    fireEvent.change(within(form).getByLabelText("Medição"), { target: { value: "31" } });
    fireEvent.change(within(form).getByLabelText("Link do SIGA"), { target: { value: "XyZ98765" } });
    fireEvent.click(within(form).getByRole("button", { name: "Acompanhar" }));
    await vi.waitFor(() => expect(chamadas.some(c => c.caminho === "/api/siga/processos-avulsos")).toBe(true));
    expect(JSON.parse(chamadas.find(c => c.caminho === "/api/siga/processos-avulsos")?.opts?.body as string)).toEqual({
      link: "XyZ98765", categoria: "medicoes", contrato_id: 7, medicao_id: 31, complemento: null });
    // trocar a categoria tira o campo Medição
    fireEvent.click(await screen.findByRole("button", { name: "Acompanhar processo" }));
    const de_novo = screen.getByRole("form", { name: "Acompanhar processo" });
    fireEvent.change(within(de_novo).getByLabelText("Categoria"), { target: { value: "outros" } });
    expect(within(de_novo).queryByLabelText("Medição")).toBeNull();
  });

  it("histórico: quem edita corrige a categoria do processo; passando a Medições liga à medição da obra (#663)", async () => {
    const chamadas: { caminho: string; opts?: RequestInit }[] = [];
    let gravado = false;
    const DEPOIS = { ...ADITIVO, categoria: "medicoes" as const, complemento: null, medicao_id: 31, medicao_titulo: "7ª Medição", o_que_e: "7ª Medição" };
    api.mockImplementation(async (caminho: string, opts?: RequestInit) => {
      chamadas.push({ caminho, opts });
      if (caminho === "/api/contratos") return OBRAS;
      if (caminho === "/api/contratos/7/medicoes") return MEDICOES_DA_OBRA;
      if (caminho === "/api/siga/processos/21/classificacao") { gravado = true; return { id: 21 }; }
      return painel([gravado ? DEPOIS : ADITIVO]);
    });
    render(<SigaPagina busca={{ processo: "21" }} agora={AGORA} />);
    expect((await screen.findByRole("heading", { level: 1 })).textContent).toBe("Histórico · Obra Alfa · Aditivo de prazo");
    fireEvent.click(screen.getByRole("button", { name: "Corrigir categoria" }));
    const form = screen.getByRole("form", { name: "Corrigir categoria" });
    await within(form).findByRole("option", { name: "Obra Alfa" });
    expect((within(form).getByLabelText("Categoria") as HTMLSelectElement).value).toBe("aditivos");
    expect((within(form).getByLabelText("Obra") as HTMLSelectElement).value).toBe("7");
    expect((within(form).getByLabelText("Complemento") as HTMLInputElement).value).toBe("de prazo");
    fireEvent.change(within(form).getByLabelText("Categoria"), { target: { value: "medicoes" } });
    await within(form).findByRole("option", { name: "7ª Medição" });
    fireEvent.change(within(form).getByLabelText("Medição"), { target: { value: "31" } });
    fireEvent.click(within(form).getByRole("button", { name: "Salvar" }));
    await vi.waitFor(() => expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Histórico · Obra Alfa · 7ª Medição"));
    const envio = chamadas.find(c => c.caminho === "/api/siga/processos/21/classificacao");
    expect(envio?.opts?.method).toBe("POST");
    expect(JSON.parse(envio?.opts?.body as string)).toEqual({ categoria: "medicoes", contrato_id: 7, medicao_id: 31, complemento: null });
    expect(screen.queryByRole("form", { name: "Corrigir categoria" })).toBeNull();
    expect(screen.getByRole("status").textContent).toBe("Categoria gravada.");
  });

  it("histórico: erro do servidor ao corrigir aparece em português e o formulário fica aberto (#663)", async () => {
    const { ApiErro } = await import("./api");
    api.mockImplementation(async (caminho: string) => {
      if (caminho === "/api/contratos") return OBRAS;
      if (caminho === "/api/siga/processos/21/classificacao") throw new ApiErro(422, "Escolha a obra do processo");
      return painel([ADITIVO]);
    });
    render(<SigaPagina busca={{ processo: "21" }} agora={AGORA} />);
    fireEvent.click(await screen.findByRole("button", { name: "Corrigir categoria" }));
    const form = screen.getByRole("form", { name: "Corrigir categoria" });
    fireEvent.change(within(form).getByLabelText("Obra"), { target: { value: "" } });
    fireEvent.click(within(form).getByRole("button", { name: "Salvar" }));
    expect((await within(form).findByRole("alert")).textContent).toContain("Escolha a obra do processo");
  });

  it("quem só consulta não vê Corrigir categoria nem Acompanhar processo; processo de protocolo do sistema não tem o que corrigir (#663)", async () => {
    api.mockResolvedValue(painel([ALFA, ADITIVO]));
    const { unmount } = render(<SigaPagina busca={{ processo: "21" }} agora={AGORA} podeEditar={false} />);
    await screen.findByRole("heading", { level: 1 });
    expect(screen.queryByRole("button", { name: "Corrigir categoria" })).toBeNull();
    unmount();
    const tabela = render(<SigaPagina busca={{}} agora={AGORA} podeEditar={false} />);
    await screen.findByRole("grid");
    expect(screen.queryByRole("button", { name: "Acompanhar processo" })).toBeNull();
    tabela.unmount();
    render(<SigaPagina busca={{ processo: String(ALFA.id) }} agora={AGORA} />);   // ALFA tem protocolo_id
    await screen.findByRole("heading", { level: 1 });
    expect(screen.queryByRole("button", { name: "Corrigir categoria" })).toBeNull();
  });

  it("as obras vêm em ordem alfabética depois de 'Sem obra'", async () => {
    comFormulario([BETA], [BETA], async () => ({ id: 8 }));
    fireEvent.click(await screen.findByRole("button", { name: "Acompanhar processo" }));
    await screen.findByRole("option", { name: "Obra Alfa" });
    expect(Array.from(document.querySelectorAll("#siga-obra option")).map(o => o.textContent)).toEqual(["Sem obra", "Obra Alfa", "Obra Zeta"]);
  });

  it("erro do servidor aparece no formulário, em português, e nada muda na lista", async () => {
    const { ApiErro } = await import("./api");
    comFormulario([BETA], [BETA], async () => { throw new ApiErro(409, "Este processo do SIGA já está sendo acompanhado: Processo Beta"); });
    const form = await preencher();
    const alerta = await within(form).findByRole("alert");
    expect(alerta.textContent).toContain("Este processo do SIGA já está sendo acompanhado: Processo Beta");
    expect(nomesNaTabela()).toEqual(["Processo Beta"]);
    expect((within(form).getByLabelText("Complemento") as HTMLInputElement).value).toBe(" de prazo ");
  });

  it("sem nenhum processo o botão Acompanhar processo também aparece", async () => {
    mostrar(painel([], { lido_em: null }));
    await screen.findByText("Nenhum processo acompanhado.");
    expect(screen.getByRole("button", { name: "Acompanhar processo" })).toBeTruthy();
  });

  it("falha ao ler: avisa em português e deixa tentar de novo", async () => {
    api.mockRejectedValue(new Error("Failed to fetch"));
    render(<SigaPagina busca={{}} agora={AGORA} />);
    const alerta = await screen.findByRole("alert");
    expect(alerta.textContent).toContain("Não foi possível ler os processos do SIGA");
    expect(alerta.textContent).not.toContain("Failed to fetch");
    api.mockResolvedValue(painel([ALFA]));
    fireEvent.click(screen.getByRole("button", { name: "Tentar de novo" }));
    expect(await screen.findByRole("grid")).toBeTruthy();
  });

  // issue #343: botoes de atualizar e robo em andamento
  const RODADA = (tipo: "automatica" | "pedido", processos: number[]): Robo => ({
    estado: "lendo", rodada: { id: 4, tipo, iniciada_em: "2026-10-28T15:20:00+00:00", processos }, pedidos: [], avisos: [] });
  const NA_FILA = (processo_id: number | null, travado = false): Robo => ({
    estado: "na_fila", rodada: null, avisos: [],
    pedidos: [{ id: 9, processo_id, usuario: "Fulano", pedido_em: "2026-10-28T15:25:00+00:00", travado }] });
  const botao = (nome: RegExp | string) => screen.getByRole("button", { name: nome }) as HTMLButtonElement;
  
  it("sem o servidor configurado, nenhum botão de atualizar; configurado, 'Pedir leitura' no topo e no histórico do processo", async () => {
    const { unmount } = mostrar(painel([ALFA]));
    await screen.findByRole("grid");
    expect(screen.queryByRole("button", { name: /Atualizar/ })).toBeNull();
    unmount();
    mostrar(painel([ALFA], { pode_atualizar: true }));
    await screen.findByRole("grid");
    expect(botao("Pedir leitura").disabled).toBe(false);
    cleanup();
    mostrar(painel([ALFA], { pode_atualizar: true }), { processo: "1" });
    expect((await screen.findByRole("button", { name: "Pedir leitura" })).hasAttribute("disabled")).toBe(false);
  });

  it("o botão do topo pede a leitura de todos (sem processo_id) e a tela relê", async () => {
    const chamadas: { caminho: string; opts?: RequestInit }[] = [];
    api.mockImplementation(async (caminho: string, opts?: RequestInit) => {
      chamadas.push({ caminho, opts });
      return caminho === "/api/siga" ? painel([ALFA], { pode_atualizar: true }) : { id: 9 };
    });
    render(<SigaPagina busca={{}} agora={AGORA} />);
    fireEvent.click(await screen.findByRole("button", { name: "Pedir leitura" }));
    await vi.waitFor(() => expect(chamadas.filter(c => c.caminho === "/api/siga")).toHaveLength(2));
    const pedidos = chamadas.filter(c => c.caminho === "/api/siga/atualizar");
    expect(pedidos.map(c => c.opts?.method)).toEqual(["POST"]);
    expect(pedidos.map(c => JSON.parse(c.opts?.body as string))).toEqual([{}]);
  });

  it("pedido na fila: o botão vira 'Na fila' desabilitado e o topo mostra a hora do pedido", async () => {
    mostrar(painel([ALFA, DELTA], { pode_atualizar: true, robo: NA_FILA(ALFA.id) }));
    await screen.findByRole("grid");
    expect(botao("Pedir leitura").disabled).toBe(false);           // pedido de um processo nao cobre todos
    expect(screen.getByText((_, el) => el?.tagName === "P" && el.textContent === "Pedido de atualização às 11:25, aguardando o robô")).toBeTruthy();
    cleanup();
    mostrar(painel([ALFA, DELTA], { pode_atualizar: true, robo: NA_FILA(ALFA.id) }), { processo: "1" });
    expect((await screen.findByRole("button", { name: "Na fila" })).hasAttribute("disabled")).toBe(true);
    cleanup();
    mostrar(painel([ALFA, DELTA], { pode_atualizar: true, robo: NA_FILA(ALFA.id) }), { processo: "3" });
    expect(await screen.findByRole("button", { name: "Pedir leitura" })).toBeTruthy();   // o pedido e' de outro processo
  });

  it("pedido de todos na fila: os dois botões ficam 'Na fila'", async () => {
    mostrar(painel([ALFA], { pode_atualizar: true, robo: NA_FILA(null) }));
    await screen.findByRole("grid");
    expect(screen.getByRole("button", { name: "Na fila" })).toBeTruthy();
    cleanup();
    mostrar(painel([ALFA], { pode_atualizar: true, robo: NA_FILA(null) }), { processo: "1" });
    expect((await screen.findByRole("button", { name: "Na fila" })).hasAttribute("disabled")).toBe(true);
  });

  it("rodada pedida na tela: indicador no topo, 'lendo...' só nas linhas da rodada e 'Lendo...' nos botões que ela cobre", async () => {
    mostrar(painel([ALFA, DELTA], { pode_atualizar: true, robo: RODADA("pedido", [ALFA.id]) }));
    await screen.findByRole("grid");
    expect(screen.getByText((_, el) => el?.tagName === "P" && el.textContent === "Robô lendo agora · começou às 11:20 · pedido feito na tela")).toBeTruthy();
    expect(within(screen.getByRole("row", { name: /Obra Alfa/ })).getByText("lendo...")).toBeTruthy();
    expect(within(screen.getByRole("row", { name: /Obra Delta/ })).queryByText("lendo...")).toBeNull();
    expect(screen.getAllByRole("button", { name: "Lendo..." }).every(b => b.hasAttribute("disabled"))).toBe(true);
    expect(screen.queryByRole("button", { name: "Pedir leitura" })).toBeNull();
    cleanup();
    mostrar(painel([ALFA, DELTA], { pode_atualizar: true, robo: RODADA("pedido", [ALFA.id]) }), { processo: "1" });
    expect((await screen.findByRole("button", { name: "Lendo..." })).hasAttribute("disabled")).toBe(true);
    cleanup();
    mostrar(painel([ALFA, DELTA], { pode_atualizar: true, robo: RODADA("pedido", [ALFA.id]) }), { processo: "3" });
    expect(await screen.findByRole("button", { name: "Pedir leitura" })).toBeTruthy();
  });

  it("rodada automática: o topo diz 'rodada automática' e 'Pedir leitura' fica 'Lendo...'", async () => {
    mostrar(painel([ALFA], { pode_atualizar: true, robo: RODADA("automatica", [ALFA.id]) }));
    await screen.findByRole("grid");
    expect(screen.getByText(/rodada automática/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Pedir leitura" })).toBeNull();
    expect(screen.getAllByRole("button", { name: "Lendo..." }).every(b => b.hasAttribute("disabled"))).toBe(true);
  });

  it("avisos do robô: os gerais em vermelho no topo, o de processo na linha dele", async () => {
    const avisos = [
      { tipo: "disparo", processo_id: null, texto: "O Windows não iniciou o robô: acesso negado" },
      { tipo: "sem_inicio", processo_id: null, texto: "O robô não começou. O usuário dele pode estar desconectado do servidor." },
      { tipo: "falha", processo_id: null, texto: "A rodada das 11:00 falhou: SIGA fora do ar" },
      { tipo: "nao_lido", processo_id: DELTA.id, texto: "não lido às 11:00: página não abriu" },
      { tipo: "nao_lidos", processo_id: null, texto: "1 de 2 processos não foram lidos" },
      { tipo: "nao_terminou", processo_id: null, texto: "A rodada das 10:40 não terminou." },
    ];
    mostrar(painel([ALFA, DELTA], { robo: { ...PARADO, avisos } }));
    await screen.findByRole("grid");
    const topo = screen.getAllByRole("alert").map(a => a.textContent ?? "");
    expect(topo.every(t => t.startsWith("Crítico: "))).toBe(true);
    expect(topo.map(t => t.replace("Crítico: ", ""))).toEqual([
      "O Windows não iniciou o robô: acesso negado", "O robô não começou. O usuário dele pode estar desconectado do servidor.",
      "A rodada das 11:00 falhou: SIGA fora do ar", "1 de 2 processos não foram lidos", "A rodada das 10:40 não terminou."]);
    expect(within(screen.getByRole("row", { name: /Obra Delta/ })).getByText("não lido às 11:00: página não abriu")).toBeTruthy();
    expect(within(screen.getByRole("row", { name: /Obra Alfa/ })).queryByText(/não lido/)).toBeNull();
  });

  it("erro do clique aparece em português ao lado do botão", async () => {
    const { ApiErro } = await import("./api");
    api.mockImplementation(async (caminho: string) => {
      if (caminho === "/api/siga/atualizar") throw new ApiErro(503, "Atualizar pelo SIGA não está disponível neste servidor");
      return painel([ALFA], { pode_atualizar: true });
    });
    render(<SigaPagina busca={{}} agora={AGORA} />);
    fireEvent.click(await screen.findByRole("button", { name: "Pedir leitura" }));
    expect((await screen.findByRole("alert")).textContent).toContain("Atualizar pelo SIGA não está disponível neste servidor");
    expect(botao("Pedir leitura").disabled).toBe(false);
  });

  it("Windows recusou: o botão volta a valer para tentar de novo e a tela não relê a cada 5 segundos", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const robo = { ...NA_FILA(ALFA.id, true), avisos: [{ tipo: "disparo", processo_id: null, texto: "O Windows não iniciou o robô: acesso negado" }] };
      mostrar(painel([ALFA], { pode_atualizar: true, robo }), { processo: "1" });
      expect((await screen.findByRole("button", { name: "Pedir leitura" })).hasAttribute("disabled")).toBe(false);
      await vi.advanceTimersByTimeAsync(60_000);
      expect(api).toHaveBeenCalledTimes(1);
    } finally { vi.useRealTimers(); }
  });

  it("com o robô ativo relê a cada 5 segundos; ao terminar mostra a leitura nova e volta a reler de hora em hora", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      mostrar(painel([ALFA], { robo: RODADA("pedido", [ALFA.id]) }));
      await screen.findByText(/Robô lendo agora/);
      expect(api).toHaveBeenCalledTimes(1);
      await vi.advanceTimersByTimeAsync(5_000);
      expect(api).toHaveBeenCalledTimes(2);
      api.mockResolvedValue(painel([ALFA], { lido_em: "2026-10-28T15:28:00+00:00" }));
      await vi.advanceTimersByTimeAsync(5_000);
      expect(await screen.findByText("1 processo · última leitura 11:28")).toBeTruthy();
      const depois = api.mock.calls.length;
      await vi.advanceTimersByTimeAsync(60_000);
      expect(api).toHaveBeenCalledTimes(depois);
      await vi.advanceTimersByTimeAsync(60 * 60_000);
      expect(api.mock.calls.length).toBeGreaterThan(depois);
    } finally { vi.useRealTimers(); }
  });

  // issue #657: processo encerrado (medição recebida ou arquivado) sai da tabela principal
  const RECEBIDO = processo({
    id: 7, nome: "Processo Zeta", contrato_id: 10, obra: "Obra Zeta", medicao_id: 34, medicao_titulo: "5ª Medição",
    dias_uteis: 40, encerrado: "recebida" });
  const ARQUIVADO = processo({
    id: 8, nome: "Processo Eta", setor: "ARQUIVO", dias_uteis: 12, hoje: 1, encerrado: "arquivado",
    ultima: mov("2026-10-28T09:00:00-04:00", "Arquivamento") });
  const encerrados = () => screen.getByRole("group", { name: "Encerrados" }) as HTMLDetailsElement;

  it("encerrados: fora da tabela principal e do contador, na seção 'Encerrados', recolhida, no fim da página", async () => {
    const { container } = mostrar(painel([RECEBIDO, GAMA, ARQUIVADO, DELTA]));
    const grade = await screen.findByRole("grid");
    expect(nomesEm(grade)).toEqual(["Obra Delta · 4ª Medição", "Processo Gama"]);
    // os encerrados continuam numa secao so', sem categoria
    expect(encerrados().querySelector(".sg__secao")).toBeNull();
    expect(screen.getByText("2 processos · última leitura 11:00")).toBeTruthy();
    const secao = encerrados();
    expect(secao.open).toBe(false);
    expect(secao.querySelector("summary")?.textContent).toBe("Encerrados 2");
    expect(within(secao).getAllByRole("row").slice(1).map(l => l.getAttribute("aria-label"))).toEqual(["Obra Zeta · 5ª Medição", "Processo Eta"]);
    expect(within(secao).getAllByRole("columnheader").map(c => c.textContent)).toEqual(
      ["Processo", "Onde está", "Situação", "Última movimentação", "Protocolado em", "Abrir"]);
    expect(within(within(secao).getByRole("row", { name: /Obra Zeta/ })).getByText("Medição recebida")).toBeTruthy();
    expect(within(within(secao).getByRole("row", { name: "Processo Eta" })).getByText("Arquivado")).toBeTruthy();
    // no fim da página: depois da tabela principal
    expect(grade.compareDocumentPosition(secao) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(container.querySelector(".pagina")?.lastElementChild).toBe(secao);
  });

  it("encerrado nunca fica vermelho, âmbar nem verde, e não mostra 'não lido'", async () => {
    const avisos = [{ tipo: "nao_lido", processo_id: ARQUIVADO.id, texto: "não lido às 11:00: página não abriu" }];
    mostrar(painel([RECEBIDO, ARQUIVADO, GAMA], { robo: { ...PARADO, avisos } }));
    await screen.findByRole("grid");
    const secao = encerrados();
    expect(secao.querySelector(".sg__dias, .sg__nao-lido, [class*='--acao'], [class*='--atencao'], [class*='--hoje']")).toBeNull();
    expect(within(secao).queryByText(/não lido|dias úteis|hoje/)).toBeNull();
  });

  it("só encerrados: 'Nenhum processo em andamento.' no lugar da tabela, e a seção Encerrados", async () => {
    mostrar(painel([RECEBIDO]));
    expect(await screen.findByText("Nenhum processo em andamento.")).toBeTruthy();
    expect(screen.queryByRole("grid")).toBeNull();
    expect(screen.getByText("0 processos · última leitura 11:00")).toBeTruthy();
    expect(within(encerrados()).getByRole("row", { name: /Obra Zeta/ })).toBeTruthy();
  });

  it("sem encerrado não há seção Encerrados; a linha do encerrado abre o histórico dele", async () => {
    const { unmount } = mostrar(painel([GAMA]));
    await screen.findByRole("grid");
    expect(screen.queryByRole("group", { name: "Encerrados" })).toBeNull();
    unmount();
    mostrar(painel([GAMA, ARQUIVADO]));
    await screen.findByRole("grid");
    fireEvent.click(within(encerrados()).getByRole("row", { name: "Processo Eta" }));
    expect(window.location.search).toBe("?processo=8");
  });
});
