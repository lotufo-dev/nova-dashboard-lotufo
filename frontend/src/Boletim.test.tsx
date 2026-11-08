import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AceiteDiferenca, FormBoletim } from "./Boletim";
import type { Medicao } from "./Medicoes";

const { apiForm, api } = vi.hoisted(() => ({ apiForm: vi.fn(), api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), apiForm, api }));

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
    expect(enviado()!.get("numero_orgao")).toBe("SMO 14/2026");
  });

  it("mexer num campo lido tira a marca; voltar ao valor lido a devolve (gate Sol, rodada 1)", async () => {
    abrir({ lido: true, fonte: "texto", avisos: [], campos: { numero_orgao: "7", data: "2026-08-10", valor_centavos: 1200001 } });
    await waitFor(() => expect(campo(/Nº no órgão/).value).toBe("7"));
    fireEvent.change(campo(/Nº no órgão/), { target: { value: "8" } });
    expect(screen.getAllByText("Lido da capa")).toHaveLength(2);
    fireEvent.change(campo(/Nº no órgão/), { target: { value: "7" } });
    expect(screen.getAllByText("Lido da capa")).toHaveLength(3);
    fireEvent.click(screen.getByRole("button", { name: "Aceitar e registrar o boletim" }));
    await waitFor(() => expect(enviado()).toBeTruthy());
    // a origem e' do servidor (confere o PDF e os campos contra a leitura dele): a tela nao manda "lido"
    expect([enviado()!.get("numero_orgao"), enviado()!.get("lido")]).toEqual(["7", null]);
  });

  it("valor negativo vindo da leitura não é proposto", async () => {
    abrir({ lido: true, fonte: "texto", avisos: [], campos: { numero_orgao: "7", data: "2026-08-10", valor_centavos: -1234 } });
    await waitFor(() => expect(campo(/Nº no órgão/).value).toBe("7"));
    expect(campo(/Valor aprovado/).value).toBe("");
    expect(screen.getAllByText("Lido da capa")).toHaveLength(2);
  });

  it("trocar o PDF tira o que veio da leitura anterior e mantém o que a pessoa digitou", async () => {
    abrir({ lido: true, fonte: "texto", avisos: [], campos: { numero_orgao: "7", data: "2026-08-10", valor_centavos: 1200001 } });
    await waitFor(() => expect(campo(/Nº no órgão/).value).toBe("7"));
    fireEvent.change(campo(/Nº no órgão/), { target: { value: "SMO 7/2026" } });
    apiForm.mockImplementation(async () => ({ lido: false, fonte: null, avisos: [], campos: {} }));
    fireEvent.drop(screen.getByTestId("soltar-boletim"), { dataTransfer: { files: [PDF] } });
    await waitFor(() => expect(campo(/Valor aprovado/).value).toBe(""));
    expect([campo(/Nº no órgão/).value, campo(/Data do boletim/).value]).toEqual(["SMO 7/2026", ""]);
  });

  it("a capa não aprovada mostra o aviso do servidor e não preenche nada", async () => {
    abrir({ lido: false, fonte: "texto", campos: {},
      avisos: ["A capa não está aprovada (situação: EM ANÁLISE); digite os valores do boletim"] });
    expect(await screen.findByText(/A capa não está aprovada/)).toBeTruthy();
    expect(campo(/Valor aprovado/).value).toBe("");
  });
});

describe("AceiteDiferenca (issue #288)", () => {
  afterEach(() => { cleanup(); api.mockReset(); });
  const COM_BOLETIM = { ...M, estado: "boletim_recebido", valor_atestado_centavos: 1200001,
    boletins: [{ id: 9, tem_arquivo: true, valor_centavos: 1200001 }] } as Medicao;
  const agirReal = () => vi.fn(async (fn: () => Promise<unknown>) => { await fn(); return true; });

  it("aprovado abaixo do pedido: aceita com justificativa obrigatória", async () => {
    api.mockResolvedValue({ id: 1 });
    const agir = agirReal();
    render(<AceiteDiferenca m={COM_BOLETIM} podeEditar salvando={false} agir={agir} />);
    fireEvent.click(screen.getByRole("button", { name: "Aceitar a diferença" }));
    fireEvent.change(screen.getByLabelText("Justificativa"), { target: { value: "curta" } });
    fireEvent.click(screen.getByRole("button", { name: "Aceitar a diferença" }));
    expect(screen.getByText("Informe a justificativa (ao menos 10 caracteres).")).toBeTruthy();
    expect(agir).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Justificativa"), { target: { value: "  glosa de itens não executados " } });
    fireEvent.click(screen.getByRole("button", { name: "Aceitar a diferença" }));
    await waitFor(() => expect(api).toHaveBeenCalledTimes(1));
    expect(api.mock.calls[0][0]).toBe("/api/medicoes/5/diferenca-aceita");
    expect(JSON.parse(api.mock.calls[0][1].body)).toEqual({ justificativa: "glosa de itens não executados" });
  });

  it("já aceita mostra o selo; diretoria não vê o botão; sem diferença abaixo, nada", () => {
    const { container, rerender } = render(<AceiteDiferenca m={{ ...COM_BOLETIM, diferenca_aceita: { atesto_id: 9,
      justificativa: "glosa", usuario: "Eng", criado_em: "2026-11-08 10:00:00", diferenca_centavos: -34566 } }}
      podeEditar salvando={false} agir={agirReal()} />);
    expect(screen.getByText("Diferença aceita")).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
    rerender(<AceiteDiferenca m={COM_BOLETIM} podeEditar={false} salvando={false} agir={agirReal()} />);
    expect(container.textContent).toBe("");
    rerender(<AceiteDiferenca m={{ ...COM_BOLETIM, valor_atestado_centavos: 1234567 }} podeEditar salvando={false} agir={agirReal()} />);
    expect(container.textContent).toBe("");
    rerender(<AceiteDiferenca m={{ ...COM_BOLETIM, boletins: [] }} podeEditar salvando={false} agir={agirReal()} />);
    expect(container.textContent).toBe("");
    rerender(<AceiteDiferenca m={{ ...COM_BOLETIM, estado: "cancelada" }} podeEditar salvando={false} agir={agirReal()} />);
    expect(container.textContent).toBe("");
  });

  it("capa do SMO divergente do cadastro com o aprovado igual ao pedido também se aceita (issue #286)", () => {
    const { container, rerender } = render(<AceiteDiferenca m={{ ...COM_BOLETIM, valor_atestado_centavos: 1234567,
      capa_divergencias: ["Fim da execução: capa do SMO diz 31/03/2028, cadastro diz 31/12/2027"] }}
      podeEditar salvando={false} agir={agirReal()} />);
    expect(screen.getByRole("button", { name: "Aceitar a diferença" })).toBeTruthy();
    rerender(<AceiteDiferenca m={{ ...COM_BOLETIM, valor_atestado_centavos: 1234567, capa_divergencias: [] }}
      podeEditar salvando={false} agir={agirReal()} />);
    expect(container.textContent).toBe("");
  });
});
