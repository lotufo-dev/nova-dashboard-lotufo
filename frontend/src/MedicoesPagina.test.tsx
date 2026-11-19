import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Anteriores, ComparadosDaLinha, FilaMedicoes, GrupoDoQuadro, LinhaDoQuadro, LinhaFila, PassoDoQuadro } from "./filaMedicoes";
import type { Usuario } from "./Login";
import MedicoesPagina from "./MedicoesPagina";
import type { Parada } from "./parada";
import type { ObraResumo, SerieObra } from "./resumoMedicoes";

const { api, apiForm } = vi.hoisted(() => ({ api: vi.fn(), apiForm: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api, apiForm }));
// #653: o formulário de iniciar é a Nova planilha/carta, que tem teste próprio (PlanilhaCarta.test.tsx); aqui importa que é
// ELE que abre, com a obra, a série e a competência da tela
vi.mock("./PlanilhaCarta", async (original) => ({
  ...(await original<typeof import("./PlanilhaCarta")>()),
  NovaPlanilhaCarta: ({ contratoId, tipo, inicial, aoRegistrar }: { contratoId: number; tipo?: string;
    inicial?: { numero?: number; competencia?: string }; aoRegistrar: (r: { medicao_id: number }) => void }) => (
    <div data-nova-planilha={contratoId} data-tipo={tipo} data-competencia={inicial?.competencia} data-numero={inicial?.numero ?? ""}>
      <button type="button" onClick={() => aoRegistrar({ medicao_id: 99 })}>Registrar planilha/carta</button>
    </div>
  ),
}));

// Obras, medições e valores inventados. A resposta é a de GET /api/medicoes/fila (`fila_medicoes.fila`).
const usuario = { id: 1, nome: "Pessoa da Engenharia", email: "eng@exemplo.com.br", perfil: "admin" } as Usuario;

const SERIE: SerieObra = { aberta_id: null, aberta_numero: null, aberta_passo: null, ultima: null, prevista_id: null, prevista_numero: null,
  prevista_competencia: null };
const obra = (extra: Partial<ObraResumo>): ObraResumo => ({
  contrato_id: 1, obra: "Obra", contratante: "SINFRA", orgao_sub: null, aberta: false, prevista_id: null, projeto: null,
  encerramento: false, ultima: null, ha_dias: null, prevista: null, proxima: 1, proxima_tipo: "execucao", sem_no_mes: true,
  ultima_medicao: null, execucao: SERIE, ...extra });

const NOMES = ["Planilha e carta", "Análise do órgão", "Espelhos", "Notas", "Envio da nota", "Pagamento"];
const parada = (dias: number | null, situacao: Parada["situacao"], extra: Partial<Parada> = {}): Parada => ({
  desde: dias === null ? null : "2026-11-01", dias_uteis: dias, hoje: dias === 0, situacao, prazo_orgao_dias: null, esperada: null,
  alem_do_prazo: false, ...extra });
const valores = (pedido: number | null, aprovado: number | null): ComparadosDaLinha => {
  const ha = pedido !== null && aprovado !== null;
  return { pedido_centavos: pedido, aprovado_centavos: aprovado, aprovado_com_pedido_centavos: ha ? aprovado : null,
    pedido_do_aprovado_centavos: ha ? pedido : null, abaixo_do_pedido_centavos: ha ? Math.max(0, pedido - aprovado) : null,
    acima_do_pedido_centavos: ha ? Math.max(0, aprovado - pedido) : null };
};
const linha = (id: number, obra_: string, tem: number[], atual: number, extra: Partial<LinhaFila>): LinhaFila => ({
  contrato_id: id, obra: obra_, contratante: "SINFRA", orgao_sub: "SUEF II", medicao_id: id * 10, medicao_ids: [id * 10], titulo: "8ª Medição",
  competencia: "2026-10", com_quem: "lotufo",
  passo: { numero: atual, nome: NOMES[atual - 1], posicao: tem.indexOf(atual) + 1, total: tem.length },
  passos: tem.map(n => ({ numero: n, nome: NOMES[n - 1], situacao: n < atual ? "feito" : n === atual ? "atual" : "futuro" })),
  parada: parada(3, "andamento"), ...valores(null, null), acao: null, ...extra });

const SEIS = [1, 2, 3, 4, 5, 6];
const ALFA = linha(12, "Estações Alfa", SEIS, 3, { parada: parada(12, "critico"), ...valores(1462998169, 1462998101), acao: "gerar_espelho" });
const BETA = linha(13, "Corredor Beta", SEIS, 5, { titulo: "30ª Medição + Reajuste", parada: parada(1, "andamento"),
  ...valores(172000000, 166000000), acao: "enviar_nota" });
