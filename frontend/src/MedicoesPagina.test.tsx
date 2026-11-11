import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Usuario } from "./Login";
import MedicoesPagina from "./MedicoesPagina";
import type { LinhaAnterior, LinhaQuadro, ObraResumo, PassoQuadro, ResumoMedicoes, SerieObra } from "./resumoMedicoes";

const { api, apiForm } = vi.hoisted(() => ({ api: vi.fn(), apiForm: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api, apiForm }));
// #653: o formulário de iniciar é a Nova planilha/carta, que tem teste próprio (PlanilhaCarta.test.tsx); aqui importa que é
// ELE que abre, com a obra, a série e a competência do quadro
vi.mock("./PlanilhaCarta", async (original) => ({
  ...(await original<typeof import("./PlanilhaCarta")>()),
  NovaPlanilhaCarta: ({ contratoId, tipo, inicial, aoRegistrar }: { contratoId: number; tipo?: string;
    inicial?: { numero?: number; competencia?: string }; aoRegistrar: (r: { medicao_id: number }) => void }) => (
    <div data-nova-planilha={contratoId} data-tipo={tipo} data-competencia={inicial?.competencia} data-numero={inicial?.numero ?? ""}>
      <button type="button" onClick={() => aoRegistrar({ medicao_id: 99 })}>Registrar planilha/carta</button>
    </div>
  ),
}));

const usuario = { id: 1, nome: "Pessoa da Engenharia", email: "eng@exemplo.com.br", perfil: "admin" } as Usuario;

const SERIE: SerieObra = { aberta_id: null, aberta_numero: null, aberta_passo: null, ultima: null, prevista_id: null, prevista_numero: null,
  prevista_competencia: null };
const obra = (extra: Partial<ObraResumo>): ObraResumo => ({
  contrato_id: 1, obra: "Obra", contratante: "SINFRA", orgao_sub: null, aberta: false, prevista_id: null, projeto: null,
  encerramento: false, ultima: null, ha_dias: null, prevista: null, proxima: 1, proxima_tipo: "execucao", sem_no_mes: true,
  ultima_medicao: null, execucao: SERIE, ...extra });

const NOMES = ["Planilha e carta", "Análise do órgão", "Espelhos", "Notas", "Envio da nota", "Pagamento"];
const passo = (numero: number, situacao: PassoQuadro["situacao"], data: string | null = null, medicao_id: number | null = null,
  siga: PassoQuadro["siga"] = null): PassoQuadro =>
  ({ numero, nome: NOMES[numero - 1], situacao, data, medicao_id, siga });
const linha = (extra: Partial<LinhaQuadro>): LinhaQuadro => ({
  contrato_id: 1, obra: "Obra", contratante: "SINFRA", orgao_sub: null, medicoes: [], passos: [], iniciar: false,
  pedido_centavos: null, aprovado_centavos: null, ...extra });

const QUADRO: LinhaQuadro[] = [
  // a obra com os seis passos: dois feitos (com a data), o da vez e os que faltam
  linha({ contrato_id: 12, obra: "Estações Alfa", medicoes: [{ id: 70, titulo: "8ª Medição" }],
    passos: [passo(1, "feito", "2026-11-02"), passo(2, "feito", "2026-11-04"), passo(3, "atual", null, 70), passo(4, "futuro"),
      passo(5, "futuro"), passo(6, "futuro")],
    pedido_centavos: 1462998169, aprovado_centavos: 1462998101 }),
  // a obra que começa em Espelhos, com execução e reajuste
  linha({ contrato_id: 14, obra: "Complexo Zeta", contratante: "MTPAR",
    medicoes: [{ id: 72, titulo: "24ª Medição" }, { id: 73, titulo: "Reajuste da 24ª Medição" }],
    passos: [passo(3, "feito"), passo(4, "atual", null, 73), passo(5, "futuro"), passo(6, "futuro")], pedido_centavos: 308126381 }),
  linha({ contrato_id: 1, obra: "Cinco Bairros", iniciar: true }),
  linha({ contrato_id: 3, obra: "Complexo Gama", contratante: "MTPAR", iniciar: true }),
];

const ANTERIORES: LinhaAnterior[] = [
  { contrato_id: 13, obra: "MT Epsilon", medicao_id: 71, titulo: "29ª Medição", numero: 29, competencia: "2026-08",
    passo: { numero: 2, nome: "Análise do órgão" } },
  { contrato_id: 14, obra: "Complexo Zeta", medicao_id: 60, titulo: "23ª Medição + Reajuste", numero: 23, competencia: "2026-09",
    passo: { numero: 6, nome: "Pagamento" } },
];

