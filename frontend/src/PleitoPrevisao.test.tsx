import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import PleitoPrevisao from "./PleitoPrevisao";

const { api, apiForm } = vi.hoisted(() => ({ api: vi.fn(), apiForm: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api, apiForm }));

const planilha = () => new File(["PK"], "Mem. e Cron. - Prev. de Reajuste.xlsx",
  { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });

function anexar() {
  fireEvent.change(screen.getByLabelText("Anexar planilha de previsão"), { target: { files: [planilha()] } });
}

// issue #272: a planilha do pleito vira a tabela competencia x valor para conferir antes de gravar
describe("Previsão de reajuste do pleito", () => {
  afterEach(() => { cleanup(); api.mockReset(); apiForm.mockReset(); });

  it("lê a planilha, mostra competência × valor para conferir e grava com origem pleito ao aceitar", async () => {
    apiForm.mockResolvedValue({ reconhecida: true, linhas: [
      { competencia: "2026-03", valor_centavos: 123456, medicao: "1ª Medição", periodo: "23/02/2026 a 31/03/2026" },
      { competencia: "2026-04", valor_centavos: -1507, medicao: "2ª Medição", periodo: "01/04/2026 a 30/04/2026" }] });
    api.mockResolvedValue({});
    const aoGravar = vi.fn();
    render(<PleitoPrevisao pleitoId={9} aoGravar={aoGravar} />);
    anexar();
    const tabela = await screen.findByRole("table", { name: "Previsão lida da planilha" });
    expect(apiForm.mock.calls[0][0]).toBe("/api/pleitos/9/previsao/ler");
    const linhas = within(tabela).getAllByRole("row");
    expect(linhas).toHaveLength(1 + 2 + 1);                          // cabeca, 2 competencias, total
    expect(linhas[1].textContent).toContain("03/2026");
    expect(linhas[1].textContent).toContain("1ª Medição");
    expect(linhas[1].textContent).toContain("R$ 1.234,56");
    expect(linhas[2].textContent).toContain("−R$ 15,07");
    expect(linhas[3].textContent).toContain("R$ 1.219,49");
    // ler nao grava: so' o aceite chama a rota que grava
    expect(api).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Aceitar previsão" }));
    await waitFor(() => expect(api).toHaveBeenCalledTimes(1));
    const [caminho, opcoes] = api.mock.calls[0];
    expect(caminho).toBe("/api/pleitos/9/previsao");
    expect(JSON.parse(opcoes.body)).toEqual({ origem: "pleito", linhas: [
      { competencia: "2026-03", valor_centavos: 123456 }, { competencia: "2026-04", valor_centavos: -1507 }] });
    expect(await screen.findByText("Previsão gravada: 2 competências.")).toBeTruthy();
    expect(aoGravar).toHaveBeenCalled();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("planilha fora do modelo mostra o aviso e a tabela vazia para digitar, que grava com origem manual", async () => {
    apiForm.mockResolvedValue({ reconhecida: false, mensagem: "Não reconheci a planilha; digite a previsão",
      motivo: "falta a aba Resumo", linhas: [] });
    api.mockResolvedValue({});
    render(<PleitoPrevisao pleitoId={9} aoGravar={() => {}} />);
    anexar();
    expect((await screen.findByRole("alert")).textContent).toContain("Não reconheci a planilha; digite a previsão");
    expect(screen.getByText(/falta a aba Resumo/)).toBeTruthy();
    const tabela = screen.getByRole("table", { name: "Previsão digitada" });
    const competencia = within(tabela).getByLabelText("Competência da linha 1") as HTMLInputElement;
    const valor = within(tabela).getByLabelText("Valor previsto da linha 1") as HTMLInputElement;
    expect(competencia.value).toBe("");
    expect(valor.value).toBe("");
    fireEvent.change(competencia, { target: { value: "2026-09" } });
    fireEvent.paste(valor, { clipboardData: { getData: () => "1.500,25" } });
    fireEvent.click(screen.getByRole("button", { name: "Adicionar competência" }));
    fireEvent.change(within(tabela).getByLabelText("Competência da linha 2"), { target: { value: "2026-10" } });
    fireEvent.paste(within(tabela).getByLabelText("Valor previsto da linha 2"), { clipboardData: { getData: () => "10" } });
    fireEvent.click(screen.getByRole("button", { name: "Gravar previsão" }));
    await waitFor(() => expect(api).toHaveBeenCalledTimes(1));
    expect(JSON.parse(api.mock.calls[0][1].body)).toEqual({ origem: "manual", linhas: [
      { competencia: "2026-09", valor_centavos: 150025 }, { competencia: "2026-10", valor_centavos: 1000 }] });
  });

  it("linha digitada sem competência ou sem valor não grava e diz o que falta", async () => {
    render(<PleitoPrevisao pleitoId={9} aoGravar={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Digitar a previsão" }));
    fireEvent.change(screen.getByLabelText("Competência da linha 1"), { target: { value: "2026-09" } });
    fireEvent.click(screen.getByRole("button", { name: "Gravar previsão" }));
    expect((await screen.findByRole("alert")).textContent).toContain("Preencha a competência e o valor de todas as linhas");
    expect(api).not.toHaveBeenCalled();
  });
});
