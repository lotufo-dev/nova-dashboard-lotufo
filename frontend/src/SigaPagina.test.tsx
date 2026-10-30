import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import SigaPagina from "./SigaPagina";
import type { Movimentacao, PainelSiga, ProcessoSiga, Robo } from "./siga";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

// 28/10/2026, 11h30 em Cuiaba. Pessoas, obras e processos fictícios.
const AGORA = new Date("2026-10-28T15:30:00Z");
const mov = (data: string, evento: string, extra: Partial<Movimentacao> = {}): Movimentacao => ({
  data, evento, cad_lotacao: "PROTOC/ORGAO", cad_pessoa: "Beltrano", at_lotacao: "COFIN/ORGAO", at_pessoa: "Fulano", ...extra });
const processo = (extra: Partial<ProcessoSiga>): ProcessoSiga => ({
  id: 1, codigo: null, link: null, numero: null, nome: null, contrato_id: null, obra: null, medicao_id: null,
  medicao_titulo: null, protocolo_id: null, situacao: "1º Volume - Aguardando Andamento [COFIN, [X]]", setor: "COFIN",
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
    mov("2026-10-28T09:30:00-04:00", "Recebimento | texto do órgão"),
    mov("2026-10-25T08:00:00-04:00", "Transferência", { cad_pessoa: "Sicrana", cad_lotacao: "PROTOC/ORGAO", at_lotacao: "GABIN/ORGAO", at_pessoa: "" }),
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

const PARADO: Robo = { estado: "parado", rodada: null, pedidos: [], avisos: [] };
const painel = (processos: ProcessoSiga[], extra: Partial<PainelSiga> = {}): PainelSiga =>
  ({ lido_em: "2026-10-28T15:00:00+00:00", atrasado: false, processos, pode_atualizar: false, robo: PARADO, ...extra });
const mostrar = (dados: PainelSiga, busca: Record<string, string> = {}) => {
  api.mockResolvedValue(dados);
  return render(<SigaPagina busca={busca} agora={AGORA} />);
};
const grupo = (nome: string) => screen.getByText(nome).closest("tbody") as HTMLElement;
const nomesNoGrupo = (nome: string) => within(grupo(nome)).getAllByRole("row").slice(1).map(l => l.getAttribute("aria-label"));

describe("SigaPagina", () => {
  afterEach(() => { cleanup(); api.mockReset(); window.history.replaceState(null, "", "/"); });

  it("separa os processos de medições dos outros; o ligado mostra a obra e a medição com link para a etapa 4, o outro o nome do robô", async () => {
    mostrar(painel([ALFA, BETA]));
    await screen.findByText("Processos de medições");
    expect(nomesNoGrupo("Processos de medições")).toEqual(["Obra Alfa · 7ª Medição"]);
    expect(nomesNoGrupo("Outros processos")).toEqual(["Processo Beta"]);
    const link = screen.getByRole("link", { name: "7ª Medição" });
    expect(link.getAttribute("href")).toBe("/obras/7/medicoes/31#etapa-4");
    expect(within(grupo("Processos de medições")).getByText("Obra Alfa")).toBeTruthy();
  });

  it("?processo= (o 'Abrir' do aviso) abre o painel desse processo; id que não existe cai no primeiro", async () => {
    const { unmount } = mostrar(painel([ALFA, DELTA]), { processo: String(DELTA.id) });
    expect((await screen.findByRole("complementary", { name: "Detalhe do processo" })).textContent).toMatch(/Obra Delta/);
    expect(screen.getByRole("row", { name: /Obra Delta/ }).getAttribute("aria-selected")).toBe("true");
    unmount();
    mostrar(painel([ALFA, DELTA]), { processo: "999" });
    expect((await screen.findByRole("complementary", { name: "Detalhe do processo" })).textContent).toMatch(/Obra Alfa/);
  });

  it("grupo vazio não aparece", async () => {
    mostrar(painel([BETA]));
    await screen.findByText("Outros processos");
    expect(screen.queryByText("Processos de medições")).toBeNull();
  });

  it("quem andou hoje vem primeiro (o mais recente no topo), depois os parados há mais tempo", async () => {
    mostrar(painel([DELTA, ALFA, EPSILON, BETA, GAMA]));
    await screen.findByText("Outros processos");
    expect(nomesNoGrupo("Processos de medições")).toEqual(["Obra Épsilon · 2ª Medição", "Obra Alfa · 7ª Medição", "Obra Delta · 4ª Medição"]);
    expect(nomesNoGrupo("Outros processos")).toEqual(["Processo Gama", "Processo Beta"]);
  });

  it("movimentação hoje: ponto verde e a contagem em Hoje; sem movimentação, sem ponto", async () => {
    mostrar(painel([ALFA, DELTA]));
    const linha = await screen.findByRole("row", { name: /Obra Alfa/ });
    expect(linha.querySelector(".sg__ponto--hoje")).toBeTruthy();
    expect(within(linha).getByText("1")).toBeTruthy();
    expect(screen.getByRole("row", { name: /Obra Delta/ }).querySelector(".sg__ponto--hoje")).toBeNull();
  });

  it("selo âmbar a partir de 5 dias úteis no setor, vermelho a partir de 10, nenhum antes", async () => {
    mostrar(painel([DELTA, BETA, GAMA]));
    await screen.findByText("Outros processos");
    expect(screen.getByText("12 dias úteis").closest(".selo")?.className).toContain("selo--acao");
    expect(screen.getByText("6 dias úteis").closest(".selo")?.className).toContain("selo--atencao");
    expect(screen.getByText("3 dias úteis").closest(".selo")).toBeNull();
  });

  it("No setor há: minutos e horas antes de um dia útil", async () => {
    mostrar(painel([ALFA, EPSILON]));
    await screen.findByText("Processos de medições");
    expect(screen.getByText("3 h")).toBeTruthy();       // desde 08h00, agora 11h30
    expect(screen.getByText("30 min")).toBeTruthy();    // desde 11h00
  });

  it("Onde está: setor, caixa de entrada e volume; Última ação sem o texto depois de ' |'", async () => {
    mostrar(painel([ALFA, BETA]));
    const beta = await screen.findByRole("row", { name: /Processo Beta/ });
    expect(within(beta).getByText("GABIN")).toBeTruthy();
    expect(within(beta).getByText("caixa de entrada")).toBeTruthy();
    expect(within(beta).getByText("(2º Volume)")).toBeTruthy();
    const alfa = screen.getByRole("row", { name: /Obra Alfa/ });
    expect(within(alfa).getByText("Recebimento")).toBeTruthy();
    expect(within(alfa).queryByText(/texto do órgão/)).toBeNull();
    expect(within(alfa).getByText("Fulano")).toBeTruthy();                // Com quem
    expect(within(alfa).getByText("01/10/2026")).toBeTruthy();            // Protocolado
  });

  it("a primeira linha abre no painel; clicar em outra troca o painel (número, situação, Abrir no SIGA, movimentações da mais recente para a mais antiga)", async () => {
    mostrar(painel([ALFA, BETA]));
    const painelAlfa = await screen.findByRole("complementary", { name: "Detalhe do processo" });
    expect(within(painelAlfa).getByRole("heading", { name: /Obra Alfa · 7ª Medição/ })).toBeTruthy();
    expect(within(painelAlfa).getByText("ORGAO-PRO-2026/00001")).toBeTruthy();
    expect(within(painelAlfa).getByText("1º Volume - Aguardando Andamento [COFIN, [X]]")).toBeTruthy();
    const abrir = within(painelAlfa).getByRole("link", { name: /Abrir no SIGA/ });
    expect(abrir.getAttribute("href")).toBe("https://siga.exemplo.com.br/acompanhar?n=ABC123");
    const itens = within(painelAlfa).getAllByRole("listitem").map(li => li.textContent ?? "");
    expect(itens).toHaveLength(3);
    expect(itens[0]).toContain("Recebimento");          // 28/10, a mais recente
    expect(itens[1]).toContain("Transferência");        // 25/10
    expect(itens[1]).toContain("→ GABIN");
    expect(itens[1]).toContain("Sicrana");
    expect(itens[2]).toContain("Cadastro");             // 20/10, a mais antiga
    expect(itens[0]).toContain("28/10/2026 às 09:30");

    fireEvent.click(screen.getByRole("row", { name: /Processo Beta/ }));
    const painelBeta = screen.getByRole("complementary", { name: "Detalhe do processo" });
    expect(within(painelBeta).getByRole("heading", { name: "Processo Beta" })).toBeTruthy();
    expect(within(painelBeta).queryByRole("link", { name: /Abrir no SIGA/ })).toBeNull();   // sem código, sem link
  });

  it("sem nenhum processo: só a linha 'Nenhum processo acompanhado.'", async () => {
    mostrar(painel([], { lido_em: null }));
    expect(await screen.findByText("Nenhum processo acompanhado.")).toBeTruthy();
    expect(screen.queryByText(/Lido às/)).toBeNull();
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByRole("complementary")).toBeNull();
  });

  it("mostra a hora local da última leitura; atrasado avisa desde quando, em dia não avisa", async () => {
    const { unmount } = mostrar(painel([ALFA], { atrasado: true, lido_em: "2026-10-28T12:00:00+00:00" }));
    const lido = await screen.findByText((_, el) => el?.tagName === "P" && el.textContent === "Lido às 08:00");
    expect(lido).toBeTruthy();
    expect(screen.getByText("O monitor do SIGA não lê desde 28/10 08:00.")).toBeTruthy();
    unmount();
    mostrar(painel([ALFA]));
    await screen.findByText("Processos de medições");
    expect(screen.getByText((_, el) => el?.tagName === "P" && el.textContent === "Lido às 11:00")).toBeTruthy();
    expect(screen.queryByText(/O monitor do SIGA não lê/)).toBeNull();
  });

  it("filtra por obra, nome do robô ou número, sem diferenciar maiúscula e acento", async () => {
    mostrar(painel([ALFA, EPSILON, BETA]), { q: "EPSILON" });
    await screen.findByText("Processos de medições");
    expect(nomesNoGrupo("Processos de medições")).toEqual(["Obra Épsilon · 2ª Medição"]);
    expect(screen.queryByText("Outros processos")).toBeNull();
  });

  it("digitar na busca troca o filtro na URL", async () => {
    mostrar(painel([ALFA, BETA]));
    const campo = await screen.findByRole("searchbox", { name: "Buscar obra" });
    fireEvent.change(campo, { target: { value: "alfa" } });
    expect(window.location.search).toBe("?q=alfa");
  });

  it("rele a cada 15 minutos sem perder a linha aberta; o aviso de atraso aparece quando a resposta nova o traz; ao sair, para", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      mostrar(painel([ALFA, BETA]));
      await screen.findByText("Processos de medições");
      fireEvent.click(screen.getByRole("row", { name: /Processo Beta/ }));
      expect(api).toHaveBeenCalledTimes(1);
      expect(screen.queryByText(/O monitor do SIGA não lê/)).toBeNull();
      api.mockResolvedValue(painel([ALFA, BETA], { atrasado: true, lido_em: "2026-10-28T12:00:00+00:00" }));
      await vi.advanceTimersByTimeAsync(15 * 60_000);
      expect(api).toHaveBeenCalledTimes(2);
      expect(await screen.findByText("O monitor do SIGA não lê desde 28/10 08:00.")).toBeTruthy();
      expect(screen.getByRole("complementary", { name: "Detalhe do processo" }).querySelector("h2")?.textContent).toBe("Processo Beta");
      cleanup();
      await vi.advanceTimersByTimeAsync(30 * 60_000);
      expect(api).toHaveBeenCalledTimes(2);
    } finally { vi.useRealTimers(); }
  });

  // issue #339: link colado na tela SIGA
  const OBRAS = [{ id: 9, orgao: "ORGAO", numero_instrumento: "IC 9/2026", nome_curto: "Obra Zeta", estado: "em_andamento" },
                 { id: 7, orgao: "ORGAO", numero_instrumento: "IC 7/2026", nome_curto: "Obra Alfa", estado: "em_andamento" }];
  const NOVO = processo({ id: 8, codigo: "XyZ98765", nome: "Aditivo de prazo", contrato_id: 7, obra: "Obra Alfa",
    situacao: null, setor: "", com_quem: "", desde: null, dias_uteis: null, ultima: null, protocolado_em: null, movimentacoes: [] });
  const comFormulario = (antes: ProcessoSiga[], depois: ProcessoSiga[], resposta: () => Promise<unknown>) => {
    const chamadas: { caminho: string; opts?: RequestInit }[] = [];
    let gravado = false;
    api.mockImplementation(async (caminho: string, opts?: RequestInit) => {
      chamadas.push({ caminho, opts });
      if (caminho === "/api/contratos") return OBRAS;
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
    fireEvent.change(within(form).getByLabelText("Nome"), { target: { value: "Aditivo de prazo" } });
    await within(form).findByRole("option", { name: "Obra Alfa" });
    fireEvent.change(within(form).getByLabelText("Obra"), { target: { value: "7" } });
    fireEvent.change(within(form).getByLabelText("Nº do processo"), { target: { value: "ORGAO-PRO-2026/00009" } });
    fireEvent.click(within(form).getByRole("button", { name: "Acompanhar" }));
    return form;
  };

  it("Acompanhar processo: abre o formulário com link, nome, obra (em ordem alfabética, 'Sem obra' primeiro) e número; envia, a lista recarrega e o novo abre no painel", async () => {
    const chamadas = comFormulario([BETA], [BETA, NOVO], async () => ({ id: 8 }));
    await preencher();
    const linha = await screen.findByRole("row", { name: "Aditivo de prazo" });
    expect(within(linha).getByText("Obra Alfa")).toBeTruthy();
    expect(screen.getByRole("complementary", { name: "Detalhe do processo" }).querySelector("h2")?.textContent).toBe("Aditivo de prazo");
    expect(screen.queryByRole("form", { name: "Acompanhar processo" })).toBeNull();
    const envio = chamadas.find(c => c.caminho === "/api/siga/processos-avulsos");
    expect(envio?.opts?.method).toBe("POST");
    expect(JSON.parse(envio?.opts?.body as string)).toEqual({
      link: "https://siga.exemplo.com.br/acompanhar?n=XyZ98765", nome: "Aditivo de prazo", numero: "ORGAO-PRO-2026/00009", contrato_id: 7 });
    const opcoes = Array.from(document.querySelectorAll("#siga-obra option")).map(o => o.textContent);
    expect(opcoes).toEqual([]);   // formulario fechado depois de gravar
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
    expect(nomesNoGrupo("Outros processos")).toEqual(["Processo Beta"]);
    expect((within(form).getByLabelText("Nome") as HTMLInputElement).value).toBe("Aditivo de prazo");
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
    expect(await screen.findByText("Processos de medições")).toBeTruthy();
  });

  // issue #343: botoes de atualizar e robo em andamento
  const RODADA = (tipo: "automatica" | "pedido", processos: number[]): Robo => ({
    estado: "lendo", rodada: { id: 4, tipo, iniciada_em: "2026-10-28T15:20:00+00:00", processos }, pedidos: [], avisos: [] });
  const NA_FILA = (processo_id: number | null): Robo => ({
    estado: "na_fila", rodada: null, avisos: [],
    pedidos: [{ id: 9, processo_id, usuario: "Fulano", pedido_em: "2026-10-28T15:25:00+00:00" }] });
  const botao = (nome: RegExp | string) => screen.getByRole("button", { name: nome }) as HTMLButtonElement;
  const painelDireita = () => screen.getByRole("complementary", { name: "Detalhe do processo" });

  it("sem o servidor configurado, nenhum botão de atualizar; configurado, 'Atualizar todos' no topo e 'Atualizar processo' no painel", async () => {
    const { unmount } = mostrar(painel([ALFA]));
    await screen.findByText("Processos de medições");
    expect(screen.queryByRole("button", { name: /Atualizar/ })).toBeNull();
    unmount();
    mostrar(painel([ALFA], { pode_atualizar: true }));
    await screen.findByText("Processos de medições");
    expect(botao("Atualizar todos").disabled).toBe(false);
    expect(within(painelDireita()).getByRole("button", { name: "Atualizar processo" })).toBeTruthy();
  });

  it("os botões pedem a leitura com e sem processo_id e a tela relê", async () => {
    const chamadas: { caminho: string; opts?: RequestInit }[] = [];
    api.mockImplementation(async (caminho: string, opts?: RequestInit) => {
      chamadas.push({ caminho, opts });
      return caminho === "/api/siga" ? painel([ALFA], { pode_atualizar: true }) : { id: 9 };
    });
    render(<SigaPagina busca={{}} agora={AGORA} />);
    fireEvent.click(await screen.findByRole("button", { name: "Atualizar processo" }));
    await vi.waitFor(() => expect(chamadas.filter(c => c.caminho === "/api/siga")).toHaveLength(2));
    fireEvent.click(botao("Atualizar todos"));
    await vi.waitFor(() => expect(chamadas.filter(c => c.caminho === "/api/siga")).toHaveLength(3));
    const pedidos = chamadas.filter(c => c.caminho === "/api/siga/atualizar");
    expect(pedidos.map(c => c.opts?.method)).toEqual(["POST", "POST"]);
    expect(pedidos.map(c => JSON.parse(c.opts?.body as string))).toEqual([{ processo_id: ALFA.id }, {}]);
  });

  it("pedido na fila: o botão vira 'Na fila' desabilitado e o topo mostra a hora do pedido no lugar de 'Lido às'", async () => {
    mostrar(painel([ALFA, DELTA], { pode_atualizar: true, robo: NA_FILA(ALFA.id) }));
    await screen.findByText("Processos de medições");
    expect(within(painelDireita()).getByRole("button", { name: "Na fila" }).hasAttribute("disabled")).toBe(true);
    expect(botao("Atualizar todos").disabled).toBe(false);           // pedido de um processo nao cobre todos
    expect(screen.getByText((_, el) => el?.tagName === "P" && el.textContent === "Pedido de atualização às 11:25, aguardando o robô")).toBeTruthy();
    expect(screen.queryByText(/Lido às/)).toBeNull();
    fireEvent.click(screen.getByRole("row", { name: /Obra Delta/ }));
    expect(within(painelDireita()).getByRole("button", { name: "Atualizar processo" })).toBeTruthy();
  });

  it("pedido de todos na fila: os dois botões ficam 'Na fila'", async () => {
    mostrar(painel([ALFA], { pode_atualizar: true, robo: NA_FILA(null) }));
    await screen.findByText("Processos de medições");
    expect(screen.getAllByRole("button", { name: "Na fila" })).toHaveLength(2);
  });

  it("rodada pedida na tela: indicador no topo, 'lendo...' só nas linhas da rodada e 'Lendo...' nos botões que ela cobre", async () => {
    mostrar(painel([ALFA, DELTA], { pode_atualizar: true, robo: RODADA("pedido", [ALFA.id]) }));
    await screen.findByText("Processos de medições");
    expect(screen.getByText((_, el) => el?.tagName === "P" && el.textContent === "Robô lendo agora · começou às 11:20 · pedido feito na tela")).toBeTruthy();
    expect(within(screen.getByRole("row", { name: /Obra Alfa/ })).getByText("lendo...")).toBeTruthy();
    expect(within(screen.getByRole("row", { name: /Obra Delta/ })).queryByText("lendo...")).toBeNull();
    expect(screen.getAllByRole("button", { name: "Lendo..." }).every(b => b.hasAttribute("disabled"))).toBe(true);
    expect(screen.queryByRole("button", { name: "Atualizar todos" })).toBeNull();
    expect(within(painelDireita()).getByRole("button", { name: "Lendo..." })).toBeTruthy();
    fireEvent.click(screen.getByRole("row", { name: /Obra Delta/ }));
    expect(within(painelDireita()).getByRole("button", { name: "Atualizar processo" })).toBeTruthy();
  });

  it("rodada automática: o topo diz 'rodada automática' e 'Atualizar todos' fica 'Lendo...'", async () => {
    mostrar(painel([ALFA], { pode_atualizar: true, robo: RODADA("automatica", [ALFA.id]) }));
    await screen.findByText("Processos de medições");
    expect(screen.getByText(/rodada automática/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Atualizar todos" })).toBeNull();
    expect(screen.getAllByRole("button", { name: "Lendo..." }).every(b => b.hasAttribute("disabled"))).toBe(true);
  });

  it("avisos do robô: os gerais em vermelho no topo, o de processo na linha dele", async () => {
    const avisos = [
      { tipo: "disparo", processo_id: null, texto: "O Windows não iniciou o robô: acesso negado" },
      { tipo: "falha", processo_id: null, texto: "A rodada das 11:00 falhou: SIGA fora do ar" },
      { tipo: "nao_lido", processo_id: DELTA.id, texto: "não lido às 11:00: página não abriu" },
      { tipo: "nao_lidos", processo_id: null, texto: "1 de 2 processos não foram lidos" },
    ];
    mostrar(painel([ALFA, DELTA], { robo: { ...PARADO, avisos } }));
    await screen.findByText("Processos de medições");
    const topo = screen.getAllByRole("alert").map(a => a.textContent ?? "");
    expect(topo).toHaveLength(3);
    expect(topo.every(t => t.startsWith("Crítico: "))).toBe(true);
    expect(topo.map(t => t.replace("Crítico: ", ""))).toEqual([
      "O Windows não iniciou o robô: acesso negado", "A rodada das 11:00 falhou: SIGA fora do ar", "1 de 2 processos não foram lidos"]);
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
    fireEvent.click(await screen.findByRole("button", { name: "Atualizar todos" }));
    expect((await screen.findByRole("alert")).textContent).toContain("Atualizar pelo SIGA não está disponível neste servidor");
    expect(botao("Atualizar todos").disabled).toBe(false);
  });

  it("Windows recusou: o botão volta a valer para tentar de novo e a tela não relê a cada 5 segundos", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const robo = { ...NA_FILA(ALFA.id), avisos: [{ tipo: "disparo", processo_id: null, texto: "O Windows não iniciou o robô: acesso negado" }] };
      mostrar(painel([ALFA], { pode_atualizar: true, robo }));
      await screen.findByText("Processos de medições");
      expect(within(painelDireita()).getByRole("button", { name: "Atualizar processo" }).hasAttribute("disabled")).toBe(false);
      await vi.advanceTimersByTimeAsync(60_000);
      expect(api).toHaveBeenCalledTimes(1);
    } finally { vi.useRealTimers(); }
  });

  it("com o robô ativo relê a cada 5 segundos; ao terminar mostra 'Lido às' novo e volta aos 15 minutos", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      mostrar(painel([ALFA], { robo: RODADA("pedido", [ALFA.id]) }));
      await screen.findByText(/Robô lendo agora/);
      expect(api).toHaveBeenCalledTimes(1);
      await vi.advanceTimersByTimeAsync(5_000);
      expect(api).toHaveBeenCalledTimes(2);
      api.mockResolvedValue(painel([ALFA], { lido_em: "2026-10-28T15:28:00+00:00" }));
      await vi.advanceTimersByTimeAsync(5_000);
      expect(await screen.findByText((_, el) => el?.tagName === "P" && el.textContent === "Lido às 11:28")).toBeTruthy();
      const depois = api.mock.calls.length;
      await vi.advanceTimersByTimeAsync(60_000);
      expect(api).toHaveBeenCalledTimes(depois);
      await vi.advanceTimersByTimeAsync(15 * 60_000);
      expect(api.mock.calls.length).toBeGreaterThan(depois);
    } finally { vi.useRealTimers(); }
  });
});
