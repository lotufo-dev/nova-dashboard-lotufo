import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { comLeitura, leituraDeTeste } from "./andamentoTeste";
import Contratos from "./Contratos";
import type { ObraLista } from "./listaObras";
import { useRota } from "./rota";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

// Dados sintéticos: dois contratantes (SINFRA com duas superintendências, MTPAR) e uma obra encerrada. `posicao` é o que
// a lista mostra (na cota da Lotufo, do servidor); os valores cheios ao lado são outros de propósito.
const posicao = (vigente: number, medido: number, aReceber: number | null) =>
  ({ vigente_centavos: vigente, medido_centavos: medido, saldo_centavos: vigente - medido, a_receber_centavos: aReceber });
// #822: a leitura do andamento vem do servidor; `comLeitura` põe em cada obra a que ele mandaria para o ritmo e o necessário dela
const obra = (id: number, nome: string, extra: Partial<ObraLista> = {}): ObraLista => comLeitura({
  id, orgao: "SINFRA - SUEF II", contratante: "SINFRA", orgao_sub: "SUEF II", numero_instrumento: `IC ${id}/2026`, nome_curto: nome,
  estado: "ativo", entidade_id: 1, valor_vigente_centavos: 1000_00, medido_centavos: 250_00, saldo_centavos: 750_00, percentual_direito_bp: 10000,
  posicao: posicao(1000_00, 250_00, 100_00), contratante_chave: "sinfra",
  execucao_fim_vigente: "2027-03-31", vigencia_fim_vigente: "2027-06-30", dias_execucao: 100, dias_vigencia: 200, ...extra });
// #805: o medido da competência fechada (agosto) e o da anterior (julho), e o ritmo contra o necessário por mês
const doMes = (valor: number, referencia: number) =>
  ({ competencia: "2026-08", valor_centavos: valor, referencia_competencia: "2026-07", referencia_centavos: referencia });

const OBRAS: ObraLista[] = [
  // mede 27% do necessário: devagar
  obra(1, "Estações BRT", { andamento: { ritmo_centavos: 27_00, necessario_centavos: 100_00 }, medido_mes: doMes(80_00, 100_00) }),
  // consórcio a 49%: cheio 3.000,01 / 1.500,00; na cota 1.470,00 / 735,00. Mede 120% do necessário: adiantada
  obra(2, "MT-388", { orgao: "SINFRA - SUPU", orgao_sub: "SUPU", percentual_direito_bp: 4900, valor_vigente_centavos: 3000_01, medido_centavos: 1500_00, saldo_centavos: 1500_01,
    posicao: posicao(1470_00, 735_00, 49_01), andamento: { ritmo_centavos: 120_00, necessario_centavos: 100_00 }, medido_mes: doMes(60_00, 20_00) }),
  // paralisada: sem necessário (não há prazo a cumprir) e sem medição no mês
  obra(3, "Granito", { orgao: "MTPAR", contratante: "MTPAR", contratante_chave: "mtpar", orgao_sub: null, valor_vigente_centavos: 2000_00, medido_centavos: 500_00,
    saldo_centavos: 1500_00, posicao: posicao(2000_00, 500_00, 100_00), estado: "suspenso", execucao_fim_vigente: "2026-12-31",
    andamento: { ritmo_centavos: 10_00, necessario_centavos: null }, medido_mes: doMes(0, 0) }),
  obra(4, "Deciolândia", { orgao: "MTPAR", contratante: "MTPAR", contratante_chave: "mtpar", orgao_sub: null, estado: "encerrado", execucao_fim_vigente: "2025-12-31" }),
];

// o painel da diretoria (`/api/diretoria`): o farol de cada obra, o medido do ano e os reajustes
const farol = (contrato_id: number, obra: string, f: "verde" | "atencao" | "vermelho") => ({ contrato_id, seq: contrato_id, obra,
  contratante: "SINFRA", empreita: "PRÓPRIA", direito: 1, pi_va: 0, faturados: 0, saldo: 0, status: "EM ANDAMENTO", termino: null,
  farol: f, motivo: "", motivos: [] });
const PAINEL = { hoje: "2026-09-24", medido_ano: { ano: "2026", valor_centavos: 100_00 },
  avisos: [],
  obras: [farol(1, "Estações BRT", "vermelho"), farol(2, "MT-388", "verde"), farol(3, "Granito", "atencao")],
  reajustes_apostilamento: { competencias: 2, valor_centavos: 300_00, obras: [{ contrato_id: 2, obra: "MT-388", competencias: 2, valor_centavos: 300_00 }] } };

const AVISOS = [
  { tipo: "execucao_vencendo", nivel: "critico", publico: ["operacao"], contrato_id: 1, obra: "Estações BRT", dias: 5, valor_centavos: null,
    mensagem: "Estações BRT: execução termina em 5 dias (04/11/2026)", destino: { tela: "contrato", id: 1, aba: "prazos" }, data: "2026-11-04", sentido: "prazo" },
  { tipo: "vigencia_vencendo", nivel: "atencao", publico: ["operacao"], contrato_id: 1, obra: "Estações BRT", dias: 50, valor_centavos: null,
    mensagem: "Estações BRT: vigência termina em 50 dias (20/12/2026)", destino: { tela: "contrato", id: 1, aba: "prazos" }, data: "2026-12-20", sentido: "prazo" },
  { tipo: "documento_vencendo", nivel: "atencao", publico: ["operacao"], contrato_id: null, obra: null, entidade_id: 1, entidade: "Construtora Alfa",
    dias: 9, valor_centavos: null, mensagem: "Construtora Alfa: certidão vence em 9 dias", destino: null, data: "2026-10-25", sentido: "prazo" },
];

