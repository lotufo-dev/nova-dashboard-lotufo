import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DocumentosObra } from "./ObraAbas";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

const item = (situacao: string, extra: Record<string, unknown> = {}) => ({ entidade_id: 1, entidade: "Lotufo", tipo_id: 1,
  tipo: "CND Federal", chave: null, jurisdicao: null, situacao, validade: "2026-12-31", dias: 60, certidao_id: 1,
  link_emissao: null, ...extra });
const checklist = (pronto: boolean, itens: unknown[]) => ({ contrato_id: 1, entidade_id: 1, entidade: "Lotufo", pronto, itens });

// texto na tela (26/10/2026): o quadro mostra o veredito no selo; so' o documento sem validade vira aviso
describe("Documentos exigidos da obra", () => {
  afterEach(() => { cleanup(); api.mockReset(); });

  it("com documento sem validade, o aviso crítico aparece numa frase", async () => {
    api.mockResolvedValue(checklist(false, [item("pendente", { validade: null, dias: null })]));
    render(<DocumentosObra contratoId={1} />);
    const quadro = (await screen.findByRole("heading", { name: "Medição" })).closest("section")!;
    expect(await within(quadro).findByText("Lotufo: 1 documento sem validade hoje.")).toBeTruthy();
  });

  it("pronto: só o selo, sem frase de apoio nem aviso", async () => {
    api.mockResolvedValue(checklist(true, [item("ok"), item("vencendo", { tipo_id: 2, tipo: "FGTS", dias: 10 })]));
    render(<DocumentosObra contratoId={1} />);
    const quadro = (await screen.findByRole("heading", { name: "Medição" })).closest("section")!;
    expect(await within(quadro).findByText("Pronto para protocolar")).toBeTruthy();
    expect(within(quadro).queryByText(/sem validade hoje/)).toBeNull();
    expect(within(quadro).queryByText(/estão valendo hoje|vence em breve/)).toBeNull();
    expect(quadro.querySelector("td[title]")).toBeNull();
  });

  it("sem documento exigido: uma linha curta", async () => {
    api.mockResolvedValue(checklist(true, []));
    render(<DocumentosObra contratoId={1} />);
    expect((await screen.findAllByText("Nenhum documento exigido.")).length).toBe(2);
    expect(screen.queryByText(/não exige documentos/)).toBeNull();
  });
});
