import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Usuario } from "./Login";
import MedicaoNova from "./MedicaoNova";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));
vi.mock("./Espelho", () => ({ default: ({ abrirForm, parte }: { abrirForm?: boolean; parte?: string }) => <div data-espelho={parte} data-abre-form={String(!!abrirForm)} /> }));

const usuario = { id: 1, nome: "Leo", email: "l@l.com", perfil: "admin" } as Usuario;

// #153: a tela Nova medição virou a etapa 1 (Espelho) da página da medição
describe("Medição que ainda não existe", () => {
  afterEach(() => { cleanup(); api.mockReset(); });

  it("abre na etapa 1 com o formulário do espelho; as outras etapas liberam depois", async () => {
    api.mockResolvedValue({ obra: "Escola", orgao: "SINFRA", instrumento: "CT 1/2026", percentual_lotufo_bp: 10000 });
    const { container } = render(<MedicaoNova contratoId={7} usuario={usuario} origem={null} />);
    expect(await screen.findByRole("heading", { name: "Nova medição", level: 1 })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Espelho", level: 2 })).toBeTruthy();
    const espelho = container.querySelector("[data-espelho='espelho']")!;
    expect(espelho.getAttribute("data-abre-form")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: /Etapa 4: Envio ao órgão/ }));
    // o selo diz que libera depois; o corpo nao repete
    expect(screen.getByText("Libera depois da etapa 3")).toBeTruthy();
    expect(screen.queryByText("Libera depois da etapa 3.")).toBeNull();
    expect(container.querySelector("[data-espelho]")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Voltar à etapa atual" }));
    expect(container.querySelector("[data-espelho]")).not.toBeNull();
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
