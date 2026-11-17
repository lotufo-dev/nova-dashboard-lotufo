import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Contratos from "./Contratos";
import type { ObraLista } from "./listaObras";
import { useRota } from "./rota";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

// Dados sintéticos: dois contratantes (SINFRA com duas superintendências, MTPAR) e uma obra encerrada. `posicao` é o que
// a lista mostra (na cota da Lotufo, do servidor); os valores cheios ao lado são outros de propósito.
const posicao = (vigente: number, medido: number, aReceber: number | null) =>
  ({ vigente_centavos: vigente, medido_centavos: medido, saldo_centavos: vigente - medido, a_receber_centavos: aReceber });
const obra = (id: number, nome: string, extra: Partial<ObraLista> = {}): ObraLista => ({
  id, orgao: "SINFRA - SUEF II", contratante: "SINFRA", orgao_sub: "SUEF II", numero_instrumento: `IC ${id}/2026`, nome_curto: nome,
  estado: "ativo", entidade_id: 1, valor_vigente_centavos: 1000_00, medido_centavos: 250_00, saldo_centavos: 750_00, percentual_direito_bp: 10000,
  posicao: posicao(1000_00, 250_00, 100_00),
  execucao_fim_vigente: "2027-03-31", vigencia_fim_vigente: "2027-06-30", dias_execucao: 100, dias_vigencia: 200, ...extra });

const OBRAS: ObraLista[] = [
  obra(1, "Estações BRT"),
  // consórcio a 49%: cheio 3.000,01 / 1.500,00; na cota 1.470,00 / 735,00
  obra(2, "MT-388", { orgao: "SINFRA - SUPU", orgao_sub: "SUPU", percentual_direito_bp: 4900, valor_vigente_centavos: 3000_01, medido_centavos: 1500_00, saldo_centavos: 1500_01,
    posicao: posicao(1470_00, 735_00, 49_01) }),
  obra(3, "Granito", { orgao: "MTPAR", contratante: "MTPAR", orgao_sub: null, valor_vigente_centavos: 2000_00, medido_centavos: 500_00,
    saldo_centavos: 1500_00, posicao: posicao(2000_00, 500_00, 100_00), estado: "suspenso", execucao_fim_vigente: "2026-12-31" }),
  obra(4, "Deciolândia", { orgao: "MTPAR", contratante: "MTPAR", orgao_sub: null, estado: "encerrado", execucao_fim_vigente: "2025-12-31" }),
];

// o painel da diretoria (`/api/diretoria`): o farol de cada obra, o medido do ano, a curva e os reajustes
const farol = (contrato_id: number, obra: string, f: "verde" | "atencao" | "vermelho") => ({ contrato_id, seq: contrato_id, obra,
  contratante: "SINFRA", empreita: "PRÓPRIA", direito: 1, pi_va: 0, faturados: 0, saldo: 0, status: "EM ANDAMENTO", termino: null,
  farol: f, motivo: "", motivos: [] });
