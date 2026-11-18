import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiErro } from "./api";
import Espelho from "./Espelho";
import { ir } from "./rota";

const { api, apiForm } = vi.hoisted(() => ({ api: vi.fn(), apiForm: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api, apiForm }));

const REGRA = { situacao: "ativa", saidas: 4, entradas: [
  { chave: "medicao", rotulo: "Valor da medição", natureza: "medicao" },
  { chave: "reajuste", rotulo: "Valor do reajuste", natureza: "reajuste" }] };

const saida = (chave: string, natureza: string, municipio: string, valor: number) => ({
  chave, natureza, rotulo: natureza === "medicao" ? "Medição" : "Reajuste", emissor: "lotufo", municipio,
  valor, mo: 1, material: 1, inss: 1, iss: 1, irrf: 1, ibs: null, cbs: null, liquido: valor - 3 });

const PREVIA = { medicoes: [{ tipo: "execucao", valor_centavos: 63452958, existente: null },
                            { tipo: "reajuste", valor_centavos: 3865583, existente: null }], avisos: [],
  saidas: [saida("caceres-medicao", "medicao", "Cáceres", 52843623), saida("porto-medicao", "medicao", "Porto Esperidião", 10609335),
           saida("caceres-reajuste", "reajuste", "Cáceres", 3219258), saida("porto-reajuste", "reajuste", "Porto Esperidião", 646325)] };

const ESPELHO = { id: 7, numero: 10, competencia: "2026-05", versao: 1, situacao: "vigente", criado_em: "2026-09-22 14:00:00",
  entradas: { medicao: 63452958, reajuste: 3865583 },
  criado_por_nome: "Maria", motivo: null, saidas: PREVIA.saidas, medicoes: [{ id: 1, tipo: "execucao", estado: "espelho_gerado" }],
  arquivos: [{ documento_id: 3, saida: "caceres-medicao", nome: "ESPELHO - MT-388 - 10ª Medição (05.2026) - Cáceres.docx", tamanho: 29000 }],
  envio: null };

