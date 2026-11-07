import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Contratos from "./Contratos";
import type { ObraLista } from "./listaObras";
import { useRota } from "./rota";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

// Dados sintéticos: dois contratantes (SINFRA com duas superintendências, MTPAR) e uma obra encerrada.
const obra = (id: number, nome: string, extra: Partial<ObraLista & { percentual_direito_bp: number; a_receber_centavos: number | null }> = {}): ObraLista => ({
  id, orgao: "SINFRA - SUEF II", contratante: "SINFRA", orgao_sub: "SUEF II", numero_instrumento: `IC ${id}/2026`, nome_curto: nome,
  estado: "ativo", entidade_id: 1, valor_vigente_centavos: 1000_00, medido_execucao_centavos: 250_00, saldo_centavos: 750_00, percentual_direito_bp: 10000, a_receber_centavos: 100_00,
  execucao_fim_vigente: "2027-03-31", vigencia_fim_vigente: "2027-06-30", dias_execucao: 100, dias_vigencia: 200, ...extra });

const OBRAS: ObraLista[] = [
  obra(1, "Estações BRT"),
  obra(2, "MT-388", { orgao: "SINFRA - SUPU", orgao_sub: "SUPU", percentual_direito_bp: 4900, a_receber_centavos: 0, valor_vigente_centavos: 3000_00, medido_execucao_centavos: 1500_00, saldo_centavos: 1500_00 }),
  obra(3, "Granito", { orgao: "MTPAR", contratante: "MTPAR", orgao_sub: null, valor_vigente_centavos: 2000_00, medido_execucao_centavos: 500_00,
    saldo_centavos: 1500_00, estado: "suspenso", execucao_fim_vigente: "2026-12-31" }),
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

describe("Obras: posição financeira", () => {
  beforeEach(() => {
    api.mockImplementation(async (caminho: string) => {
      if (caminho === "/api/contratos") return OBRAS;
      if (caminho === "/api/entidades") return [{ id: 1, nome: "Construtora Alfa Ltda", nome_curto: "Alfa" }];
      if (caminho === "/api/inicio") return { avisos: AVISOS };
      throw new Error(`chamada inesperada: ${caminho}`);
    });
  });
  afterEach(() => { cleanup(); api.mockReset(); window.history.replaceState(null, "", "/"); });

  const totais = () => screen.getByLabelText("Totais").textContent!.replace(/\u00a0/g, " ");
  const rodape = () => document.querySelector(".obras-rodape span")!.textContent;
  const nomes = () => within(screen.getByRole("table")).getAllByRole("row").slice(1).map(l => within(l).getAllByRole("cell")[0].textContent);

  it("é uma tabela só, sem nível por contratante, com chips e as colunas aprovadas", async () => {
    abrir("/obras");
    await screen.findByRole("table");
    expect(screen.getByRole("heading", { level: 1 }).textContent).toContain("posição financeira");
    const cabecalho = screen.getAllByRole("columnheader").map(c => c.textContent);
    expect(cabecalho).toEqual(["Obra", "Valor vigente", "Medido", "Saldo a executar", "Executado", "A receber"]);
    expect(screen.queryByRole("heading", { name: "Contratantes" })).toBeNull();
    // 3 em andamento; a encerrada só com "Ver todas"
    expect(nomes()).toEqual(["Estações BRTSINFRA", "GranitoMTPAR", "MT-388SINFRA · cota 49%"]);
    expect(rodape()).toBe("Mostrando 3 de 4 obras");
    // o valor cheio e o a receber de cada obra; o % em verde
    const brt = screen.getByRole("link", { name: "Estações BRT" }).closest("tr")!;
    expect(brt.textContent).toMatch(/R\$\s*1\.000,00/);
    expect(brt.textContent).toMatch(/R\$\s*250,00/);
    expect(brt.textContent).toMatch(/R\$\s*750,00/);
    expect(brt.textContent).toMatch(/R\$\s*100,00/);
    expect(brt.textContent).toContain("25%");
    expect(brt.querySelector(".progresso--feito")).toBeTruthy();
  });

  it("os chips têm um item por contratante com a contagem e filtram, e os totais acompanham o filtro", async () => {
    abrir("/obras");
    await screen.findByRole("table");
    const chips = within(screen.getByRole("navigation", { name: "Contratante" })).getAllByRole("link");
    expect(chips.map(c => c.textContent)).toEqual(["Todas4", "MTPAR2", "SINFRA2"]);
    expect(totais()).toMatch(/Contratado R\$ 0,0 mi/);   // valores de teste são de centavos: tudo arredonda a 0,0 mi
    fireEvent.click(chips[2]);
    expect(window.location.search).toBe("?c=SINFRA");
    await screen.findByRole("table");
    expect(nomes()).toEqual(["Estações BRTSINFRA", "MT-388SINFRA · cota 49%"]);
    expect(rodape()).toBe("Mostrando 2 de 2 obras");
    expect(chips[2].getAttribute("aria-current")).toBe("true");
  });

  it("os totais somam as linhas mostradas (contratado, medido, saldo e a receber)", async () => {
    const { totaisDe } = await import("./listaObras");
    const t = totaisDe(OBRAS.filter(o => o.estado !== "encerrado") as never);
    expect(t).toMatchObject({ contratado: 6000_00, medido: 2250_00, saldo: 3750_00, aReceber: 200_00, temReceber: true });
    expect(totaisDe([{ ...OBRAS[0], a_receber_centavos: null }] as never).temReceber).toBe(false);
  });

  it("o a receber aparece em milhões nos totais e vira traço sem o total liberado", async () => {
    api.mockImplementation(async (caminho: string) => {
      if (caminho === "/api/contratos") return OBRAS.map(o => ({ ...o, valor_vigente_centavos: 100_000_000_00, medido_execucao_centavos: 40_000_000_00, a_receber_centavos: null }));
      if (caminho === "/api/entidades") return [];
      return { avisos: [] };
    });
    abrir("/obras?c=SINFRA");
    await screen.findByRole("table");
    expect(totais()).toContain("Contratado R$ 200,0 mi");
    expect(totais()).toContain("Medido R$ 80,0 mi");
    expect(totais()).toContain("Saldo R$ 120,0 mi");
    expect(totais()).toContain("A receber —");
    expect(screen.getAllByRole("row")[1].textContent).toContain("—");
  });

  it("clicar na linha ou no nome abre a página da obra", async () => {
    abrir("/obras");
    await screen.findByRole("table");
    expect(screen.getByRole("link", { name: "Estações BRT" }).getAttribute("href")).toBe("/obras/1");
    fireEvent.click(screen.getByRole("link", { name: "Granito" }).closest("tr")!);
    expect(window.location.pathname).toBe("/obras/3");
  });

  it("consórcio mostra a cota em cinza e obra sem consórcio não", async () => {
    abrir("/obras");
    await screen.findByRole("table");
    const cota = document.querySelector(".obras-posicao__cota")!;
    expect(cota.textContent).toContain("cota 49%");
    expect(document.querySelectorAll(".obras-posicao__cota")).toHaveLength(1);
  });

  it("'Ver todas' traz as encerradas e os totais as incluem", async () => {
    abrir("/obras?c=MTPAR");
    await screen.findByRole("table");
    expect(nomes()).toEqual(["GranitoMTPAR"]);
    fireEvent.click(screen.getByRole("link", { name: "Ver todas" }));
    expect(window.location.search).toBe("?c=MTPAR&situacao=todas");
    await screen.findByText("Só em andamento");
    expect(rodape()).toBe("Mostrando 2 de 2 obras");
    expect(nomes()).toEqual(["DeciolândiaMTPAR", "GranitoMTPAR"]);
    expect(screen.queryByRole("link", { name: "Ver todas" })).toBeNull();
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
    expect(nomes()).toEqual(["MT-388SINFRA · cota 49%"]);
    cleanup();
    abrir("/obras?orgao=MTPAR");
    await screen.findByRole("table");
    expect(window.location.search).toBe("?c=MTPAR");
  });
});
