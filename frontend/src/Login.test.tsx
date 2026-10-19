import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Login from "./Login";
import { ApiErro } from "./api";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));
vi.mock("./LoginFundo3D", () => ({ iniciarFundo: () => () => {} }));

function tentar() {
  render(<Login aoEntrar={() => {}} />);
  fireEvent.change(screen.getByLabelText("E-mail"), { target: { value: "admin@lotufo.com" } });
  fireEvent.change(screen.getByLabelText("Senha"), { target: { value: "senha-forte-123" } });
  fireEvent.click(screen.getByRole("button", { name: "Entrar" }));
}

describe("Login: recusas", () => {
  afterEach(() => { cleanup(); api.mockReset(); });

  it("429 (limite por computador) mostra o aviso do servidor, não 'senha errada'", async () => {
    const texto = "Muitas tentativas de entrar a partir deste computador. Tente de novo em alguns minutos.";
    api.mockRejectedValue(new ApiErro(429, texto));
    tentar();
    expect((await screen.findByRole("alert")).textContent).toBe(texto);
  });

  it("401 continua com a mensagem de credencial recusada", async () => {
    api.mockRejectedValue(new ApiErro(401, "E-mail ou senha inválidos, ou usuário bloqueado"));
    tentar();
    expect((await screen.findByRole("alert")).textContent).toContain("Confira os dois e tente de novo.");
  });
});