describe("Espelho", () => {
  afterEach(() => { cleanup(); api.mockReset(); apiForm.mockReset(); });

  it("obra sem regra ativa não explica o fluxo antigo nem oferece o botão", async () => {
    api.mockResolvedValueOnce({ regra: null, espelhos: [] });
    render(<Espelho contratoId={1} podeEditar aoMudar={() => {}} />);
    expect(await screen.findByRole("heading", { name: "Nova medição" })).toBeTruthy();
    expect(screen.queryByText(/fluxo antigo/)).toBeNull();
    expect(screen.queryByRole("button", { name: /Gerar espelho/ })).toBeNull();
  });

  it("medição sem regra ativa mostra só \"Nenhum espelho.\"", async () => {
    api.mockResolvedValueOnce({ regra: null, espelhos: [] });
    render(<Espelho contratoId={1} podeEditar aoMudar={() => {}} medicao={{ id: 1, tipo: "execucao" }} parte="espelho" />);
    expect(await screen.findByText("Nenhum espelho.")).toBeTruthy();
    expect(screen.queryByText(/fluxo antigo/)).toBeNull();
  });

  it("quem só consulta não ganha o formulário aberto, mesmo com abrirForm (gate Sol, PR #528)", async () => {
    api.mockResolvedValueOnce({ regra: REGRA, espelhos: [] });
    render(<Espelho contratoId={1} podeEditar={false} aoMudar={() => {}} medicao={{ id: 1, tipo: "execucao" }} parte="espelho" abrirForm />);
    expect(await screen.findByText("Nenhum espelho.")).toBeTruthy();
    expect(screen.queryByLabelText("Nº da medição")).toBeNull();
  });

  it("o formulário só conta como rascunho depois de preenchido (guarda de saída)", async () => {
    const confirmar = vi.spyOn(window, "confirm").mockReturnValue(false);
    window.history.replaceState(null, "", "/obras/1");
    api.mockResolvedValueOnce({ regra: REGRA, espelhos: [] });
    render(<Espelho contratoId={1} podeEditar aoMudar={() => {}} abrirForm />);
    await screen.findByLabelText("Nº da medição");
    ir({ tela: "avisos" });                       // aberto e vazio: sai sem perguntar
    expect(confirmar).not.toHaveBeenCalled();
    window.history.replaceState(null, "", "/obras/1");
    fireEvent.change(screen.getByLabelText("Nº da medição"), { target: { value: "10" } });
    ir({ tela: "avisos" });
    expect(confirmar).toHaveBeenCalledTimes(1);
    expect(window.location.pathname).toBe("/obras/1");
    confirmar.mockRestore();
  });

  it("conferir manda número, competência e valores e renderiza o extrato, com uma coluna por nota", async () => {
    api.mockResolvedValueOnce({ regra: REGRA, espelhos: [] });
    api.mockResolvedValueOnce(PREVIA);
    render(<Espelho contratoId={1} podeEditar aoMudar={() => {}} />);
    fireEvent.click(await screen.findByRole("button", { name: /Gerar espelho/ }));
    fireEvent.change(screen.getByLabelText("Nº da medição"), { target: { value: "10" } });
    fireEvent.change(screen.getByLabelText("Competência"), { target: { value: "052026" } });
    fireEvent.change(screen.getByLabelText("Valor da medição"), { target: { value: "634.529,58" } });
    fireEvent.change(screen.getByLabelText("Valor do reajuste"), { target: { value: "38.655,83" } });
    fireEvent.click(screen.getByRole("button", { name: "Conferir" }));
    await waitFor(() => expect(screen.getAllByText(/528\.436,23/).length).toBeGreaterThan(0));
    expect(api).toHaveBeenLastCalledWith("/api/contratos/1/espelho/previa", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ numero: 10, competencia: "2026-05", entradas: { medicao: "634.529,58", reajuste: "38.655,83" } }) }));
    // #722: a conferencia e' um extrato -- uma coluna por nota e uma linha por valor, com o liquido no rodape
    expect(screen.getAllByRole("columnheader")).toHaveLength(1 + PREVIA.saidas.length);      // "Saída" + as notas
    expect(screen.getAllByRole("rowheader").map(x => x.textContent)).toEqual(["Valor", "Mão de obra", "Material", "INSS", "ISS", "IRRF", "Líquido"]);
    const liquido = screen.getByRole("rowheader", { name: "Líquido" }).closest("tr")!;
    expect(within(liquido).getAllByRole("cell")).toHaveLength(PREVIA.saidas.length);
    expect(liquido.closest("tfoot")).not.toBeNull();
    // as retencoes ficam recuadas sob o valor
    expect(["INSS", "ISS", "IRRF"].map(r => screen.getByRole("rowheader", { name: r }).closest("tr")!.className)).toEqual(Array(3).fill("extrato__retencao"));
    expect(screen.getByRole("button", { name: "Gerar" })).toBeTruthy();
  });

  it("período vem com o mês da competência e só vai ao servidor quando muda", async () => {
    api.mockResolvedValueOnce({ regra: REGRA, espelhos: [] });
    api.mockResolvedValueOnce({ ...PREVIA, periodo: "05/02/2026 A 28/02/2026" });
    render(<Espelho contratoId={1} podeEditar aoMudar={() => {}} />);
    fireEvent.click(await screen.findByRole("button", { name: /Gerar espelho/ }));
    fireEvent.change(screen.getByLabelText("Nº da medição"), { target: { value: "15" } });
    fireEvent.change(screen.getByLabelText("Competência"), { target: { value: "2026-02" } });
    expect((screen.getByLabelText("Período: de") as HTMLInputElement).value).toBe("2026-02-01");
    expect((screen.getByLabelText("até") as HTMLInputElement).value).toBe("2026-02-28");
    fireEvent.change(screen.getByLabelText("Período: de"), { target: { value: "2026-02-05" } });
    fireEvent.change(screen.getByLabelText("Valor da medição"), { target: { value: "100,00" } });
    fireEvent.click(screen.getByRole("button", { name: "Conferir" }));
    expect(await screen.findByText("05/02/2026 A 28/02/2026")).toBeTruthy();
    expect(JSON.parse(api.mock.lastCall![1].body)).toMatchObject({ periodo_inicio: "2026-02-05", periodo_fim: "2026-02-28" });
  });

  // issue #190: valor como em caixa registradora; o que vai ao servidor e' o mesmo texto de antes
  it("digitar 5000000 no valor mostra 50.000,00 e manda \"50.000,00\"; o campo vazio segue vazio (vale zero)", async () => {
    api.mockResolvedValueOnce({ regra: REGRA, espelhos: [] });
    api.mockResolvedValueOnce(PREVIA);
    render(<Espelho contratoId={1} podeEditar aoMudar={() => {}} />);
    fireEvent.click(await screen.findByRole("button", { name: /Gerar espelho/ }));
    fireEvent.change(screen.getByLabelText("Nº da medição"), { target: { value: "10" } });
    fireEvent.change(screen.getByLabelText("Competência"), { target: { value: "2026-05" } });
    const valor = screen.getByLabelText("Valor da medição") as HTMLInputElement;
    for (const c of "5000000") fireEvent.input(valor, { target: { value: valor.value + c }, inputType: "insertText", data: c });
    expect(valor.value).toBe("50.000,00");
    fireEvent.click(screen.getByRole("button", { name: "Conferir" }));
    await screen.findByRole("button", { name: "Gerar" });
    expect(JSON.parse(api.mock.lastCall![1].body).entradas).toEqual({ medicao: "50.000,00", reajuste: "" });
  });

  it("issue #589: o reajuste aceita o “-” e vai negativo; a medição não aceita o sinal", async () => {
    api.mockResolvedValueOnce({ regra: REGRA, espelhos: [] });
    api.mockResolvedValueOnce(PREVIA);
    render(<Espelho contratoId={1} podeEditar aoMudar={() => {}} />);
    fireEvent.click(await screen.findByRole("button", { name: /Gerar espelho/ }));
    fireEvent.change(screen.getByLabelText("Nº da medição"), { target: { value: "10" } });
    fireEvent.change(screen.getByLabelText("Competência"), { target: { value: "2026-05" } });
    const digitar = (el: HTMLInputElement, texto: string) => {
      for (const c of texto) fireEvent.input(el, { target: { value: el.value + c }, inputType: "insertText", data: c });
    };
    const medicao = screen.getByLabelText("Valor da medição") as HTMLInputElement;
    const reajuste = screen.getByLabelText("Valor do reajuste") as HTMLInputElement;
    digitar(medicao, "-100001");
    digitar(reajuste, "-1001");
    expect([medicao.value, reajuste.value]).toEqual(["1.000,01", "-10,01"]);
    fireEvent.click(screen.getByRole("button", { name: "Conferir" }));
    await screen.findByRole("button", { name: "Gerar" });
    expect(JSON.parse(api.mock.lastCall![1].body).entradas).toEqual({ medicao: "1.000,01", reajuste: "-10,01" });
  });

  // rodada 2 da PR #193 (C3): colar invalido segura o Conferir; o campo vazio nao vira zero calado
  it("colar em formato inválido bloqueia o Conferir", async () => {
    api.mockResolvedValueOnce({ regra: REGRA, espelhos: [] });
    render(<Espelho contratoId={1} podeEditar aoMudar={() => {}} />);
    fireEvent.click(await screen.findByRole("button", { name: /Gerar espelho/ }));
    fireEvent.change(screen.getByLabelText("Nº da medição"), { target: { value: "10" } });
    fireEvent.change(screen.getByLabelText("Competência"), { target: { value: "2026-05" } });
    fireEvent.paste(screen.getByLabelText("Valor da medição"), { clipboardData: { getData: () => "8900000.00" } });
    fireEvent.click(screen.getByRole("button", { name: "Conferir" }));
    expect(api).toHaveBeenCalledTimes(1);   // so' a carga da regra
    expect(screen.getByRole("alert").textContent).toContain("formato inválido");
  });

  it("trocar a competência volta o período ao mês inteiro dela", async () => {
    api.mockResolvedValueOnce({ regra: REGRA, espelhos: [] });
    render(<Espelho contratoId={1} podeEditar aoMudar={() => {}} />);
    fireEvent.click(await screen.findByRole("button", { name: /Gerar espelho/ }));
    fireEvent.change(screen.getByLabelText("Competência"), { target: { value: "2026-08" } });
    fireEvent.change(screen.getByLabelText("Período: de"), { target: { value: "2026-07-01" } });
    fireEvent.change(screen.getByLabelText("Competência"), { target: { value: "2026-07" } });
    expect((screen.getByLabelText("Período: de") as HTMLInputElement).value).toBe("2026-07-01");
    expect((screen.getByLabelText("até") as HTMLInputElement).value).toBe("2026-07-31");
  });

  it("na medição, o espelho vigente não enviado mostra o arquivo e o botão de enviar", async () => {
    api.mockResolvedValueOnce({ regra: REGRA, espelhos: [ESPELHO] });
    render(<Espelho contratoId={1} podeEditar aoMudar={() => {}} medicao={{ id: 1, tipo: "execucao" }} />);
    expect(await screen.findByText("Não enviado ao faturamento")).toBeTruthy();
    expect(screen.getByRole("link", { name: /ESPELHO - MT-388/ }).getAttribute("href")).toBe("/api/espelhos/7/arquivos/3");
    expect(screen.getByRole("button", { name: "Enviar ao faturamento" })).toBeTruthy();
    // sem tamanho do arquivo nem "versão · gerado por" ao lado
    expect(screen.queryByText(/KB/)).toBeNull();
    expect(screen.queryByText(/gerado em/)).toBeNull();
    // "Gerar de novo" parte dos valores da versao vigente
    fireEvent.click(screen.getByRole("button", { name: "Gerar de novo" }));
    expect((screen.getByLabelText("Valor da medição") as HTMLInputElement).value).toBe("634.529,58");
    expect((screen.getByLabelText("Nº da medição") as HTMLInputElement).value).toBe("10");
  });

  // issue #208: na medicao de Projeto, o misto antigo (superado para ela) nao aparece nem como "mora na execucao"
  it("na medição, o espelho superado por uma versão mais nova dela não aparece", async () => {
    const misto = { ...ESPELHO, id: 7, versao: 1, medicoes: [{ id: 1, tipo: "execucao", estado: "protocolada" },
      { id: 2, tipo: "projeto", estado: "espelho_gerado", superado: true }] };
    const novo = { ...ESPELHO, id: 8, versao: 2, medicoes: [{ id: 2, tipo: "projeto", estado: "espelho_gerado" }],
      arquivos: [{ documento_id: 4, saida: "projeto", nome: "ESPELHO - MT-388 - 10ª Medição de Projeto.docx", tamanho: 1 }] };
    api.mockResolvedValueOnce({ regra: REGRA, espelhos: [novo, misto] });
    render(<Espelho contratoId={1} podeEditar aoMudar={() => {}} medicao={{ id: 2, tipo: "projeto" }} />);
    expect(await screen.findByRole("link", { name: /Medição de Projeto/ })).toBeTruthy();
    expect(screen.queryByText(/mora/)).toBeNull();
    expect(screen.getAllByRole("article")).toHaveLength(1);
  });

  // issue #208: desmembramento inverso, a execucao tem espelho novo e o misto antigo mora no Projeto protocolado
  it("na medição de Projeto, o misto superado para a execução mora nela, sem aviso de lar", async () => {
    const misto = { ...ESPELHO, medicoes: [{ id: 1, tipo: "execucao", estado: "espelho_gerado", superado: true },
      { id: 2, tipo: "projeto", estado: "protocolada" }] };
    api.mockResolvedValueOnce({ regra: REGRA, espelhos: [misto] });
    render(<Espelho contratoId={1} podeEditar aoMudar={() => {}} medicao={{ id: 2, tipo: "projeto" }} />);
    expect(await screen.findByRole("link", { name: /ESPELHO - MT-388/ })).toBeTruthy();
    expect(screen.queryByText(/mora/)).toBeNull();
  });

  // issue #212: o misto superado para a execucao fica so' para leitura na pagina do Projeto, e o anexo vai para o Projeto
  it("misto com a execução superada: na medição de Projeto, sem enviar nem gerar de novo, e o anexo vai para o Projeto", async () => {
    const misto = { ...ESPELHO, medicoes: [{ id: 1, tipo: "execucao", estado: "espelho_gerado", superado: true },
      { id: 2, tipo: "projeto", estado: "protocolada" }] };
    api.mockResolvedValueOnce({ regra: REGRA, espelhos: [misto] });
    apiForm.mockResolvedValueOnce({ documento_id: 50, repetido: false });
    render(<Espelho contratoId={1} podeEditar aoMudar={() => {}} medicao={{ id: 2, tipo: "projeto" }} />);
    expect(await screen.findByText(/só para leitura/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Enviar/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Gerar de novo" })).toBeNull();
    const arquivo = new File(["%PDF"], "oficio.pdf", { type: "application/pdf" });
    fireEvent.change(screen.getByLabelText(/Anexar evidência do órgão/), { target: { files: [arquivo] } });
    await waitFor(() => expect(apiForm).toHaveBeenCalledTimes(1));
    expect(apiForm.mock.lastCall![0]).toBe("/api/medicoes/2/documentos");
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("oficio.pdf anexado como evidência do órgão em: 10ª Medição de Projeto."));
  });

  it("misto com o Projeto superado: na medição de execução, só leitura com o link para o Projeto e o anexo na execução", async () => {
    const misto = { ...ESPELHO, medicoes: [{ id: 1, tipo: "execucao", estado: "protocolada" },
      { id: 2, tipo: "projeto", estado: "espelho_gerado", superado: true }] };
    api.mockResolvedValueOnce({ regra: REGRA, espelhos: [misto] });
    apiForm.mockResolvedValueOnce({ documento_id: 51, repetido: false });
    render(<Espelho contratoId={1} podeEditar aoMudar={() => {}} medicao={{ id: 1, tipo: "execucao" }} />);
    const nota = await screen.findByText(/só para leitura/);
    expect(nota.querySelector("a")?.textContent).toBe("10ª Medição de Projeto");
    expect(screen.queryByRole("button", { name: /Enviar/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Gerar de novo" })).toBeNull();
    const arquivo = new File(["%PDF"], "oficio.pdf", { type: "application/pdf" });
    fireEvent.change(screen.getByLabelText(/Anexar evidência do órgão/), { target: { files: [arquivo] } });
    await waitFor(() => expect(apiForm).toHaveBeenCalledTimes(1));
    expect(apiForm.mock.lastCall![0]).toBe("/api/medicoes/1/documentos");
  });

  // rodada 1 do revisor da PR #236: "Reajuste da 10ª Medição" e' masculino; as frases nao levam artigo antes do titulo
  it("misto com o reajuste superado: a nota nomeia o reajuste sem artigo de gênero", async () => {
    const misto = { ...ESPELHO, medicoes: [{ id: 1, tipo: "execucao", estado: "protocolada" },
      { id: 3, tipo: "reajuste", estado: "espelho_gerado", superado: true }] };
    api.mockResolvedValueOnce({ regra: REGRA, espelhos: [misto] });
    render(<Espelho contratoId={1} podeEditar aoMudar={() => {}} medicao={{ id: 1, tipo: "execucao" }} />);
    const nota = await screen.findByText(/só para leitura/);
    expect(nota.textContent).toContain("já existe espelho mais novo para Reajuste da 10ª Medição.");
    expect(nota.textContent).not.toMatch(/\b(a|à) Reajuste|dela\b/);
  });

  it("misto com a execução superada: na página do reajuste, o anexo vai para o reajuste e a mensagem o nomeia", async () => {
    const misto = { ...ESPELHO, medicoes: [{ id: 1, tipo: "execucao", estado: "espelho_gerado", superado: true },
      { id: 3, tipo: "reajuste", estado: "protocolada" }] };
    api.mockResolvedValueOnce({ regra: REGRA, espelhos: [misto] });
    apiForm.mockResolvedValueOnce({ documento_id: 52, repetido: false });
    render(<Espelho contratoId={1} podeEditar aoMudar={() => {}} medicao={{ id: 3, tipo: "reajuste" }} />);
    await screen.findByText(/só para leitura/);
    const arquivo = new File(["%PDF"], "oficio.pdf", { type: "application/pdf" });
    fireEvent.change(screen.getByLabelText(/Anexar evidência do órgão/), { target: { files: [arquivo] } });
    await waitFor(() => expect(apiForm).toHaveBeenCalledTimes(1));
    expect(apiForm.mock.lastCall![0]).toBe("/api/medicoes/3/documentos");
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("oficio.pdf anexado como evidência do órgão em: Reajuste da 10ª Medição."));
  });

  it("misto com a execução superada, por etapa: nenhuma das duas partes oferece enviar ou gerar de novo", async () => {
    const misto = { ...ESPELHO, medicoes: [{ id: 1, tipo: "execucao", estado: "espelho_gerado", superado: true },
      { id: 2, tipo: "projeto", estado: "protocolada" }] };
    api.mockResolvedValue({ regra: REGRA, espelhos: [misto] });
    render(<>
      <Espelho contratoId={1} podeEditar aoMudar={() => {}} medicao={{ id: 2, tipo: "projeto" }} parte="espelho" />
      <Espelho contratoId={1} podeEditar aoMudar={() => {}} medicao={{ id: 2, tipo: "projeto" }} parte="faturamento" />
    </>);
    await waitFor(() => expect(screen.getAllByText(/só para leitura/)).toHaveLength(2));
    expect(screen.queryByRole("button", { name: /Enviar/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Gerar de novo" })).toBeNull();
  });

  it("versão já enviada: reenvio só com a confirmação marcada (S8)", async () => {
    const enviado = { ...ESPELHO, envio: { id: 9, remetente: "maria@l.com", para: ["f@x.com"], copia: [], assunto: "A",
      enviado_em: "2026-10-10 13:00:00" } };
    const posts: Record<string, unknown>[] = [];
    const MSG = "Esta versão do espelho já foi enviada ao faturamento (às 10:05 por Leo). Para mandar de novo, confirme o reenvio.";
    api.mockImplementation((caminho: string, opts?: RequestInit) => {
      if (caminho === "/api/contratos/1/espelho") return Promise.resolve({ regra: REGRA, espelhos: [enviado] });
      if (caminho === "/api/espelhos/7/envio") return Promise.resolve({ para: ["f@x.com"], copia: [], assunto: "Emissão NF",
        corpo: "Bom dia.", anexos: [], total: 0, limite: 1,
        avisos: ["a versão 1 deste espelho já foi enviada ao faturamento; este envio substitui"] });
      if (caminho === "/api/espelhos/7/enviar") {
        const corpo = JSON.parse(String(opts?.body));
        posts.push(corpo);
        return corpo.reenviar ? Promise.resolve({ envio_id: 10 })
          : Promise.reject(new ApiErro(409, MSG, { mensagem: MSG, codigo: "ESPELHO_JA_ENVIADO" }));
      }
      if (caminho.startsWith("/api/correio/remetente")) return Promise.resolve({ remetente: "eu@lotufo.com" });
      return Promise.resolve([]);
    });
    render(<Espelho contratoId={1} podeEditar aoMudar={() => {}} medicao={{ id: 1, tipo: "execucao" }} />);
    fireEvent.click(await screen.findByRole("button", { name: "Enviar de novo" }));
    const caixa = await screen.findByLabelText("Confirmo o reenvio desta versão (substitui o envio anterior)") as HTMLInputElement;
    expect(caixa.checked).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Enviar" }));          // sem marcar: nao pede reenvio
    expect(await screen.findByText(MSG)).toBeTruthy();
    expect(posts[0].reenviar).toBeUndefined();
    expect(screen.queryByRole("button", { name: "Liberar envio" })).toBeNull();   // nao ha reserva a liberar
    fireEvent.click(screen.getByLabelText("Confirmo o reenvio desta versão (substitui o envio anterior)"));
    fireEvent.click(screen.getByRole("button", { name: "Enviar" }));
    await waitFor(() => expect(posts).toHaveLength(2));
    expect(posts[1].reenviar).toBe(true);
  });

  // issue #284: a prevista (ou planilha/carta) sem boletim so' gera o espelho com a justificativa
  it("medição sem boletim pede a justificativa e a manda ao gerar; o valor da medição aparece com a origem", async () => {
    const previa = { ...PREVIA, periodo: "01/05/2026 A 31/05/2026",
      medicoes: [{ tipo: "execucao", valor_centavos: 63452958, existente: "prevista", sem_boletim: true }],
      travados: [{ tipo: "execucao", valor_centavos: 63452958, fonte: "pedido", opcional: true, sem_boletim: true }] };
    api.mockResolvedValueOnce({ regra: REGRA, espelhos: [] });
    api.mockResolvedValueOnce(previa);
    render(<Espelho contratoId={1} podeEditar aoMudar={() => {}} abrirForm inicial={{ numero: 10, competencia: "2026-05" }} />);
    fireEvent.change(await screen.findByLabelText("Valor da medição"), { target: { value: "634.529,58" } });
    fireEvent.click(screen.getByRole("button", { name: "Conferir" }));
    await screen.findByRole("button", { name: "Gerar" });
    expect(screen.getByText(/Sem o boletim do órgão: Medição 10 de execução/)).toBeTruthy();
    expect(screen.getByText(/Medição 10 de execução \(pedido\)/)).toBeTruthy();
    expect(screen.queryByText("Versão nova")).toBeNull();          // a prevista ganha o 1o espelho
    fireEvent.click(screen.getByRole("button", { name: "Gerar" }));
    expect(await screen.findByText(/Informe a justificativa/)).toBeTruthy();
    expect(api).toHaveBeenCalledTimes(2);                          // nada foi ao servidor
    // #722: a justificativa obrigatoria fica na caixa propria (CaixaJustificativa)
    expect(screen.getByLabelText("Justificativa para seguir sem boletim").closest(".justificativa")).not.toBeNull();
    fireEvent.change(screen.getByLabelText("Justificativa para seguir sem boletim"),
                     { target: { value: "NF vai junto com o ofício" } });
    api.mockResolvedValueOnce({ espelho_id: 7 });
    api.mockResolvedValueOnce({ regra: REGRA, espelhos: [] });
    fireEvent.click(screen.getByRole("button", { name: "Gerar" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/contratos/1/espelho", expect.objectContaining({ method: "POST" })));
    const corpo = JSON.parse(api.mock.calls.find(c => c[0] === "/api/contratos/1/espelho" && c[1]?.method === "POST")![1].body);
    expect(corpo.justificativa_sem_boletim).toBe("NF vai junto com o ofício");
  });

  it("a origem do valor diz boletim só quando há boletim; o atestado digitado aparece como aprovado (#284)", async () => {
    const com = (fonte: string, sem_boletim: boolean) => ({ ...PREVIA, periodo: "01/05/2026 A 31/05/2026",
      medicoes: [{ tipo: "execucao", valor_centavos: 63452958, existente: sem_boletim ? "planilha_enviada" : "boletim_recebido", sem_boletim }],
      travados: [{ tipo: "execucao", valor_centavos: 63452958, fonte, opcional: sem_boletim, sem_boletim }] });
    for (const [fonte, sem, rotulo] of [["atestado", true, "(aprovado)"], ["boletim", false, "(aprovado do boletim)"]] as const) {
      cleanup(); api.mockReset();
      api.mockResolvedValueOnce({ regra: REGRA, espelhos: [] });
      api.mockResolvedValueOnce(com(fonte, sem));
      render(<Espelho contratoId={1} podeEditar aoMudar={() => {}} abrirForm inicial={{ numero: 10, competencia: "2026-05" }} />);
      fireEvent.change(await screen.findByLabelText("Valor da medição"), { target: { value: "634.529,58" } });
      fireEvent.click(screen.getByRole("button", { name: "Conferir" }));
      await screen.findByRole("button", { name: "Gerar" });
      const linha = screen.getByText(/Medição 10 de execução \(/).textContent ?? "";
      expect(linha).toContain(rotulo);
      if (sem) expect(linha).not.toContain("do boletim");
    }
  });
});

// #514: passo Espelhos da pagina da obra
describe("Espelho: o passo Espelhos (#514)", () => {
  afterEach(() => { cleanup(); api.mockReset(); apiForm.mockReset(); });
  // total das saidas: 52.843.623 + 10.609.335 + 3.219.258 + 646.325 = 67.318.541 (centavo impar)
  const comDuas = { ...ESPELHO, medicoes: [{ id: 1, tipo: "execucao", estado: "espelho_gerado" }, { id: 2, tipo: "reajuste", estado: "espelho_gerado" }] };

  it("uma linha por nota (empresa, município, valor, espelho) e o total igual ao aprovado das medições do espelho", async () => {
    api.mockResolvedValue({ regra: REGRA, espelhos: [comDuas] });
    render(<Espelho contratoId={1} podeEditar aoMudar={() => {}} medicao={{ id: 1, tipo: "execucao" }} parte="espelho"
      referencias={{ 1: { valor: 63452958, fonte: "aprovado" }, 2: { valor: 3865583, fonte: "aprovado" } }} />);
    const tabela = await screen.findByRole("table", { name: "Espelhos da medição 10" });
    const linhas = within(tabela).getAllByRole("row");
    expect(linhas).toHaveLength(6);                        // cabecalho, 4 notas, total
    expect(within(linhas[1]).getByText("Medição · Lotufo")).toBeTruthy();
    expect(within(linhas[1]).getByText("Cáceres")).toBeTruthy();
    // so' a saida com arquivo tem o "gerado", que baixa o espelho dela
    expect(within(linhas[1]).getByRole("link", { name: /Baixar o espelho/ }).getAttribute("href")).toBe("/api/espelhos/7/arquivos/3");
    expect(within(linhas[2]).queryByRole("link")).toBeNull();
    expect(within(linhas[5]).getByText("R$ 673.185,41")).toBeTruthy();
    expect(within(linhas[5]).getByText("igual ao aprovado")).toBeTruthy();
  });

  it("total diferente diz o valor de referência; no misto (execução aprovada, reajuste pedido) a referência diz as duas", async () => {
    api.mockResolvedValue({ regra: REGRA, espelhos: [comDuas] });
    render(<Espelho contratoId={1} podeEditar aoMudar={() => {}} medicao={{ id: 1, tipo: "execucao" }} parte="espelho"
      referencias={{ 1: { valor: 63452957, fonte: "aprovado" }, 2: { valor: 3865583, fonte: "pedido" } }} />);
    expect(await screen.findByText("diferente da referência (aprovado + pedido) (R$ 673.185,40)")).toBeTruthy();
    expect(screen.queryByText(/igual/)).toBeNull();
  });

  it("os três casos da referência: tudo pedido, misto e tudo aprovado (gate Sol, PR #555)", async () => {
    api.mockResolvedValue({ regra: REGRA, espelhos: [comDuas] });
    const ver = async (r1: "aprovado" | "pedido", r2: "aprovado" | "pedido", texto: string) => {
      const { unmount } = render(<Espelho contratoId={1} podeEditar aoMudar={() => {}} medicao={{ id: 1, tipo: "execucao" }} parte="espelho"
        referencias={{ 1: { valor: 63452958, fonte: r1 }, 2: { valor: 3865583, fonte: r2 } }} />);
      expect(await screen.findByText(texto)).toBeTruthy();
      unmount();
    };
    await ver("pedido", "pedido", "igual ao pedido");
    await ver("aprovado", "pedido", "igual à referência (aprovado + pedido)");
    await ver("aprovado", "aprovado", "igual ao aprovado");
  });

  it("sem referência de uma das medições, o total aparece sem conferência", async () => {
    api.mockResolvedValue({ regra: REGRA, espelhos: [comDuas] });
    render(<Espelho contratoId={1} podeEditar aoMudar={() => {}} medicao={{ id: 1, tipo: "execucao" }} parte="espelho"
      referencias={{ 1: { valor: 63452958, fonte: "aprovado" } }} />);
    await screen.findByRole("table", { name: "Espelhos da medição 10" });
    expect(screen.queryByText(/igual ao|diferente do/)).toBeNull();
  });

  it("a parte do faturamento diz se o espelho já foi enviado", async () => {
    api.mockResolvedValue({ regra: REGRA, espelhos: [ESPELHO] });
    render(<Espelho contratoId={1} podeEditar aoMudar={() => {}} medicao={{ id: 1, tipo: "execucao" }} parte="faturamento" />);
    expect(await screen.findByText("Não enviado ao faturamento")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Enviar ao faturamento" })).toBeTruthy();
  });

  // issue #798: o espelho que foi ao faturamento por e-mail, fora do sistema
  const POR_FORA = { ...ESPELHO, medicoes: [{ id: 1, tipo: "execucao", estado: "espelho_enviado" }],
    envio_externo: { enviado_em: "2026-10-20", observacao: "pelo Outlook", registrado_em: "2026-10-22 13:00:00", registrado_por_nome: "Maria" } };
  const faturamento = (podeEditar = true, aoMudar = () => {}) =>
    render(<Espelho contratoId={1} podeEditar={podeEditar} aoMudar={aoMudar} medicao={{ id: 1, tipo: "execucao" }} parte="faturamento" />);

  it("“Já enviei por fora” registra a data e a observação, e o passo passa a mostrar o envio por fora (#798)", async () => {
    const posts: { caminho: string; corpo: Record<string, unknown> }[] = [];
    let registrado = false;
    api.mockImplementation((caminho: string, opts?: RequestInit) => {
      if (caminho === "/api/contratos/1/espelho") return Promise.resolve({ regra: REGRA, espelhos: [registrado ? POR_FORA : ESPELHO] });
      if (opts?.method === "POST") {
        posts.push({ caminho, corpo: JSON.parse(String(opts.body)) });
        registrado = true;
        return Promise.resolve({ espelho_id: 7, enviado_em: "2026-10-20" });
      }
      return Promise.resolve([]);
    });
    const aoMudar = vi.fn();
    faturamento(true, aoMudar);
    const botao = await screen.findByRole("button", { name: "Já enviei por fora" });
    expect(botao.className).toBe("botao-link");
    expect(screen.getByRole("button", { name: "Enviar ao faturamento" }).className).toContain("btn--primario");
    fireEvent.click(botao);
    const janela = within(screen.getByRole("dialog", { name: "Registrar envio do espelho por fora" }));
    const data = janela.getByLabelText("Data do envio") as HTMLInputElement;
    expect(data.required).toBe(true);
    expect(data.max).toBe(data.value);                      // abre em hoje, e o futuro nao se escolhe
    fireEvent.change(data, { target: { value: "2026-10-20" } });
    fireEvent.change(janela.getByLabelText("Observação (opcional)"), { target: { value: "  pelo Outlook " } });
    fireEvent.click(janela.getByRole("button", { name: "Registrar" }));
    expect(await screen.findByText("Enviado por fora em 20/10/2026")).toBeTruthy();
    expect(posts).toEqual([{ caminho: "/api/espelhos/7/envio-externo", corpo: { enviado_em: "2026-10-20", observacao: "pelo Outlook" } }]);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByText("Não enviado ao faturamento")).toBeNull();
    expect(screen.queryByRole("button", { name: "Já enviei por fora" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Enviar ao faturamento" })).toBeNull();
    // o envio pelo sistema continua possivel, sem ser a acao principal
    expect(screen.getByRole("button", { name: "Enviar de novo" }).className).not.toContain("btn--primario");
    expect(screen.getByRole("status").textContent).toBe("Envio por fora registrado. A medição passou a Espelho enviado.");
    expect(aoMudar).toHaveBeenCalledTimes(1);
  });

  it("sem observação, o registro por fora manda só a data (#798)", async () => {
    const corpos: unknown[] = [];
    api.mockImplementation((caminho: string, opts?: RequestInit) => {
      if (opts?.method === "POST") { corpos.push(JSON.parse(String(opts.body))); return Promise.resolve({}); }
      return Promise.resolve(caminho === "/api/contratos/1/espelho" ? { regra: REGRA, espelhos: [ESPELHO] } : []);
    });
    faturamento();
    fireEvent.click(await screen.findByRole("button", { name: "Já enviei por fora" }));
    const data = (screen.getByLabelText("Data do envio") as HTMLInputElement).value;
    fireEvent.click(screen.getByRole("button", { name: "Registrar" }));
    await waitFor(() => expect(corpos).toEqual([{ enviado_em: data }]));
  });

  it("quem só consulta não vê “Já enviei por fora”, e o espelho já enviado não o oferece (#798)", async () => {
    api.mockResolvedValue({ regra: REGRA, espelhos: [ESPELHO] });
    const { unmount } = faturamento(false);
    expect(await screen.findByText("Não enviado ao faturamento")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Já enviei por fora" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Enviar ao faturamento" })).toBeNull();
    unmount();
    api.mockResolvedValue({ regra: REGRA, espelhos: [{ ...ESPELHO, envio: { id: 9, remetente: "maria@l.com", para: ["f@x.com"],
      copia: [], assunto: "A", enviado_em: "2026-10-10 13:00:00" } }] });
    faturamento();
    expect(await screen.findByRole("button", { name: "Enviar de novo" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Já enviei por fora" })).toBeNull();
  });

  it("a recusa do registro por fora aparece na janela; no 409 a lista é lida de novo (#798)", async () => {
    const MSG_DATA = "A data do envio é anterior ao período do espelho (início em 01/05/2026)";
    const MSG_JA = "O envio por fora desta versão do espelho já está registrado (em 20/10/2026, por Maria).";
    let recusa: ApiErro = new ApiErro(422, MSG_DATA);
    let leituras = 0;
    api.mockImplementation((caminho: string, opts?: RequestInit) => {
      if (opts?.method === "POST") return Promise.reject(recusa);
      if (caminho === "/api/contratos/1/espelho") { leituras += 1; return Promise.resolve({ regra: REGRA, espelhos: [leituras > 1 ? POR_FORA : ESPELHO] }); }
      return Promise.resolve([]);
    });
    const aoMudar = vi.fn();
    faturamento(true, aoMudar);
    fireEvent.click(await screen.findByRole("button", { name: "Já enviei por fora" }));
    fireEvent.click(screen.getByRole("button", { name: "Registrar" }));
    expect(await screen.findByText(MSG_DATA)).toBeTruthy();
    expect(screen.getByRole("dialog")).toBeTruthy();         // a janela fica, com o que foi digitado
    expect(leituras).toBe(1);
    expect(aoMudar).not.toHaveBeenCalled();
    recusa = new ApiErro(409, MSG_JA, { mensagem: MSG_JA, codigo: "ESPELHO_ENVIO_EXTERNO_JA_REGISTRADO" });
    fireEvent.click(screen.getByRole("button", { name: "Registrar" }));
    expect(await screen.findByText(MSG_JA)).toBeTruthy();
    expect(await screen.findByText("Enviado por fora em 20/10/2026")).toBeTruthy();    // o que ja' vale, atras da janela
    expect(aoMudar).toHaveBeenCalledTimes(1);
  });

  it("depois do registro por fora, enviar pelo sistema pede a confirmação do reenvio (#798)", async () => {
    api.mockImplementation((caminho: string) => {
      if (caminho === "/api/contratos/1/espelho") return Promise.resolve({ regra: REGRA, espelhos: [POR_FORA] });
      if (caminho === "/api/espelhos/7/envio") return Promise.resolve({ para: ["f@x.com"], copia: [], assunto: "Emissão NF",
        corpo: "Bom dia.", anexos: [], total: 0, limite: 1,
        avisos: ["a versão 1 deste espelho já foi enviada ao faturamento; este envio substitui"] });
      if (caminho.startsWith("/api/correio/remetente")) return Promise.resolve({ remetente: "eu@lotufo.com" });
      return Promise.resolve([]);
    });
    faturamento();
    fireEvent.click(await screen.findByRole("button", { name: "Enviar de novo" }));
    const caixa = await screen.findByLabelText("Confirmo o reenvio desta versão (substitui o envio anterior)") as HTMLInputElement;
    expect(caixa.checked).toBe(false);
  });

  it("consórcio que emite só a cota: as notas somam a cota e o espelho confere pelo valor cheio da medição (code-review)", async () => {
    const cota = { ...ESPELHO, entradas: { medicao: 1000001 }, medicoes: [{ id: 1, tipo: "execucao", estado: "espelho_gerado" }],
      saidas: [saida("cuiaba-medicao", "medicao", "Cuiabá", 180000)] };
    api.mockResolvedValue({ regra: REGRA, espelhos: [cota] });
    render(<Espelho contratoId={1} podeEditar aoMudar={() => {}} medicao={{ id: 1, tipo: "execucao" }} parte="espelho"
      referencias={{ 1: { valor: 1000001, fonte: "aprovado" } }} />);
    expect(await screen.findByText("igual ao aprovado")).toBeTruthy();
    // duas linhas (#558): a soma das notas e o valor da medição, com a conferência junto deste
    const linhas = within(screen.getByRole("table", { name: "Espelhos da medição 10" })).getAllByRole("row");
    const notas = linhas[linhas.length - 2], medicao = linhas[linhas.length - 1];
    expect(within(notas).getByText("Total das notas")).toBeTruthy();
    expect(within(notas).getByText("R$ 1.800,00")).toBeTruthy();
    expect(within(notas).queryByText(/igual|diferente/)).toBeNull();
    expect(within(medicao).getByText("Valor da medição")).toBeTruthy();
    expect(within(medicao).getByText("R$ 10.000,01")).toBeTruthy();
    expect(within(medicao).getByText("igual ao aprovado")).toBeTruthy();
  });

  it("obra própria ou consórcio que emite o cheio: uma linha só, rotulada Total, com a conferência (#558)", async () => {
    api.mockResolvedValue({ regra: REGRA, espelhos: [comDuas] });   // as notas somam o mesmo que as entradas
    render(<Espelho contratoId={1} podeEditar aoMudar={() => {}} medicao={{ id: 1, tipo: "execucao" }} parte="espelho"
      referencias={{ 1: { valor: 63452958, fonte: "aprovado" }, 2: { valor: 3865583, fonte: "aprovado" } }} />);
    const tabela = await screen.findByRole("table", { name: "Espelhos da medição 10" });
    const linhas = within(tabela).getAllByRole("row");
    expect(linhas).toHaveLength(6);                        // cabecalho, 4 notas, uma linha de total
    const total = linhas[5];
    expect(within(total).getByText("Total")).toBeTruthy();
    expect(within(total).getByText("R$ 673.185,41")).toBeTruthy();
    expect(within(total).getByText("igual ao aprovado")).toBeTruthy();
    expect(within(tabela).queryByText("Total das notas")).toBeNull();
    expect(within(tabela).queryByText("Valor da medição")).toBeNull();
  });
});
