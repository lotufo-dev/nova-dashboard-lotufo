import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Notas } from "./Notas";

const { api, apiForm } = vi.hoisted(() => ({ api: vi.fn(), apiForm: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api, apiForm }));

const medicao = { id: 1, numero: 27, tipo: "execucao", competencia: "2026-08", estado: "espelho_enviado" } as any;

const DADOS = {
  esperadas: [
    { chave: "medicao", natureza: "medicao", emissor: "lotufo", municipio: "Cuiabá", valor: 71919072,
      iss: 1438381, inss: 3164439, irrf: 863029, ibs: null, cbs: null, liquido: 66352723, nota_id: null },
  ],
  notas: [],
  faltam: 1,
  pode_declarar: true,
};

describe("Notas", () => {
  afterEach(() => { cleanup(); api.mockReset(); apiForm.mockReset(); });

  it("mostra a nota esperada e a falta, sem lista de NFs do RM", async () => {
    api.mockResolvedValueOnce(DADOS);
    render(<Notas medicao={medicao} podeEditar aoMudar={() => {}} />);
    await waitFor(() => expect(screen.getByText(/Cuiabá/)).toBeTruthy());
    expect(screen.getAllByText(/719\.190,72/).length).toBeGreaterThan(0);
    expect(screen.getByText("Falta 1 nota")).toBeTruthy();
    // sem nota ainda: a celula fica com o tracinho, sem "aguardando"
    expect(screen.queryByText("aguardando")).toBeNull();
    expect(screen.queryByText(/Vincular nota do RM/)).toBeNull();
    // sem nota vinculada, declarar completas nao aparece
    expect(screen.queryByRole("button", { name: /Declarar completas/ })).toBeNull();
  });

  it("gravar a justificativa muda o rótulo e desabilita o botão enquanto a chamada roda", async () => {
    api.mockResolvedValueOnce({
      ...DADOS, faltam: 0,
      esperadas: [{ ...DADOS.esperadas[0], nota_id: 5 }],
      notas: [{ nota_id: 5, coligada: 1, numero: "2288", serie: null, emissao: "2026-09-14", valor_centavos: 71919072,
                valor_pdf_centavos: 71919072, origem_nota: "pdf", confirmacao: "aguardando_rm", documento_id: 3,
                conferencia: [{ campo: "iss", espelho: 1438381, nota: 1438581, grau: "divergente" }],
                justificativa: null, leitura: "cuiaba", municipio: "Cuiabá", regra: "pdf", recebido_centavos: 0 }],
      pode_declarar: false,
    });
    render(<Notas medicao={{ ...medicao, estado: "nota_emitida" }} podeEditar aoMudar={() => {}} />);
    await waitFor(() => expect(screen.getByText(/nº 2288/)).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Justificar" }));
    fireEvent.change(screen.getByLabelText(/Justificativa da divergência/), { target: { value: "Arredondamento do município" } });
    api.mockReturnValueOnce(new Promise(() => {}));   // a chamada nunca termina
    fireEvent.click(screen.getByRole("button", { name: "Gravar justificativa" }));
    const botao = await screen.findByRole("button", { name: "Gravando…" }) as HTMLButtonElement;
    expect(botao.disabled).toBe(true);
  });

  it("a tabela de notas é densa: cabe a 1024 px sem rolar (B-04, 10/10/2026)", async () => {
    api.mockResolvedValueOnce(DADOS);
    render(<Notas medicao={medicao} podeEditar aoMudar={() => {}} />);
    await waitFor(() => expect(screen.getByText(/Cuiabá/)).toBeTruthy());
    expect(screen.getByRole("table").className).toContain("tabela--densa");
  });

  it("nota vinculada e divergente mostra a diferenca e o botao de justificar", async () => {
    api.mockResolvedValueOnce({
      ...DADOS, faltam: 0,
      esperadas: [{ ...DADOS.esperadas[0], nota_id: 5 }],
      notas: [{ nota_id: 5, coligada: 1, numero: "2288", serie: null, emissao: "2026-09-14", valor_centavos: 71919072,
                valor_pdf_centavos: 71919072, origem_nota: "pdf", confirmacao: "aguardando_rm", documento_id: 3,
                conferencia: [{ campo: "iss", espelho: 1438381, nota: 1438581, grau: "divergente" }],
                justificativa: null, leitura: "cuiaba", municipio: "Cuiabá", regra: "pdf", recebido_centavos: 0 }],
      pode_declarar: false,
    });
    render(<Notas medicao={{ ...medicao, estado: "nota_emitida" }} podeEditar aoMudar={() => {}} />);
    await waitFor(() => expect(screen.getByText(/nº 2288/)).toBeTruthy());
    expect(screen.getByText("aguardando o RM")).toBeTruthy();
    expect(screen.getByText(/diverge do espelho: ISS/)).toBeTruthy();
    // notas completas: nenhum selo de falta nem frase de contagem
    expect(screen.queryByText(/notas completas|Falta|Faltam/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Justificar" }));
    expect(screen.getByLabelText(/Justificativa da divergência/)).toBeTruthy();
  });

  it("destaca só a célula do campo que diverge, com o valor lido na nota (G3-11)", async () => {
    api.mockResolvedValueOnce({
      ...DADOS, faltam: 0,
      esperadas: [{ ...DADOS.esperadas[0], nota_id: 5 }],
      notas: [{ nota_id: 5, coligada: 1, numero: "2288", serie: null, emissao: "2026-09-14", valor_centavos: 71919072,
                valor_pdf_centavos: 71919072, origem_nota: "pdf", confirmacao: "aguardando_rm", documento_id: 3,
                conferencia: [{ campo: "iss", espelho: 1438381, nota: 1438581, grau: "divergente" },
                              { campo: "irrf", espelho: 863029, nota: 863030, grau: "arredondamento" }],
                justificativa: null, leitura: "cuiaba", municipio: "Cuiabá", regra: "pdf", recebido_centavos: 0 }],
      pode_declarar: false,
    });
    render(<Notas medicao={{ ...medicao, estado: "nota_emitida" }} podeEditar aoMudar={() => {}} />);
    await waitFor(() => expect(screen.getByText(/nº 2288/)).toBeTruthy());
    const linha = screen.getByRole("table").querySelector("tbody tr")!;
    const destacadas = Array.from(linha.querySelectorAll("td.notas__celula--diverge"));
    expect(destacadas).toHaveLength(1);
    expect(destacadas[0].textContent).toContain("14.383,81");
    expect(destacadas[0].textContent).toMatch(/na nota.*14\.385,81/);
    expect(linha.querySelector(".notas__celula--diverge:not(td)")).toBeNull();     // municipio confere
    // o arredondamento de 1 centavo nao vira frase
    expect(screen.queryByText(/arredondamento de 1 centavo/)).toBeNull();
  });

  it("líquido divergente destaca a célula do Líquido e diz o nome do campo (revisão da PR #97)", async () => {
    api.mockResolvedValueOnce({
      ...DADOS, faltam: 0,
      esperadas: [{ ...DADOS.esperadas[0], nota_id: 5 }],
      notas: [{ nota_id: 5, coligada: 1, numero: "2288", serie: null, emissao: "2026-09-14", valor_centavos: 71919072,
                valor_pdf_centavos: 71919072, origem_nota: "pdf", confirmacao: "aguardando_rm", documento_id: 3,
                conferencia: [{ campo: "liquido", espelho: 66352723, nota: 66357723, grau: "divergente" }],
                justificativa: null, leitura: "cuiaba", municipio: "Cuiabá", regra: "pdf", recebido_centavos: 0 }],
      pode_declarar: false,
    });
    render(<Notas medicao={{ ...medicao, estado: "nota_emitida" }} podeEditar aoMudar={() => {}} />);
    await waitFor(() => expect(screen.getByText(/nº 2288/)).toBeTruthy());
    const destacadas = Array.from(screen.getByRole("table").querySelectorAll("td.notas__celula--diverge"));
    expect(destacadas).toHaveLength(1);
    expect(destacadas[0].textContent).toMatch(/663\.527,23 no espelho; na nota .*663\.577,23/);
    expect(screen.getByText(/diverge do espelho: líquido/)).toBeTruthy();
  });

  it("conferência antiga que hoje bate com o espelho (versão nova) não destaca dois valores iguais", async () => {
    api.mockResolvedValueOnce({
      ...DADOS, faltam: 0,
      esperadas: [{ ...DADOS.esperadas[0], iss: 1438581, nota_id: 5 }],     // espelho novo: ISS igual ao da nota
      notas: [{ nota_id: 5, coligada: 1, numero: "2288", serie: null, emissao: "2026-09-14", valor_centavos: 71919072,
                valor_pdf_centavos: 71919072, origem_nota: "pdf", confirmacao: "aguardando_rm", documento_id: 3,
                conferencia: [{ campo: "iss", espelho: 1438381, nota: 1438581, grau: "divergente" }],
                justificativa: null, leitura: "cuiaba", municipio: "Cuiabá", regra: "pdf", recebido_centavos: 0 }],
      pode_declarar: false,
    });
    render(<Notas medicao={{ ...medicao, estado: "nota_emitida" }} podeEditar aoMudar={() => {}} />);
    await waitFor(() => expect(screen.getByText(/nº 2288/)).toBeTruthy());
    expect(screen.getByRole("table").querySelectorAll(".notas__celula--diverge")).toHaveLength(0);
  });

  it("município divergente destaca o município da saída, não os valores", async () => {
    api.mockResolvedValueOnce({
      ...DADOS, faltam: 0,
      esperadas: [{ ...DADOS.esperadas[0], nota_id: 5 }],
      notas: [{ nota_id: 5, coligada: 1, numero: "2288", serie: null, emissao: "2026-09-14", valor_centavos: 71919072,
                valor_pdf_centavos: 71919072, origem_nota: "pdf", confirmacao: "aguardando_rm", documento_id: 3,
                conferencia: [{ campo: "municipio", espelho: "Cuiabá", nota: "Várzea Grande", grau: "divergente" }],
                justificativa: null, leitura: "cuiaba", municipio: "Várzea Grande", regra: "pdf", recebido_centavos: 0 }],
      pode_declarar: false,
    });
    render(<Notas medicao={{ ...medicao, estado: "nota_emitida" }} podeEditar aoMudar={() => {}} />);
    await waitFor(() => expect(screen.getByText(/nº 2288/)).toBeTruthy());
    const linha = screen.getByRole("table").querySelector("tbody tr")!;
    expect(linha.querySelectorAll("td.notas__celula--diverge")).toHaveLength(0);
    const municipio = linha.querySelector("span.notas__celula--diverge")!;
    expect(municipio.textContent).toMatch(/^Cuiabá no espelho; na nota Várzea Grande$/);
  });
});

describe("Notas: só o botão da ação em curso troca o rótulo", () => {
  afterEach(() => { cleanup(); api.mockReset(); apiForm.mockReset(); });

  const COM_DIVERGENCIA = {
    ...DADOS, faltam: 1, pode_declarar: true,
    esperadas: [{ ...DADOS.esperadas[0], nota_id: 5 }],
    notas: [{ nota_id: 5, coligada: 1, numero: "2288", serie: null, emissao: "2026-09-14", valor_centavos: 71919072,
              valor_pdf_centavos: 71919072, origem_nota: "pdf", confirmacao: "aguardando_rm", documento_id: 3,
              conferencia: [{ campo: "iss", espelho: 1438381, nota: 1438581, grau: "divergente" }],
              justificativa: null, leitura: "cuiaba", municipio: "Cuiabá", regra: "pdf", recebido_centavos: 0 }],
  };

  async function abrir() {
    api.mockImplementation((_url: string, opts?: { method?: string }) =>
      opts?.method === "POST" ? new Promise(() => {}) : Promise.resolve(COM_DIVERGENCIA));
    render(<Notas medicao={{ ...medicao, estado: "nota_emitida" }} podeEditar aoMudar={() => {}} />);
    await waitFor(() => expect(screen.getByText(/diverge do espelho: ISS/)).toBeTruthy());
  }

  it("justificativa em curso: 'Declarar completas' fica desabilitado mas mantém o rótulo", async () => {
    await abrir();
    fireEvent.click(screen.getByRole("button", { name: "Justificar" }));
    fireEvent.change(screen.getByLabelText(/Justificativa da divergência/), { target: { value: "Arredondamento" } });
    fireEvent.click(screen.getByRole("button", { name: "Gravar justificativa" }));
    await screen.findByRole("button", { name: "Gravando…" });
    const vizinho = screen.getByRole("button", { name: "Declarar completas" }) as HTMLButtonElement;
    expect(vizinho.disabled).toBe(true);
  });

  it("declaração em curso: 'Declarar completas' vira 'Gravando…' e desabilita", async () => {
    await abrir();
    fireEvent.change(screen.getByLabelText(/Declarar as notas completas/), { target: { value: "Sem serviço no mês" } });
    fireEvent.click(screen.getByRole("button", { name: "Declarar completas" }));
    const botao = await screen.findByRole("button", { name: "Gravando…" }) as HTMLButtonElement;
    expect(botao.disabled).toBe(true);
  });

  it("registro manual em curso: 'Registrar nota' vira 'Registrando…' e 'Declarar completas' mantém o rótulo", async () => {
    apiForm.mockResolvedValue({ documento_id: 9, repetido: false, nota_id: null, conferencia: [], faltam: 1,
      estado: "espelho_enviado", leitura: { ok: false, motivo: "ilegível" } });
    await abrir();
    const arquivo = new File(["x"], "nota.pdf", { type: "application/pdf" });
    fireEvent.change(screen.getByLabelText(/Anexar notas à medição/), { target: { files: [arquivo] } });
    await screen.findByRole("button", { name: "Registrar nota" });
    fireEvent.change(screen.getByLabelText("Número da nota"), { target: { value: "2290" } });
    fireEvent.change(screen.getByLabelText("Emissão"), { target: { value: "2026-09-14" } });
    fireEvent.change(screen.getByLabelText(/^Valor/), { target: { value: "719190,72" } });
    fireEvent.click(screen.getByRole("button", { name: "Registrar nota" }));
    const botao = await screen.findByRole("button", { name: "Registrando…" }) as HTMLButtonElement;
    expect(botao.disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Declarar completas" }) as HTMLButtonElement).disabled).toBe(true);
  });

  // issue #188: na pagina da medicao, a execucao e o reajuste em dois blocos; cada um anexa na sua medicao
  it("dois blocos: o título e o anexo de cada um vão para a medição do bloco", async () => {
    api.mockImplementation(async (url: string) => url === "/api/medicoes/1/notas" ? DADOS : { ...DADOS, faltam: 2,
      esperadas: [DADOS.esperadas[0], { ...DADOS.esperadas[0], chave: "reajuste-2", municipio: "Várzea Grande" }] });
    apiForm.mockResolvedValue({ documento_id: 9, repetido: false, nota_id: 4, conferencia: [], faltam: 1,
      estado: "espelho_enviado", leitura: { ok: true, motivo: null, leiaute: "cuiaba", numero: 2301 } });
    const reajuste = { ...medicao, id: 2, tipo: "reajuste" };
    render(<>
      <Notas medicao={medicao} rotulo="Execução · 27ª Medição" podeEditar aoMudar={() => {}} />
      <Notas medicao={reajuste} rotulo="Reajuste da 27ª Medição" podeEditar aoMudar={() => {}} />
    </>);
    expect(await screen.findByText("Falta 1 nota")).toBeTruthy();
    expect(await screen.findByText("Faltam 2 notas")).toBeTruthy();
    const arquivo = new File(["x"], "nota.pdf", { type: "application/pdf" });
    fireEvent.change(screen.getByLabelText("Anexar notas: Reajuste da 27ª Medição"), { target: { files: [arquivo] } });
    await waitFor(() => expect(apiForm).toHaveBeenCalledWith("/api/medicoes/2/notas", expect.any(FormData)));
    expect(apiForm).toHaveBeenCalledTimes(1);
  });
});

// issue #190: o valor da nota manual se digita como em caixa registradora e vai ao servidor no mesmo formato
describe("Notas: valor da nota manual (CampoValor)", () => {
  afterEach(() => { cleanup(); api.mockReset(); apiForm.mockReset(); });

  it("digitar 5000000 manda \"50.000,00\", como antes", async () => {
    apiForm.mockResolvedValue({ documento_id: 9, repetido: false, nota_id: null, conferencia: [], faltam: 1,
      estado: "espelho_enviado", leitura: { ok: false, motivo: "ilegível" } });
    api.mockImplementation((_url: string, opts?: { method?: string }) =>
      opts?.method === "POST" ? new Promise(() => {}) : Promise.resolve(DADOS));
    render(<Notas medicao={medicao} podeEditar aoMudar={() => {}} />);
    await waitFor(() => expect(screen.getByText(/Cuiabá/)).toBeTruthy());
    const arquivo = new File(["x"], "nota.pdf", { type: "application/pdf" });
    fireEvent.change(screen.getByLabelText(/Anexar notas à medição/), { target: { files: [arquivo] } });
    await screen.findByRole("button", { name: "Registrar nota" });
    fireEvent.change(screen.getByLabelText("Número da nota"), { target: { value: "2290" } });
    fireEvent.change(screen.getByLabelText("Emissão"), { target: { value: "2026-09-14" } });
    const valor = screen.getByLabelText(/^Valor/) as HTMLInputElement;
    for (const c of "5000000") fireEvent.input(valor, { target: { value: valor.value + c }, inputType: "insertText", data: c });
    expect(valor.value).toBe("50.000,00");
    fireEvent.click(screen.getByRole("button", { name: "Registrar nota" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/medicoes/1/notas/manual", expect.objectContaining({
      method: "POST", body: JSON.stringify({ documento_id: 9, numero: 2290, emissao: "2026-09-14", valor: "50.000,00" }) })));
  });

  // issue #71: so' o admin desfaz o vinculo, e com motivo
  const COM_NOTA = {
    ...DADOS, faltam: 0, pode_declarar: false,
    esperadas: [{ ...DADOS.esperadas[0], nota_id: 5 }],
    notas: [{ alocacao_id: 77, nota_id: 5, coligada: 1, numero: "2288", serie: null, emissao: "2026-09-14",
              valor_centavos: 71919072, valor_pdf_centavos: 71919072, origem_nota: "rm", confirmacao: "so_rm",
              documento_id: null, conferencia: [], justificativa: null, leitura: null, municipio: "Cuiabá",
              regra: "valor_exato", recebido_centavos: 0 }],
  };

  it("sem ser admin, não oferece desfazer o vínculo da nota", async () => {
    api.mockResolvedValueOnce(COM_NOTA);
    render(<Notas medicao={{ ...medicao, estado: "nota_emitida" }} podeEditar aoMudar={() => {}} />);
    await waitFor(() => expect(screen.getByText(/nº 2288/)).toBeTruthy());
    expect(screen.queryByRole("button", { name: /Desfazer vínculo/ })).toBeNull();
    // a nota que confere nao leva "confere" ao lado
    expect(screen.queryByText("confere")).toBeNull();
  });

  it("nota que veio do PDF anexado na medição não oferece desfazer o vínculo (o servidor recusa)", async () => {
    api.mockResolvedValueOnce({ ...COM_NOTA, notas: [{ ...COM_NOTA.notas[0], documento_id: 3, origem_nota: "pdf" }] });
    render(<Notas medicao={{ ...medicao, estado: "nota_emitida" }} podeEditar podeDesfazer aoMudar={() => {}} />);
    await waitFor(() => expect(screen.getByText(/nº 2288/)).toBeTruthy());
    expect(screen.queryByRole("button", { name: /Desfazer vínculo/ })).toBeNull();
  });

  it("o admin desfaz o vínculo informando o motivo", async () => {
    api.mockResolvedValueOnce(COM_NOTA);
    const aoMudar = vi.fn();
    render(<Notas medicao={{ ...medicao, estado: "nota_emitida" }} podeEditar={false} podeDesfazer aoMudar={aoMudar} />);
    fireEvent.click(await screen.findByRole("button", { name: /Desfazer vínculo/ }));
    fireEvent.change(screen.getByLabelText(/Motivo para desfazer o vínculo/), { target: { value: "NF de outra obra" } });
    api.mockResolvedValueOnce({ ok: true, estado: "nota_emitida" });
    api.mockResolvedValueOnce({ ...COM_NOTA, notas: [], faltam: 1, esperadas: DADOS.esperadas });
    fireEvent.click(screen.getByRole("button", { name: "Desfazer o vínculo" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/medicoes/1/notas/alocacoes/77/desfazer", expect.objectContaining({
      method: "POST", body: JSON.stringify({ motivo: "NF de outra obra" }) })));
    await waitFor(() => expect(aoMudar).toHaveBeenCalled());
  });
});