const ZETA = linha(14, "Complexo Zeta", [2, 3, 4, 5, 6], 4, { contratante: "MTPAR", orgao_sub: null, titulo: "24ª Medição", com_quem: "faturamento",
  parada: parada(0, "feito"), ...valores(308126381, 308126481) });
const GAMA = linha(15, "Bairros Gama", SEIS, 6, { com_quem: "orgao", titulo: "35ª Medição",
  parada: parada(41, "critico", { prazo_orgao_dias: 45, esperada: "2026-11-09", alem_do_prazo: true }), ...valores(20900000, 20900000) });
const DELTA = linha(16, "Rodovia Delta", SEIS, 2, { com_quem: "orgao", titulo: "29ª Medição", parada: parada(null, null), ...valores(85600000, null) });

const passoQ = (numero: number, situacao: PassoDoQuadro["situacao"], extra: Partial<PassoDoQuadro> = {}): PassoDoQuadro =>
  ({ numero, nome: NOMES[numero - 1], situacao, data: null, medicao_id: null, siga: null, parada: null, ...extra });
const noQuadro = (l: LinhaFila, extra: Partial<LinhaDoQuadro> = {}): LinhaDoQuadro => ({
  contrato_id: l.contrato_id, obra: l.obra, contratante: l.contratante ?? "", orgao_sub: l.orgao_sub, medicoes: [{ id: l.medicao_id, titulo: l.titulo }],
  iniciar: false, ...valores(l.pedido_centavos, l.aprovado_centavos),
  passos: l.passos.map(p => passoQ(p.numero, p.situacao, { data: p.situacao === "feito" ? `2026-11-0${p.numero}` : null,
    medicao_id: p.situacao === "atual" ? l.medicao_id : null, parada: p.situacao === "atual" ? l.parada : null })), ...extra });
const QUADRO: GrupoDoQuadro[] = [
  { contratante: "SINFRA", pedido_centavos: 1741498169, aprovado_centavos: 1649898101, aprovado_com_pedido_centavos: 1649898101,
    pedido_do_aprovado_centavos: 1655898169, abaixo_do_pedido_centavos: 6000068, linhas: [ALFA, BETA, GAMA, DELTA].map(l => noQuadro(l)) },
  { contratante: "MTPAR", pedido_centavos: 308126381, aprovado_centavos: 308126481, aprovado_com_pedido_centavos: 308126481,
    pedido_do_aprovado_centavos: 308126381, abaixo_do_pedido_centavos: 0, linhas: [noQuadro(ZETA)] },
];
const ANTERIORES: Anteriores = {
  linhas: [linha(21, "MT Épsilon", SEIS, 5, { titulo: "29ª Medição", competencia: "2026-09", parada: parada(19, "critico"),
    ...valores(151000000, 148000000), acao: "enviar_nota" }),
  linha(22, "Rodovia Capa", SEIS, 2, { titulo: "27ª Medição", competencia: "2026-08", com_quem: "orgao", parada: parada(33, "critico"), ...valores(64000000, null) })],
  esperam_pagamento: 17, antes_do_ano_inicial: 4, ano_inicial: "2025",
};

const FILA: FilaMedicoes = {
  hoje: "2026-11-18", mes: "2026-10",
  obras: [obra({ contrato_id: 1, obra: "Cinco Bairros", proxima: 35 }), obra({ contrato_id: 3, obra: "Complexo Gama", contratante: "MTPAR", proxima: 24 })],
  limites: { dias_atencao: 5, dias_critico: 10, diferenca_critica_por_mil: 5 },
  numeros: { com: { lotufo: { quantidade: 2, criticas: 1, breves: 0, alem_do_prazo: 0 }, faturamento: { quantidade: 1, criticas: 0, breves: 0, alem_do_prazo: 0 },
    orgao: { quantidade: 2, criticas: 1, breves: 0, alem_do_prazo: 1 } }, concluidas: 1, sem_medicao: 2,
    pedido_centavos: 2049624550, aprovado_centavos: 1958024582, aprovado_com_pedido_centavos: 1958024582, pedido_do_aprovado_centavos: 1964024550,
    abaixo_do_pedido_centavos: 6000068 },
  grupos: [{ com_quem: "lotufo", linhas: [ALFA, BETA] }, { com_quem: "faturamento", linhas: [ZETA] }, { com_quem: "orgao", linhas: [GAMA, DELTA] }],
  concluidas: [{ contrato_id: 30, obra: "Ponte Ni", medicao_id: 300, titulo: "7ª Medição", recebida_em: "2026-11-10" }],
  sem_medicao: [{ contrato_id: 1, obra: "Cinco Bairros", contratante: "SINFRA" }, { contrato_id: 3, obra: "Complexo Gama", contratante: "MTPAR" }],
  quadro: QUADRO, anteriores: ANTERIORES,
};