function Pagina() {
  const { rota, busca, ir } = useRota();
  // a vista vem do endereço, como no App; fora de Obras (o filtro de antes que vira a página do contratante), nada
  return rota.tela === "obras" ? <Contratos ir={ir} busca={busca} aba={rota.aba} /> : <p>outra tela</p>;
}

function abrir(url: string) {
  window.history.replaceState(null, "", url);
  return render(<Pagina />);
}

describe("Obras: posição financeira na cota da Lotufo, por contratante", () => {
  beforeEach(() => {
    api.mockImplementation(async (caminho: string) => {
      if (caminho === "/api/contratos") return OBRAS;
      if (caminho === "/api/entidades") return [{ id: 1, nome: "Construtora Alfa Ltda", nome_curto: "Alfa" }];
      if (caminho === "/api/inicio") return { avisos: AVISOS };
      if (caminho === "/api/diretoria") return { ...PAINEL, obras: [], reajustes_apostilamento: undefined };       // sem farol nem reajuste: so' a lista
      throw new Error(`chamada inesperada: ${caminho}`);
    });
  });
  afterEach(() => { cleanup(); api.mockReset(); window.history.replaceState(null, "", "/"); });

  it("#774: os números da lista são exatos, somam as linhas e trazem o medido do ano só com a lista inteira", async () => {
    abrir("/obras/todas");
    await screen.findByRole("table");
    // 1.000,00 + 1.470,00 + 2.000,00 de vigente; 250,00 + 735,00 + 500,00 de medido (33%)
    expect(totais()).toBe("ContratadoR$ 4.470,00Medido (33%)R$ 1.485,00Saldo a executarR$ 2.985,00A receberR$ 249,01Medido em 2026R$ 100,00");
    cleanup();
    abrir("/obras?q=granito");
    await screen.findByRole("table");
    expect(totais()).toBe("ContratadoR$ 2.000,00Medido (25%)R$ 500,00Saldo a executarR$ 1.500,00A receberR$ 100,00");
  });

  it("o a receber antigo e o sem atualização do RM ficam numa linha própria, fora do total, e seguem o filtro", async () => {
    // docs/adr/0006: o servidor manda o que fica à parte em cada obra; a lista soma as obras que mostra
    const comAntigo = OBRAS.map(o => ({ ...o, posicao: { ...o.posicao!, a_receber_ano_inicial: "2025",
      a_receber_anterior_centavos: o.id === 1 ? 70_003 : 0, a_receber_sem_atualizacao_centavos: o.id === 3 ? 40_001 : 0 } }));
    api.mockImplementation(async (caminho: string) => {
      if (caminho === "/api/contratos") return comAntigo;
      if (caminho === "/api/entidades") return [{ id: 1, nome: "Construtora Alfa Ltda", nome_curto: "Alfa" }];
      if (caminho === "/api/inicio") return { avisos: AVISOS };
      if (caminho === "/api/diretoria") return { ...PAINEL, obras: [], reajustes_apostilamento: undefined };
      throw new Error(`chamada inesperada: ${caminho}`);
    });
    abrir("/obras/todas");
    await screen.findByRole("table");
    expect(totais()).toContain("A receberR$ 249,01");                       // o total não muda
    const bloco = screen.getByLabelText("Em aberto fora do total");
    expect((bloco.textContent ?? "").replace(/\u00a0/g, " ")).toContain("Em aberto de competências anteriores a 2025R$ 700,03");
    expect((bloco.textContent ?? "").replace(/\u00a0/g, " ")).toContain("Sem atualização do RMR$ 400,01");
    cleanup();
    abrir("/obras?q=granito");
    await screen.findByRole("table");
    expect(screen.getByLabelText("Em aberto fora do total").textContent?.replace(/\u00a0/g, " ")).toBe("Sem atualização do RMR$ 400,01");
  });

  it("sem nada à parte, a lista não ganha a linha", async () => {
    abrir("/obras/todas");
    await screen.findByRole("table");
    expect(screen.queryByLabelText("Em aberto fora do total")).toBeNull();
  });

  it("#774: a obra que não está em dia leva o selo do farol sob o nome; a em dia não leva marca", async () => {
    const base = api.getMockImplementation()!;
    api.mockImplementation(async (caminho: string) => (caminho === "/api/diretoria" ? PAINEL : base(caminho)));
    abrir("/obras/todas");
    await screen.findByRole("table", { name: /Obras, posição/ });
    const tabela = screen.getByRole("table", { name: /Obras, posição/ });
    const linha = (nome: string) => within(tabela).getByRole("link", { name: nome }).closest("tr")!;
    await waitFor(() => expect(linha("Estações BRT").querySelector(".selo--critico")).toBeTruthy());
    expect(linha("Estações BRT").querySelector(".selo--critico")!.textContent).toBe("Crítico");
    expect(linha("Estações BRT").querySelector(".selo .glifo--critico")).toBeTruthy();
    expect(linha("Granito").querySelector(".selo--breve")!.textContent).toBe("Atenção");
    expect(linha("MT-388").querySelector(".selo")).toBeNull();
    // o subtotal do contratante traz o executado dele, por piso: SINFRA 985,00 de 2.470,00 (39,9%) e' 39%
    expect(grupos()[1].querySelector(".obras-exec__pct")!.textContent).toBe("39%");
  });

  it("#779: o executado dos totais e do contratante e' por piso: 99,6% aparece como 99%, nunca 100% antes de concluir", async () => {
    api.mockImplementation(async (caminho: string) => {
      if (caminho === "/api/contratos") return [obra(1, "Estações BRT", { medido_centavos: 996_00, saldo_centavos: 4_00, posicao: posicao(1000_00, 996_00, null) })];
      if (caminho === "/api/entidades") return [];
      if (caminho === "/api/inicio") return { avisos: [] };
      if (caminho === "/api/diretoria") return { ...PAINEL, obras: [] };
      throw new Error(`chamada inesperada: ${caminho}`);
    });
    abrir("/obras/todas");
    await screen.findByRole("table", { name: /Obras, posição/ });
    expect(totais()).toContain("Medido (99%)R$ 996,00");
    expect(grupos()[0].querySelector(".obras-exec__pct")!.textContent).toBe("99%");
  });

  it("medido acima do valor vigente: o saldo negativo sai em crítico com o glifo, como no alto da página da obra", async () => {
    api.mockImplementation(async (caminho: string) => {
      if (caminho === "/api/contratos") return [obra(1, "5 Bairros", { posicao: posicao(1000_00, 1002_50, null) }),
        obra(2, "Leblon", { posicao: posicao(1000_00, 400_00, null) })];
      if (caminho === "/api/entidades") return [];
      if (caminho === "/api/inicio") return { avisos: [] };
      if (caminho === "/api/diretoria") return { ...PAINEL, obras: [] };
      throw new Error(`chamada inesperada: ${caminho}`);
    });
    abrir("/obras/todas");
    const tabela = await screen.findByRole("table", { name: /Obras, posição/ });
    const saldos = [...tabela.querySelectorAll<HTMLElement>('tbody td[data-rotulo="Saldo a executar"]')]
      .filter(td => td.closest("tr")!.querySelector(".obras-exec"));
    const negativo = saldos.find(td => td.textContent!.includes("2,50"))!;
    expect(negativo.className).toContain("negativo");
    expect(negativo.querySelector(".glifo--critico")).toBeTruthy();
    expect(negativo.closest("tr")!.querySelector(".obras-exec__pct")!.textContent).toBe("100%");
    const positivo = saldos.find(td => td.textContent!.includes("600,00"))!;
    expect(positivo.className).not.toContain("negativo");
    expect(positivo.querySelector(".glifo")).toBeNull();
  });

  it("#774: ?termina=90 (os links do QDOP) recorta a lista pelo fim do prazo e oferece voltar a todas", async () => {
    abrir("/obras?termina=150");
    await screen.findByRole("table");
    expect(nomes()).toEqual(["Estações BRT", "MT-388"]);     // a suspensa só conta a vigência; a encerrada fica fora
    expect(screen.getByText("Terminam em até 150 dias")).toBeTruthy();
    // #805: o endereço de antes ("/obras" com filtro) passa a ser o da tabela de todas as obras, com o filtro
    expect(window.location.pathname + window.location.search).toBe("/obras/todas?termina=150");
    expect(screen.getByRole("link", { name: "Tirar o filtro" }).getAttribute("href")).toBe("/obras/todas");
    expect(screen.queryByText(/Medido em 2026/)).toBeNull();
  });

  it("#774: sem o painel da diretoria a lista continua, com um aviso no lugar do farol e dos reajustes", async () => {
    const base = api.getMockImplementation()!;
    api.mockImplementation(async (caminho: string) => {
      if (caminho === "/api/diretoria") throw new Error("falhou");
      return base(caminho);
    });
    abrir("/obras/todas");
    await screen.findByRole("table");
    expect((await screen.findByRole("alert")).textContent).toContain("Não foi possível carregar o farol e os reajustes.");
    expect(nomes()).toHaveLength(3);
    expect(totais()).not.toContain("Medido em");
  });

  const limpo = (s: string | null | undefined) => (s ?? "").replace(/ /g, " ");
  const totais = () => limpo(screen.getByLabelText("Totais").textContent);
  const rodape = () => document.querySelector(".obras-rodape span")!.textContent;
  const linhasDeObra = () => [...document.querySelectorAll<HTMLTableRowElement>("tr.linha--obra")];
  const nomes = () => linhasDeObra().map(l => within(l).getAllByRole("cell")[0].querySelector("a")!.textContent);
  const grupos = () => [...document.querySelectorAll<HTMLTableRowElement>("tr.obras-grupo")];
  const campoBusca = () => screen.getByRole("searchbox", { name: "Buscar obra" }) as HTMLInputElement;

  it("o cabeçalho diz uma vez 'cota da Lotufo', sem chips de contratante e com as colunas de antes", async () => {
    abrir("/obras/todas");
    await screen.findByRole("table");
    expect(screen.getByRole("heading", { level: 1 }).textContent).toContain("cota da Lotufo");
    expect(document.body.textContent!.match(/cota/gi)).toHaveLength(1);         // nenhuma legenda sob número nem na linha
    expect(screen.queryByRole("navigation", { name: "Contratante" })).toBeNull();
    expect(document.querySelector(".chip")).toBeNull();
    const cabecalho = screen.getAllByRole("columnheader").map(c => c.textContent);
    expect(cabecalho).toEqual(["Obra", "Valor vigente", "Medido", "Saldo a executar", "Executado", "Andamento", "A receber"]);
  });

  it("#805: a coluna Andamento traz o ritmo contra o necessário e, sob o nome, o fim da execução e o motivo da situação", async () => {
    const base = api.getMockImplementation()!;
    const comMotivo = { ...PAINEL, obras: [
      { ...farol(1, "Estações BRT", "vermelho"), motivos: [
        { tipo: "execucao_vencendo", nivel: "critico", dias: 5, valor_centavos: null, texto: "execução termina em 5 dias (04/11/2026)" },
        { tipo: "vigencia_vencendo", nivel: "atencao", dias: 50, valor_centavos: null, texto: "vigência termina em 50 dias" }] },
      farol(2, "MT-388", "verde"), farol(3, "Granito", "atencao")] };
    api.mockImplementation(async (caminho: string) => (caminho === "/api/diretoria" ? comMotivo : base(caminho)));
    abrir("/obras/todas");
    const tabela = await screen.findByRole("table", { name: /Obras, posição/ });
    const linha = (nome: string) => within(tabela).getByRole("link", { name: nome }).closest("tr")!;
    const andamento = (nome: string) => limpo(linha(nome).querySelector('td[data-rotulo="Andamento"]')!.textContent);
    // a palavra e a razão; os valores por mês ficam na página do contratante e na vista Andamento
    expect(andamento("Estações BRT")).toBe("Devagar · mede 27% do necessário");
    expect(linha("Estações BRT").querySelector(".andamento--devagar")).toBeTruthy();
    expect(andamento("MT-388")).toBe("Adiantada · mede 120% do necessário");
    expect(andamento("Granito")).toBe("—");                                    // paralisada: sem necessário, sem leitura
    expect([...linha("Estações BRT").querySelectorAll(".obras-posicao__sub")].map(d => d.textContent)).toEqual(["IC 1/2026", "execução até 31/03/2027"]);
    // o motivo escrito ao lado do selo (o primeiro, o mais grave); os outros ficam nos avisos da obra
    await waitFor(() => expect(linha("Estações BRT").querySelector(".obras-situacao")).toBeTruthy());
    const situacao = linha("Estações BRT").querySelector(".obras-situacao")!;
    expect(situacao.querySelector(".selo--critico")!.textContent).toBe("Crítico");
    expect(situacao.querySelector(".obras-situacao__motivo")!.textContent).toBe("execução termina em 5 dias (04/11/2026)");
    expect(within(situacao as HTMLElement).getByRole("link", { name: /^mais 1\s*motivo de Estações BRT$/ }).getAttribute("href")).toBe("/avisos?obra=1");
    expect(linha("MT-388").querySelector(".obras-situacao")).toBeNull();          // em dia: sem marca
  });

  it("as obras aparecem em grupos por contratante, cada grupo com o nome e o subtotal", async () => {
    abrir("/obras/todas");
    await screen.findByRole("table");
    // #805: o cabeçalho de grupo forte, com o nome que leva à página do contratante e quantas obras o grupo mostra
    expect(grupos().map(g => g.querySelector("th")!.textContent)).toEqual(["MTPAR1 obra", "SINFRA2 obras"]);
    expect(grupos().map(g => g.querySelector("th a")!.getAttribute("href"))).toEqual(["/obras/contratante/mtpar", "/obras/contratante/sinfra"]);
    // 3 em andamento; a encerrada só com "Ver todas". Dentro do grupo, na ordem do nome
    expect(nomes()).toEqual(["Granito", "Estações BRT", "MT-388"]);
    expect(rodape()).toBe("Mostrando 3 de 4 obras");
    const sinfra = grupos()[1];
    expect(sinfra.closest("tbody")!.querySelectorAll("tr.linha--obra")).toHaveLength(2);
    const subtotal = within(sinfra).getAllByRole("cell").map(c => limpo(c.textContent));
    expect(subtotal[0]).toBe("R$ 2.470,00");     // 1.000,00 + 1.470,00
    expect(subtotal[1]).toBe("R$ 985,00");
    expect(subtotal[2]).toBe("R$ 1.485,00");
    expect(subtotal[5]).toBe("R$ 149,01");
  });

  it("obra em consórcio aparece com vigente, medido, saldo e a receber na cota, não no cheio", async () => {
    abrir("/obras/todas");
    await screen.findByRole("table");
    const linha = limpo(screen.getByRole("link", { name: "MT-388" }).closest("tr")!.textContent);
    expect(linha).toContain("R$ 1.470,00");
    expect(linha).toContain("R$ 735,00");
    expect(linha).toContain("R$ 49,01");
    expect(linha).toContain("50%");
    expect(linha).not.toContain("3.000,01");
    expect(linha).not.toContain("1.500,0");
    const brt = screen.getByRole("link", { name: "Estações BRT" }).closest("tr")!;
    expect(limpo(brt.textContent)).toContain("R$ 750,00");
    expect(brt.textContent).toContain("25%");
    expect((brt.querySelector(".obras-exec__barra") as HTMLElement).style.width).toBe("25%");
    // #720: o percentual e' numero ao lado da barra, sem selo nem simbolo de situacao (0% nao se le como "feito")
    expect(brt.querySelector(".obras-exec__pct")!.textContent).toBe("25%");
    expect(brt.querySelector(".obras-exec .selo, .obras-exec .glifo")).toBeNull();
  });

  it("os totais do topo somam as linhas na cota e o a receber vira traço sem o total liberado", async () => {
    const mi = 1_000_000_00;
    api.mockImplementation(async (caminho: string) => {
      if (caminho === "/api/contratos") return OBRAS.map(o => ({ ...o, valor_vigente_centavos: 400 * mi, medido_centavos: 160 * mi, posicao: posicao(100 * mi, 40 * mi, null) }));
      if (caminho === "/api/entidades") return [];
      return { avisos: [] };
    });
    abrir("/obras/todas");
    await screen.findByRole("table");
    expect(totais()).toContain("ContratadoR$ 300.000.000,00");
    expect(totais()).toContain("Medido (40%)R$ 120.000.000,00");
    expect(totais()).toContain("Saldo a executarR$ 180.000.000,00");
    expect(totais()).toContain("A receber—");
    expect(within(grupos()[0]).getAllByRole("cell")[5].textContent).toBe("—");
    expect(within(linhasDeObra()[0]).getAllByRole("cell")[6].textContent).toBe("—");
  });

  it("digitar parte do nome ou do número do contrato filtra a lista e os totais; limpar volta tudo", async () => {
    abrir("/obras/todas");
    await screen.findByRole("table");
    fireEvent.change(campoBusca(), { target: { value: "grani" } });
    expect(nomes()).toEqual(["Granito"]);
    expect(grupos().map(g => g.querySelector("th a")!.textContent)).toEqual(["MTPAR"]);
    expect(window.location.search).toBe("?q=grani");
    expect(rodape()).toBe("Mostrando 1 de 4 obras");
    fireEvent.change(campoBusca(), { target: { value: "ic 2/" } });
    expect(nomes()).toEqual(["MT-388"]);
    fireEvent.change(campoBusca(), { target: { value: "nada disso" } });
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.getByText("Nenhuma obra.")).toBeTruthy();
    fireEvent.change(campoBusca(), { target: { value: "" } });
    expect(nomes()).toHaveLength(3);
    expect(window.location.search).toBe("");
  });

  it("a busca vem da URL (?q=) ao abrir; o endereço de antes da #805 passa a ser o da tabela, com a busca", async () => {
    abrir("/obras?q=brt");
    await screen.findByRole("table");
    expect(campoBusca().value).toBe("brt");
    expect(nomes()).toEqual(["Estações BRT"]);
    expect(window.location.pathname + window.location.search).toBe("/obras/todas?q=brt");
    // limpar a busca fica na tabela (não volta para "Por contratante")
    fireEvent.change(campoBusca(), { target: { value: "" } });
    expect(window.location.pathname + window.location.search).toBe("/obras/todas");
    expect(nomes()).toHaveLength(3);
  });

  it("clicar na linha ou no nome abre a página da obra", async () => {
    abrir("/obras/todas");
    await screen.findByRole("table");
    expect(screen.getByRole("link", { name: "Estações BRT" }).getAttribute("href")).toBe("/obras/1");
    fireEvent.click(screen.getByRole("link", { name: "Granito" }).closest("tr")!);
    expect(window.location.pathname).toBe("/obras/3");
  });

  it("'Ver todas' traz as encerradas, mesmo com a busca filtrando", async () => {
    abrir("/obras/todas?c=MTPAR");
    await screen.findByRole("table");
    expect(nomes()).toEqual(["Granito"]);
    fireEvent.click(screen.getByRole("link", { name: "Ver todas" }));
    expect(window.location.search).toBe("?c=MTPAR&situacao=todas");
    await screen.findByText("Só em andamento");
    expect(rodape()).toBe("Mostrando 2 de 2 obras");
    expect(nomes()).toEqual(["Deciolândia", "Granito"]);
    expect(screen.queryByRole("link", { name: "Ver todas" })).toBeNull();
    cleanup();
    abrir("/obras?q=granito");
    await screen.findByRole("table");
    expect(screen.getByRole("link", { name: "Ver todas" })).toBeTruthy();
  });

  it("na tabela, o recorte por contratante (?c=) mostra só o grupo dele e oferece tirar o filtro", async () => {
    abrir("/obras/todas?c=SINFRA");
    await screen.findByRole("table");
    expect(grupos().map(g => g.querySelector("th a")!.textContent)).toEqual(["SINFRA"]);
    expect(rodape()).toBe("Mostrando 2 de 2 obras");
    fireEvent.click(screen.getByRole("link", { name: "Tirar o filtro" }));
    expect(window.location.pathname + window.location.search).toBe("/obras/todas");
    expect(grupos()).toHaveLength(2);
    expect(screen.queryByRole("link", { name: "Tirar o filtro" })).toBeNull();
  });

  it("#805: o link de antes com contratante (/obras?c=) abre a página do contratante, pela chave do servidor", async () => {
    abrir("/obras?c=SINFRA");
    await waitFor(() => expect(window.location.pathname).toBe("/obras/contratante/sinfra"));
    expect(window.location.search).toBe("");
    cleanup();
    // com outro filtro junto, quem filtra é a tabela: o recorte continua nela
    abrir("/obras?c=SINFRA&q=brt");
    await screen.findByRole("table");
    expect(window.location.pathname + window.location.search).toBe("/obras/todas?c=SINFRA&q=brt");
    expect(nomes()).toEqual(["Estações BRT"]);
    cleanup();
    // contratante que a lista não conhece: a tabela, vazia
    abrir("/obras?c=Outro");
    await screen.findByText("Nenhuma obra.");
    expect(window.location.pathname + window.location.search).toBe("/obras/todas?c=Outro");
  });

  it("a lista não tem mais a coluna nem o botão de avisos", async () => {
    abrir("/obras/todas");
    await screen.findByRole("table");
    expect(screen.queryByRole("button", { name: /Avisos/ })).toBeNull();
    expect(screen.queryByRole("columnheader", { name: "Avisos" })).toBeNull();
  });

  it("os Avisos saíram de dentro de Obras (#805): ?avisos=1 não abre mais nada na lista, e ela não lê a fila de avisos", async () => {
    abrir("/obras?c=SINFRA&avisos=1");
    await screen.findByRole("table");
    expect(screen.queryByRole("heading", { name: /Avisos/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Fechar os avisos" })).toBeNull();
    expect(document.body.textContent).not.toContain("execução termina em 5 dias");
    expect(api).not.toHaveBeenCalledWith("/api/inicio");
    expect(api).not.toHaveBeenCalledWith("/api/entidades");
  });

  it("?orgao= vira ?c= na URL e o nome inteiro do órgão continua filtrando", async () => {
    abrir("/obras/todas?orgao=SINFRA%20-%20SUPU");
    await screen.findByRole("table");
    expect(nomes()).toEqual(["MT-388"]);
    cleanup();
    abrir("/obras/todas?orgao=MTPAR");
    await screen.findByRole("table");
    expect(window.location.search).toBe("?c=MTPAR");
    cleanup();
    // #805: o link de antes ("/obras?orgao=<nome do órgão>", o do caminho da página da obra) abre a página do contratante
    abrir("/obras?orgao=SINFRA%20-%20SUPU");
    await waitFor(() => expect(window.location.pathname).toBe("/obras/contratante/sinfra"));
  });
});

describe("Obras em níveis (#805): Por contratante, Todas as obras, Andamento e QDOP", () => {
  const limpo = (s: string | null | undefined) => (s ?? "").replace(/[ \s]+/g, " ").trim();
  beforeEach(() => {
    api.mockImplementation(async (caminho: string) => {
      if (caminho === "/api/contratos") return OBRAS;
      if (caminho === "/api/entidades") return [];
      if (caminho === "/api/inicio") return { avisos: [] };
      if (caminho === "/api/diretoria") return { ...PAINEL, prazo_pagamento: { SINFRA: 47 },
        avisos: [{ ...AVISOS[0] }, { ...AVISOS[1] }, { ...AVISOS[0], contrato_id: 2, obra: "MT-388" }] };
      throw new Error(`chamada inesperada: ${caminho}`);
    });
  });
  afterEach(() => { cleanup(); api.mockReset(); window.history.replaceState(null, "", "/"); });

  it("/obras abre em 'Por contratante': as quatro vistas no alto, cada uma com endereço", async () => {
    abrir("/obras");
    const vistas = screen.getByRole("navigation", { name: "Vistas de Obras" });
    expect(within(vistas).getAllByRole("link").map(a => [a.textContent, a.getAttribute("href")])).toEqual(
      [["Por contratante", "/obras"], ["Todas as obras", "/obras/todas"], ["Andamento", "/obras/andamento"], ["QDOP", "/obras/qdop"]]);
    expect(within(vistas).getByRole("link", { name: "Por contratante" }).getAttribute("aria-current")).toBe("page");
    await screen.findByRole("list", { name: "Contratantes" });
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByRole("searchbox", { name: "Buscar obra" })).toBeNull();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toContain("cota da Lotufo");
  });

  it("a faixa da carteira: contratado, medido, medido no mês com a variação, a receber e quantas obras estão devagar", async () => {
    abrir("/obras");
    const faixa = await screen.findByLabelText("Números da carteira");
    const numeros = [...faixa.querySelectorAll(".obras-numero")].map(n => limpo(n.textContent));
    expect(numeros).toEqual([
      "ContratadoR$ 4.470,00",
      "Medido (33%)R$ 1.485,00",
      // agosto: 80,00 + 60,00; julho: 100,00 + 20,00
      "Medido em agostoR$ 140,00▲ +16,7%× julsubiu 16,7% em relação a julho",
      "A receberR$ 249,01",
      "Andamento1 de 2obra devagar",
    ]);
    expect(faixa.querySelector(".variacao--bom")).toBeTruthy();
    expect(faixa.querySelector(".marca-etapa__cor--em_aberto")).toBeTruthy();       // o a receber leva a marca do em aberto
    expect(faixa.querySelector(".obras-etiqueta--devagar")!.textContent).toBe("obra devagar");
  });

  it("um bloco por contratante, do maior contratado para o menor, com os números dele e o que pede atenção", async () => {
    abrir("/obras");
    const lista = await screen.findByRole("list", { name: "Contratantes" });
    const blocos = [...lista.querySelectorAll<HTMLElement>(".obras-contratante")];
    expect(blocos.map(b => b.querySelector("h2")!.textContent)).toEqual(["SINFRA", "MTPAR"]);       // 2.470,00 e 2.000,00
    const [sinfra, mtpar] = blocos;
    // o bloco inteiro leva à página do contratante: o link é o nome
    expect(within(sinfra).getByRole("link", { name: "SINFRA" }).getAttribute("href")).toBe("/obras/contratante/sinfra");
    expect(sinfra.querySelector(".obras-contratante__n")!.textContent).toBe("2 obras");
    const linhas = (b: HTMLElement) => [...b.querySelectorAll(".obras-contratante__numeros > div")].map(d => limpo(d.textContent));
    await waitFor(() => expect(linhas(sinfra)[4]).toBe("Prazo de pagamento47 dias"));
    expect(linhas(sinfra)).toEqual([
      "ContratadoR$ 2.470,0055,3% da carteira",
      "Executado39%",
      "Medido em agoR$ 140,00▲ +16,7%× julsubiu 16,7% em relação a julho",
      "A receberR$ 149,01",
      "Prazo de pagamento47 dias",
    ]);
    expect(sinfra.querySelector(".obras-em-aberto")).toBeTruthy();
    // decisão do dono de 18/11/2026: o bloco do contratante não leva a etiqueta do andamento ("1 devagar")
    expect([...sinfra.querySelectorAll(".obras-etiquetas li")].map(li => limpo(li.textContent))).toEqual(["2 avisos críticos"]);
    expect(sinfra.querySelector(".obras-etiqueta--devagar")).toBeNull();
    expect(sinfra.querySelector(".selo--critico .glifo--critico")).toBeTruthy();
    // a MTPAR não tem prazo de pagamento no sistema, nem medição em agosto; a obra dela está paralisada
    expect(linhas(mtpar)).toEqual(["ContratadoR$ 2.000,0044,7% da carteira", "Executado25%", "Medido em ago—", "A receberR$ 100,00", "Prazo de pagamento—"]);
    expect([...mtpar.querySelectorAll(".obras-etiquetas li")].map(li => limpo(li.textContent))).toEqual(["1 paralisada"]);
    expect(mtpar.querySelector(".obras-etiquetas .glifo")).toBeNull();
  });

  it("contratante sem nada que peça atenção fica 'Em dia'; sem órgão no cadastro, o bloco não é link", async () => {
    const base = api.getMockImplementation()!;
    api.mockImplementation(async (caminho: string) => {
      if (caminho === "/api/contratos") return [obra(9, "Travessia", { orgao: "sem cadastro", contratante: "sem cadastro", contratante_chave: null,
        andamento: { ritmo_centavos: 110_00, necessario_centavos: 100_00 } })];
      if (caminho === "/api/diretoria") return { ...PAINEL, obras: [], avisos: [] };
      return base(caminho);
    });
    abrir("/obras");
    const bloco = (await screen.findByRole("list", { name: "Contratantes" })).querySelector<HTMLElement>(".obras-contratante")!;
    expect(bloco.querySelector(".obras-etiquetas--emdia")!.textContent).toBe("Em dia");
    expect(bloco.querySelector("a")).toBeNull();
    expect(bloco.querySelector("h2")!.textContent).toBe("sem cadastro");
    expect(limpo(screen.getByLabelText("Números da carteira").textContent)).toContain("Andamento0 de 1obras devagar");
    expect(screen.getByLabelText("Números da carteira").querySelector(".obras-etiqueta--devagar")).toBeNull();
  });

  it("a vista Andamento ordena do menor para o maior percentual do necessário, e o percentual aparece", async () => {
    abrir("/obras/andamento");
    const tabela = await screen.findByRole("table", { name: /Obras pelo andamento/ });
    expect(within(tabela).getAllByRole("columnheader").map(c => c.textContent)).toEqual(
      ["Obra", "Do necessário", "Andamento", "Ritmo mensal", "Necessário por mês", "Fim da execução"]);
    const linhas = [...tabela.querySelectorAll("tbody tr")].map(tr => [...tr.querySelectorAll("td")].map(td => limpo(td.textContent)));
    // a paralisada (sem necessário) não tem prazo a cumprir e fica fora
    expect(linhas).toEqual([
      ["Estações BRTSINFRA", "27%", "Devagar", "R$ 27,00", "R$ 100,00", "31/03/2027"],
      ["MT-388SINFRA", "120%", "Adiantada", "R$ 120,00", "R$ 100,00", "31/03/2027"],
    ]);
    expect(tabela.querySelector(".andamento--devagar .andamento__barra")).toBeTruthy();
    expect(screen.getByLabelText("Números da carteira")).toBeTruthy();
    expect(screen.queryByRole("searchbox", { name: "Buscar obra" })).toBeNull();
  });

  it("#822: fora da régua, a vista Andamento e 'Todas as obras' escrevem o motivo no lugar da leitura, e a contagem do alto não as conta", async () => {
    // as três mediriam 10% do necessário (devagar); o servidor as tirou da régua
    const fora = (motivo: Parameters<typeof leituraDeTeste>[2]) => ({ ritmo_centavos: 10_00, necessario_centavos: 100_00, leitura: leituraDeTeste(10_00, 100_00, motivo) });
    const obras = [
      obra(1, "Estações BRT", { andamento: { ritmo_centavos: 27_00, necessario_centavos: 100_00 } }),
      obra(5, "Cavalaria", { execucao_fim_vigente: "2026-12-20", andamento: fora({ motivo: "prazo_no_fim", prorrogacao_pedida: true }) }),
      obra(6, "Leblon", { execucao_fim_vigente: "2026-11-30", andamento: fora({ motivo: "prazo_no_fim" }) }),
      obra(7, "Maternidade", { execucao_fim_vigente: "2027-12-31", andamento: fora({ motivo: "prorrogacao_pedida", prorrogacao_pedida: true }) }),
      obra(8, "Orla", { andamento: fora({ motivo: "sem_medicao", sem_medicao_desde: "2026-07" }) }),
    ];
    const base = api.getMockImplementation()!;
    api.mockImplementation(async (caminho: string) => (caminho === "/api/contratos" ? obras : base(caminho)));
    abrir("/obras/andamento");
    const tabela = await screen.findByRole("table", { name: /Obras pelo andamento/ });
    const linhas = [...tabela.querySelectorAll("tbody tr")].map(tr => [...tr.querySelectorAll("td")].map(td => limpo(td.textContent)));
    // primeiro quem tem leitura; depois a sem medição, e as de prazo no fim ou prorrogação pedida pela que termina antes
    expect(linhas).toEqual([
      ["Estações BRTSINFRA", "27%", "Devagar", "R$ 27,00", "R$ 100,00", "31/03/2027"],
      ["OrlaSINFRA", "—", "Sem medição desde 07/2026", "R$ 10,00", "R$ 100,00", "31/03/2027"],
      ["LeblonSINFRA", "—", "Prazo no fim", "R$ 10,00", "R$ 100,00", "30/11/2026"],
      ["CavalariaSINFRA", "—", "Prazo no fim · prorrogação pedida", "R$ 10,00", "R$ 100,00", "20/12/2026"],
      ["MaternidadeSINFRA", "—", "Prorrogação pedida", "R$ 10,00", "R$ 100,00", "31/12/2027"],
    ]);
    // só a obra com leitura tem barra; o motivo vai em tinta, sem tom de valor
    expect(tabela.querySelectorAll(".andamento__trilho").length).toBe(1);
    expect(tabela.querySelectorAll(".andamento--fora").length).toBe(4);
    // "1 de 1" é só quem tem leitura; as duas com o prazo no fim vão ao lado, em tinta (sem tom de valor)
    const andamentoDaFaixa = [...screen.getByLabelText("Números da carteira").querySelectorAll(".obras-numero")].at(-1)!;
    expect(limpo(andamentoDaFaixa.textContent)).toBe("Andamento1 de 1obra devagar2 com prazo no fim");
    expect(andamentoDaFaixa.querySelectorAll(".obras-etiqueta").length).toBe(1);
    cleanup();
    abrir("/obras/todas");
    const todas = await screen.findByRole("table", { name: /Obras, posição/ });
    const andamento = (nome: string) => within(todas).getByRole("link", { name: nome }).closest("tr")!.querySelector('td[data-rotulo="Andamento"]')!;
    expect(limpo(andamento("Cavalaria").textContent)).toBe("Prazo no fim · prorrogação pedida");
    expect(limpo(andamento("Orla").textContent)).toBe("Sem medição desde 07/2026");
    expect(limpo(andamento("Estações BRT").textContent)).toBe("Devagar · mede 27% do necessário");
    // a célula com o motivo não é a "sem leitura" que a faixa média esconde
    expect(andamento("Cavalaria").className).toBe("obras-posicao__andamento");
  });

  it("Todas as obras: os reajustes esperando apostilamento ficam acima da tabela, recolhidos, e o painel é pedido uma vez", async () => {
    abrir("/obras/todas");
    await screen.findByRole("table", { name: /Obras, posição/ });
    // os totais da tabela continuam os dela (somam as colunas e seguem o filtro), com o medido do ano
    expect(await screen.findByText("Medido em 2026")).toBeTruthy();
    expect(screen.getByRole("searchbox", { name: "Buscar obra" })).toBeTruthy();
    const reajustes = document.querySelector<HTMLDetailsElement>("details.obras-reajustes")!;
    expect(reajustes.open).toBe(false);
    expect(limpo(reajustes.querySelector("summary")!.textContent)).toBe("Reajustes esperando apostilamento11 obraR$ 300,00");
    expect(reajustes.compareDocumentPosition(screen.getByRole("table", { name: /Obras, posição/ })) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(reajustes).getByRole("link", { name: "MT-388", hidden: true }).getAttribute("href")).toBe("/obras/2/reajuste");
    // #802: sem previsto x medido em tela nenhuma
    expect(document.body.textContent).not.toMatch(/previsto/i);
    expect(api.mock.calls.filter(c => c[0] === "/api/diretoria")).toHaveLength(1);
  });

  it("QDOP: como estava, com o botão de exportar; sem a faixa e sem a busca", async () => {
    abrir("/obras/qdop");
    expect((await screen.findByRole("link", { name: /Exportar QDOP/ })).getAttribute("href")).toBe("/api/diretoria/qdop.xlsx");
    expect(screen.queryByLabelText("Totais")).toBeNull();
    expect(screen.queryByLabelText("Números da carteira")).toBeNull();
    expect(screen.queryByRole("searchbox", { name: "Buscar obra" })).toBeNull();
  });

  it("sem reajuste esperando apostilamento, o painel dele não aparece", async () => {
    const base = api.getMockImplementation()!;
    api.mockImplementation(async (caminho: string) => (caminho === "/api/diretoria"
      ? { ...PAINEL, reajustes_apostilamento: { competencias: 0, valor_centavos: 0, obras: [] } } : base(caminho)));
    abrir("/obras/todas");
    expect(await screen.findByText("Medido em 2026")).toBeTruthy();
    expect(screen.queryByText(/Reajustes esperando apostilamento/)).toBeNull();
  });

  it("sem o painel da diretoria, 'Por contratante' continua com os números das obras e avisa o que faltou", async () => {
    const base = api.getMockImplementation()!;
    api.mockImplementation(async (caminho: string) => {
      if (caminho === "/api/diretoria") throw new Error("falhou");
      return base(caminho);
    });
    abrir("/obras");
    await screen.findByRole("list", { name: "Contratantes" });
    expect((await screen.findByRole("alert")).textContent).toContain("Não foi possível carregar os avisos das obras e o prazo de pagamento.");
    expect(limpo(screen.getByLabelText("Números da carteira").textContent)).toContain("ContratadoR$ 4.470,00");
  });
});
