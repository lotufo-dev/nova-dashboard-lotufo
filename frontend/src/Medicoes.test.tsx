import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Medicoes from "./Medicoes";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

const medicao = (extra: Record<string, unknown> = {}) => ({
  id: 70, numero: 7, tipo: "execucao", competencia: "2026-09", estado: "nota_emitida", valor_protocolado_centavos: 100,
  valor_protocolado_origem: null, valor_atestado_centavos: null, valor_atestado_origem: null, atestado_em: null,
  nf_emitida_em: null, recebida_em: null, congelada: 0, protocolos: [], notas: [], ...extra });

function responder(rm: { configurado: boolean; ultima_sincronizacao: string | null; ultimo_erro: string | null }) {
  api.mockImplementation(async (url: string) => {
    if (url.startsWith("/api/medicoes/andamento")) return [{ id: 70, proximo_passo: "Envio da nota", desde: "2026-10-01" }];
    if (url === "/api/rm/status") return rm;
    return [medicao(), medicao({ id: 60, numero: 6, estado: "recebida", recebida_em: "2026-09-20",
      notas: [{ nota_id: 1, numero: "0002322", serie: null, emissao: null, valor_centavos: 1, coligada: 1,
        recebido_centavos: 1, recebido_em: null, origem: "rm", regra: null }] })];
  });
}