const RESUMO: ResumoMedicoes = {
  hoje: "2026-11-07", mes: "2026-10",
  contagens: { "sem-medicao": 2, "planilha-gerada": 0, "planilha-enviada": 0, "boletim-recebido": 0, faturamento: 0, "aguardando-nota": 0,
    "enviar-nota": 0, "aguardando-pagamento": 0, iniciar: 2, "em-andamento": 4 },
  linhas: [],
  obras: [obra({ contrato_id: 1, obra: "Cinco Bairros", proxima: 35 }), obra({ contrato_id: 3, obra: "Complexo Gama", contratante: "MTPAR", proxima: 24 })],
  quadro: QUADRO, anteriores: ANTERIORES,
};

function responder(extra: (url: string, opcoes?: { method?: string }) => unknown = () => undefined, regraAtiva = true) {
  api.mockImplementation(async (url: string, opcoes?: { method?: string }) => {
    const x = extra(url, opcoes);
    if (x !== undefined) return x;
    if (url.startsWith("/api/medicoes/resumo")) return { ...RESUMO, mes: url.split("mes=")[1] ?? RESUMO.mes };
    if (url.endsWith("/espelho")) return { regra: { situacao: regraAtiva ? "ativa" : "pendente" } };
    if (url.includes("/planilhas/sugestao")) return { numero: 35, numero_orgao: 401, competencia: "2026-10", periodo_inicio: "2026-10-01", periodo_fim: "2026-10-31" };
    return [];
  });
}

const linhaDa = (tabela: HTMLElement, nome: string) => within(tabela).getByRole("link", { name: nome }).closest("tr") as HTMLElement;

