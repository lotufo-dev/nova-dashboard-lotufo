import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Usuario } from "./Login";
import MedicaoNova from "./MedicaoNova";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));
vi.mock("./Espelho", () => ({ default: ({ parte }: { parte?: string }) => <div data-espelho={parte} /> }));
// o formulario tem teste proprio (PlanilhaCarta.test.tsx); aqui so' importa que ele e' o primeiro passo
vi.mock("./PlanilhaCarta", () => ({ NovaPlanilhaCarta: ({ contratoId }: { contratoId: number }) => <div data-nova-planilha={contratoId} /> }));

const usuario = { id: 1, nome: "Leo", email: "l@l.com", perfil: "admin" } as Usuario;
const CAB = { obra: "Escola", orgao: "SINFRA", instrumento: "CT 1/2026", percentual_lotufo_bp: 10000 };
// a obra com regra de espelho ativa (a planilha/carta e' o 1o passo dela) ou a do fluxo antigo
function responder(situacao: string | null, cab: object = CAB) {
  api.mockImplementation(async (url: string) => (url.endsWith("/espelho") ? { regra: situacao ? { situacao } : null, espelhos: [] } : cab));
}

// #153: a tela Nova medição virou o primeiro passo da página da medição; #653: com a barra dos seis passos de Passos.tsx
describe("Medição que ainda não existe", () => {
  afterEach(() => { cleanup(); api.mockReset(); });

  // #289: o primeiro passo deixou de ser o espelho e passou a ser a planilha/carta
  it("abre no passo 1 (Planilha e carta) com a Nova planilha/carta, sem o espelho; os outros passos liberam depois", async () => {
    responder("ativa");
    const { container } = render(<MedicaoNova contratoId={7} usuario={usuario} origem={null} />);
    expect(await screen.findByRole("heading", { name: "Nova medição", level: 1 })).toBeTruthy();
    await waitFor(() => expect(container.querySelector("[data-nova-planilha='7']")).not.toBeNull());
    expect(container.querySelector("[data-espelho]")).toBeNull();
    // #653: a barra é a da página da medição, com os seis nomes; as cinco etapas antigas saíram
    const barra = screen.getByRole("navigation", { name: "Passos da medição" });
    expect(within(barra).getAllByRole("button").map(b => b.getAttribute("aria-label"))).toEqual([
      "Passo 1: Planilha e carta", "Passo 2: Análise do órgão", "Passo 3: Espelhos", "Passo 4: Notas", "Passo 5: Envio da nota",
      "Passo 6: Pagamento"]);
    expect(screen.getByRole("heading", { name: "Planilha e carta", level: 2 })).toBeTruthy();
    expect(container.textContent).not.toMatch(/Faturamento|Envio ao órgão|Etapa/);
    expect(container.innerHTML).not.toMatch(/Faturamento|Envio ao órgão|Etapa \d|etapa-\d/);
    fireEvent.click(screen.getByRole("button", { name: "Passo 5: Envio da nota" }));
    // o selo diz que libera depois; o corpo nao repete
    expect(screen.getByText("Libera depois do passo 4")).toBeTruthy();
    expect(container.querySelector("[data-nova-planilha]")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Voltar ao passo atual" }));
    expect(container.querySelector("[data-nova-planilha]")).not.toBeNull();
  });

  it("obra fora do fluxo do espelho: sem o formulário, com o lançamento à mão (gate Sol, PR #382)", async () => {
    responder(null);
    const { container } = render(<MedicaoNova contratoId={7} usuario={usuario} origem={null} />);
    expect((await screen.findByRole("link", { name: "Lançar a medição à mão" })).getAttribute("href")).toBe("/obras/7/medicoes");
    // #653: a obra sem planilha e carta começa em Espelhos, como na página da medição
    expect(within(screen.getByRole("navigation", { name: "Passos da medição" })).getAllByRole("button").map(b => b.getAttribute("aria-label")))
      .toEqual(["Passo 1: Espelhos", "Passo 2: Notas", "Passo 3: Envio da nota", "Passo 4: Pagamento"]);
    expect(screen.getByRole("heading", { name: "Espelhos", level: 2 })).toBeTruthy();
    expect(container.querySelector("[data-nova-planilha]")).toBeNull();
  });

  it("diretoria não vê o formulário da planilha/carta", async () => {
    responder("ativa");
    const { container } = render(<MedicaoNova contratoId={7} usuario={{ ...usuario, perfil: "diretoria" } as Usuario} origem={null} />);
    await screen.findByRole("heading", { name: "Nova medição", level: 1 });
    expect(container.querySelector("[data-nova-planilha]")).toBeNull();
  });

  it("o cabeçalho só diz a cota quando a Lotufo não tem 100%", async () => {
    api.mockResolvedValue({ obra: "Escola", orgao: "SINFRA", instrumento: "CT 1/2026", percentual_lotufo_bp: 10000 });
    const { container } = render(<MedicaoNova contratoId={7} usuario={usuario} origem={null} />);
    await screen.findByText("SINFRA");
    expect(container.querySelector(".med-meta")!.textContent).not.toMatch(/cota|valores cheios/);
    cleanup();
    api.mockResolvedValue({ obra: "Escola", orgao: "SINFRA", instrumento: "CT 1/2026", percentual_lotufo_bp: 4000 });
    render(<MedicaoNova contratoId={7} usuario={usuario} origem={null} />);
    expect(await screen.findByText("cota 40%")).toBeTruthy();
    expect(screen.queryByText(/valores cheios/)).toBeNull();
  });
});
