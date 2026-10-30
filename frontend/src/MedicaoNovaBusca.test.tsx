import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Usuario } from "./Login";
import MedicaoNova from "./MedicaoNova";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

const usuario = { id: 1, nome: "Leonardo Praeiro", email: "l@l.com", perfil: "admin" } as Usuario;
const REGRA = { situacao: "ativa", saidas: 4, entradas: [
  { chave: "medicao", rotulo: "Valor da medição", natureza: "medicao" },
  { chave: "projeto", rotulo: "Valor do projeto", natureza: "projeto" }] };

function montar(busca: Record<string, string>) {
  api.mockImplementation(async (caminho: string) => caminho.includes("/cabecalho")
    ? { obra: "Obra Teste", orgao: "SINFRA", instrumento: "CT 1/2026", percentual_lotufo_bp: 10000 } : { regra: REGRA, espelhos: [] });
  render(<MedicaoNova contratoId={4} usuario={usuario} origem={null} busca={busca} />);
}

describe("Medição nova: número e competência vindos da janela Iniciar processo (#151)", () => {
  afterEach(() => { cleanup(); api.mockReset(); });

  it("?numero=15&competencia=2027-01 abre o formulário preenchido", async () => {
    montar({ numero: "15", competencia: "2027-01" });
    expect((await screen.findByLabelText("Nº da medição") as HTMLInputElement).value).toBe("15");
    expect((screen.getByLabelText("Competência") as HTMLInputElement).value).toBe("01/2027");
    expect(screen.getByLabelText("Valor do projeto")).toBeTruthy();
  });

  it("número 0, fora do padrão ou competência inválida são ignorados", async () => {
    montar({ numero: "0", competencia: "2027-13" });
    expect((await screen.findByLabelText("Nº da medição") as HTMLInputElement).value).toBe("");
    expect((screen.getByLabelText("Competência") as HTMLInputElement).value).toBe("");
  });

  it("tipo=projeto: título e número de Projeto, só os valores de Projeto", async () => {
    montar({ numero: "3", competencia: "2026-09", tipo: "projeto" });
    expect((await screen.findByLabelText("Nº da medição de Projeto") as HTMLInputElement).value).toBe("3");
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Nova medição de Projeto");
    expect(screen.getByLabelText("Valor do projeto")).toBeTruthy();
    expect(screen.queryByLabelText("Valor da medição")).toBeNull();
  });
});
