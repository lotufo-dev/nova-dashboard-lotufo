import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Usuario } from "./Login";
import MedicaoNova from "./MedicaoNova";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));
// desde a #289 o 1o passo e' a planilha/carta, que tem teste proprio (PlanilhaCarta.test.tsx); aqui so' importa o
// que a busca da URL entrega a ela
vi.mock("./PlanilhaCarta", () => ({
  NovaPlanilhaCarta: ({ tipo, inicial }: { tipo?: string; inicial?: { numero?: number; competencia?: string } }) =>
    <div data-nova-planilha data-tipo={tipo} data-numero={inicial?.numero ?? ""} data-competencia={inicial?.competencia ?? ""} />,
}));

const usuario = { id: 1, nome: "Leonardo Praeiro", email: "l@l.com", perfil: "admin" } as Usuario;

function montar(busca: Record<string, string>) {
  api.mockImplementation(async (caminho: string) => caminho.includes("/cabecalho")
    ? { obra: "Obra Teste", orgao: "SINFRA", instrumento: "CT 1/2026", percentual_lotufo_bp: 10000 }
    : { regra: { situacao: "ativa" }, espelhos: [] });
  return render(<MedicaoNova contratoId={4} usuario={usuario} origem={null} busca={busca} />);
}

async function planilha(container: HTMLElement) {
  await waitFor(() => expect(container.querySelector("[data-nova-planilha]")).not.toBeNull());
  return container.querySelector("[data-nova-planilha]") as HTMLElement;
}

describe("Medição nova: número e competência vindos da janela Iniciar processo (#151)", () => {
  afterEach(() => { cleanup(); api.mockReset(); });

  it("?numero=15&competencia=2027-01 abre a planilha/carta preenchida, na série de execução", async () => {
    const { container } = montar({ numero: "15", competencia: "2027-01" });
    const el = await planilha(container);
    expect(el.dataset.numero).toBe("15");
    expect(el.dataset.competencia).toBe("2027-01");
    expect(el.dataset.tipo).toBe("execucao");
  });

  it("número 0, fora do padrão ou competência inválida são ignorados", async () => {
    const { container } = montar({ numero: "0", competencia: "2027-13" });
    const el = await planilha(container);
    expect(el.dataset.numero).toBe("");
    expect(el.dataset.competencia).toBe("");
  });

  it("obra sem planilha/carta: o lançamento à mão leva o número, a competência e a série da janela", async () => {
    api.mockImplementation(async (caminho: string) => caminho.includes("/cabecalho")
      ? { obra: "Obra Teste", orgao: "SINFRA", instrumento: "CT 1/2026", percentual_lotufo_bp: 10000 } : { regra: null, espelhos: [] });
    render(<MedicaoNova contratoId={4} usuario={usuario} origem={null} busca={{ numero: "3", competencia: "2026-09", tipo: "projeto" }} />);
    const link = await screen.findByRole("link", { name: "Lançar a medição à mão" });
    expect(link.getAttribute("href")).toBe("/obras/4/medicoes?numero=3&competencia=2026-09&tipo=projeto");
  });

  it("tipo=projeto: título de Projeto e a planilha/carta na série de Projeto", async () => {
    const { container } = montar({ numero: "3", competencia: "2026-09", tipo: "projeto" });
    const el = await planilha(container);
    expect(el.dataset.tipo).toBe("projeto");
    expect(el.dataset.numero).toBe("3");
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Nova medição de Projeto");
  });

  it("issue #567: sem nada na busca, o tipo fica para a planilha/carta escolher pela última medição", async () => {
    const { container } = montar({});
    const el = await planilha(container);
    expect(el.dataset.tipo).toBeUndefined();
  });
});
