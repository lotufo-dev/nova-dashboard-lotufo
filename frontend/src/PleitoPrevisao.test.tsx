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
    apiForm.mockResolvedValueOnce({ reconhecida: true, sha256: "ab".repeat(32), linhas: [
      { competencia: "2026-03", valor_centavos: 123456, medicao: "1ª Medição", periodo: "23/02/2026 a 31/03/2026" },
      { competencia: "2026-04", valor_centavos: -1507, medicao: "2ª Medição", periodo: "01/04/2026 a 30/04/2026" }] });
    // a confirmacao usa a contagem do servidor (aqui diferente da tela, de proposito)
    apiForm.mockResolvedValueOnce({ previsao_gravada: 3 });
    api.mockResolvedValue({});
    const aoGravar = vi.fn();
    render(<PleitoPrevisao pleitoId={9} dataBase="2024-06" ciclo={2026} aoGravar={aoGravar} />);
    anexar();
    const tabela = await screen.findByRole("table", { name: "Previsão lida da planilha" });
    expect(apiForm.mock.calls[0][0]).toBe("/api/pleitos/9/previsao/ler");
    // a data-base e o ciclo a que a previsao se liga, acima da tabela de conferencia
    expect(screen.getByText("Data-base 06/2024, ciclo 2026")).toBeTruthy();
    const linhas = within(tabela).getAllByRole("row");
    expect(linhas).toHaveLength(1 + 2 + 1);                          // cabeca, 2 competencias, total
    expect(linhas[1].textContent).toContain("03/2026");
    expect(linhas[1].textContent).toContain("1ª Medição");
    expect(linhas[1].textContent).toContain("R$ 1.234,56");
    expect(linhas[2].textContent).toContain("−R$ 15,07");
    expect(linhas[3].textContent).toContain("R$ 1.219,49");
    // ler nao grava: so' o aceite chama a rota que grava
    expect(api).not.toHaveBeenCalled();
    expect(apiForm).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Aceitar previsão" }));
    await waitFor(() => expect(apiForm).toHaveBeenCalledTimes(2));
    // o aceite devolve a MESMA planilha: o servidor rele e grava o que leu; a tela nao manda origem nem valores
    const [caminho, fd] = apiForm.mock.calls[1];
    expect(caminho).toBe("/api/pleitos/9/previsao/planilha");
    expect((fd as FormData).get("arquivo")).toBe(apiForm.mock.calls[0][1].get("arquivo"));
    // so' o arquivo e o sha256 da leitura conferida (o servidor recusa outro arquivo); nem origem nem valores
    expect([...(fd as FormData).keys()]).toEqual(["arquivo", "sha256"]);
    expect((fd as FormData).get("sha256")).toBe("ab".repeat(32));
    expect(api).not.toHaveBeenCalled();
    expect(await screen.findByText("Previsão gravada: 3 competências.")).toBeTruthy();
    expect(aoGravar).toHaveBeenCalled();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("planilha fora do modelo mostra o aviso e a tabela vazia para digitar, que grava com origem manual", async () => {
    apiForm.mockResolvedValue({ reconhecida: false, mensagem: "Não reconheci a planilha; digite a previsão",
      motivo: "falta a aba Resumo", linhas: [] });
    api.mockResolvedValue({ previsao_gravada: 2 });
    render(<PleitoPrevisao pleitoId={9} dataBase="2024-06" ciclo={2026} aoGravar={() => {}} />);
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
    // indice deflacionario: a linha marcada como negativa vai com o sinal
    fireEvent.click(within(tabela).getByRole("checkbox", { name: "Reajuste negativo na linha 2" }));
    fireEvent.click(screen.getByRole("button", { name: "Gravar previsão" }));
    await waitFor(() => expect(api).toHaveBeenCalledTimes(1));
    expect(api.mock.calls[0][0]).toBe("/api/pleitos/9/previsao/digitada");
    expect(JSON.parse(api.mock.calls[0][1].body)).toEqual({ linhas: [
      { competencia: "2026-09", valor_centavos: 150025 }, { competencia: "2026-10", valor_centavos: -1000 }] });
    expect(await screen.findByText("Previsão gravada: 2 competências.")).toBeTruthy();
  });

  it("linha digitada sem competência ou sem valor não grava e diz o que falta", async () => {
    render(<PleitoPrevisao pleitoId={9} dataBase="2024-06" ciclo={2026} aoGravar={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Digitar a previsão" }));
    fireEvent.change(screen.getByLabelText("Competência da linha 1"), { target: { value: "2026-09" } });
    fireEvent.click(screen.getByRole("button", { name: "Gravar previsão" }));
    expect((await screen.findByRole("alert")).textContent).toContain("Preencha a competência e o valor de todas as linhas");
    expect(api).not.toHaveBeenCalled();
  });
});
