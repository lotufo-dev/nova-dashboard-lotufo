import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
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
  estado: "ativo", entidade_id: 1, valor_vigente_centavos: 1000_00, medido_execucao_centavos: 250_00, saldo_centavos: 750_00, percentual_direito_bp: 10000,
  posicao: posicao(1000_00, 250_00, 100_00),
  execucao_fim_vigente: "2027-03-31", vigencia_fim_vigente: "2027-06-30", dias_execucao: 100, dias_vigencia: 200, ...extra });

const OBRAS: ObraLista[] = [
  obra(1, "Estações BRT"),
  // consórcio a 49%: cheio 3.000,01 / 1.500,00; na cota 1.470,00 / 735,00
  obra(2, "MT-388", { orgao: "SINFRA - SUPU", orgao_sub: "SUPU", percentual_direito_bp: 4900, valor_vigente_centavos: 3000_01, medido_execucao_centavos: 1500_00, saldo_centavos: 1500_01,
    posicao: posicao(1470_00, 735_00, 49_01) }),
  obra(3, "Granito", { orgao: "MTPAR", contratante: "MTPAR", orgao_sub: null, valor_vigente_centavos: 2000_00, medido_execucao_centavos: 500_00,
    saldo_centavos: 1500_00, posicao: posicao(2000_00, 500_00, 100_00), estado: "suspenso", execucao_fim_vigente: "2026-12-31" }),
  obra(4, "Deciolândia", { orgao: "MTPAR", contratante: "MTPAR", orgao_sub: null, estado: "encerrado", execucao_fim_vigente: "2025-12-31" }),
];

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
      throw new Error(`chamada inesperada: ${caminho}`);
    });
  });
  afterEach(() => { cleanup(); api.mockReset(); window.history.replaceState(null, "", "/"); });

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
    expect(brt.querySelector(".progresso--feito")).toBeTruthy();
  });

  it("os totais do topo somam as linhas na cota e o a receber vira traço sem o total liberado", async () => {
    const mi = 1_000_000_00;
    api.mockImplementation(async (caminho: string) => {
      if (caminho === "/api/contratos") return OBRAS.map(o => ({ ...o, valor_vigente_centavos: 400 * mi, medido_execucao_centavos: 160 * mi, posicao: posicao(100 * mi, 40 * mi, null) }));
      if (caminho === "/api/entidades") return [];
      return { avisos: [] };
    });
    abrir("/obras");
    await screen.findByRole("table");
    expect(totais()).toContain("Contratado R$ 300,0 mi");
    expect(totais()).toContain("Medido R$ 120,0 mi");
    expect(totais()).toContain("Saldo R$ 180,0 mi");
    expect(totais()).toContain("A receber —");
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