const PAINEL = { hoje: "2026-09-24", medido_ano: { ano: "2026", valor_centavos: 100_00 },
  curva_carteira: [{ competencia: "2026-09", previsto_centavos: 200_00, previsto_anterior_centavos: 200_00, medido_centavos: 150_00 }],
  carteira: { saldo_centavos: 0, por_orgao: [] }, avisos: [],
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
  const { busca, ir } = useRota();
  return <Contratos ir={ir} busca={busca} />;
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
    abrir("/obras");
    await screen.findByRole("table");
    // 1.000,00 + 1.470,00 + 2.000,00 de vigente; 250,00 + 735,00 + 500,00 de medido (33%)
    expect(totais()).toBe("ContratadoR$ 4.470,00Medido (33%)R$ 1.485,00Saldo a executarR$ 2.985,00A receberR$ 249,01Medido em 2026R$ 100,00");
    cleanup();
    abrir("/obras?q=granito");
    await screen.findByRole("table");
    expect(totais()).toBe("ContratadoR$ 2.000,00Medido (25%)R$ 500,00Saldo a executarR$ 1.500,00A receberR$ 100,00");
  });

  it("#774: a obra que não está em dia leva o selo do farol sob o nome; a em dia não leva marca", async () => {
    const base = api.getMockImplementation()!;
    api.mockImplementation(async (caminho: string) => (caminho === "/api/diretoria" ? PAINEL : base(caminho)));
    abrir("/obras");
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
    abrir("/obras");
    await screen.findByRole("table", { name: /Obras, posição/ });
    expect(totais()).toContain("Medido (99%)R$ 996,00");
    expect(grupos()[0].querySelector(".obras-exec__pct")!.textContent).toBe("99%");
  });

  it("#774: ?termina=90 (os links do QDOP) recorta a lista pelo fim do prazo e oferece voltar a todas", async () => {
    abrir("/obras?termina=150");
    await screen.findByRole("table");
    expect(nomes()).toEqual(["Estações BRTIC 1/2026", "MT-388IC 2/2026"]);     // a suspensa só conta a vigência; a encerrada fica fora
    expect(screen.getByText("Terminam em até 150 dias")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Todas as obras" }).getAttribute("href")).toBe("/obras");
    expect(screen.queryByText(/Medido em 2026/)).toBeNull();
  });

  it("#774: sem o painel da diretoria a lista continua, com um aviso no lugar do farol, da curva e dos reajustes", async () => {
    const base = api.getMockImplementation()!;
    api.mockImplementation(async (caminho: string) => {
      if (caminho === "/api/diretoria") throw new Error("falhou");
      return base(caminho);
    });
    abrir("/obras");
    await screen.findByRole("table");
    expect((await screen.findByRole("alert")).textContent).toContain("Não foi possível carregar o farol, a curva e os reajustes.");
    expect(nomes()).toHaveLength(3);
    expect(totais()).not.toContain("Medido em");
  });

  const limpo = (s: string | null | undefined) => (s ?? "").replace(/ /g, " ");
  const totais = () => limpo(screen.getByLabelText("Totais").textContent);
  const rodape = () => document.querySelector(".obras-rodape span")!.textContent;
  const linhasDeObra = () => [...document.querySelectorAll<HTMLTableRowElement>("tr.linha--obra")];
  const nomes = () => linhasDeObra().map(l => within(l).getAllByRole("cell")[0].textContent);
  const grupos = () => [...document.querySelectorAll<HTMLTableRowElement>("tr.obras-grupo")];
  const campoBusca = () => screen.getByRole("searchbox", { name: "Buscar obra" }) as HTMLInputElement;

  it("o cabeçalho diz uma vez 'cota da Lotufo', sem chips de contratante e com as colunas de antes", async () => {
    abrir("/obras");
    await screen.findByRole("table");
    expect(screen.getByRole("heading", { level: 1 }).textContent).toContain("cota da Lotufo");
    expect(document.body.textContent!.match(/cota/gi)).toHaveLength(1);         // nenhuma legenda sob número nem na linha
    expect(screen.queryByRole("navigation", { name: "Contratante" })).toBeNull();
    expect(document.querySelector(".chip")).toBeNull();
    const cabecalho = screen.getAllByRole("columnheader").map(c => c.textContent);
    expect(cabecalho).toEqual(["Obra", "Valor vigente", "Medido", "Saldo a executar", "Executado", "A receber"]);
  });

  it("as obras aparecem em grupos por contratante, cada grupo com o nome e o subtotal", async () => {
    abrir("/obras");
    await screen.findByRole("table");
    expect(grupos().map(g => g.querySelector("th")!.textContent)).toEqual(["MTPAR", "SINFRA"]);
    // 3 em andamento; a encerrada só com "Ver todas". Dentro do grupo, na ordem do nome
    expect(nomes()).toEqual(["GranitoIC 3/2026", "Estações BRTIC 1/2026", "MT-388IC 2/2026"]);
    expect(rodape()).toBe("Mostrando 3 de 4 obras");
    const sinfra = grupos()[1];
    expect(sinfra.closest("tbody")!.querySelectorAll("tr.linha--obra")).toHaveLength(2);
    const subtotal = within(sinfra).getAllByRole("cell").map(c => limpo(c.textContent));
    expect(subtotal[0]).toBe("R$ 2.470,00");     // 1.000,00 + 1.470,00
    expect(subtotal[1]).toBe("R$ 985,00");
    expect(subtotal[2]).toBe("R$ 1.485,00");
    expect(subtotal[4]).toBe("R$ 149,01");
  });

  it("obra em consórcio aparece com vigente, medido, saldo e a receber na cota, não no cheio", async () => {
    abrir("/obras");
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
    abrir("/obras");
    await screen.findByRole("table");
    expect(totais()).toContain("ContratadoR$ 300.000.000,00");
    expect(totais()).toContain("Medido (40%)R$ 120.000.000,00");
    expect(totais()).toContain("Saldo a executarR$ 180.000.000,00");
    expect(totais()).toContain("A receber—");
    expect(within(grupos()[0]).getAllByRole("cell")[4].textContent).toBe("—");
    expect(within(linhasDeObra()[0]).getAllByRole("cell")[5].textContent).toBe("—");
  });

  it("digitar parte do nome ou do número do contrato filtra a lista e os totais; limpar volta tudo", async () => {
    abrir("/obras");
    await screen.findByRole("table");
    fireEvent.change(campoBusca(), { target: { value: "grani" } });
    expect(nomes()).toEqual(["GranitoIC 3/2026"]);
    expect(grupos().map(g => g.querySelector("th")!.textContent)).toEqual(["MTPAR"]);
    expect(window.location.search).toBe("?q=grani");
    expect(rodape()).toBe("Mostrando 1 de 4 obras");
    fireEvent.change(campoBusca(), { target: { value: "ic 2/" } });
    expect(nomes()).toEqual(["MT-388IC 2/2026"]);
    fireEvent.change(campoBusca(), { target: { value: "nada disso" } });
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.getByText("Nenhuma obra.")).toBeTruthy();
    fireEvent.change(campoBusca(), { target: { value: "" } });
    expect(nomes()).toHaveLength(3);
    expect(window.location.search).toBe("");
  });

  it("a busca vem da URL (?q=) ao abrir", async () => {
    abrir("/obras?q=brt");
    await screen.findByRole("table");
    expect(campoBusca().value).toBe("brt");
    expect(nomes()).toEqual(["Estações BRTIC 1/2026"]);
  });

  it("clicar na linha ou no nome abre a página da obra", async () => {
    abrir("/obras");
    await screen.findByRole("table");
    expect(screen.getByRole("link", { name: "Estações BRT" }).getAttribute("href")).toBe("/obras/1");
    fireEvent.click(screen.getByRole("link", { name: "Granito" }).closest("tr")!);
    expect(window.location.pathname).toBe("/obras/3");
  });

  it("'Ver todas' traz as encerradas, mesmo com a busca filtrando", async () => {
    abrir("/obras?c=MTPAR");
    await screen.findByRole("table");
    expect(nomes()).toEqual(["GranitoIC 3/2026"]);
    fireEvent.click(screen.getByRole("link", { name: "Ver todas" }));
    expect(window.location.search).toBe("?c=MTPAR&situacao=todas");
    await screen.findByText("Só em andamento");
    expect(rodape()).toBe("Mostrando 2 de 2 obras");
    expect(nomes()).toEqual(["DeciolândiaIC 4/2026", "GranitoIC 3/2026"]);
    expect(screen.queryByRole("link", { name: "Ver todas" })).toBeNull();
    cleanup();
    abrir("/obras?q=granito");
    await screen.findByRole("table");
    expect(screen.getByRole("link", { name: "Ver todas" })).toBeTruthy();
  });

  it("o link de antes com contratante (?c=) mostra só o grupo dele e oferece 'Todas as obras'", async () => {
    abrir("/obras?c=SINFRA");
    await screen.findByRole("table");
    expect(grupos().map(g => g.querySelector("th")!.textContent)).toEqual(["SINFRA"]);
    expect(rodape()).toBe("Mostrando 2 de 2 obras");
    fireEvent.click(screen.getByRole("link", { name: "Todas as obras" }));
    expect(window.location.search).toBe("");
    expect(grupos()).toHaveLength(2);
    expect(screen.queryByRole("link", { name: "Todas as obras" })).toBeNull();
  });

  it("a lista não tem mais a coluna nem o botão de avisos", async () => {
    abrir("/obras");
    await screen.findByRole("table");
    expect(screen.queryByRole("button", { name: /Avisos/ })).toBeNull();
    expect(screen.queryByRole("columnheader", { name: "Avisos" })).toBeNull();
  });

  it("os Avisos seguem abrindo por ?avisos=1, do recorte do contratante", async () => {
    abrir("/obras?c=SINFRA&avisos=1");
    await screen.findByRole("heading", { name: "Avisos · SINFRA" });
    const area = document.getElementById("avisos-area")!;
    expect(area.textContent).toContain("execução termina em 5 dias");
    expect(area.textContent).not.toContain("Construtora Alfa: certidão");
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Fechar os avisos" })); });
    expect(window.location.search).toBe("?c=SINFRA");
    expect(screen.queryByRole("heading", { name: /Avisos ·/ })).toBeNull();
  });

  it("'todas' com os Avisos abertos inclui os avisos sem obra", async () => {
    abrir("/obras?c=todas&avisos=1");
    await screen.findByRole("heading", { name: "Avisos · Todas as obras" });
    expect(document.getElementById("avisos-area")!.textContent).toContain("Construtora Alfa");
  });

  it("?orgao= vira ?c= na URL e o nome inteiro do órgão continua filtrando", async () => {
    abrir("/obras?orgao=SINFRA%20-%20SUPU");
    await screen.findByRole("table");
    expect(nomes()).toEqual(["MT-388IC 2/2026"]);
    cleanup();
    abrir("/obras?orgao=MTPAR");
    await screen.findByRole("table");
    expect(window.location.search).toBe("?c=MTPAR");
  });
});