function responder(extra: (url: string, opcoes?: { method?: string }) => unknown = () => undefined, regraAtiva = true) {
  api.mockImplementation(async (url: string, opcoes?: { method?: string }) => {
    const x = extra(url, opcoes);
    if (x !== undefined) return x;
    if (url.startsWith("/api/medicoes/fila")) return { ...FILA, mes: url.split("mes=")[1] ?? FILA.mes };
    if (url.endsWith("/espelho")) return { regra: { situacao: regraAtiva ? "ativa" : "pendente" } };
    if (url.includes("/planilhas/sugestao")) return { numero: 35, numero_orgao: 401, competencia: "2026-10", periodo_inicio: "2026-10-01", periodo_fim: "2026-10-31" };
    return [];
  });
}

const linhaDa = (tabela: HTMLElement, nome: string) => within(tabela).getByRole("link", { name: nome }).closest("tr") as HTMLElement;
const texto = (el: Element | null | undefined) => (el?.textContent ?? "").replace(/\s/g, " ");

describe("Medições: fila de trabalho, quadro do mês e meses anteriores (#805)", () => {
  // só a data é falsa (os timers reais seguem): a competência em trabalho é o mês anterior ao de hoje
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-11-18T15:00:00Z"));
    window.history.replaceState(null, "", "/medicoes");
  });
  afterEach(() => { cleanup(); vi.useRealTimers(); api.mockReset(); apiForm.mockReset(); });

  it("abre na fila de trabalho da competência anterior ao mês corrente, com um painel por quem tem de agir", async () => {
    responder();
    render(<MedicoesPagina usuario={usuario} />);
    await screen.findByRole("table", { name: "Com a Lotufo" });
    expect(api.mock.calls[0][0]).toBe("/api/medicoes/fila?mes=2026-10");
    expect(screen.getByText("outubro de 2026")).toBeTruthy();
    expect(screen.getAllByRole("heading", { level: 2 }).map(h => h.textContent).slice(1, 4)).toEqual(["Com a Lotufo", "Com o faturamento", "Com o órgão"]);
    // as três vistas são endereços; a da vez leva aria-current, e os meses anteriores, a quantidade que pede ação
    const vistas = within(screen.getByRole("navigation", { name: "Vistas de Medições" })).getAllByRole("link");
    expect(vistas.map(v => v.getAttribute("href"))).toEqual(["/medicoes", "/medicoes/quadro", "/medicoes/anteriores"]);
    expect(vistas.map(v => v.getAttribute("aria-current"))).toEqual(["page", null, null]);
    expect(texto(vistas[2])).toBe("Meses anteriores2, 2 medições pedem ação");
    // a base dos valores entra uma vez, no cabeçalho da página
    expect(screen.getByText("Competência · valor cheio")).toBeTruthy();
  });

  it("a linha traz a obra, a medição, a barra de passos, o tempo parado, o pedido, o aprovado com a diferença e o botão do passo", async () => {
    responder();
    render(<MedicoesPagina usuario={usuario} />);
    const tabela = await screen.findByRole("table", { name: "Com a Lotufo" });
    expect(within(tabela).getAllByRole("columnheader").map(c => c.textContent)).toEqual(["Obra", "Passo", "Parada há", "Pedido", "Aprovado", "Próximo passo"]);
    // a ordem é a do servidor: a mais parada primeiro
    expect(within(tabela).getAllByRole("row").slice(1).map(r => r.querySelector(".medicoes__obra")?.textContent)).toEqual(["Estações Alfa", "Corredor Beta"]);
    const alfa = linhaDa(tabela, "Estações Alfa");
    expect(within(alfa).getByRole("link", { name: "Estações Alfa" }).getAttribute("href")).toBe("/obras/12/medicoes");
    expect(within(alfa).getByRole("link", { name: "8ª Medição" }).getAttribute("href")).toBe("/obras/12/medicoes/120");
    expect(texto(alfa.querySelector(".fila__medicao"))).toBe("8ª Medição · SINFRA · SUEF II");
    const celulas = within(alfa).getAllByRole("cell");
    expect(celulas[0].querySelectorAll(".barra-passos__passo")).toHaveLength(6);
    expect(texto(celulas[0].querySelector(".barra-passos__nome"))).toBe("Espelhos · , passo 3 de 6");
    expect(celulas[1].querySelector(".selo--critico .glifo--critico")).not.toBeNull();
    expect(texto(celulas[1])).toBe("12 dias úteis");
    expect(texto(celulas[2])).toMatch(/14\.629\.981,69/);
    // o corte de até 0,5% do pedido sai no tom da atenção
    expect(texto(celulas[3])).toMatch(/14\.629\.981,01/);
    expect(celulas[3].querySelector(".diferenca")?.className).toBe("diferenca diferenca--leve");
    // o botão é um link para a página da medição, no passo da vez
    const botao = within(alfa).getByRole("link", { name: "Gerar espelho: 8ª Medição de Estações Alfa" });
    expect(botao.getAttribute("href")).toBe("/obras/12/medicoes/120#passo-3");
    expect(botao.className).toBe("btn btn--pequeno btn--primario");
    // o corte acima de 0,5% do pedido sai no tom do crítico
    const beta = within(linhaDa(tabela, "Corredor Beta")).getAllByRole("cell");
    expect(beta[3].querySelector(".diferenca")?.className).toBe("diferenca diferenca--ruim");
    expect(within(linhaDa(tabela, "Corredor Beta")).getByRole("link", { name: "Enviar a nota: 30ª Medição + Reajuste de Corredor Beta" }).getAttribute("href"))
      .toBe("/obras/13/medicoes/130#passo-5");
  });

  it("com o faturamento e com o órgão o botão é Abrir; o pagamento diz o prazo do órgão, e o aprovado acima do pedido sai escrito", async () => {
    responder();
    render(<MedicoesPagina usuario={usuario} />);
    const faturamento = await screen.findByRole("table", { name: "Com o faturamento" });
    const zeta = linhaDa(faturamento, "Complexo Zeta");
    expect(within(zeta).getAllByRole("cell")[0].querySelectorAll(".barra-passos__passo")).toHaveLength(5);
    expect(texto(within(zeta).getAllByRole("cell")[1])).toBe("hoje");
    expect(texto(within(zeta).getAllByRole("cell")[3].querySelector(".diferenca"))).toBe("+ R$ 1,00acima do pedido");
    const abrir = within(zeta).getByRole("link", { name: "Abrir: 24ª Medição de Complexo Zeta" });
    expect(abrir.className).toBe("btn btn--pequeno");
    expect(abrir.getAttribute("href")).toBe("/obras/14/medicoes/140#passo-4");
    const orgao = screen.getByRole("table", { name: "Com o órgão" });
    const gama = within(linhaDa(orgao, "Bairros Gama")).getAllByRole("cell");
    expect(texto(gama[1])).toBe("41 dias úteisprazo do órgão venceu em 09/11");
    expect(texto(gama[3].querySelector(".diferenca"))).toBe("= igual ao pedido");
    // em análise: sem a data do evento não há dias, e sem aprovado não há diferença
    const delta = within(linhaDa(orgao, "Rodovia Delta")).getAllByRole("cell");
    expect([texto(delta[1]), texto(delta[3])]).toEqual(["—", "—"]);
  });

  it("a faixa de números: com quem está, concluídas, sem medição e o aprovado do mês com o corte", async () => {
    responder();
    render(<MedicoesPagina usuario={usuario} />);
    const faixa = (await screen.findByLabelText("Números de outubro")) as HTMLElement;
    const numero = (rotulo: string) => texto(within(faixa).getByText(rotulo).closest(".fila-numero"));
    expect(numero("Com a Lotufo")).toBe("Com a Lotufo21 há 10+ dias úteis1 há 10 dias úteis ou mais");
    expect(numero("Com o faturamento")).toBe("Com o faturamento1");
    expect(numero("Com o órgão")).toBe("Com o órgão21 além do prazo do órgão");
    expect(numero("Concluídas no mês")).toBe("Concluídas no mês1");
    expect(numero("Sem medição")).toBe("Sem medição2");
    const aprovado = within(faixa).getByText("Aprovado em outubro").closest(".fila-numero") as HTMLElement;
    expect(texto(aprovado)).toMatch(/19\.580\.245,82/);
    expect(aprovado.querySelector(".diferenca")?.className).toBe("diferenca diferenca--leve");
    expect(aprovado.querySelector(".marca-etapa__cor--boletim")).not.toBeNull();
  });

  it("embaixo da fila: as concluídas no mês e as obras sem medição, com o Iniciar", async () => {
    responder();
    render(<MedicoesPagina usuario={usuario} />);
    const concluidas = (await screen.findByRole("heading", { name: "Concluídas no mês" })).closest("section") as HTMLElement;
    expect(within(concluidas).getByRole("link", { name: "Ponte Ni · 7ª Medição" }).getAttribute("href")).toBe("/obras/30/medicoes/300");
    expect(texto(concluidas)).toContain("recebida em 10/11");
    const sem = screen.getByRole("heading", { name: "Sem medição em outubro" }).closest("section") as HTMLElement;
    expect(within(sem).getAllByRole("button", { name: /^Iniciar a medição de / })).toHaveLength(2);
  });

  it("Iniciar abre a Nova planilha/carta na competência da tela (#653)", async () => {
    responder();
    render(<MedicoesPagina usuario={usuario} />);
    fireEvent.click(await screen.findByRole("button", { name: "Iniciar a medição de Cinco Bairros" }));
    const janela = await screen.findByRole("dialog");
    expect(within(janela).getByRole("heading", { name: "Cinco Bairros · outubro de 2026" })).toBeTruthy();
    // o mesmo formulário da página da obra e da medição; o nº fica com a sugestão da obra, a competência é a da tela
    const form = await waitFor(() => { const f = janela.querySelector("[data-nova-planilha='1']"); expect(f).not.toBeNull(); return f as HTMLElement; });
    expect([form.dataset.tipo, form.dataset.competencia, form.dataset.numero]).toEqual(["execucao", "2026-10", ""]);
    fireEvent.click(within(janela).getByRole("button", { name: "Registrar planilha/carta" }));
    await waitFor(() => expect(window.location.pathname).toBe("/obras/1/medicoes/99"));
  });

  it("outro mês nas setas: a competência vai para a URL e o formulário abre nela, com a série de projeto", async () => {
    responder(url => url.startsWith("/api/medicoes/fila")
      ? { ...FILA, mes: url.split("mes=")[1], obras: [obra({ contrato_id: 1, obra: "Cinco Bairros", proxima: 3, proxima_tipo: "projeto" })] } : undefined);
    render(<MedicoesPagina usuario={usuario} />);
    await screen.findByRole("table", { name: "Com a Lotufo" });
    fireEvent.click(screen.getByRole("button", { name: "Mês anterior" }));
    expect(screen.getByText("setembro de 2026")).toBeTruthy();
    await waitFor(() => expect(api.mock.calls.map(c => c[0])).toContain("/api/medicoes/fila?mes=2026-09"));
    expect(window.location.search).toBe("?mes=2026-09");
    // as vistas levam a competência escolhida
    await waitFor(() => expect(within(screen.getByRole("navigation", { name: "Vistas de Medições" })).getAllByRole("link").map(v => v.getAttribute("href")))
      .toEqual(["/medicoes?mes=2026-09", "/medicoes/quadro?mes=2026-09", "/medicoes/anteriores?mes=2026-09"]));
    await waitFor(() => expect(document.querySelector(".medicoes")?.getAttribute("aria-busy")).toBeNull());
    fireEvent.click(screen.getByRole("button", { name: "Iniciar a medição de Cinco Bairros" }));
    const janela = await screen.findByRole("dialog");
    const form = await waitFor(() => { const f = janela.querySelector("[data-nova-planilha='1']"); expect(f).not.toBeNull(); return f as HTMLElement; });
    expect([form.dataset.tipo, form.dataset.competencia]).toEqual(["projeto", "2026-09"]);
    // voltar à competência em trabalho tira o mês da URL
    fireEvent.click(within(janela).getByRole("button", { name: "Fechar" }));
    fireEvent.click(screen.getByRole("button", { name: "Mês seguinte" }));
    expect(window.location.search).toBe("");
  });

  it("a competência pedida na URL (?mes=) é a que a tela abre", async () => {
    responder();
    render(<MedicoesPagina usuario={usuario} busca={{ mes: "2026-08" }} />);
    await screen.findByRole("table", { name: "Com a Lotufo" });
    expect(api.mock.calls[0][0]).toBe("/api/medicoes/fila?mes=2026-08");
    expect(screen.getByText("agosto de 2026")).toBeTruthy();
  });

  it("a obra sem regra de espelho ativa lança a medição à mão, na competência da tela", async () => {
    responder(url => url === "/api/contratos/3/medicoes" ? { id: 55 } : undefined, false);
    render(<MedicoesPagina usuario={usuario} />);
    fireEvent.click(await screen.findByRole("button", { name: "Iniciar a medição de Complexo Gama" }));
    const janela = await screen.findByRole("dialog");
    const form = await within(janela).findByRole("form", { name: "Nova medição" });
    expect(janela.querySelector("[data-nova-planilha]")).toBeNull();
    expect((within(form).getByLabelText("Nº") as HTMLInputElement).value).toBe("24");
    expect((within(form).getByLabelText("Competência") as HTMLInputElement).value).toBe("10/2026");
    fireEvent.click(within(form).getByRole("button", { name: "Nova medição" }));
    await waitFor(() => expect(window.location.pathname).toBe("/obras/3/medicoes/55"));
    const chamada = api.mock.calls.find(c => c[0] === "/api/contratos/3/medicoes");
    expect(JSON.parse((chamada![1] as { body: string }).body)).toEqual({ numero: 24, tipo: "execucao", competencia: "2026-10" });
  });

  it("Fechar a janela tira o formulário e a fila continua", async () => {
    responder();
    render(<MedicoesPagina usuario={usuario} />);
    fireEvent.click(await screen.findByRole("button", { name: "Iniciar a medição de Cinco Bairros" }));
    const janela = await screen.findByRole("dialog");
    fireEvent.click(within(janela).getByRole("button", { name: "Fechar" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.getByRole("table", { name: "Com a Lotufo" })).toBeTruthy();
  });

  it("sem medição em andamento na competência: uma linha curta, e os blocos de baixo continuam", async () => {
    responder(url => url.startsWith("/api/medicoes/fila") ? { ...FILA, grupos: [] } : undefined);
    render(<MedicoesPagina usuario={usuario} />);
    expect(await screen.findByText("Nenhuma medição em andamento em outubro.")).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.getByRole("heading", { name: "Sem medição em outubro" })).toBeTruthy();
  });

  it("quem só consulta vê a fila sem botão de escrita: Abrir em toda linha e nenhum Iniciar", async () => {
    responder();
    render(<MedicoesPagina usuario={{ ...usuario, perfil: "diretoria" }} />);
    const tabela = await screen.findByRole("table", { name: "Com a Lotufo" });
    const abrir = within(tabela).getByRole("link", { name: "Abrir: 8ª Medição de Estações Alfa" });
    expect(abrir.className).toBe("btn btn--pequeno");
    expect(within(tabela).queryByRole("link", { name: /Gerar espelho/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Iniciar/ })).toBeNull();
    expect(screen.getByRole("heading", { name: "Sem medição em outubro" }).closest("section")?.textContent).toContain("Cinco Bairros");
  });

  it("falha ao ler as medições: mensagem em português", async () => {
    api.mockRejectedValue(new Error("falhou"));
    render(<MedicoesPagina usuario={usuario} />);
    expect(await screen.findByRole("alert")).toBeTruthy();
  });

  describe("Quadro do mês (#643)", () => {
    it("uma linha por obra e uma coluna por passo, agrupadas por contratante sob o cabeçalho com o pedido, o aprovado e o corte", async () => {
      responder();
      render(<MedicoesPagina usuario={usuario} aba="quadro" />);
      const tabela = await screen.findByRole("table", { name: "Quadro do mês" });
      expect(within(tabela).getAllByRole("columnheader").map(c => c.textContent)).toEqual(["Obra", ...NOMES, "Pedido", "Aprovado"]);
      const grupos = [...tabela.querySelectorAll("tr.quadro__grupo")] as HTMLElement[];
      expect(grupos.map(g => texto(g.querySelector("th")))).toEqual(["SINFRA4 obras", "MTPAR1 obra"]);
      const sinfra = within(grupos[0]).getAllByRole("cell");
      expect(texto(sinfra[0])).toMatch(/17\.414\.981,69/);
      expect(texto(sinfra[1])).toMatch(/16\.498\.981,01/);
      expect(sinfra[1].querySelector(".diferenca")?.className).toBe("diferenca diferenca--leve");
      // no grupo só entra o corte: o aprovado acima do pedido da MT-PAR não aparece na linha que soma
      expect(texto(within(grupos[1]).getAllByRole("cell")[1].querySelector(".diferenca"))).toBe("= igual ao pedido");
      // quatro obras da SINFRA, uma da MT-PAR; nenhuma linha de "Iniciar"
      expect(within(tabela).getAllByRole("row")).toHaveLength(1 + 2 + 5);
      expect(within(tabela).queryByRole("button")).toBeNull();
    });

    it("o passo feito mostra a data, o da vez é o link com o selo do tempo parado e os dias, e o que falta fica a fazer", async () => {
      responder();
      render(<MedicoesPagina usuario={usuario} aba="quadro" />);
      const tabela = await screen.findByRole("table", { name: "Quadro do mês" });
      const celulas = within(linhaDa(tabela, "Estações Alfa")).getAllByRole("cell");
      expect(celulas[0].textContent).toContain("01/11");
      expect(celulas[0].querySelector(".glifo--feito")).not.toBeNull();
      // o selo "Atual" leva a situação do tempo parado, e os dias vão embaixo
      expect(celulas[2].querySelector(".selo--critico .glifo--critico")).not.toBeNull();
      expect(texto(celulas[2])).toBe("Atual12 dias úteis");
      const atual = within(celulas[2]).getByRole("link", { name: "Abrir 8ª Medição de Estações Alfa: Espelhos, há 12 dias úteis" });
      expect(atual.getAttribute("href")).toBe("/obras/12/medicoes/120#passo-3");
      expect(celulas[2].getAttribute("aria-current")).toBe("step");
      expect(celulas.slice(3, 6).map(c => c.textContent)).toEqual(["A fazer", "A fazer", "A fazer"]);
      expect(celulas[7].querySelector(".diferenca")).not.toBeNull();
      // o passo que a obra não tem fica vazio; o evento de hoje diz "hoje"; sem a data do evento, só "Atual", em andamento
      const zeta = within(linhaDa(tabela, "Complexo Zeta")).getAllByRole("cell");
      expect(zeta[0].textContent).toBe("");
      expect(texto(zeta[3])).toBe("Atualhoje");
      expect(within(zeta[3]).getByRole("link", { name: "Abrir 24ª Medição de Complexo Zeta: Notas, desde hoje" })).toBeTruthy();
      // o aprovado acima do pedido aparece na linha da obra
      expect(texto(zeta[7].querySelector(".diferenca"))).toBe("+ R$ 1,00acima do pedido");
      const delta = within(linhaDa(tabela, "Rodovia Delta")).getAllByRole("cell");
      expect(texto(delta[1])).toBe("Atual");
      expect(delta[1].querySelector(".selo--andamento")).not.toBeNull();
    });

    it("a medição com processo vivo do SIGA mostra o setor e o tempo no setor na célula do passo (#664)", async () => {
      const siga = { processo_id: 5, setor: "SUPE", dias_uteis: 5, desde: "2026-10-20T09:00:00-04:00", hoje: 0 };
      const comSiga = noQuadro(DELTA, { passos: noQuadro(DELTA).passos.map(p => p.numero === 2 ? { ...p, siga } : p) });
      responder(url => url.startsWith("/api/medicoes/fila")
        ? { ...FILA, quadro: [{ ...QUADRO[0], linhas: [comSiga] }] } : undefined);
      render(<MedicoesPagina usuario={usuario} aba="quadro" />);
      const tabela = await screen.findByRole("table", { name: "Quadro do mês" });
      const posicao = within(linhaDa(tabela, "Rodovia Delta")).getAllByRole("cell")[1].querySelector(".quadro__siga") as HTMLElement;
      expect(posicao.textContent).toBe("No SIGA: SUPE 5 dias úteis");
      expect(posicao.querySelector(".quadro__siga-tempo--breve .glifo--breve")).not.toBeNull();
    });

    it("as obras sem medição saem da matriz e ficam no bloco de baixo, com o Iniciar", async () => {
      responder();
      render(<MedicoesPagina usuario={usuario} aba="quadro" />);
      await screen.findByRole("table", { name: "Quadro do mês" });
      const sem = screen.getByRole("heading", { name: "Sem medição em outubro" }).closest("section") as HTMLElement;
      fireEvent.click(within(sem).getByRole("button", { name: "Iniciar a medição de Cinco Bairros" }));
      expect(within(await screen.findByRole("dialog")).getByRole("heading", { name: "Cinco Bairros · outubro de 2026" })).toBeTruthy();
    });

    it("o quadro cabe a 1024 px: tabela de largura fixa, sem caixa de rolagem; no celular a célula leva o nome do passo", async () => {
      responder();
      render(<MedicoesPagina usuario={usuario} aba="quadro" />);
      const tabela = await screen.findByRole("table", { name: "Quadro do mês" });
      expect(tabela.className).toContain("quadro__tabela");
      expect(tabela.closest(".tabela-wrap")).toBeNull();
      expect(within(linhaDa(tabela, "Estações Alfa")).getAllByRole("cell").map(c => c.getAttribute("data-rotulo")))
        .toEqual([...NOMES, "Pedido", "Aprovado"]);
    });

    it("sem medição na competência: uma linha curta no lugar da tabela", async () => {
      responder(url => url.startsWith("/api/medicoes/fila") ? { ...FILA, quadro: [] } : undefined);
      render(<MedicoesPagina usuario={usuario} aba="quadro" />);
      expect(await screen.findByText("Nenhuma medição na competência.")).toBeTruthy();
      expect(screen.queryByRole("table", { name: "Quadro do mês" })).toBeNull();
    });
  });

  describe("Meses anteriores", () => {
    it("só o que pede ação, nos painéis de quem tem de agir, com a competência, o valor e o tempo parado", async () => {
      responder();
      render(<MedicoesPagina usuario={usuario} aba="anteriores" />);
      const lotufo = await screen.findByRole("table", { name: "Com a Lotufo" });
      const epsilon = linhaDa(lotufo, "MT Épsilon");
      expect(texto(epsilon.querySelector(".fila__medicao"))).toBe("29ª Medição · 09/2026 · SINFRA · SUEF II");
      const celulas = within(epsilon).getAllByRole("cell");
      expect(texto(celulas[1])).toBe("19 dias úteis");
      expect(texto(celulas[2])).toMatch(/1\.510\.000,00/);
      expect(within(epsilon).getByRole("link", { name: "Enviar a nota: 29ª Medição de MT Épsilon" }).getAttribute("href")).toBe("/obras/21/medicoes/210#passo-5");
      expect(within(screen.getByRole("table", { name: "Com o órgão" })).getByRole("link", { name: "Rodovia Capa" })).toBeTruthy();
      expect(screen.queryByRole("table", { name: "Com o faturamento" })).toBeNull();
      expect(within(screen.getByRole("navigation", { name: "Vistas de Medições" })).getAllByRole("link").map(v => v.getAttribute("aria-current")))
        .toEqual([null, null, "page"]);
    });

    it("o que só espera pagamento e o que é de antes de 2025 viram uma linha, com o link para a página A receber (#816)", async () => {
      responder();
      render(<MedicoesPagina usuario={usuario} aba="anteriores" />);
      await screen.findByRole("table", { name: "Com a Lotufo" });
      const resumo = document.querySelector(".fila-resumo") as HTMLElement;
      expect(texto(resumo)).toBe("17 medições esperam pagamento · 4 medições abertas de antes de 2025Ver em A receber");
      expect(within(resumo).getByRole("link", { name: "Ver em A receber" }).getAttribute("href")).toBe("/a-receber");
      expect(within(resumo).queryByRole("link", { name: /Fechamento/ })).toBeNull();
    });

    it("nada pede ação: uma linha curta; sem nada esperando pagamento, a linha de resumo não aparece", async () => {
      responder(url => url.startsWith("/api/medicoes/fila")
        ? { ...FILA, anteriores: { linhas: [], esperam_pagamento: 1, antes_do_ano_inicial: 0, ano_inicial: "2025" } } : undefined);
      const { unmount } = render(<MedicoesPagina usuario={usuario} aba="anteriores" />);
      expect(await screen.findByText("Nenhuma medição de meses anteriores pede ação.")).toBeTruthy();
      expect(texto(document.querySelector(".fila-resumo"))).toBe("1 medição espera pagamentoVer em A receber");
      // sem contagem, a aba não leva o contador
      expect(texto(within(screen.getByRole("navigation", { name: "Vistas de Medições" })).getAllByRole("link")[2])).toBe("Meses anteriores");
      unmount();
      responder(url => url.startsWith("/api/medicoes/fila")
        ? { ...FILA, anteriores: { linhas: [], esperam_pagamento: 0, antes_do_ano_inicial: 0, ano_inicial: "2025" } } : undefined);
      render(<MedicoesPagina usuario={usuario} aba="anteriores" />);
      await screen.findByText("Nenhuma medição de meses anteriores pede ação.");
      expect(document.querySelector(".fila-resumo")).toBeNull();
    });
  });
});
