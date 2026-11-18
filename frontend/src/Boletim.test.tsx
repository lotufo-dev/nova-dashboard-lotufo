import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AceiteDiferenca, FormBoletim, PassoBoletim } from "./Boletim";
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

describe("confirmação do boletim com o par (issue #625)", () => {
  afterEach(() => { cleanup(); apiForm.mockReset(); });
  const LIDA = { lido: true, fonte: "texto", avisos: [], campos: { numero_orgao: "7", data: "2026-08-10", valor_centavos: 1200001 } };

  async function registrar(m: Medicao, resposta: unknown) {
    apiForm.mockImplementation(async (url: string) => url.endsWith("/leitura") ? LIDA : resposta);
    let feito: string | undefined;
    const agir = vi.fn(async (fn: () => Promise<unknown>, msg?: string | ((r: unknown) => string)) => {
      const r = await fn(); feito = typeof msg === "function" ? msg(r) : msg; return true;
    });
    render(<FormBoletim m={m} salvando={false} agir={agir} aoFechar={() => {}} />);
    fireEvent.drop(screen.getByTestId("soltar-boletim"), { dataTransfer: { files: [PDF] } });
    await waitFor(() => expect(campo(/Nº no órgão/).value).toBe("7"));
    fireEvent.click(screen.getByRole("button", { name: "Aceitar e registrar o boletim" }));
    await waitFor(() => expect(agir).toHaveBeenCalled());
    await waitFor(() => expect(feito).toBeDefined());
    return feito;
  }

  it("registrado também no reajuste: nomeia o par e o valor", async () => {
    expect(await registrar(M, { id: 1, par: { medicao_id: 6, tipo: "reajuste", numero: 7, aprovado_centavos: 9586401 } }))
      .toBe("Boletim registrado na 7ª medição e no reajuste (R$ 95.864,01).");
  });

  it("registrado no reajuste e também na medição", async () => {
    expect(await registrar({ ...M, tipo: "reajuste" } as Medicao,
      { id: 1, par: { medicao_id: 4, tipo: "execucao", numero: 7, aprovado_centavos: 151140495 } }))
      .toBe("Boletim registrado no reajuste e na medição (R$ 1.511.404,95).");
  });

  it("par de fora: o motivo numa linha", async () => {
    expect(await registrar(M, { id: 1, par: { motivo: "Reajuste nº 7 sem boletim: registre o envio da planilha/carta antes do boletim do órgão" } }))
      .toBe("Boletim registrado. Reajuste nº 7 sem boletim: registre o envio da planilha/carta antes do boletim do órgão.");
  });

  it("sem par: a confirmação de sempre", async () => {
    expect(await registrar(M, { id: 1, par: null })).toBe("Boletim registrado.");
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
    // #722: a justificativa obrigatoria fica na caixa propria (CaixaJustificativa)
    expect(screen.getByLabelText("Justificativa").closest(".justificativa")).not.toBeNull();
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
    fireEvent.click(screen.getByRole("button", { name: "Aceitar a diferença" }));
    // a janela lista o que a capa diverge, que o aceite leva junto
    expect(screen.getByRole("list", { name: "Divergências da capa do SMO aceitas junto" }).textContent)
      .toBe("Fim da execução: capa do SMO diz 31/03/2028, cadastro diz 31/12/2027");
    rerender(<AceiteDiferenca m={{ ...COM_BOLETIM, valor_atestado_centavos: 1234567, capa_divergencias: [] }}
      podeEditar salvando={false} agir={agirReal()} />);
    expect(container.textContent).toBe("");
  });
});

