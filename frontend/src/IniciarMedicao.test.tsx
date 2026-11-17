import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { ApiErro, comPontoFinal } from "./api";
import IniciarMedicao from "./IniciarMedicao";
import type { ObraResumo } from "./resumoMedicoes";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

afterEach(() => { cleanup(); api.mockReset(); });

const OBRA = { contrato_id: 7, obra: "Obra Alfa", proxima_tipo: "execucao", prevista_id: null } as unknown as ObraResumo;

test("a mensagem do servidor ganha ponto final antes da frase seguinte, sem dobrar o que já tem", () => {
  expect(comPontoFinal("Contrato não encontrado")).toBe("Contrato não encontrado.");
  expect(comPontoFinal("Sem conexão com o servidor. ")).toBe("Sem conexão com o servidor.");
  expect(comPontoFinal("Tente de novo?")).toBe("Tente de novo?");
  expect(comPontoFinal("")).toBe("");
});

test("falha ao ler a regra da obra: a mensagem do servidor não emenda na frase seguinte", async () => {
  api.mockRejectedValue(new ApiErro(404, "Contrato não encontrado"));
  render(<IniciarMedicao obra={OBRA} mes="2026-10" />);
  expect((await screen.findByRole("alert")).textContent)
    .toBe("Não foi possível ler a regra da obra: Contrato não encontrado. Escolha a obra de novo para tentar outra vez.");
});