describe("Medições: quadro do mês (#643)", () => {
  // só a data é falsa (os timers reais seguem): a competência em trabalho é o mês anterior ao de hoje
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-11-07T15:00:00Z"));
    window.history.replaceState(null, "", "/medicoes");
  });
  afterEach(() => { cleanup(); vi.useRealTimers(); api.mockReset(); apiForm.mockReset(); });

  it("abre no quadro da competência anterior ao mês corrente, com uma linha por obra e uma coluna por passo", async () => {
    responder();
    render(<MedicoesPagina usuario={usuario} />);
    const tabela = await screen.findByRole("table", { name: "Quadro do mês" });
    expect(api.mock.calls[0][0]).toBe("/api/medicoes/resumo?mes=2026-10");
    expect(screen.getByText("outubro de 2026")).toBeTruthy();
    expect(within(tabela).getAllByRole("columnheader").map(c => c.textContent)).toEqual(["Obra", ...NOMES, "Pedido", "Aprovado"]);
    expect(within(tabela).getAllByRole("row").slice(1)).toHaveLength(4);
  });

  it("o passo feito mostra a data, o da vez é o link para a medição e o que falta fica a fazer", async () => {
    responder();
    render(<MedicoesPagina usuario={usuario} />);
    const tabela = await screen.findByRole("table", { name: "Quadro do mês" });
    const celulas = within(linhaDa(tabela, "Estações Alfa")).getAllByRole("cell");
    expect(celulas[0].textContent).toContain("02/11");
    expect(celulas[1].textContent).toContain("04/11");
    const atual = within(celulas[2]).getByRole("link", { name: "Abrir 8ª Medição de Estações Alfa: Espelhos" });
    // #653: o link cai no passo da vez da página da medição
    expect(atual.getAttribute("href")).toBe("/obras/12/medicoes/70#passo-3");
    expect(celulas[2].getAttribute("aria-current")).toBe("step");
    expect(celulas.slice(3, 6).map(c => c.textContent)).toEqual(["A fazer", "A fazer", "A fazer"]);
    // pedido e aprovado em colunas separadas
    expect(celulas[6].textContent).toMatch(/14\.629\.981,69/);
    expect(celulas[7].textContent).toMatch(/14\.629\.981,01/);
  });

  it("o passo que a obra não tem fica vazio, e o passo da vez abre a medição menos adiantada", async () => {
    responder();
    render(<MedicoesPagina usuario={usuario} />);
    const tabela = await screen.findByRole("table", { name: "Quadro do mês" });
    const celulas = within(linhaDa(tabela, "Complexo Zeta")).getAllByRole("cell");
    expect(celulas[0].textContent).toBe("");
    expect(celulas[1].textContent).toBe("");
    expect(celulas[2].textContent).toBe("Feito");
    expect(within(celulas[3]).getByRole("link", { name: "Abrir Reajuste da 24ª Medição de Complexo Zeta: Notas" }).getAttribute("href"))
      .toBe("/obras/14/medicoes/73#passo-4");
    expect(celulas[7].textContent).toBe("—");
  });

  it("a medição com processo vivo do SIGA mostra o setor e o tempo no setor na célula do passo, com a cor de atraso da tela SIGA (#664)", async () => {
    const siga = (setor: string, dias_uteis: number | null, desde: string | null = "2026-10-20T09:00:00-04:00", hoje = 0) =>
      ({ processo_id: 5, setor, dias_uteis, desde, hoje });
    const quadro = [
      // na análise do órgão há 4 dias úteis: sem cor
      linha({ contrato_id: 21, obra: "Obra Um", medicoes: [{ id: 81, titulo: "3ª Medição" }],
        passos: [passo(1, "feito", "2026-11-02"), passo(2, "atual", null, 81, siga("SUPE", 4)), passo(3, "futuro")] }),
      // no pagamento há 5 dias úteis: atenção
      linha({ contrato_id: 22, obra: "Obra Dois", medicoes: [{ id: 82, titulo: "4ª Medição" }],
        passos: [passo(5, "feito"), passo(6, "atual", null, 82, siga("COFIN", 5))] }),
      // execução no pagamento (10 dias úteis: ação) e o reajuste ainda nas notas: a célula do pagamento é "A fazer", com a posição
      linha({ contrato_id: 23, obra: "Obra Três", medicoes: [{ id: 83, titulo: "5ª Medição" }, { id: 84, titulo: "Reajuste da 5ª Medição" }],
        passos: [passo(4, "atual", null, 84), passo(6, "futuro", null, null, siga("GABIN", 10))] }),
      // entrou no setor hoje (o mesmo texto da tela SIGA) e o processo sem data de entrada (só o setor)
      linha({ contrato_id: 24, obra: "Obra Quatro", medicoes: [{ id: 85, titulo: "6ª Medição" }],
        passos: [passo(6, "atual", null, 85, siga("PROTOC", 0, "2026-11-07T08:00:00-04:00"))] }),
      linha({ contrato_id: 25, obra: "Obra Cinco", medicoes: [{ id: 86, titulo: "7ª Medição" }],
        passos: [passo(6, "atual", null, 86, siga("ASSEJUR", null, null))] }),
      // parado há 12 dias úteis, com movimentação hoje: "hoje", como na tela SIGA
      linha({ contrato_id: 26, obra: "Obra Seis", medicoes: [{ id: 87, titulo: "8ª Medição" }],
        passos: [passo(6, "atual", null, 87, siga("COFIN", 12, "2026-10-20T09:00:00-04:00", 2))] }),
    ];
    responder(url => url.startsWith("/api/medicoes/resumo") ? { ...RESUMO, mes: "2026-10", quadro } : undefined);
    render(<MedicoesPagina usuario={usuario} />);
    const tabela = await screen.findByRole("table", { name: "Quadro do mês" });
    const posicao = (obra: string, coluna: number) => within(linhaDa(tabela, obra)).getAllByRole("cell")[coluna].querySelector(".quadro__siga");
    const um = posicao("Obra Um", 1) as HTMLElement;
    expect(um.textContent).toBe("No SIGA: SUPE 4 dias úteis");
    expect(um.querySelector(".quadro__siga-tempo")?.className).toBe("quadro__siga-tempo num");
    // a célula continua com a situação e o link do passo
    expect(within(linhaDa(tabela, "Obra Um")).getByRole("link", { name: "Abrir 3ª Medição de Obra Um: Análise do órgão" })).toBeTruthy();
    const dois = posicao("Obra Dois", 5) as HTMLElement;
    expect(dois.textContent).toBe("No SIGA: COFIN 5 dias úteis");
    expect(dois.querySelector(".quadro__siga-tempo")?.classList.contains("quadro__siga-tempo--atencao")).toBe(true);
    const tres = within(linhaDa(tabela, "Obra Três")).getAllByRole("cell")[5];
    expect(tres.textContent).toBe("A fazerNo SIGA: GABIN 10 dias úteis");
    expect(tres.querySelector(".quadro__siga-tempo")?.classList.contains("quadro__siga-tempo--acao")).toBe(true);
    expect((posicao("Obra Quatro", 5) as HTMLElement).textContent).toBe("No SIGA: PROTOC 3 h");
    expect((posicao("Obra Cinco", 5) as HTMLElement).textContent).toBe("No SIGA: ASSEJUR");
    const seis = posicao("Obra Seis", 5) as HTMLElement;
    expect(seis.textContent).toBe("No SIGA: COFIN hoje");
    expect(seis.querySelector(".quadro__siga-tempo")?.className).toBe("quadro__siga-tempo num quadro__siga-tempo--hoje");
  });

  it("a medição sem processo do SIGA não mostra o bloco (#664)", async () => {
    responder();
    render(<MedicoesPagina usuario={usuario} />);
    const tabela = await screen.findByRole("table", { name: "Quadro do mês" });
    expect(tabela.querySelector(".quadro__siga")).toBeNull();
    expect(within(tabela).queryByText(/No SIGA/)).toBeNull();
  });

  it("a obra sem medição na competência mostra Iniciar, e a Nova planilha/carta abre na competência do quadro (#653)", async () => {
    responder();
    render(<MedicoesPagina usuario={usuario} />);
    const tabela = await screen.findByRole("table", { name: "Quadro do mês" });
    expect(within(tabela).getAllByRole("button", { name: /^Iniciar a medição de / })).toHaveLength(2);
    fireEvent.click(within(tabela).getByRole("button", { name: "Iniciar a medição de Cinco Bairros" }));
    const janela = await screen.findByRole("dialog");
    expect(within(janela).getByRole("heading", { name: "Cinco Bairros · outubro de 2026" })).toBeTruthy();
    // o mesmo formulário da página da obra e da medição; o nº fica com a sugestão da obra, a competência é a do quadro
    const form = await waitFor(() => { const f = janela.querySelector("[data-nova-planilha='1']"); expect(f).not.toBeNull(); return f as HTMLElement; });
    expect([form.dataset.tipo, form.dataset.competencia, form.dataset.numero]).toEqual(["execucao", "2026-10", ""]);
    // o formulário antigo do quadro (áreas de soltar arquivo, botão próprio) saiu
    expect(within(janela).queryByRole("button", { name: "Iniciar medição" })).toBeNull();
    expect(within(janela).queryByRole("form", { name: "Nova medição" })).toBeNull();
    fireEvent.click(within(janela).getByRole("button", { name: "Registrar planilha/carta" }));
    await waitFor(() => expect(window.location.pathname).toBe("/obras/1/medicoes/99"));
  });

  it("outro mês no seletor: o formulário abre na competência escolhida, e a série de projeto vai junto", async () => {
    responder(url => url.startsWith("/api/medicoes/resumo")
      ? { ...RESUMO, mes: url.split("mes=")[1], obras: [obra({ contrato_id: 1, obra: "Cinco Bairros", proxima: 3, proxima_tipo: "projeto" })] } : undefined);
    render(<MedicoesPagina usuario={usuario} />);
    await screen.findByRole("table", { name: "Quadro do mês" });
    fireEvent.click(screen.getByRole("button", { name: "Mês anterior" }));
    await waitFor(() => expect(screen.getByRole("table", { name: "Quadro do mês" }).getAttribute("aria-busy")).toBeNull());
    fireEvent.click(screen.getByRole("button", { name: "Iniciar a medição de Cinco Bairros" }));
    const janela = await screen.findByRole("dialog");
    const form = await waitFor(() => { const f = janela.querySelector("[data-nova-planilha='1']"); expect(f).not.toBeNull(); return f as HTMLElement; });
    expect([form.dataset.tipo, form.dataset.competencia]).toEqual(["projeto", "2026-09"]);
  });

  it("a obra sem regra de espelho ativa lança a medição à mão, na competência do quadro", async () => {
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

  it("a obra sem regra de espelho com medição prevista no cronograma: abre a prevista, sem criar outra", async () => {
    responder(url => url.startsWith("/api/medicoes/resumo")
      ? { ...RESUMO, obras: [obra({ contrato_id: 3, obra: "Complexo Gama", contratante: "MTPAR", proxima: 24, prevista_id: 80 })] } : undefined, false);
    render(<MedicoesPagina usuario={usuario} />);
    fireEvent.click(await screen.findByRole("button", { name: "Iniciar a medição de Complexo Gama" }));
    const janela = await screen.findByRole("dialog");
    expect((await within(janela).findByRole("link", { name: "Abrir a 24ª medição, prevista no cronograma" })).getAttribute("href")).toBe("/obras/3/medicoes/80");
    expect(within(janela).queryByRole("form")).toBeNull();
  });

  it("Fechar a janela tira o formulário e o quadro continua", async () => {
    responder();
    render(<MedicoesPagina usuario={usuario} />);
    fireEvent.click(await screen.findByRole("button", { name: "Iniciar a medição de Cinco Bairros" }));
    const janela = await screen.findByRole("dialog");
    fireEvent.click(within(janela).getByRole("button", { name: "Fechar" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.getByRole("table", { name: "Quadro do mês" })).toBeTruthy();
  });

  it("o seletor de mês relê o quadro pela competência escolhida", async () => {
    responder();
    render(<MedicoesPagina usuario={usuario} />);
    await screen.findByRole("table", { name: "Quadro do mês" });
    fireEvent.click(screen.getByRole("button", { name: "Mês anterior" }));
    expect(screen.getByText("setembro de 2026")).toBeTruthy();
    await waitFor(() => expect(api.mock.calls.map(c => c[0])).toContain("/api/medicoes/resumo?mes=2026-09"));
    fireEvent.click(screen.getByRole("button", { name: "Mês seguinte" }));
    fireEvent.click(screen.getByRole("button", { name: "Mês seguinte" }));
    await waitFor(() => expect(api.mock.calls.map(c => c[0])).toContain("/api/medicoes/resumo?mes=2026-11"));
  });

  it("Meses anteriores: as medições abertas de outras competências, com o passo atual e Abrir", async () => {
    responder();
    render(<MedicoesPagina usuario={usuario} />);
    const tabela = await screen.findByRole("table", { name: "Meses anteriores" });
    const linhas = within(tabela).getAllByRole("row").slice(1);
    expect(linhas).toHaveLength(2);
    expect(linhas[0].textContent).toContain("MT Epsilon");
    expect(linhas[0].textContent).toContain("08/2026");
    expect(linhas[0].textContent).toContain("Análise do órgão");
    expect(within(linhas[0]).getByRole("link", { name: "Abrir 29ª Medição de MT Epsilon" }).getAttribute("href")).toBe("/obras/13/medicoes/71#passo-2");
    expect(linhas[1].textContent).toContain("23ª Medição + Reajuste");
    expect(linhas[1].textContent).toContain("Pagamento");
    expect(within(linhas[1]).getByRole("link", { name: "Abrir 23ª Medição + Reajuste de Complexo Zeta" }).getAttribute("href")).toBe("/obras/14/medicoes/60#passo-6");
  });

  it("sem medição aberta de meses anteriores: uma linha curta no lugar da tabela", async () => {
    responder(url => url.startsWith("/api/medicoes/resumo") ? { ...RESUMO, anteriores: [] } : undefined);
    render(<MedicoesPagina usuario={usuario} />);
    await screen.findByRole("table", { name: "Quadro do mês" });
    expect(screen.queryByRole("table", { name: "Meses anteriores" })).toBeNull();
    expect(screen.getByText("Nenhuma medição aberta de meses anteriores.")).toBeTruthy();
  });

  it("a diretoria vê o quadro sem o Iniciar", async () => {
    responder();
    render(<MedicoesPagina usuario={{ ...usuario, perfil: "diretoria" }} />);
    const tabela = await screen.findByRole("table", { name: "Quadro do mês" });
    expect(within(tabela).getAllByRole("row").slice(1)).toHaveLength(4);
    expect(screen.queryByRole("button", { name: /Iniciar/ })).toBeNull();
    expect(within(tabela).getByRole("link", { name: "Abrir 8ª Medição de Estações Alfa: Espelhos" })).toBeTruthy();
  });

  it("o quadro cabe a 1024 px: tabela de largura fixa, sem caixa de rolagem horizontal", async () => {
    responder();
    render(<MedicoesPagina usuario={usuario} />);
    const tabela = await screen.findByRole("table", { name: "Quadro do mês" });
    expect(tabela.className).toContain("quadro__tabela");
    expect(tabela.closest(".tabela-wrap")).toBeNull();
    // no celular cada obra vira um bloco: a célula leva o nome do passo
    expect(within(linhaDa(tabela, "Estações Alfa")).getAllByRole("cell").map(c => c.getAttribute("data-rotulo")))
      .toEqual([...NOMES, "Pedido", "Aprovado"]);
  });

  it("falha ao ler as medições: mensagem em português", async () => {
    api.mockRejectedValue(new Error("falhou"));
    render(<MedicoesPagina usuario={usuario} />);
    expect(await screen.findByRole("alert")).toBeTruthy();
  });
});