describe("Obras: as vistas Resumo e QDOP vieram da Carteira (#748)", () => {
  afterEach(() => { cleanup(); api.mockReset(); });

  it("#774: duas vistas, Posição e QDOP; o Resumo entrou na Posição (o link antigo abre nela) e o painel é pedido uma vez", async () => {
    api.mockImplementation(async (caminho: string) => {
      if (caminho === "/api/diretoria") return PAINEL;
      if (caminho === "/api/contratos") return OBRAS;
      if (caminho === "/api/entidades") return [];
      if (caminho === "/api/inicio") return { avisos: [] };
      throw new Error(`chamada inesperada: ${caminho}`);
    });
    render(<Contratos ir={() => {}} busca={{}} aba="resumo" />);
    const vistas = screen.getByRole("navigation", { name: "Vistas da lista de Obras" });
    expect(within(vistas).getAllByRole("link").map(a => [a.textContent, a.getAttribute("href")])).toEqual(
      [["Posição", "/obras"], ["QDOP", "/obras/qdop"]]);
    expect(within(vistas).getByRole("link", { name: "Posição" }).getAttribute("aria-current")).toBe("page");
    // o que era do Resumo mora na lista: o medido do ano entre os totais, a curva e os reajustes
    expect(await screen.findByText("Medido em 2026")).toBeTruthy();
    expect(screen.getByLabelText("Totais")).toBeTruthy();
    expect(screen.getByRole("searchbox", { name: "Buscar obra" })).toBeTruthy();
    expect(screen.getByRole("img", { name: /Previsto e medido de execução acumulados/ })).toBeTruthy();
    const reajustes = screen.getByRole("table", { name: /Reajustes esperando apostilamento/ });
    expect(within(reajustes).getByRole("link", { name: "MT-388" }).getAttribute("href")).toBe("/obras/2/reajuste");
    // os cartoes por contratante sairam: o subtotal de cada um ja' esta' na tabela
    expect(screen.queryByText("Por contratante")).toBeNull();
    expect(api.mock.calls.filter(c => c[0] === "/api/diretoria")).toHaveLength(1);
    cleanup();
    render(<Contratos ir={() => {}} busca={{}} aba="qdop" />);
    expect((await screen.findByRole("link", { name: /Exportar QDOP/ })).getAttribute("href")).toBe("/api/diretoria/qdop.xlsx");
    expect(screen.queryByLabelText("Totais")).toBeNull();
    expect(screen.queryByRole("searchbox", { name: "Buscar obra" })).toBeNull();
  });

  it("#774: sem reajuste esperando apostilamento, o painel dele não aparece", async () => {
    api.mockImplementation(async (caminho: string) => {
      if (caminho === "/api/diretoria") return { ...PAINEL, reajustes_apostilamento: { competencias: 0, valor_centavos: 0, obras: [] } };
      if (caminho === "/api/contratos") return OBRAS;
      if (caminho === "/api/entidades") return [];
      return { avisos: [] };
    });
    render(<Contratos ir={() => {}} busca={{}} />);
    expect(await screen.findByText("Medido em 2026")).toBeTruthy();
    expect(screen.queryByText(/Reajustes esperando apostilamento/)).toBeNull();
  });
});
