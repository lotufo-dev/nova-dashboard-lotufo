import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { NovaMedicaoManual } from "./Medicoes";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

afterEach(() => { cleanup(); api.mockReset(); });

it("nova medição manual abre com o número, a competência e a série vindos da janela Iniciar processo (#151)", async () => {
  api.mockResolvedValueOnce({ id: 5 });
  render(<NovaMedicaoManual contratoId={3} aoCriar={() => {}} inicial={{ numero: "12", competencia: "2026-10", tipo: "projeto" }} />);
  expect((screen.getByLabelText("Nº") as HTMLInputElement).value).toBe("12");
  expect((screen.getByLabelText("Tipo") as HTMLSelectElement).value).toBe("projeto");
  expect((screen.getByLabelText("Competência") as HTMLInputElement).value).toBe("10/2026");
  fireEvent.click(screen.getByRole("button", { name: /Nova medição/ }));
  await waitFor(() => expect(api).toHaveBeenCalledWith("/api/contratos/3/medicoes", expect.objectContaining({
    method: "POST", body: JSON.stringify({ numero: 12, tipo: "projeto", competencia: "2026-10" }) })));
});

it("medição de reajuste à mão vem com o valor previsto e a origem, e manda o valor e a data-base (#276)", async () => {
  api.mockImplementation(async (url: string) => (url.includes("/reajuste/sugestao")
    ? { competencia: "2026-09", data_base_mes: "2024-06", bases: [{ data_base_mes: "2024-06", aplica_a: "", ciclo: 2026,
      valor_centavos: 2_000_03, origem: "pleito", origem_texto: "previsto no pleito" }] }
    : { id: 5 }));
  render(<NovaMedicaoManual contratoId={3} aoCriar={() => {}} />);
  expect(screen.queryByLabelText("Reajuste")).toBeNull();
  fireEvent.change(screen.getByLabelText("Nº"), { target: { value: "2" } });
  fireEvent.change(screen.getByLabelText("Tipo"), { target: { value: "reajuste" } });
  fireEvent.change(screen.getByLabelText("Competência"), { target: { value: "092026" } });
  await waitFor(() => expect((screen.getByLabelText("Reajuste") as HTMLInputElement).value).toBe("2.000,03"));
  expect(screen.getByText("previsto no pleito")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: /Nova medição/ }));
  await waitFor(() => expect(api).toHaveBeenCalledWith("/api/contratos/3/medicoes", expect.objectContaining({
    method: "POST", body: JSON.stringify({ numero: 2, tipo: "reajuste", competencia: "2026-09", valor: "2.000,03",
      data_base_mes: "2024-06" }) })));
});

it("nova medição manual: digitar 092026 manda a competência 2026-09", async () => {
  api.mockResolvedValueOnce({ id: 5 });
  render(<NovaMedicaoManual contratoId={3} aoCriar={() => {}} />);
  fireEvent.change(screen.getByLabelText("Nº"), { target: { value: "7" } });
  fireEvent.change(screen.getByLabelText("Competência"), { target: { value: "092026" } });
  fireEvent.click(screen.getByRole("button", { name: /Nova medição/ }));
  await waitFor(() => expect(api).toHaveBeenCalled());
  expect(api).toHaveBeenCalledWith("/api/contratos/3/medicoes", expect.objectContaining({
    method: "POST", body: JSON.stringify({ numero: 7, tipo: "execucao", competencia: "2026-09" }) }));
});