// texto na tela (26/10/2026): sem contador ao lado dos titulos, sem "desde" nem carimbo de sincronizacao do RM
describe("Medições da obra", () => {
  afterEach(() => { cleanup(); api.mockReset(); });

  it("sem frase de apoio: contador, 'desde' e sincronização do RM saem; a coluna Notas traz os números", async () => {
    responder({ configurado: true, ultima_sincronizacao: "2026-10-26T08:00:00-04:00", ultimo_erro: null });
    render(<Medicoes contratoId={3} busca={{}} />);
    expect(await screen.findByRole("heading", { name: "Em andamento" })).toBeTruthy();
    // #653: o próximo passo é o nome do passo, e a medição abre na âncora dele
    expect(screen.getByText("Envio da nota")).toBeTruthy();
    expect(screen.getAllByRole("link", { name: /Medição/ }).map(l => l.getAttribute("href"))).toContain("/obras/3/medicoes/70#passo-5");
    expect(screen.queryByText(/desde|sincronizado|1 medição|recebidas, canceladas/)).toBeNull();
    expect(screen.queryByText(/Sincronização com o RM falhou/)).toBeNull();
    expect(screen.getByText("NF 2322")).toBeTruthy();
  });

  // #774: o estado nas situacoes da fundacao, com forma alem da cor; a competencia sob o nome e a marca sob o estado
  it("obra sem medição: cada painel diz isso numa linha curta, sem tabela vazia", async () => {
    api.mockImplementation(async (url: string) => url === "/api/rm/status" ? { configurado: false, ultima_sincronizacao: null, ultimo_erro: null } : []);
    render(<Medicoes contratoId={3} busca={{}} />);
    expect(await screen.findByText("Nenhuma medição aberta.")).toBeTruthy();
    expect(screen.getByText("Nenhuma medição anterior.")).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("o estado vira selo: em andamento e recebida com o glifo, cancelada neutra e riscada; nota diverge é crítico", async () => {
    const divergente = { nota_id: 9, numero: "0000009", serie: null, emissao: null, valor_centavos: 1, coligada: 1, recebido_centavos: 0,
      recebido_em: null, origem: "rm", regra: null, situacao: "ativa", confirmacao: "divergente", conferencia: [{ campo: "valor", espelho: 1, nota: 2, grau: "divergente" }] };
    api.mockImplementation(async (url: string) => {
      if (url.startsWith("/api/medicoes/andamento")) return [];
      if (url === "/api/rm/status") return { configurado: false, ultima_sincronizacao: null, ultimo_erro: null };
      return [medicao({ notas: [divergente], congelada: 1, final: 1 }), medicao({ id: 60, numero: 6, estado: "recebida", recebida_em: "2026-09-20" }),
        medicao({ id: 50, numero: 5, estado: "cancelada" })];
    });
    render(<Medicoes contratoId={3} busca={{}} />);
    await screen.findByRole("heading", { name: "Em andamento" });
    const linha = (nome: string) => screen.getByRole("link", { name: nome }).closest("tr") as HTMLElement;
    const estado = (nome: string) => linha(nome).querySelector(".estado-medicao .selo")!;
    expect(estado("7ª Medição").className).toContain("selo--andamento");
    expect(estado("7ª Medição").querySelector(".glifo--andamento")).toBeTruthy();
    expect(within(estado("7ª Medição") as HTMLElement).getByText("Nota emitida")).toBeTruthy();
    expect(within(linha("7ª Medição")).getByText("final").closest(".selo")!.className).toContain("selo--breve");
    expect(within(linha("7ª Medição")).getByText("09/2026")).toBeTruthy();
    expect(estado("6ª Medição").className).toContain("selo--feito");
    expect(estado("6ª Medição").querySelector(".glifo--feito")).toBeTruthy();
    expect(within(linha("6ª Medição")).getByText("recebida em 20/09/2026")).toBeTruthy();
    expect(estado("5ª Medição").className).toBe("selo selo--riscado");
    expect(estado("5ª Medição").querySelector(".glifo")).toBeNull();
    // o ponto de cor sozinho saiu da lista da obra
    expect(document.querySelector(".estado__ponto")).toBeNull();
  });

  // issue #647: Pedido (protocolado) e Aprovado (atestado) em colunas próprias, nas duas tabelas
  it("mostra Pedido e Aprovado; medição sem aprovado mostra “—”", async () => {
    api.mockImplementation(async (url: string) => {
      if (url.startsWith("/api/medicoes/andamento")) return [{ id: 70, proximo_passo: "Envio da nota", desde: "2026-10-01" }];
      if (url === "/api/rm/status") return { configurado: false, ultima_sincronizacao: null, ultimo_erro: null };
      return [medicao({ valor_protocolado_centavos: 25001 }),
        medicao({ id: 60, numero: 6, estado: "recebida", recebida_em: "2026-09-20", valor_protocolado_centavos: 15003,
          valor_atestado_centavos: 14901 })];
    });
    render(<Medicoes contratoId={3} busca={{}} />);
    await screen.findByRole("heading", { name: "Em andamento" });
    const [abertas, anteriores] = screen.getAllByRole("table");
    const celulas = (tabela: HTMLElement, seletor: string) => within(tabela).getAllByRole("row")
      .map(l => Array.from(l.querySelectorAll(seletor), c => (c.textContent ?? "").replace(/\s/g, " ")).join("|"))
      .filter(Boolean);
    expect(celulas(abertas, "th")[0]).toBe("Medição|Estado|Pedido|Aprovado|Próximo passo");
    expect(celulas(anteriores, "th")[0]).toBe("Medição|Estado|Pedido|Aprovado|Notas e recebimento");
    expect(celulas(abertas, "td")[0]).toContain("|R$ 250,01|—|");
    expect(celulas(anteriores, "td")[0]).toContain("|R$ 150,03|R$ 149,01|");
  });

  // issue #748: o custo lançado no RM (era a aba Custo da Carteira) vira coluna, só na obra que tem cadastro de custo
  it("coluna Custo lançado no RM só na obra com custo, uma vez por competência, na primeira execução", async () => {
    const lista = [medicao(), medicao({ id: 71, numero: 7, tipo: "reajuste" }),
      medicao({ id: 60, numero: 6, competencia: "2026-08", estado: "recebida", recebida_em: "2026-09-20" }),
      medicao({ id: 50, numero: 5, competencia: "2026-07", estado: "recebida", recebida_em: "2026-08-20" })];
    api.mockImplementation(async (url: string) => {
      if (url.startsWith("/api/medicoes/andamento")) return [];
      if (url === "/api/rm/status") return { configurado: false, ultima_sincronizacao: null, ultimo_erro: null };
      if (url === "/api/contratos/3/custo") {
        return { linhas: [{ competencia: "2026-09", custo_centavos: 123_457 }, { competencia: "2026-08", custo_centavos: 98_701 },
          { competencia: "2026-07", custo_centavos: 0 }, { competencia: "2026-06", custo_centavos: 55_555 }] };
      }
      return lista;
    });
    render(<Medicoes contratoId={3} busca={{}} />);
    await screen.findByRole("heading", { name: "Em andamento" });
    const [abertas, anteriores] = screen.getAllByRole("table");
    expect(within(abertas).getAllByRole("columnheader").map(h => h.textContent)).toContain("Custo lançado no RM");
    const linha = (tabela: HTMLElement, nome: string) => within(tabela).getByRole("link", { name: nome }).closest("tr") as HTMLElement;
    const custo = (tr: HTMLElement) => (tr.children[4].textContent ?? "").replace(/\s/g, " ");
    expect(custo(linha(abertas, "7ª Medição"))).toBe("R$ 1.234,57");
    expect(custo(linha(abertas, "Reajuste da 7ª Medição"))).toBe("—");      // uma vez só por competência
    expect(custo(linha(anteriores, "6ª Medição"))).toBe("R$ 987,01");
    expect(custo(linha(anteriores, "5ª Medição"))).toBe("—");               // zero não é custo lançado
    // a coluna fica fora de total, sem a palavra margem
    expect(document.body.textContent).not.toMatch(/margem|lucro/i);
    expect(abertas.querySelector("tfoot")).toBeNull();
    cleanup();
    api.mockImplementation(async (url: string) => {
      // #804: a obra sem cadastro de custo responde sem erro, vazia e com o motivo
      if (url === "/api/contratos/3/custo") return { contrato_id: 3, sem_cadastro: true, motivo: "Esta obra não tem cadastro de custo.", linhas: [] };
      if (url === "/api/rm/status") return { configurado: false, ultima_sincronizacao: null, ultimo_erro: null };
      return url.startsWith("/api/medicoes/andamento") ? [] : lista;
    });
    render(<Medicoes contratoId={3} busca={{}} />);
    await screen.findByRole("heading", { name: "Em andamento" });
    expect(screen.queryByText("Custo lançado no RM")).toBeNull();
    expect(screen.queryByText(/cadastro de custo/)).toBeNull();
  });

  it("a falha da última sincronização do RM vira selo, só quando acontece", async () => {
    responder({ configurado: true, ultima_sincronizacao: null, ultimo_erro: "tempo esgotado" });
    render(<Medicoes contratoId={3} busca={{}} />);
    const selo = await screen.findByText("Sincronização com o RM falhou");
    expect(selo.closest(".selo")?.className).toContain("selo--breve");
  });
});
