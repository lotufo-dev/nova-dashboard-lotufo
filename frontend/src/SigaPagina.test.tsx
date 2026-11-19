/// <reference types="node" />
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Caminho from "./Caminho";
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
// a leitura de "parado" como o servidor a manda (`siga.parado`, #840: sobre os dias sem movimentacao); o encerrado nao tem
const tempoDe = (p: Pick<ProcessoSiga, "encerrado" | "hoje" | "dias_sem_movimentacao">): ProcessoSiga["situacao_tempo"] => {
  const d = p.dias_sem_movimentacao;
  return p.encerrado ? null : p.hoje > 0 ? "feito" : d === null ? null : d >= 10 ? "critico" : d >= 5 ? "breve" : "andamento";
};
const processo = (extra: Partial<ProcessoSiga>): ProcessoSiga => {
  const p: ProcessoSiga = {
    id: 1, codigo: null, link: null, numero: null, nome: null, contrato_id: null, obra: null, contratante: null, orgao_sub: null, medicao_id: null,
    categoria: extra.medicao_id ? "medicoes" : "outros", categoria_a_conferir: null, complemento: null, o_que_e: extra.medicao_titulo ?? "Outro",
    medicao_titulo: null, protocolo_id: null, situacao: "1º Volume - Aguardando Andamento [COFIN, [X]]", encerrado: null, setor: "COFIN",
    caixa_entrada: false, com_quem: "Fulano", desde: "2026-10-20T10:00:00-04:00", dias_uteis: 6, dias_sem_movimentacao: null, hoje: 0, situacao_tempo: null,
    ultima: mov("2026-10-20T10:00:00-04:00", "Recebimento"), protocolado_em: "2026-10-01T08:00:00-04:00",
    movimentacoes: [mov("2026-10-20T10:00:00-04:00", "Recebimento")], ...extra };
  // sem dizer, os dias sem movimentacao sao os do setor (o processo nao andou desde que entrou)
  if (extra.dias_sem_movimentacao === undefined) p.dias_sem_movimentacao = p.dias_uteis;
  return { ...p, situacao_tempo: extra.situacao_tempo !== undefined ? extra.situacao_tempo : tempoDe(p) };
};

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
// a faixa de numeros contada como o servidor conta: so' os vivos; parado e' o critico; nao lido e' o que leva o aviso
const painel = (processos: ProcessoSiga[], extra: Partial<PainelSiga> = {}): PainelSiga => {
  const vivos = processos.filter(p => p.encerrado === null);
  const naoLidos = new Set((extra.robo ?? PARADO).avisos.filter(a => a.tipo === "nao_lido").map(a => a.processo_id));
  return { lido_em: "2026-10-28T15:00:00+00:00", atrasado: false, processos, pode_atualizar: false, robo: PARADO,
    numeros: { acompanhados: vivos.length, parados: vivos.filter(p => p.situacao_tempo === "critico").length,
      andaram_hoje: vivos.filter(p => p.hoje > 0).length, nao_lidos: vivos.filter(p => naoLidos.has(p.id)).length },
    limites: { dias_atencao: 5, dias_critico: 10 }, ...extra };
};
// a tela carregou: ha' pelo menos um painel de categoria (cada um tem a propria tabela)
const carregada = async () => (await screen.findAllByRole("grid"))[0];
const paineis = () => screen.getAllByRole("region").filter(s => s.classList.contains("sg-grupo"));
const tituloDe = (s: HTMLElement) => within(s).getByRole("heading", { level: 2 }).textContent;
const numerosDaFaixa = () => [...screen.getByLabelText("Processos no SIGA").querySelectorAll(".sg-numero")].map(n => [
  n.querySelector("dt")?.textContent, n.querySelector(".sg-numero__valor")?.textContent, n.querySelector("dt .glifo")?.className ?? null]);
