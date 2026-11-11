import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DocumentosObra } from "./ObraAbas";
import { hrefDe } from "./rota";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

const item = (situacao: string, extra: Record<string, unknown> = {}) => ({ entidade_id: 1, entidade: "Construtora Alfa", tipo_id: 1,
  tipo: "CND Federal", chave: null, jurisdicao: null, situacao, validade: "2026-12-31", dias: 60, certidao_id: 1,
  link_emissao: "https://exemplo.com.br/emitir", ...extra });
const checklist = (pronto: boolean, itens: unknown[]) => ({ contrato_id: 1, entidade_id: 1, entidade: "Construtora Alfa", pronto, itens });
const quadroDe = async (nome: string) => (await screen.findByRole("heading", { name: nome })).closest("section")!;

// #661: a obra responde "pode protocolar hoje?" para a medicao e para o reajuste; a certidao da empresa,
// uma a uma, mora em Documentos. O veredito vem do servidor (`pronto`); a tela so' lista o que falta.
describe("Documentos da obra", () => {
  afterEach(() => { cleanup(); api.mockReset(); });

  it("mostra o veredito da medição e o do reajuste, cada um com a sua natureza", async () => {
    api.mockImplementation((url: string) => Promise.resolve(url.includes("natureza=reajuste")
      ? checklist(false, [item("pendente", { validade: null, dias: null })])
      : checklist(true, [item("ok")])));
    render(<DocumentosObra contratoId={7} />);
    expect(await within(await quadroDe("Medição")).findByText("Pronto para protocolar")).toBeTruthy();
    expect(await within(await quadroDe("Reajuste")).findByText("Falta documento para protocolar")).toBeTruthy();
    expect(api.mock.calls.map(c => c[0]).sort()).toEqual(
      ["/api/contratos/7/checklist-protocolo", "/api/contratos/7/checklist-protocolo?natureza=reajuste"]);
  });

  it("com certidão vencida, diz o que falta numa linha por item e leva à empresa em Documentos", async () => {
    api.mockResolvedValue(checklist(false, [
      item("pendente", { validade: null, dias: null }),
      item("ok", { tipo_id: 2, tipo: "FGTS" }),
      item("pendente", { entidade_id: 2, entidade: "Construtora Beta", tipo_id: 3, tipo: "CNDT", validade: null, dias: null }),
      item("pendente", { entidade_id: 3, entidade: "Construtora Gama", tipo_id: null, tipo: "Regularidade mensal",
        chave: "regularidade", validade: null, dias: null, competencia: null, esperada: "2026-10" })]));
    render(<DocumentosObra contratoId={1} />);
    const quadro = await quadroDe("Medição");
    const linhas = await within(quadro).findAllByRole("listitem");
    expect(linhas.map(l => l.textContent)).toEqual(
      ["CND FederalConstrutora Alfa", "CNDTConstrutora Beta", "Regularidade mensal de 10/2026Construtora Gama"]);
    const destino = (n: number) => within(linhas[n]).getByRole("link").getAttribute("href");
    expect(destino(0)).toBe(hrefDe({ tela: "documentos-empresa", id: 1 }));
    expect(destino(1)).toBe(hrefDe({ tela: "documentos-empresa", id: 2 }));
    expect(destino(2)).toBe(hrefDe({ tela: "documentos-empresa", id: 3, aba: "regularidade" }));
    expect(destino(0)).toBe("/documentos/1");
  });

  it("a lista completa de certidões por empresa não aparece: sem tabela, sem validade, sem emitir", async () => {
    api.mockResolvedValue(checklist(true, [item("ok"), item("vencendo", { tipo_id: 2, tipo: "FGTS", dias: 10 })]));
    render(<DocumentosObra contratoId={1} />);
    const quadro = await quadroDe("Medição");
    expect(await within(quadro).findByText("Pronto para protocolar")).toBeTruthy();
    expect(document.querySelector("table")).toBeNull();
    expect(screen.queryByText("CND Federal")).toBeNull();
    expect(screen.queryByText("FGTS")).toBeNull();
    expect(screen.queryByText(/31\/12\/2026|Em dia|Vence em/)).toBeNull();
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("sem documento exigido: uma linha curta, sem veredito", async () => {
    api.mockResolvedValue(checklist(true, []));
    render(<DocumentosObra contratoId={1} />);
    expect((await screen.findAllByText("Nenhum documento exigido.")).length).toBe(2);
    expect(screen.queryByText("Pronto para protocolar")).toBeNull();
  });
});
