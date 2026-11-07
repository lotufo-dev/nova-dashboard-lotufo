import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FormBoletim } from "./Boletim";
import type { Medicao } from "./Medicoes";

const { apiForm } = vi.hoisted(() => ({ apiForm: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), apiForm }));

const M = { id: 5, numero: 7, tipo: "execucao", competencia: "2026-07", estado: "planilha_enviada",
  valor_protocolado_centavos: 1234567, valor_protocolado_origem: null, valor_atestado_centavos: null,
  valor_atestado_origem: null, atestado_em: null, nf_emitida_em: null, recebida_em: null, congelada: 0,
  protocolos: [] } as Medicao;
const PDF = new File(["%PDF-1.4"], "boletim.pdf", { type: "application/pdf" });

function abrir(leitura: unknown) {
  apiForm.mockImplementation(async (url: string) => url.endsWith("/leitura") ? leitura : { id: 1 });
  const agir = vi.fn(async (fn: () => Promise<unknown>) => { await fn(); return true; });
  render(<FormBoletim m={M} salvando={false} agir={agir} aoFechar={() => {}} />);
  fireEvent.drop(screen.getByTestId("soltar-boletim"), { dataTransfer: { files: [PDF] } });
  return agir;
}
const campo = (rotulo: RegExp) => screen.getByLabelText(rotulo) as HTMLInputElement;
const enviado = () => apiForm.mock.calls.find(c => c[0] === "/api/medicoes/5/boletim")?.[1] as FormData | undefined;

describe("FormBoletim (issue #290)", () => {
  afterEach(() => { cleanup(); apiForm.mockReset(); });

  it("arrastar a capa lida preenche nº, data e valor, marca os três como lidos e mostra a diferença", async () => {
    abrir({ lido: true, fonte: "texto", avisos: [], campos: { numero_orgao: "7", data: "2026-08-10", valor_centavos: 1200001 } });
    await waitFor(() => expect(campo(/Nº no órgão/).value).toBe("7"));
    expect(apiForm.mock.calls[0][0]).toBe("/api/medicoes/5/boletim/leitura");
    expect(campo(/Data do boletim/).value).toBe("2026-08-10");
    expect(campo(/Valor aprovado/).value).toBe("12.000,01");
    expect(screen.getAllByText("Lido da capa")).toHaveLength(3);
    const quadro = screen.getByLabelText("Pedido e aprovado");
    // pedido 12.345,67, aprovado 12.000,01 (centavo impar): diferenca de -345,66 (sinal de menos U+2212)
    expect(quadro.textContent).toContain("12.345,67");
    expect(quadro.textContent).toContain("12.000,01");
    expect(quadro.textContent).toContain("−R$ 345,66");
  });

  it("PDF sem leitura deixa os três campos vazios para digitar e grava como manual", async () => {
    const agir = abrir({ lido: false, fonte: null, avisos: [], campos: {} });
    await waitFor(() => expect(apiForm).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByRole("button", { name: "Registrar boletim" })).toBeTruthy());
    expect([campo(/Nº no órgão/).value, campo(/Data do boletim/).value, campo(/Valor aprovado/).value]).toEqual(["", "", ""]);
    expect(screen.queryByText("Lido da capa")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Registrar boletim" }));
    expect(screen.getByText("Informe o nº do boletim no órgão.")).toBeTruthy();
    expect(agir).not.toHaveBeenCalled();
    fireEvent.change(campo(/Nº no órgão/), { target: { value: "SMO 14/2026" } });
    fireEvent.change(campo(/Data do boletim/), { target: { value: "2026-08-10" } });
    fireEvent.change(campo(/Valor aprovado/), { target: { value: "12.000,01" } });
    fireEvent.click(screen.getByRole("button", { name: "Registrar boletim" }));
    await waitFor(() => expect(enviado()).toBeTruthy());
    expect(enviado()!.get("lido")).toBe("false");
    expect(enviado()!.get("numero_orgao")).toBe("SMO 14/2026");
  });

  it("mexer num campo lido tira a marca: o boletim grava como digitado", async () => {
    abrir({ lido: true, fonte: "texto", avisos: [], campos: { numero_orgao: "7", data: "2026-08-10", valor_centavos: 1200001 } });
    await waitFor(() => expect(campo(/Nº no órgão/).value).toBe("7"));
    fireEvent.change(campo(/Nº no órgão/), { target: { value: "8" } });
    expect(screen.getAllByText("Lido da capa")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Aceitar e registrar o boletim" }));
    await waitFor(() => expect(enviado()).toBeTruthy());
    expect([enviado()!.get("numero_orgao"), enviado()!.get("lido")]).toEqual(["8", "false"]);
  });

  it("a capa não aprovada mostra o aviso do servidor e não preenche nada", async () => {
    abrir({ lido: false, fonte: "texto", campos: {},
      avisos: ["A capa não está aprovada (situação: EM ANÁLISE); digite os valores do boletim"] });
    expect(await screen.findByText(/A capa não está aprovada/)).toBeTruthy();
    expect(campo(/Valor aprovado/).value).toBe("");
  });
});