describe("boletim da MT-PAR (issue #753)", () => {
  afterEach(() => { cleanup(); apiForm.mockReset(); });
  const MT = { ...M, estado: "prevista", boletim_modelo: "mtpar" } as Medicao;

  function soltar(leitura: unknown, m: Medicao = MT) {
    apiForm.mockImplementation(async (url: string) => url.endsWith("/leitura") ? leitura : { id: 1, par: null });
    const agir = vi.fn(async (fn: () => Promise<unknown>) => { await fn(); return true; });
    render(<FormBoletim m={m} salvando={false} agir={agir} aoFechar={() => {}} />);
    fireEvent.drop(screen.getByTestId("soltar-boletim"), { dataTransfer: { files: [PDF] } });
    return agir;
  }

  it("as duas leituras batem: nº, data e valor vêm lidos do boletim, sem o meio do SMO", async () => {
    soltar({ modelo: "mtpar", lido: true, fonte: "texto", avisos: [], recusa: null,
      campos: { numero_orgao: "7", data: "2026-08-01", valor_centavos: 12345679 },
      leituras: [{ fonte: "Visto", valor_centavos: 12345679 }, { fonte: "Controle financeiro", valor_centavos: 12345679 }] });
    await waitFor(() => expect(campo(/Valor aprovado/).value).toBe("123.456,79"));
    expect(screen.getAllByText("Lido do boletim")).toHaveLength(3);
    expect(screen.queryByText("Lido da capa")).toBeNull();
    expect((screen.getByLabelText("Meio") as HTMLSelectElement).value).toBe("");
    // com o valor proposto, as duas leituras não se repetem na tela
    expect(screen.queryByLabelText("Leituras do valor")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Aceitar e registrar o boletim" }));
    await waitFor(() => expect(enviado()).toBeTruthy());
    expect([enviado()!.get("numero_orgao"), enviado()!.get("data"), enviado()!.get("valor"), enviado()!.get("meio")])
      .toEqual(["7", "2026-08-01", "123.456,79", null]);
  });

  it("o valor não veio proposto: as duas leituras aparecem para conferir e a pessoa digita", async () => {
    const agir = soltar({ modelo: "mtpar", lido: true, fonte: "texto", recusa: null,
      avisos: ["O valor não saiu ao lado do rótulo no boletim: confira no PDF e digite o valor aprovado"],
      campos: { numero_orgao: "7", data: "2026-08-01" },
      leituras: [{ fonte: "Visto", valor_centavos: null }, { fonte: "Controle financeiro", valor_centavos: 12345679 }] });
    const quadro = await screen.findByLabelText("Leituras do valor");
    expect(quadro.textContent).toBe("Visto—Controle financeiroR$\u00a0123.456,79");
    expect(screen.getByText(/O valor não saiu ao lado do rótulo/)).toBeTruthy();
    expect(campo(/Valor aprovado/).value).toBe("");
    fireEvent.click(screen.getByRole("button", { name: "Aceitar e registrar o boletim" }));
    expect(screen.getByText("Informe o valor aprovado.")).toBeTruthy();
    expect(agir).not.toHaveBeenCalled();
    fireEvent.change(campo(/Valor aprovado/), { target: { value: "123.456,79" } });
    fireEvent.click(screen.getByRole("button", { name: "Aceitar e registrar o boletim" }));
    await waitFor(() => expect(enviado()!.get("valor")).toBe("123.456,79"));
  });

  it("leituras que não batem: as duas quantias na tela", async () => {
    soltar({ modelo: "mtpar", lido: true, fonte: "texto", recusa: null,
      avisos: ["As duas leituras do valor não batem: confira no PDF e digite o valor aprovado"],
      campos: { numero_orgao: "7", data: "2026-08-01" },
      leituras: [{ fonte: "Visto", valor_centavos: 12345679 }, { fonte: "Controle financeiro", valor_centavos: 12345678 }] });
    const quadro = await screen.findByLabelText("Leituras do valor");
    expect(quadro.textContent).toContain("123.456,79");
    expect(quadro.textContent).toContain("123.456,78");
  });

  it("leitura só do controle financeiro: \"Usar este valor\" preenche o campo, sem virar valor lido", async () => {
    const agir = soltar({ modelo: "mtpar", lido: true, fonte: "texto", recusa: null,
      avisos: ["O valor não saiu ao lado do rótulo no boletim: confira no PDF e digite o valor aprovado"],
      campos: { numero_orgao: "7", data: "2026-08-01" },
      leituras: [{ fonte: "Visto", valor_centavos: null, pode_usar: false },
        { fonte: "Controle financeiro", valor_centavos: 12345679, pode_usar: true }] });
    const quadro = await screen.findByLabelText("Leituras do valor");
    expect(campo(/Valor aprovado/).value).toBe("");
    // um botão só, ao lado da leitura do controle financeiro
    expect(screen.getAllByRole("button", { name: "Usar este valor" })).toHaveLength(1);
    expect(quadro.textContent).toBe("Visto—Controle financeiroR$\u00a0123.456,79 Usar este valor");
    fireEvent.click(screen.getByRole("button", { name: "Usar este valor" }));
    expect(campo(/Valor aprovado/).value).toBe("123.456,79");
    // o valor entrou como digitado: só o nº e a data levam o selo de lido, e nenhum aviso de valor diferente
    expect(screen.getAllByText("Lido do boletim")).toHaveLength(2);
    expect(screen.queryByText(/o formulário diz/)).toBeNull();
    // usado, o botão sai; a leitura continua na tela
    expect(screen.queryByRole("button", { name: "Usar este valor" })).toBeNull();
    expect(screen.getByLabelText("Leituras do valor").textContent).toContain("123.456,79");
    expect(agir).not.toHaveBeenCalled();                    // o clique não registra
    fireEvent.click(screen.getByRole("button", { name: "Aceitar e registrar o boletim" }));
    await waitFor(() => expect(enviado()!.get("valor")).toBe("123.456,79"));
  });

  it("o valor que entrou por \"Usar este valor\" sai quando outro PDF é escolhido; o digitado fica", async () => {
    const leitura = { modelo: "mtpar", lido: true, fonte: "texto", recusa: null, avisos: [],
      campos: { numero_orgao: "7", data: "2026-08-01" },
      leituras: [{ fonte: "Visto", valor_centavos: null, pode_usar: false },
        { fonte: "Controle financeiro", valor_centavos: 12345679, pode_usar: true }] };
    soltar(leitura);
    fireEvent.click(await screen.findByRole("button", { name: "Usar este valor" }));
    expect(campo(/Valor aprovado/).value).toBe("123.456,79");
    apiForm.mockImplementation(async () => ({ modelo: "mtpar", lido: false, fonte: null, avisos: [], campos: {}, leituras: [],
      recusa: "Este boletim é da 6ª medição, e esta é a 7ª: escolha o PDF da 7ª medição" }));
    fireEvent.drop(screen.getByTestId("soltar-boletim"), { dataTransfer: { files: [PDF] } });
    await screen.findByRole("alert");
    expect(campo(/Valor aprovado/).value).toBe("");
    // o valor que a pessoa digitou depois de usar a leitura é dela: fica
    apiForm.mockImplementation(async () => leitura);
    fireEvent.drop(screen.getByTestId("soltar-boletim"), { dataTransfer: { files: [PDF] } });
    fireEvent.click(await screen.findByRole("button", { name: "Usar este valor" }));
    fireEvent.change(campo(/Valor aprovado/), { target: { value: "123.456,80" } });
    fireEvent.drop(screen.getByTestId("soltar-boletim"), { dataTransfer: { files: [PDF] } });
    await waitFor(() => expect(apiForm).toHaveBeenCalledTimes(4));
    expect(campo(/Valor aprovado/).value).toBe("123.456,80");
  });

  it("sem `pode_usar` não há botão: leituras que divergem e linha do quadro não lida", async () => {
    soltar({ modelo: "mtpar", lido: true, fonte: "texto", recusa: null,
      avisos: ["As duas leituras do valor não batem: confira no PDF e digite o valor aprovado"],
      campos: { numero_orgao: "7", data: "2026-08-01" },
      leituras: [{ fonte: "Visto", valor_centavos: 12345679, pode_usar: false },
        { fonte: "Controle financeiro", valor_centavos: 12345678, pode_usar: false }] });
    await screen.findByLabelText("Leituras do valor");
    expect(screen.queryByRole("button", { name: "Usar este valor" })).toBeNull();
    cleanup();
    soltar({ modelo: "mtpar", lido: true, fonte: "texto", recusa: null,
      avisos: ["A linha da medição não foi lida no controle financeiro: confira no PDF e digite o valor aprovado"],
      campos: { numero_orgao: "7", data: "2026-08-01" },
      leituras: [{ fonte: "Visto", valor_centavos: 12345679, pode_usar: false },
        { fonte: "Controle financeiro", valor_centavos: null, pode_usar: false }] });
    await screen.findByLabelText("Leituras do valor");
    expect(screen.queryByRole("button", { name: "Usar este valor" })).toBeNull();
  });

  it("valor digitado diferente da leitura: avisa com os dois valores e deixa registrar", async () => {
    const agir = soltar({ modelo: "mtpar", lido: true, fonte: "texto", recusa: null,
      avisos: ["O valor não saiu ao lado do rótulo no boletim: confira no PDF e digite o valor aprovado"],
      campos: { numero_orgao: "7", data: "2026-08-01" },
      leituras: [{ fonte: "Visto", valor_centavos: null, pode_usar: false },
        { fonte: "Controle financeiro", valor_centavos: 12345679, pode_usar: true }] });
    await screen.findByLabelText("Leituras do valor");
    expect(screen.queryByText(/o formulário diz/)).toBeNull();          // campo vazio: nada a comparar
    fireEvent.change(campo(/Valor aprovado/), { target: { value: "123.456,80" } });      // um centavo acima
    expect(screen.getByText(/o formulário diz/).textContent)
      .toBe("Atenção: Valor aprovado: o formulário diz R$\u00a0123.456,80, o boletim diz R$\u00a0123.456,79 no controle financeiro.");
    fireEvent.click(screen.getByRole("button", { name: "Aceitar e registrar o boletim" }));
    await waitFor(() => expect(enviado()!.get("valor")).toBe("123.456,80"));
    expect(agir).toHaveBeenCalledTimes(1);
    // digitado o valor lido, o aviso some
    fireEvent.change(campo(/Valor aprovado/), { target: { value: "123.456,79" } });
    expect(screen.queryByText(/o formulário diz/)).toBeNull();
  });

  it("valor proposto e trocado pela pessoa: o aviso diz o que as duas leituras trazem", async () => {
    soltar({ modelo: "mtpar", lido: true, fonte: "texto", avisos: [], recusa: null,
      campos: { numero_orgao: "7", data: "2026-08-01", valor_centavos: 12345679 },
      leituras: [{ fonte: "Visto", valor_centavos: 12345679, pode_usar: false },
        { fonte: "Controle financeiro", valor_centavos: 12345679, pode_usar: false }] });
    await waitFor(() => expect(campo(/Valor aprovado/).value).toBe("123.456,79"));
    expect(screen.queryByText(/o formulário diz/)).toBeNull();
    fireEvent.change(campo(/Valor aprovado/), { target: { value: "100.000,01" } });
    expect(screen.getByText(/o formulário diz/).textContent)
      .toBe("Atenção: Valor aprovado: o formulário diz R$\u00a0100.000,01, o boletim diz R$\u00a0123.456,79 no Visto e no controle financeiro.");
    expect(screen.queryByLabelText("Leituras do valor")).toBeNull();    // o quadro das leituras continua fora
    expect(screen.queryByRole("button", { name: "Usar este valor" })).toBeNull();
  });

  it("leituras que divergem: o aviso diz a que não é a do campo", async () => {
    soltar({ modelo: "mtpar", lido: true, fonte: "texto", recusa: null,
      avisos: ["As duas leituras do valor não batem: confira no PDF e digite o valor aprovado"],
      campos: { numero_orgao: "7", data: "2026-08-01" },
      leituras: [{ fonte: "Total do reajuste", valor_centavos: 1234567, pode_usar: false },
        { fonte: "Controle financeiro", valor_centavos: 1234566, pode_usar: false }] });
    await screen.findByLabelText("Leituras do valor");
    fireEvent.change(campo(/Valor aprovado/), { target: { value: "12.345,67" } });
    expect(screen.getByText(/o formulário diz/).textContent)
      .toBe("Atenção: Valor aprovado: o formulário diz R$\u00a012.345,67, o boletim diz R$\u00a012.345,66 no controle financeiro.");
    fireEvent.change(campo(/Valor aprovado/), { target: { value: "1,00" } });
    expect(screen.getByText(/o formulário diz/).textContent)
      .toBe("Atenção: Valor aprovado: o formulário diz R$\u00a01,00, o boletim diz R$\u00a012.345,67 no total do reajuste e R$\u00a012.345,66 no controle financeiro.");
  });

  it("boletim de outra obra pelo contrato da capa: a recusa por extenso, sem leituras nem botão", async () => {
    soltar({ modelo: "mtpar", lido: false, fonte: null, avisos: [], campos: {}, leituras: [],
      recusa: "Este boletim é de outra obra: traz o contrato 12/2023, e o desta obra é o 45/2025" });
    expect((await screen.findByRole("alert")).textContent).toBe("Este boletim é de outra obra: traz o contrato 12/2023, e o desta obra é o 45/2025");
    expect(screen.queryByText("boletim.pdf")).toBeNull();
    expect(screen.queryByLabelText("Leituras do valor")).toBeNull();
    expect(screen.queryByRole("button", { name: "Usar este valor" })).toBeNull();
  });

  it("boletim de outra medição: a recusa do servidor por extenso, e o PDF sai do formulário", async () => {
    const agir = soltar({ modelo: "mtpar", lido: false, fonte: null, avisos: [], campos: {}, leituras: [],
      recusa: "Este boletim é da 6ª medição, e esta é a 7ª: escolha o PDF da 7ª medição" });
    expect((await screen.findByRole("alert")).textContent).toBe("Este boletim é da 6ª medição, e esta é a 7ª: escolha o PDF da 7ª medição");
    expect(screen.queryByText("boletim.pdf")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Registrar boletim" }));
    expect(screen.getByText("Arraste ou escolha o PDF do boletim.")).toBeTruthy();
    expect(agir).not.toHaveBeenCalled();
  });

  it("o passo mostra um cartão por medição: o boletim anexado com o PDF, e o formulário na que falta", () => {
    const execucao = { ...MT, estado: "boletim_recebido", valor_atestado_centavos: 12345679, atestado_em: "2026-08-01",
      boletins: [{ id: 9, tem_arquivo: true, valor_centavos: 12345679, atestado_em: "2026-08-01" }] } as Medicao;
    const reajuste = { ...MT, id: 6, tipo: "reajuste", valor_protocolado_centavos: null, boletins: [] } as Medicao;
    render(<PassoBoletim ms={[execucao, reajuste]} podeEditar salvando={false} agir={vi.fn()} />);
    const daMedicao = screen.getByRole("region", { name: "Boletim · 7ª Medição" });
    expect(daMedicao.textContent).toContain("Anexado");
    expect(screen.getByLabelText("Boletim anexado: 7ª Medição").textContent).toContain("123.456,79");
    expect(screen.getByLabelText("Boletim anexado: 7ª Medição").textContent).toContain("01/08/2026");
    expect(screen.getByRole("link", { name: "Abrir o PDF" }).getAttribute("href")).toBe("/api/medicoes/5/boletins/9");
    // o reajuste tem o PDF próprio: o formulário já abre nele, que é a que falta
    const doReajuste = screen.getByRole("region", { name: "Boletim · Reajuste da 7ª Medição" });
    expect(doReajuste.textContent).toContain("Não anexado");
    expect(doReajuste.querySelector("form[aria-label='Registrar boletim']")).not.toBeNull();
    // o título do formulário diz de quem é o boletim: no cartão do reajuste, do reajuste
    expect(doReajuste.querySelector("form .painel__titulo")!.textContent).toBe("Registrar o boletim do reajuste da 7ª medição");
    expect(daMedicao.querySelector("form")).toBeNull();
    // um formulário por vez: abrir o da medição (boletim novo) fecha o do reajuste
    fireEvent.click(screen.getByRole("button", { name: "Registrar boletim novo" }));
    expect(daMedicao.querySelector("form[aria-label='Registrar boletim']")).not.toBeNull();
    expect(daMedicao.querySelector("form .painel__titulo")!.textContent).toBe("Registrar o boletim da 7ª medição");
    expect(doReajuste.querySelector("form")).toBeNull();
    expect(screen.getByRole("button", { name: "Anexar o boletim" })).toBeTruthy();
  });

  it("quem só consulta vê a situação do boletim, sem formulário nem botão", () => {
    render(<PassoBoletim ms={[{ ...MT, boletins: [] } as Medicao]} podeEditar={false} salvando={false} agir={vi.fn()} />);
    expect(screen.getByRole("region", { name: "Boletim" }).textContent).toBe("BoletimNão anexado");
    expect(screen.queryByRole("button")).toBeNull();
  });
});