const escolhas = () => within(screen.getByRole("navigation", { name: "Categoria dos processos" })).getAllByRole("link");
const mostrar = (dados: PainelSiga, busca: Record<string, string> = {}) => {
  api.mockResolvedValue(dados);
  return render(<SigaPagina busca={busca} agora={AGORA} />);
};
// com o caminho da barra do topo ao lado da página, como a casca o desenha (#814)
const mostrarComCaminho = (dados: PainelSiga, busca: Record<string, string> = {}) => {
  api.mockResolvedValue(dados);
  return render(<><Caminho rota={{ tela: "siga" }} busca={busca} ehH1={false} /><SigaPagina busca={busca} agora={AGORA} /></>);
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

  it("um painel por categoria, na ordem fixa, com o cabeçalho de grupo forte; dentro de cada um, do mais parado ao menos (#805)", async () => {
    mostrar(painel([ALFA, ADITIVO, INDENIZATORIO, DELTA, EPSILON, BETA, GAMA, ADITIVO_PARADO]));
    await carregada();
    expect(paineis().map(tituloDe)).toEqual(["Medições", "Aditivos", "Indenizatórios", "Outros"]);
    expect(paineis().map(nomesEm)).toEqual([
      ["Obra Delta · 4ª Medição", "Obra Alfa · 7ª Medição", "Obra Épsilon · 2ª Medição"],
      ["Obra Delta · Aditivo", "Obra Alfa · Aditivo de prazo"],
      ["Obra Épsilon · Indenizatório"],
      ["Processo Gama", "Processo Beta"]]);
    // cada painel tem a propria tabela, com as mesmas colunas, sob o cabecalho em tinta
    expect(screen.getAllByRole("grid")).toHaveLength(4);
    for (const s of paineis()) {
      // #840: os nomes e a ordem das colunas
      expect(within(s).getAllByRole("columnheader").map(c => c.textContent)).toEqual(
        ["Processo", "Contratante", "Setor", "Com quem", "No setor há", "Dias sem movimentação", "Última movimentação", "Tipo de movimentação", "Abrir"]);
      expect(s.firstElementChild?.className).toBe("sg-grupo__cabeca");
      expect(s.querySelectorAll("colgroup col")).toHaveLength(9);
    }
    // o cabecalho diz quantos processos o grupo tem e, no selo do critico, quantos estao parados alem do limite
    const cabeca = (i: number) => paineis()[i].querySelector(".sg-grupo__n") as HTMLElement;
    expect(cabeca(0).textContent).toBe("3 processos");
    expect(cabeca(0).querySelector(".selo")).toBeNull();
    expect(cabeca(2).querySelector(".num")?.textContent).toBe("1 processo");
    expect(cabeca(2).querySelector(".selo")?.className).toBe("selo selo--critico");
    expect(within(cabeca(2)).getByText("1 sem movimentação há 10 dias úteis ou mais").className).toBe("sr-only");
    expect(within(cabeca(3)).getByText("1 sem movimentação há 10+ dias úteis").getAttribute("aria-hidden")).toBe("true");
    expect(screen.queryByRole("complementary")).toBeNull();
  });

  it("categoria sem processo não tem painel e continua nas escolhas, com zero (#805)", async () => {
    mostrar(painel([ALFA, GAMA]));
    await carregada();
    expect(paineis().map(tituloDe)).toEqual(["Medições", "Outros"]);
    expect(escolhas().map(e => e.textContent)).toEqual(["Todos 2", "Medições 1", "Aditivos 0", "Indenizatórios 0", "Outros 1"]);
    expect(escolhas().map(e => e.getAttribute("href"))).toEqual(
      ["/siga", "/siga?categoria=medicoes", "/siga?categoria=aditivos", "/siga?categoria=indenizatorios", "/siga?categoria=outros"]);
    expect(escolhas().map(e => e.getAttribute("aria-current"))).toEqual(["true", null, null, null, null]);
    expect(escolhas().every(e => e.className === "escolha")).toBe(true);
  });

  it("a categoria escolhida na URL mostra só o painel dela e os encerrados dela (#805)", async () => {
    const todos = [ALFA, ADITIVO, GAMA, RECEBIDO, ARQUIVADO];
    const { unmount } = mostrar(painel(todos), { categoria: "outros" });
    await carregada();
    expect(paineis().map(tituloDe)).toEqual(["Outros"]);
    expect(nomesEm(paineis()[0])).toEqual(["Processo Gama"]);
    expect(escolhas().map(e => e.getAttribute("aria-current"))).toEqual([null, null, null, null, "true"]);
    // as quantidades das escolhas e a faixa de numeros continuam sendo as de todos os processos vivos
    expect(escolhas().map(e => e.textContent)).toEqual(["Todos 3", "Medições 1", "Aditivos 1", "Indenizatórios 0", "Outros 1"]);
    expect(numerosDaFaixa()[0].slice(0, 2)).toEqual(["Processos acompanhados", "3"]);
    expect(nomesEm(encerrados())).toEqual(["Processo Eta"]);          // o arquivado e' de Outros; a medicao recebida, nao
    unmount();
    mostrar(painel(todos), { categoria: "aditivos" });
    await carregada();
    expect(nomesNaTabela()).toEqual(["Obra Alfa · Aditivo de prazo"]);
    expect(screen.queryByRole("group", { name: "Encerrados" })).toBeNull();
  });

  it("categoria escolhida sem processo em andamento: uma linha no lugar do painel; categoria que não existe mostra todos (#805)", async () => {
    const { unmount } = mostrar(painel([ALFA, GAMA]), { categoria: "indenizatorios" });
    expect(await screen.findByText("Nenhum processo em andamento em Indenizatórios.")).toBeTruthy();
    expect(screen.queryByRole("grid")).toBeNull();
    expect(escolhas().map(e => e.getAttribute("aria-current"))).toEqual([null, null, null, "true", null]);
    unmount();
    mostrar(painel([ALFA, GAMA]), { categoria: "reajustes" });
    await carregada();
    expect(paineis().map(tituloDe)).toEqual(["Medições", "Outros"]);
    expect(escolhas()[0].getAttribute("aria-current")).toBe("true");
  });

  it("clicar na linha dentro de uma categoria guarda a categoria no endereço, e a trilha do histórico volta para ela (#805)", async () => {
    window.history.replaceState(null, "", "/siga?categoria=aditivos");
    const { unmount } = mostrar(painel([ALFA, ADITIVO]), { categoria: "aditivos" });
    fireEvent.click(await screen.findByRole("row", { name: "Obra Alfa · Aditivo de prazo" }));
    expect(window.location.pathname + window.location.search).toBe("/siga?categoria=aditivos&processo=21");
    unmount();
    mostrarComCaminho(painel([ALFA, ADITIVO]), { categoria: "aditivos", processo: "21" });
    await screen.findByRole("heading", { level: 1 });
    expect(within(screen.getByRole("navigation", { name: "Você está em" })).getByRole("link", { name: "SIGA" }).getAttribute("href"))
      .toBe("/siga?categoria=aditivos");
  });

  it("faixa de números no alto: acompanhados, parados, andaram hoje e não lidos, do servidor, com a hora da última leitura; legenda da cor (#805)", async () => {
    const avisos = [{ tipo: "nao_lido", processo_id: BETA.id, texto: "não lido às 11:00: página não abriu" }];
    mostrar(painel([ALFA, EPSILON, BETA, GAMA, INDENIZATORIO, RECEBIDO], { robo: { ...PARADO, avisos } }));
    await carregada();
    // o numero em tinta; a situacao no simbolo ao lado do rotulo
    expect(numerosDaFaixa()).toEqual([
      ["Processos acompanhados", "5", null],
      ["Sem movimentação há 10 dias úteis ou mais", "2", "glifo glifo--critico"],
      ["Andaram hoje", "2", "glifo glifo--feito"],
      ["Não lidos na última rodada", "1", "glifo glifo--breve"]]);
    expect(screen.getByLabelText("Processos no SIGA").querySelector(".sg-numero__apoio")?.textContent).toBe("última leitura 11:00");
    const legenda = screen.getByRole("list", { name: "Legenda das cores" });
    expect(within(legenda).getAllByRole("listitem").map(li => li.textContent)).toEqual(
      ["andou hoje", "sem movimentação há menos de 5 dias úteis", "sem movimentação há 5 dias úteis ou mais", "10 dias úteis ou mais"]);
    // cada situacao da legenda tem a forma dela (o glifo), alem da cor
    expect(within(legenda).getAllByRole("listitem").map(li => li.querySelector(".glifo")?.className)).toEqual(
      ["glifo glifo--feito", "glifo glifo--andamento", "glifo glifo--breve", "glifo glifo--critico"]);
  });

  it("a faixa mostra o que o servidor contou, com os limites dele, e o zero fica sem símbolo (#805)", async () => {
    mostrar(painel([ALFA, GAMA], { numeros: { acompanhados: 7, parados: 0, andaram_hoje: 0, nao_lidos: 0 }, limites: { dias_atencao: 3, dias_critico: 8 } }));
    await carregada();
    expect(numerosDaFaixa()).toEqual([
      ["Processos acompanhados", "7", null], ["Sem movimentação há 8 dias úteis ou mais", "0", null],
      ["Andaram hoje", "0", null], ["Não lidos na última rodada", "0", null]]);
    expect(within(screen.getByRole("list", { name: "Legenda das cores" })).getAllByRole("listitem").map(li => li.textContent)).toEqual(
      ["andou hoje", "sem movimentação há menos de 3 dias úteis", "sem movimentação há 3 dias úteis ou mais", "8 dias úteis ou mais"]);
    expect(within(paineis()[1]).getByText("1 sem movimentação há 8 dias úteis ou mais")).toBeTruthy();
  });

  it("Processo: obra e assunto em negrito, com link para a obra e, no processo de medição, para a medição; o nome do robô só sem obra; o número não entra no nome (#663, #805)", async () => {
    mostrar(painel([ALFA, BETA, ADITIVO]));
    const alfa = await screen.findByRole("row", { name: "Obra Alfa · 7ª Medição" });
    expect(alfa.querySelector(".sg__nome")?.textContent).toBe("Obra Alfa · 7ª Medição");
    expect(within(alfa).getByRole("link", { name: "Obra Alfa" }).getAttribute("href")).toBe("/obras/7");
    expect(within(alfa).getByRole("link", { name: "7ª Medição" }).getAttribute("href")).toBe("/obras/7/medicoes/31#passo-5");
    expect(alfa.textContent).not.toContain("ORGAO-PRO-2026/00001");
    const aditivo = screen.getByRole("row", { name: "Obra Alfa · Aditivo de prazo" });
    expect(aditivo.querySelector(".sg__nome")?.textContent).toBe("Obra Alfa · Aditivo de prazo");
    expect(within(aditivo).getAllByRole("link").map(l => l.textContent)).toEqual(["Obra Alfa"]);   // sem medicao, so' a obra
    expect(aditivo.textContent).not.toContain("Nome do robô");
    const beta = screen.getByRole("row", { name: "Processo Beta" });
    expect(within(beta).getByText("Processo Beta").className).toContain("sg__nome");
    expect(within(beta).queryByRole("link")).toBeNull();
  });

  it("o link da obra dentro da linha leva à obra, sem abrir também o histórico (#805)", async () => {
    window.history.replaceState(null, "", "/siga");
    mostrar(painel([ALFA]));
    const alfa = await screen.findByRole("row", { name: "Obra Alfa · 7ª Medição" });
    fireEvent.click(within(alfa).getByRole("link", { name: "Obra Alfa" }));
    expect(window.location.pathname + window.location.search).toBe("/obras/7");
  });

  it("Contratante: o da obra do processo, com a superintendência embaixo; sem obra, o nome do processo ocupa as duas colunas (#805)", async () => {
    mostrar(painel([{ ...ADITIVO, contratante: "SINFRA", orgao_sub: "SUEF II" }, { ...INDENIZATORIO, contratante: "MTPAR" }, BETA]));
    const celula = (nome: RegExp) => screen.getByRole("row", { name: nome }).querySelector('td[data-rotulo="Contratante"]') as HTMLElement | null;
    const colunasDe = (nome: RegExp) => [...screen.getByRole("row", { name: nome }).querySelectorAll("td")].reduce((n, td) => n + td.colSpan, 0);
    await carregada();
    expect(celula(/Aditivo de prazo/)?.textContent).toBe("SINFRASUEF II");
    expect(within(celula(/Aditivo de prazo/) as HTMLElement).getByText("SUEF II").className).toBe("sg__fraco");
    expect(celula(/Indenizatório/)?.textContent).toBe("MTPAR");
    expect(celula(/Processo Beta/)).toBeNull();
    expect((screen.getByRole("row", { name: /Processo Beta/ }).querySelector("td.sg__proc") as HTMLTableCellElement).colSpan).toBe(2);
    // com ou sem contratante, a linha fecha as mesmas nove colunas
    expect([colunasDe(/Aditivo de prazo/), colunasDe(/Indenizatório/), colunasDe(/Processo Beta/)]).toEqual([9, 9, 9]);
  });

  it("categoria a conferir: aviso discreto na linha quando o servidor diz que o nome indica outra categoria; nas demais, nada (#805)", async () => {
    const A_CONFERIR = processo({ id: 40, contrato_id: 7, obra: "Obra Alfa", complemento: "Aditivo de prazo", o_que_e: "Aditivo de prazo",
      categoria_a_conferir: "aditivos", dias_uteis: 8 });
    mostrar(painel([A_CONFERIR, BETA, ADITIVO]));
    await carregada();
    // continua em Outros, onde quem cadastrou o pos: a tela so' avisa
    expect(nomesEm(paineis()[1])).toEqual(["Obra Alfa · Aditivo de prazo", "Processo Beta"]);
    const aviso = within(paineis()[1]).getByText("categoria a conferir");
    expect(aviso.className).toBe("sg__fraco sg__conferir");
    expect(aviso.closest("tr")?.getAttribute("aria-label")).toBe("Obra Alfa · Aditivo de prazo");
    expect(screen.getAllByText("categoria a conferir")).toHaveLength(1);
    // no histórico, onde quem edita corrige, o aviso continua ao lado do número do processo
    cleanup();
    mostrar(painel([A_CONFERIR, BETA]), { processo: "40" });
    await screen.findByRole("heading", { level: 1 });
    expect(screen.getByText(/· categoria a conferir$/).className).toBe("sg__sub");
    expect(screen.getByRole("button", { name: "Corrigir categoria" })).toBeTruthy();
  });

  it("tempo no setor na situação que o servidor leu, com o glifo, e a borda da linha na mesma cor; sem leitura, sem selo nem borda (#805)", async () => {
    const SEM_DATA = processo({ id: 9, nome: "Processo Sem Data", desde: null, dias_uteis: null });
    mostrar(painel([ALFA, DELTA, BETA, GAMA, SEM_DATA]));
    await carregada();
    // "andou hoje" tambem esta' na legenda: aqui vale o selo da linha
    const selo = (texto: string) => screen.getAllByText(texto).map(e => e.closest(".sg__dias")).find(Boolean)!;
    const situacao = (texto: string) => [selo(texto).className, selo(texto).querySelector(".glifo")?.className, selo(texto).closest("tr")?.className];
    expect(situacao("12 dias úteis")).toEqual(["selo selo--critico sg__dias", "glifo glifo--critico", "sg__linha sg__linha--critico"]);
    expect(situacao("6 dias úteis")).toEqual(["selo selo--breve sg__dias", "glifo glifo--breve", "sg__linha sg__linha--breve"]);
    expect(situacao("3 dias úteis")).toEqual(["selo selo--andamento sg__dias", "glifo glifo--andamento", "sg__linha sg__linha--andamento"]);
    expect(situacao("andou hoje")).toEqual(["selo selo--feito sg__dias", "glifo glifo--feito", "sg__linha sg__linha--feito"]);
    expect(screen.getByRole("row", { name: /Obra Alfa/ }).contains(selo("andou hoje"))).toBe(true);
    const semData = screen.getByRole("row", { name: "Processo Sem Data" });
    expect(semData.className).toBe("sg__linha");
    expect(semData.querySelector(".selo")).toBeNull();
  });

  it("a cor da linha é a que o servidor manda, não uma conta da tela (#805)", async () => {
    // 12 dias uteis lidos pelo servidor como "em andamento": a tela desenha o que veio
    mostrar(painel([processo({ id: 5, nome: "Processo Gama", dias_uteis: 2, dias_sem_movimentacao: 12, situacao_tempo: "andamento" })]));
    await carregada();
    expect(screen.getByRole("row", { name: "Processo Gama" }).className).toBe("sg__linha sg__linha--andamento");
    expect(screen.getByText("12 dias úteis").closest(".selo")?.className).toBe("selo selo--andamento sg__dias");
  });

  it("entrou no setor há 5 dias úteis e andou ontem: 'No setor há' em texto comum, 'Dias sem movimentação' 1 dia útil sem atenção (#840)", async () => {
    const ONTEM = processo({ id: 30, nome: "Processo Ontem", desde: "2026-10-21T09:00:00-04:00", dias_uteis: 5, dias_sem_movimentacao: 1,
      ultima: mov("2026-10-27T16:20:00-04:00", "Recebimento") });
    mostrar(painel([ONTEM]));
    const linha = await screen.findByRole("row", { name: "Processo Ontem" });
    const noSetor = linha.querySelector('td[data-rotulo="No setor há"]') as HTMLElement;
    expect(noSetor.textContent).toBe("5 dias úteis");
    expect(noSetor.querySelector(".selo, .glifo, .icone, [class*='--']")).toBeNull();
    const semMov = linha.querySelector('td[data-rotulo="Dias sem movimentação"]') as HTMLElement;
    expect(semMov.textContent).toBe("1 dia útil");
    expect(semMov.querySelector(".selo")?.className).toBe("selo selo--andamento sg__dias");
    expect(linha.className).toBe("sg__linha sg__linha--andamento");
    expect(linha.querySelector('td[data-rotulo="Última movimentação"]')?.textContent).toBe("27/10 16:20");
  });

  it("sem movimentação há 10 dias úteis ou mais: o destaque de ação só na coluna 'Dias sem movimentação' (#840)", async () => {
    const PARADO_10 = processo({ id: 31, nome: "Processo Parado", desde: "2026-09-01T09:00:00-04:00", dias_uteis: 40, dias_sem_movimentacao: 10,
      ultima: mov("2025-12-30T08:00:00-04:00", "Juntada | documento DOC-1") });
    mostrar(painel([PARADO_10]));
    const linha = await screen.findByRole("row", { name: "Processo Parado" });
    expect(linha.querySelectorAll(".selo--critico")).toHaveLength(1);
    expect(linha.querySelector(".selo--critico")?.closest("td")?.getAttribute("data-rotulo")).toBe("Dias sem movimentação");
    expect(linha.querySelector('td[data-rotulo="No setor há"]')?.textContent).toBe("40 dias úteis");
    // o ano aparece quando nao e' o de hoje; o tipo sai sem o texto depois de " |"
    expect(linha.querySelector('td[data-rotulo="Última movimentação"]')?.textContent).toBe("30/12/2025 08:00");
    expect(linha.querySelector('td[data-rotulo="Tipo de movimentação"]')?.textContent).toBe("Juntada");
  });

  it("No setor há: minutos e horas antes de um dia útil, para quem não andou hoje", async () => {
    mostrar(painel([processo({ id: 7, nome: "Mi", dias_uteis: 0, hoje: 0, desde: "2026-10-28T11:00:00-04:00" }),
      processo({ id: 8, nome: "Ho", dias_uteis: 0, hoje: 0, desde: "2026-10-28T08:00:00-04:00" })]));
    await carregada();
    expect(screen.getByText("3 h")).toBeTruthy();       // desde 08h00, agora 11h30
    expect(screen.getByText("30 min")).toBeTruthy();    // desde 11h00
  });

  it("Setor: setor, caixa de entrada e volume; Última movimentação em data e hora e o Tipo sem o texto depois de ' |'; protocolado em, sob o nome (#840)", async () => {
    mostrar(painel([ALFA, BETA]));
    const beta = await screen.findByRole("row", { name: /Processo Beta/ });
    expect(within(beta).getByText("GABIN")).toBeTruthy();
    expect(within(beta).getByText("caixa de entrada")).toBeTruthy();
    expect(within(beta).getByText("(2º Volume)")).toBeTruthy();
    const alfa = screen.getByRole("row", { name: /Obra Alfa/ });
    expect(within(beta).getByText("GABIN").closest("td")?.getAttribute("data-rotulo")).toBe("Setor");
    expect(alfa.querySelector('td[data-rotulo="Última movimentação"]')?.textContent).toBe("28/10 09:30");
    expect(alfa.querySelector('td[data-rotulo="Tipo de movimentação"]')?.textContent).toBe("Recebimento");
    expect(within(alfa).queryByText(/texto do órgão/)).toBeNull();
    expect(within(alfa).getByText("Fulano")).toBeTruthy();                // Com quem
    expect(within(alfa).getByText("01/10/2026").closest(".sg__fraco")?.textContent).toBe("protocolado em 01/10/2026");
    expect(within(alfa).getByText("01/10/2026").closest("td")?.className).toBe("sg__proc");
  });

  it("a 1024 px as nove colunas cabem na largura do painel: o cabeçalho quebra entre palavras e a tabela não passa da caixa (#650, #805, #840)", async () => {
    // o jsdom nao mede layout: aqui so' a presenca das regras e das classes; a medida foi conferida no navegador
    const css = readFileSync(join(process.cwd(), "src", "siga.css"), "utf8").split("@container")[0];
    expect(css).not.toMatch(/\.sg__tabela th\s*\{[^}]*white-space:\s*nowrap/);
    expect(css).toMatch(/\.sg__tabela\s*\{[^}]*width:\s*100%;\s*table-layout:\s*fixed/);
    const largura = (col: string) => Number(new RegExp(`\\.sg__c-${col}\\s*\\{\\s*width:\\s*(\\d+)%`).exec(css)?.[1]);
    const colunas = ["proc", "contr", "onde", "quem", "setor", "parado", "ultima", "tipo", "seta"];
    expect(colunas.reduce((soma, c) => soma + largura(c), 0)).toBe(100);
    expect(largura("parado")).toBeGreaterThanOrEqual(14);     // o selo "25 dias úteis" em duas linhas no painel de ~724 px
    expect(largura("contr")).toBeGreaterThanOrEqual(10);      // "Contratante" no cabeçalho, separada em sílabas, sem encostar na vizinha
    expect(largura("quem")).toBeGreaterThanOrEqual(11);       // um nome sem partir a 1024 px
    mostrar(painel([ALFA]));
    const alfa = await screen.findByRole("row", { name: /Obra Alfa/ });
    expect(within(alfa).getByText("01/10/2026").className).toBe("num");
    expect(document.querySelectorAll("colgroup col")).toHaveLength(9);
  });

  it("na página estreita a linha vira bloco e a cor do tempo parado passa para o bloco (#805)", () => {
    const css = readFileSync(join(process.cwd(), "src", "siga.css"), "utf8");
    expect(css).toMatch(/\.siga\s*\{[^}]*container:\s*sg-pagina\s*\/\s*inline-size/);
    const estreita = css.slice(css.indexOf("@container sg-pagina (max-width: 640px)"));
    expect(estreita).toMatch(/\.sg__tabela, \.sg__tabela tbody, \.sg__tabela tr, \.sg__tabela td\s*\{\s*display:\s*block/);
    expect(estreita).toMatch(/\.sg__linha\[class\*="sg__linha--"\]\s*\{\s*box-shadow:\s*inset var\(--espaco-mini\) 0 0 var\(--sg-tempo\)/);
    // as quatro situacoes pintam a borda pela variavel, com a cor da situacao da fundacao
    for (const s of ["feito", "andamento", "breve", "critico"]) {
      expect(css).toContain(`.sg__linha--${s} { --sg-tempo: var(--situacao-${s}-ponto); }`);
    }
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
    expect(await carregada()).toBeTruthy();
    expect(window.location.search).toBe("");   // sai o ?processo= que nao existe
  });

  it("sem nenhum processo: só a linha 'Nenhum processo acompanhado.'", async () => {
    mostrar(painel([], { lido_em: null }));
    expect(await screen.findByText("Nenhum processo acompanhado.")).toBeTruthy();
    expect(numerosDaFaixa().map(n => n[1])).toEqual(["0", "0", "0", "0"]);
    expect(screen.queryByText(/última leitura/)).toBeNull();
    expect(screen.queryByRole("grid")).toBeNull();
    expect(screen.queryByRole("navigation", { name: "Categoria dos processos" })).toBeNull();   // sem processo nao ha' o que escolher
  });

  it("atrasado avisa desde quando; em dia não avisa", async () => {
    const { unmount } = mostrar(painel([ALFA], { atrasado: true, lido_em: "2026-10-28T12:00:00+00:00" }));
    await carregada();
    expect(screen.getByLabelText("Processos no SIGA").querySelector(".sg-numero__apoio")?.textContent).toBe("última leitura 08:00");
    expect(screen.getByText("O monitor do SIGA não lê desde 28/10 08:00.")).toBeTruthy();
    unmount();
    mostrar(painel([ALFA]));
    await carregada();
    expect(screen.queryByText(/O monitor do SIGA não lê/)).toBeNull();
  });

  it("rele de hora em hora (#657); o aviso de atraso aparece quando a resposta nova o traz; ao sair, para", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      mostrar(painel([ALFA, BETA]));
      await carregada();
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

  it("histórico: caminho, título, número, total e período, Abrir no SIGA e a medição", async () => {
    mostrarComCaminho(painel([ALFA]), { processo: "1" });
    const h1 = await screen.findByRole("heading", { level: 1 });
    expect(h1.textContent).toBe("Histórico · Obra Alfa · 7ª Medição");
    // o caminho é da barra do topo (#814): o processo é o último trecho, com o nome que a página diz
    const trilha = screen.getByRole("navigation", { name: "Você está em" });
    // o nome chega ao caminho pelo efeito da página, depois do h1 (#862): espera
    await vi.waitFor(() => expect([...trilha.querySelectorAll("li")].map(li => li.textContent)).toEqual(["Órgãos", "SIGA", "Obra Alfa · 7ª Medição"]));
    expect(within(trilha).getByRole("link", { name: "SIGA" }).getAttribute("href")).toBe("/siga");
    expect(within(trilha).getByText("Obra Alfa · 7ª Medição").closest("li")!.getAttribute("aria-current")).toBe("page");
    expect(screen.getAllByRole("navigation", { name: "Você está em" })).toHaveLength(1);   // a página não desenha trilha própria
    expect(screen.getByText("ORGAO-PRO-2026/00001 · 5 movimentações · 20/10/2026 a 28/10/2026")).toBeTruthy();
    expect(screen.getByRole("link", { name: /Abrir no SIGA/ }).getAttribute("href")).toBe("https://siga.exemplo.com.br/acompanhar?n=ABC123");
    expect(screen.getByRole("link", { name: "Ver a medição" }).getAttribute("href")).toBe("/obras/7/medicoes/31#passo-5");
  });

  it("histórico: o botão '‹ SIGA' no alto volta ao quadro, com a categoria de onde se veio; o caminho continua (#840)", async () => {
    window.history.replaceState(null, "", "/siga?categoria=aditivos&processo=21");
    mostrarComCaminho(painel([ALFA, ADITIVO]), { categoria: "aditivos", processo: "21" });
    const h1 = await screen.findByRole("heading", { level: 1 });
    const voltar = h1.closest("header")!.querySelector("a.sg__voltar") as HTMLAnchorElement;
    expect(voltar.textContent?.trim()).toBe("SIGA");
    expect(voltar.className).toBe("btn--voltar sg__voltar");
    expect(voltar.getAttribute("href")).toBe("/siga?categoria=aditivos");
    expect(voltar.compareDocumentPosition(h1) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();   // no alto, antes do título
    expect(screen.getByRole("navigation", { name: "Você está em" })).toBeTruthy();
    fireEvent.click(voltar);
    expect(window.location.pathname + window.location.search).toBe("/siga?categoria=aditivos");
    cleanup();
    // sem categoria, volta ao quadro inteiro
    mostrar(painel([ALFA]), { processo: "1" });
    await screen.findByRole("heading", { level: 1 });
    expect(document.querySelector("a.sg__voltar")?.getAttribute("href")).toBe("/siga");
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
    expect(tituloDe(linha.closest(".sg-grupo") as HTMLElement)).toBe("Aditivos");
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

  it("processo que o robô mandou sem classificação: entra na seção que o servidor sugere pelo nome e o histórico oferece confirmar", async () => {
    const SUGERIDO = processo({ id: 30, nome: "CT-901 - Aditivo de prazo - Obra Alfa", categoria: "aditivos", categoria_sugerida: true, o_que_e: "Aditivo" });
    api.mockImplementation(async (caminho: string) => caminho === "/api/contratos" ? OBRAS : painel([SUGERIDO, BETA]));
    const { unmount } = render(<SigaPagina busca={{}} agora={AGORA} />);
    await carregada();
    expect(paineis().map(tituloDe)).toEqual(["Aditivos", "Outros"]);
    expect(nomesEm(paineis()[0])).toEqual(["CT-901 - Aditivo de prazo - Obra Alfa"]);
    unmount();
    render(<SigaPagina busca={{ processo: "30" }} agora={AGORA} />);
    fireEvent.click(await screen.findByRole("button", { name: "Confirmar categoria" }));
    const form = screen.getByRole("form", { name: "Corrigir categoria" });
    expect((within(form).getByLabelText("Categoria") as HTMLSelectElement).value).toBe("aditivos");
  });

  it("quem só consulta não vê Corrigir categoria nem Acompanhar processo; processo de protocolo do sistema não tem o que corrigir (#663)", async () => {
    api.mockResolvedValue(painel([ALFA, ADITIVO]));
    const { unmount } = render(<SigaPagina busca={{ processo: "21" }} agora={AGORA} podeEditar={false} />);
    await screen.findByRole("heading", { level: 1 });
    expect(screen.queryByRole("button", { name: "Corrigir categoria" })).toBeNull();
    unmount();
    const tabela = render(<SigaPagina busca={{}} agora={AGORA} podeEditar={false} />);
    await carregada();
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
    expect(await carregada()).toBeTruthy();
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
    await carregada();
    expect(screen.queryByRole("button", { name: /Atualizar/ })).toBeNull();
    unmount();
    mostrar(painel([ALFA], { pode_atualizar: true }));
    await carregada();
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
    await carregada();
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
    await carregada();
    expect(screen.getByRole("button", { name: "Na fila" })).toBeTruthy();
    cleanup();
    mostrar(painel([ALFA], { pode_atualizar: true, robo: NA_FILA(null) }), { processo: "1" });
    expect((await screen.findByRole("button", { name: "Na fila" })).hasAttribute("disabled")).toBe(true);
  });

  it("rodada pedida na tela: indicador no topo, 'lendo...' só nas linhas da rodada e 'Lendo...' nos botões que ela cobre", async () => {
    mostrar(painel([ALFA, DELTA], { pode_atualizar: true, robo: RODADA("pedido", [ALFA.id]) }));
    await carregada();
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
    await carregada();
    expect(screen.getByText(/rodada automática/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Pedir leitura" })).toBeNull();
    expect(screen.getAllByRole("button", { name: "Lendo..." }).every(b => b.hasAttribute("disabled"))).toBe(true);
  });

  it("avisos do robô: os gerais em vermelho no topo; o não lido vira etiqueta na linha do processo, com a hora e o motivo (#805)", async () => {
    const avisos = [
      { tipo: "disparo", processo_id: null, texto: "O Windows não iniciou o robô: acesso negado" },
      { tipo: "sem_inicio", processo_id: null, texto: "O robô não começou. O usuário dele pode estar desconectado do servidor." },
      { tipo: "falha", processo_id: null, texto: "A rodada das 11:00 falhou: SIGA fora do ar" },
      { tipo: "nao_lido", processo_id: DELTA.id, texto: "não lido às 11:00: página não abriu" },
      { tipo: "nao_lidos", processo_id: null, texto: "1 de 2 processos não foram lidos" },
      { tipo: "nao_terminou", processo_id: null, texto: "A rodada das 10:40 não terminou." },
    ];
    mostrar(painel([ALFA, DELTA], { robo: { ...PARADO, avisos } }));
    await carregada();
    const topo = screen.getAllByRole("alert").map(a => a.textContent ?? "");
    expect(topo.every(t => t.startsWith("Crítico: "))).toBe(true);
    expect(topo.map(t => t.replace("Crítico: ", ""))).toEqual([
      "O Windows não iniciou o robô: acesso negado", "O robô não começou. O usuário dele pode estar desconectado do servidor.",
      "A rodada das 11:00 falhou: SIGA fora do ar", "1 de 2 processos não foram lidos", "A rodada das 10:40 não terminou."]);
    const etiqueta = screen.getByRole("row", { name: /Obra Delta/ }).querySelector(".sg__etiqueta") as HTMLElement;
    expect(within(etiqueta).getByText("Não lido").closest(".selo")?.className).toBe("selo selo--breve");   // o tom do "vence em breve"
    expect(etiqueta.querySelector(".selo .glifo")?.className).toBe("glifo glifo--breve");
    expect(within(etiqueta).getByText("às 11:00: página não abriu").className).toBe("sg__fraco");
    expect(within(screen.getByRole("row", { name: /Obra Alfa/ })).queryByText(/não lido/i)).toBeNull();
    expect(numerosDaFaixa()[3]).toEqual(["Não lidos na última rodada", "1", "glifo glifo--breve"]);
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
      expect(await screen.findByText((_, el) => el?.className === "sg-numero__apoio" && el.textContent === "última leitura 11:28")).toBeTruthy();
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
    const grade = await carregada();
    expect(paineis().flatMap(nomesEm)).toEqual(["Obra Delta · 4ª Medição", "Processo Gama"]);
    // os encerrados continuam numa secao so', sem painel por categoria
    expect(encerrados().querySelector(".sg-grupo")).toBeNull();
    expect(numerosDaFaixa()[0].slice(0, 2)).toEqual(["Processos acompanhados", "2"]);
    expect(escolhas()[0].textContent).toBe("Todos 2");
    const secao = encerrados();
    expect(secao.open).toBe(false);
    expect(secao.querySelector("summary")?.textContent).toBe("Encerrados 2");
    expect(within(secao).getAllByRole("row").slice(1).map(l => l.getAttribute("aria-label"))).toEqual(["Obra Zeta · 5ª Medição", "Processo Eta"]);
    expect(within(secao).getAllByRole("columnheader").map(c => c.textContent)).toEqual(
      ["Processo", "Contratante", "Setor", "Situação", "Última movimentação", "Tipo de movimentação", "Abrir"]);
    expect(within(within(secao).getByRole("row", { name: /Obra Zeta/ })).getByText("Medição recebida")).toBeTruthy();
    expect(within(within(secao).getByRole("row", { name: "Processo Eta" })).getByText("Arquivado")).toBeTruthy();
    // no fim da página: depois da tabela principal
    expect(grade.compareDocumentPosition(secao) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(container.querySelector(".pagina")?.lastElementChild).toBe(secao);
  });

  it("encerrado nunca fica vermelho, âmbar nem verde, e não mostra 'não lido'", async () => {
    const avisos = [{ tipo: "nao_lido", processo_id: ARQUIVADO.id, texto: "não lido às 11:00: página não abriu" }];
    mostrar(painel([RECEBIDO, ARQUIVADO, GAMA], { robo: { ...PARADO, avisos } }));
    await carregada();
    const secao = encerrados();
    expect(secao.querySelector(".sg__dias, .sg__etiqueta, .selo, .glifo, [class*='--critico'], [class*='--breve'], [class*='--feito'], [class*='--andamento']")).toBeNull();
    expect(within(secao).queryByText(/não lido|dias úteis|hoje/i)).toBeNull();
    expect(within(secao).getAllByRole("row").slice(1).every(l => l.className === "sg__linha")).toBe(true);   // sem a borda do tempo parado
  });

  it("só encerrados: 'Nenhum processo em andamento.' no lugar da tabela, e a seção Encerrados", async () => {
    mostrar(painel([RECEBIDO]));
    expect(await screen.findByText("Nenhum processo em andamento.")).toBeTruthy();
    expect(screen.queryByRole("grid")).toBeNull();
    expect(numerosDaFaixa()[0].slice(0, 2)).toEqual(["Processos acompanhados", "0"]);
    expect(within(encerrados()).getByRole("row", { name: /Obra Zeta/ })).toBeTruthy();
  });

  it("sem encerrado não há seção Encerrados; a linha do encerrado abre o histórico dele", async () => {
    const { unmount } = mostrar(painel([GAMA]));
    await carregada();
    expect(screen.queryByRole("group", { name: "Encerrados" })).toBeNull();
    unmount();
    mostrar(painel([GAMA, ARQUIVADO]));
    await carregada();
    fireEvent.click(within(encerrados()).getByRole("row", { name: "Processo Eta" }));
    expect(window.location.search).toBe("?processo=8");
  });
});

// Issue #841: criterio de encerramento. A leitura (sobrestado, encerrado e por que, a medicao proposta) vem do servidor;
// a tela desenha e manda as escritas. Obras, processos e pessoas ficticios.
describe("SigaPagina: critério de encerramento (#841)", () => {
  afterEach(() => { cleanup(); api.mockReset(); window.history.replaceState(null, "", "/"); });
  const encerrados = () => screen.getByRole("group", { name: "Encerrados" }) as HTMLDetailsElement;
  const PROPOSTA = { id: 31, contrato_id: 7, titulo: "7ª Medição", obra: "Obra Alfa", estado: "recebida" };
  const SEM_MEDICAO = processo({ id: 40, nome: "7ª Medição - Obra Alfa", categoria: "medicoes", categoria_sugerida: true,
    o_que_e: "Medição", dias_uteis: 3, medicao_proposta: PROPOSTA });
  const SOBRESTADO = processo({ id: 41, nome: "Processo Sobrestado", situacao: "1º Volume - Sobrestado [COFIN, [X]]",
    dias_uteis: 30, situacao_tempo: "sobrestado" });
  const JUNTADO = processo({ id: 42, nome: "Processo Juntado", encerrado: "juntado" });
  const A_MAO = processo({ id: 43, nome: "Processo Encerrado à Mão", encerrado: "manual",
    encerramento: { motivo: "aditivo publicado", por: "Pessoa de teste", em: "2026-10-27T14:00:00+00:00" } });
  const OBRAS = [{ id: 7, orgao: "ORGAO", numero_instrumento: "IC 7/2026", nome_curto: "Obra Alfa", estado: "em_andamento" }];
  const MEDICOES = [{ id: 31, numero: 7, tipo: "execucao", estado: "recebida" }, { id: 30, numero: 6, tipo: "execucao", estado: "recebida" },
                    { id: 29, numero: 5, tipo: "execucao", estado: "cancelada" }];

  it("sobrestado: a palavra no lugar dos dias, sem selo nem cor de atraso, e depois dos parados", async () => {
    mostrar(painel([SOBRESTADO, GAMA]));
    await carregada();
    expect(nomesNaTabela()).toEqual(["Processo Gama", "Processo Sobrestado"]);
    const linha = screen.getByRole("row", { name: "Processo Sobrestado" });
    expect(linha.className).toBe("sg__linha");
    const celula = within(linha).getByText("Sobrestado");
    expect(celula.closest(".selo")).toBeNull();
    expect(linha.querySelector(".selo, .glifo, [class*='--critico'], [class*='--breve']")).toBeNull();
  });

  it("juntado e encerrado à mão vão para Encerrados com o motivo; o à mão diz o motivo, quem e quando, e só quem edita vê Reabrir", async () => {
    const { unmount } = mostrar(painel([GAMA, JUNTADO, A_MAO]));
    await carregada();
    const secao = encerrados();
    expect(within(within(secao).getByRole("row", { name: "Processo Juntado" })).getByText("Juntado a outro processo")).toBeTruthy();
    const mao = within(secao).getByRole("row", { name: "Processo Encerrado à Mão" });
    expect(within(mao).getByText("Encerrado")).toBeTruthy();
    expect(mao.textContent).toContain("aditivo publicado · Pessoa de teste, 27/10/2026");
    expect(within(mao).getByRole("button", { name: "Reabrir" })).toBeTruthy();
    expect(within(within(secao).getByRole("row", { name: "Processo Juntado" })).queryByRole("button")).toBeNull();
    unmount();
    render(<SigaPagina busca={{}} agora={AGORA} podeEditar={false} />);
    await carregada();
    expect(within(encerrados()).queryByRole("button", { name: "Reabrir" })).toBeNull();
  });

  it("Reabrir na seção Encerrados chama o servidor, não abre o histórico e a tela relê", async () => {
    const chamadas: string[] = [];
    let reaberto = false;
    api.mockImplementation(async (caminho: string) => {
      chamadas.push(caminho);
      if (caminho === "/api/siga/processos/43/reabrir") { reaberto = true; return { id: 43 }; }
      return painel([GAMA, reaberto ? { ...A_MAO, encerrado: null, encerramento: null } : A_MAO]);
    });
    render(<SigaPagina busca={{}} agora={AGORA} />);
    await carregada();
    fireEvent.click(within(encerrados()).getByRole("button", { name: "Reabrir" }));
    await vi.waitFor(() => expect(screen.queryByRole("group", { name: "Encerrados" })).toBeNull());
    expect(chamadas).toContain("/api/siga/processos/43/reabrir");
    expect(window.location.search).toBe("");
    expect(nomesNaTabela()).toContain("Processo Encerrado à Mão");
  });

  it("processo de Medições sem medição: 'medição a ligar' na linha e, no histórico, a proposta com 'Ligar à medição', que liga pela rota", async () => {
    const chamadas: { caminho: string; opts?: RequestInit }[] = [];
    let ligado = false;
    const LIGADO = { ...SEM_MEDICAO, medicao_id: 31, contrato_id: 7, obra: "Obra Alfa", medicao_titulo: "7ª Medição", o_que_e: "7ª Medição",
      encerrado: "recebida" as const, medicao_proposta: null, categoria_sugerida: false };
    api.mockImplementation(async (caminho: string, opts?: RequestInit) => {
      chamadas.push({ caminho, opts });
      if (caminho === "/api/siga/processos/40/vinculo") { ligado = true; return { id: 40 }; }
      return painel([ligado ? LIGADO : SEM_MEDICAO]);
    });
    const { unmount } = render(<SigaPagina busca={{}} agora={AGORA} />);
    await carregada();
    expect(within(screen.getByRole("row", { name: "7ª Medição - Obra Alfa" })).getByText("medição a ligar")).toBeTruthy();
    unmount();
    render(<SigaPagina busca={{ processo: "40" }} agora={AGORA} />);
    expect((await screen.findByText(/Medição proposta/)).textContent).toBe("Medição proposta: Obra Alfa · 7ª Medição");
    fireEvent.click(screen.getByRole("button", { name: "Ligar à medição" }));
    // ligado a' medicao recebida, o servidor diz encerrado: o historico diz por que e o botao some
    await vi.waitFor(() => expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Histórico · Obra Alfa · 7ª Medição"));
    const envio = chamadas.find(c => c.caminho === "/api/siga/processos/40/vinculo");
    expect(envio?.opts?.method).toBe("POST");
    expect(JSON.parse(envio?.opts?.body as string)).toEqual({ medicao_id: 31 });
    expect(screen.queryByRole("button", { name: "Ligar à medição" })).toBeNull();
    expect(document.querySelector(".sg__sub")?.textContent).toContain("medição recebida");
    expect(screen.getByRole("button", { name: "Desfazer vínculo" })).toBeTruthy();
  });

  it("Confirmar categoria abre em Medições com a obra e a medição propostas, e a medição recebida também se escolhe", async () => {
    api.mockImplementation(async (caminho: string) => {
      if (caminho === "/api/contratos") return OBRAS;
      if (caminho === "/api/contratos/7/medicoes") return MEDICOES;
      return painel([SEM_MEDICAO]);
    });
    render(<SigaPagina busca={{ processo: "40" }} agora={AGORA} />);
    fireEvent.click(await screen.findByRole("button", { name: "Confirmar categoria" }));
    const form = screen.getByRole("form", { name: "Corrigir categoria" });
    await within(form).findByRole("option", { name: "6ª Medição" });
    expect((within(form).getByLabelText("Categoria") as HTMLSelectElement).value).toBe("medicoes");
    expect((within(form).getByLabelText("Obra") as HTMLSelectElement).value).toBe("7");
    expect((within(form).getByLabelText("Medição") as HTMLSelectElement).value).toBe("31");
    expect(within(form).queryByRole("option", { name: "5ª Medição" })).toBeNull();      // cancelada nao entra
  });

  it("Encerrar processo pede o motivo, manda à rota e o histórico passa a dizer o motivo, quem e quando, com Reabrir", async () => {
    const chamadas: { caminho: string; opts?: RequestInit }[] = [];
    let fechado = false;
    api.mockImplementation(async (caminho: string, opts?: RequestInit) => {
      chamadas.push({ caminho, opts });
      if (caminho === "/api/siga/processos/5/encerrar") { fechado = true; return { id: 5 }; }
      return painel([fechado ? { ...GAMA, encerrado: "manual", situacao_tempo: null,
        encerramento: { motivo: "pedido respondido", por: "Pessoa de teste", em: "2026-10-28T15:00:00+00:00" } } : GAMA]);
    });
    render(<SigaPagina busca={{ processo: "5" }} agora={AGORA} />);
    fireEvent.click(await screen.findByRole("button", { name: "Encerrar processo" }));
    const form = screen.getByRole("form", { name: "Encerrar processo" });
    fireEvent.change(within(form).getByLabelText("Motivo"), { target: { value: " pedido respondido " } });
    fireEvent.click(within(form).getByRole("button", { name: "Encerrar" }));
    await vi.waitFor(() => expect(screen.getByRole("button", { name: "Reabrir" })).toBeTruthy());
    const envio = chamadas.find(c => c.caminho === "/api/siga/processos/5/encerrar");
    expect(JSON.parse(envio?.opts?.body as string)).toEqual({ motivo: "pedido respondido" });
    expect(document.querySelector(".sg__sub")?.textContent).toContain("encerrado: pedido respondido (Pessoa de teste, 28/10/2026)");
    expect(screen.queryByRole("button", { name: "Encerrar processo" })).toBeNull();
  });

  it("erro do servidor ao encerrar aparece em português e o formulário fica aberto", async () => {
    const { ApiErro } = await import("./api");
    api.mockImplementation(async (caminho: string) => {
      if (caminho === "/api/siga/processos/5/encerrar") throw new ApiErro(422, "Escreva o motivo do encerramento");
      return painel([GAMA]);
    });
    render(<SigaPagina busca={{ processo: "5" }} agora={AGORA} />);
    fireEvent.click(await screen.findByRole("button", { name: "Encerrar processo" }));
    const form = screen.getByRole("form", { name: "Encerrar processo" });
    fireEvent.click(within(form).getByRole("button", { name: "Encerrar" }));
    expect((await within(form).findByRole("alert")).textContent).toContain("Escreva o motivo do encerramento");
  });

  it("quem só consulta não vê Ligar, Desfazer, Encerrar nem Reabrir, nem 'medição a ligar'", async () => {
    const LIGADO_A_MAO = processo({ id: 44, nome: "Ligado", medicao_id: 31, contrato_id: 7, obra: "Obra Alfa", medicao_titulo: "7ª Medição" });
    api.mockResolvedValue(painel([SEM_MEDICAO, LIGADO_A_MAO, A_MAO]));
    for (const id of ["40", "44", "43"]) {
      const { unmount } = render(<SigaPagina busca={{ processo: id }} agora={AGORA} podeEditar={false} />);
      await screen.findByRole("heading", { level: 1 });
      for (const nome of ["Ligar à medição", "Desfazer vínculo", "Encerrar processo", "Reabrir", "Confirmar categoria"]) {
        expect(screen.queryByRole("button", { name: nome })).toBeNull();
      }
      unmount();
    }
    render(<SigaPagina busca={{}} agora={AGORA} podeEditar={false} />);
    await carregada();
    expect(screen.queryByText("medição a ligar")).toBeNull();
  });
});
