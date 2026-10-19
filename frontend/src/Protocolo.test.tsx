import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiErro } from "./api";
import { NovoProtocolo, ProtocolosDaMedicao } from "./Protocolo";
import { ir } from "./rota";

const { api, apiForm } = vi.hoisted(() => ({ api: vi.fn(), apiForm: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api, apiForm }));

const MEDICAO = { id: 5, numero: 23, tipo: "execucao", titulo: "23ª Medição", estado: "nota_emitida",
  competencia: "2026-09", valor_protocolado_centavos: 1000000 };
const PROT = { id: 9, etapa: "unico", etapa_rotulo: "Protocolo", tem_carta: true, natureza: "execucao",
  numero_oficio: "CT-301-LT-2026", situacao: "assinado", corpo_carta: "Texto", montado_paginas: 7,
  nome_arquivo: "CT-301-LT-2026 - Obra - 23ª Medição (09.2026).pdf", assinado_arquivo: "protocolos/x.pdf",
  conferencia: { ok: false, avisos: [{ codigo: "nao_assinado", mensagem: "Nenhuma página tem o carimbo do DocuSign: o PDF parece não assinado." }],
    envelope: null, paginas_montado: 7, paginas_assinado: 7, certificado: 0 },
  medicoes: [MEDICAO], pecas: [], pendencias: [{ codigo: "conferencia", mensagem: "Nenhuma página tem o carimbo" }],
  envio_id: null, numero_orgao: null, justificativa: null, criado_em: "2026-09-16" };
const LISTA = { familia: "mtpar", etapas: [{ chave: "unico", rotulo: "Protocolo", carta: true }], pecas: [],
  medicoes: [MEDICAO], protocolos: [] as typeof PROT[] };

describe("Protocolo", () => {
  afterEach(() => { cleanup(); api.mockReset(); apiForm.mockReset(); });

  it("na obra que junta medições, cria o protocolo com as medições marcadas e o número do ofício", async () => {
    const SES = { ...LISTA, familia: "ses" };
    api.mockResolvedValueOnce(SES).mockResolvedValueOnce(PROT).mockResolvedValueOnce({ ...SES, protocolos: [PROT] });
    render(<NovoProtocolo contratoId={1} />);
    fireEvent.click(await screen.findByLabelText(/23ª Medição/));
    fireEvent.change(screen.getByLabelText(/Nº do ofício/), { target: { value: "301" } });
    fireEvent.click(screen.getByRole("button", { name: "Criar protocolo" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/contratos/1/protocolos", expect.objectContaining({ method: "POST" })));
    const corpo = JSON.parse(api.mock.calls[1][1].body);
    expect(corpo).toEqual({ etapa: "unico", medicao_ids: [5], numero_oficio: "301" });
  });

  // issue #213: o que falta não pede mais justificativa escrita; o Enviar abre o aviso "ATENÇÃO" com a lista
  it("na medição, mostra o aviso da conferência e só envia depois de confirmar o que falta", async () => {
    render(<ProtocolosDaMedicao contratoId={1} medicaoId={5} dados={{ ...LISTA, protocolos: [PROT] }}
      carregar={async () => {}} podeEditar aoMudar={() => {}} />);
    expect(await screen.findByText(/parece não assinado/)).toBeTruthy();
    fireEvent.click(screen.getByLabelText(/Incluir neste e-mail/));
    api.mockResolvedValueOnce({ para: ["protocolo@exemplo.com.br"], copia: [], assunto: "CT-301-LT-2026 - 23ª Medição - Obra",
      corpo: "Bom dia.", anexos: [{ nome: "CT.pdf", tamanho: 2048 }], total: 2048, limite: 26214400,
      pendencias: [{ codigo: "conferencia", mensagem: "Nenhuma página tem o carimbo" }] });
    fireEvent.click(screen.getByRole("button", { name: /Prévia do e-mail/ }));
    const enviar = await screen.findByRole("button", { name: "Enviar" });
    expect((enviar as HTMLButtonElement).disabled).toBe(false);
    expect(screen.queryByLabelText(/Justificativa/)).toBeNull();
    fireEvent.click(enviar);
    let aviso = screen.getByRole("alertdialog", { name: "ATENÇÃO" });
    expect(within(aviso).getByText("Nenhuma página tem o carimbo")).toBeTruthy();
    expect(within(aviso).getByText("Deseja continuar com o envio?")).toBeTruthy();
    fireEvent.click(within(aviso).getByRole("button", { name: "Cancelar" }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(api.mock.calls.some(c => c[0] === "/api/protocolos/envio")).toBe(false);
    api.mockResolvedValue({});
    fireEvent.click(enviar);
    aviso = screen.getByRole("alertdialog", { name: "ATENÇÃO" });
    fireEvent.click(within(aviso).getByRole("button", { name: "Continuar com o envio" }));
    await waitFor(() => expect(api.mock.calls.some(c => c[0] === "/api/protocolos/envio")).toBe(true));
    const corpo = JSON.parse(api.mock.calls.find(c => c[0] === "/api/protocolos/envio")![1].body);
    expect(corpo.confirmadas).toEqual(["Nenhuma página tem o carimbo"]);
  });

  it("o servidor recusar porque o que falta mudou reabre o aviso com a lista nova", async () => {
    render(<ProtocolosDaMedicao contratoId={1} medicaoId={5} dados={{ ...LISTA, protocolos: [PROT] }}
      carregar={async () => {}} podeEditar aoMudar={() => {}} />);
    fireEvent.click(await screen.findByLabelText(/Incluir neste e-mail/));
    api.mockResolvedValueOnce({ para: ["protocolo@exemplo.com.br"], copia: [], assunto: "A", corpo: "Bom dia.", anexos: [],
      total: 0, limite: 26214400, pendencias: [{ codigo: "conferencia", mensagem: "Nenhuma página tem o carimbo" }] });
    fireEvent.click(screen.getByRole("button", { name: /Prévia do e-mail/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Enviar" }));
    const nova = ["Nenhuma página tem o carimbo", "Lotufo: CND Federal sem validade hoje"];
    api.mockRejectedValueOnce(new ApiErro(422, "A lista do que falta mudou", { codigo: "CONFIRMAR_PENDENCIAS", pendencias: nova,
      itens: [{ codigo: "conferencia", mensagem: nova[0] }, { codigo: "certidao", mensagem: nova[1] }] }));
    fireEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Continuar com o envio" }));
    const aviso = await screen.findByRole("alertdialog", { name: "ATENÇÃO" });
    expect(within(aviso).getByText(/mudou desde a sua confirmação/)).toBeTruthy();
    expect(within(aviso).getByText("Lotufo: CND Federal sem validade hoje")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    // a lista "O que falta" da prévia passa a ser a de agora, com o nível de cada item (certidão é crítica)
    const linha = screen.getAllByText("Lotufo: CND Federal sem validade hoje").find(x => !aviso.contains(x))!;
    expect(linha.closest("li")?.textContent).toMatch(/Crítico/i);
    api.mockResolvedValueOnce({});
    fireEvent.click(within(aviso).getByRole("button", { name: "Continuar com o envio" }));
    await waitFor(() => expect(api.mock.calls.filter(c => c[0] === "/api/protocolos/envio")).toHaveLength(2));
    const ultimo = api.mock.calls.filter(c => c[0] === "/api/protocolos/envio")[1];
    expect(JSON.parse(ultimo[1].body).confirmadas).toEqual(nova);
  });

  it("sem nada faltando, o Enviar manda direto, sem aviso", async () => {
    render(<ProtocolosDaMedicao contratoId={1} medicaoId={5} dados={{ ...LISTA, protocolos: [{ ...PROT, pendencias: [] }] }}
      carregar={async () => {}} podeEditar aoMudar={() => {}} />);
    fireEvent.click(await screen.findByLabelText(/Incluir neste e-mail/));
    api.mockResolvedValueOnce({ para: ["protocolo@exemplo.com.br"], copia: [], assunto: "A", corpo: "Bom dia.", anexos: [],
      total: 0, limite: 26214400, pendencias: [] });
    fireEvent.click(screen.getByRole("button", { name: /Prévia do e-mail/ }));
    api.mockResolvedValue({});
    fireEvent.click(await screen.findByRole("button", { name: "Enviar" }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    await waitFor(() => expect(api.mock.calls.some(c => c[0] === "/api/protocolos/envio")).toBe(true));
    expect(JSON.parse(api.mock.calls.find(c => c[0] === "/api/protocolos/envio")![1].body).confirmadas).toBeNull();
  });

  // issue #10: o e-mail leva exatamente os protocolos vistos na prévia
  const PREVIA = { para: ["protocolo@exemplo.com.br"], copia: [], assunto: "CT-301-LT-2026 - 23ª Medição - Obra",
    corpo: "Bom dia.", anexos: [{ nome: "CT.pdf", tamanho: 2048 }], total: 2048, limite: 26214400, pendencias: [] };
  const DOIS = { ...LISTA, protocolos: [PROT, { ...PROT, id: 10, numero_oficio: "CT-302-LT-2026" }] };

  it("marcar outro protocolo com a prévia aberta fecha a prévia", async () => {
    render(<ProtocolosDaMedicao contratoId={1} medicaoId={5} dados={DOIS}
      carregar={async () => {}} podeEditar aoMudar={() => {}} />);
    const [primeiro, segundo] = await screen.findAllByLabelText(/Incluir neste e-mail/);
    fireEvent.click(primeiro);
    api.mockResolvedValueOnce(PREVIA);
    fireEvent.click(screen.getByRole("button", { name: /Prévia do e-mail/ }));
    expect(await screen.findByRole("button", { name: "Enviar" })).toBeTruthy();
    fireEvent.click(segundo);
    await waitFor(() => expect(screen.queryByRole("button", { name: "Enviar" })).toBeNull());
    expect(screen.getByRole("button", { name: /Prévia do e-mail \(2 protocolos\)/ })).toBeTruthy();
  });

  // cobre o fechamento da prévia ao mudar a seleção e o envio da nova prévia; que o Enviar usa os protocolos
  // guardados na prévia não se observa daqui, porque a prévia fecha antes que a seleção possa divergir
  it("depois de mudar a seleção, o envio leva os protocolos da nova prévia", async () => {
    const PREV = "/api/protocolos/envio/previa", ENVIO = "/api/protocolos/envio";
    api.mockImplementation(async (url: string) => url === PREV ? PREVIA : url === ENVIO ? { envio_id: 1 } : []);
    render(<ProtocolosDaMedicao contratoId={1} medicaoId={5} dados={DOIS}
      carregar={async () => {}} podeEditar aoMudar={() => {}} />);
    const [primeiro, segundo] = await screen.findAllByLabelText(/Incluir neste e-mail/);
    fireEvent.click(primeiro);
    fireEvent.click(screen.getByRole("button", { name: /Prévia do e-mail/ }));
    await screen.findByRole("button", { name: "Enviar" });
    fireEvent.click(segundo);
    fireEvent.click(await screen.findByRole("button", { name: /Prévia do e-mail \(2 protocolos\)/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Enviar" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith(ENVIO, expect.objectContaining({ method: "POST" })));
    const corpos = (url: string) => api.mock.calls.filter(c => c[0] === url).map(c => JSON.parse(c[1].body).protocolo_ids);
    expect(corpos(PREV)).toEqual([[9], [9, 10]]);
    expect(corpos(ENVIO)).toEqual([[9, 10]]);
    // revisor R3 (PR #92): o envio leva os anexos vistos na prévia, para o servidor recusar se mudaram
    const envio = JSON.parse(api.mock.calls.find(c => c[0] === ENVIO)![1].body);
    expect(envio.anexos).toEqual([{ nome: "CT.pdf", tamanho: 2048 }]);
  });

  // revisor R1 (PR #92): peça anexada ou removida, pacote montado de novo ou assinado trocado com a prévia aberta
  // recarregam o protocolo; a prévia mostrava os anexos antigos e o Enviar mandava o que não foi conferido
  it("o protocolo da prévia mudar no recarregamento fecha a prévia; recarregar sem mudança não fecha", async () => {
    const props = { contratoId: 1, medicaoId: 5, carregar: async () => {}, podeEditar: true, aoMudar: () => {} };
    api.mockImplementation(async (url: string) => url === "/api/protocolos/envio/previa" ? PREVIA : []);
    const { rerender } = render(<ProtocolosDaMedicao {...props} dados={DOIS} />);
    const [primeiro] = await screen.findAllByLabelText(/Incluir neste e-mail/);
    fireEvent.click(primeiro);
    fireEvent.click(screen.getByRole("button", { name: /Prévia do e-mail/ }));
    await screen.findByRole("button", { name: "Enviar" });
    // outro protocolo (fora da prévia) muda e a lista volta igual: a prévia fica
    rerender(<ProtocolosDaMedicao {...props} dados={{ ...DOIS, protocolos: [{ ...PROT }, { ...DOIS.protocolos[1], situacao: "rascunho" }] }} />);
    expect(screen.getByRole("button", { name: "Enviar" })).toBeTruthy();
    // o protocolo da prévia ganha uma peça e volta a rascunho: a prévia fecha
    rerender(<ProtocolosDaMedicao {...props} dados={{ ...DOIS, protocolos: [
      { ...PROT, situacao: "rascunho", assinado_arquivo: null, pecas: [{ id: 1, tipo: "planilha", nome: "nova.xlsx", tamanho: 10, ext: "xlsx" }] },
      DOIS.protocolos[1]] }} />);
    await waitFor(() => expect(screen.queryByRole("button", { name: "Enviar" })).toBeNull());
    expect(screen.getByRole("button", { name: /Prévia do e-mail \(1 protocolo\)/ })).toBeTruthy();
  });

  // gate Sol S1 (10/10/2026): o numero e' obrigatorio na primeira vez; depois da' para anexar so' o comprovante
  it("no protocolo enviado, o nº do órgão não é mais rotulado como opcional e explica quando é exigido", async () => {
    render(<ProtocolosDaMedicao contratoId={1} medicaoId={5} dados={{ ...LISTA, protocolos: [{ ...PROT, situacao: "enviado", envio_id: 3 }] }}
      carregar={async () => {}} podeEditar aoMudar={() => {}} />);
    const campo = await screen.findByLabelText("Nº do protocolo no órgão");
    expect(screen.queryByText(/opcional/)).toBeNull();
    const ajuda = document.getElementById(campo.getAttribute("aria-describedby") ?? "");
    // issue #2: a tela agora tem o campo do comprovante, e a ajuda diz que ele é opcional
    expect(ajuda?.textContent).toBe("Obrigatório; informe o número dado pelo órgão. Anexe o comprovante em PDF, se tiver.");
  });

  // issue #2 (backlog 10/10/2026): o comprovante do órgão sobe pela tela, junto do nº
  describe("comprovante do órgão", () => {
    const ENVIADO = { ...PROT, situacao: "enviado", envio_id: 3, numero_orgao: "X-1", comprovante_arquivo: null as string | null };
    const pdf = () => new File(["%PDF-1.4"], "protocolo-orgao.pdf", { type: "application/pdf" });
    // gravar relê a lista (`carregar`) e avisa a página (`aoMudar`); o link nasce da leitura nova
    const tela = (p: typeof ENVIADO) => {
      const carregar = vi.fn(async () => {});
      render(<ProtocolosDaMedicao contratoId={1} medicaoId={5} dados={{ ...LISTA, protocolos: [p] }}
        carregar={carregar} podeEditar aoMudar={() => {}} />);
      return carregar;
    };

    it("envia o PDF escolhido junto do número", async () => {
      apiForm.mockResolvedValueOnce({ ...ENVIADO, comprovante_arquivo: "protocolos/c.pdf" });
      const carregar = tela(ENVIADO);
      fireEvent.change(await screen.findByLabelText("Anexar o comprovante do órgão (PDF)"), { target: { files: [pdf()] } });
      expect(await screen.findByText("protocolo-orgao.pdf")).toBeTruthy();
      fireEvent.click(screen.getByRole("button", { name: "Salvar" }));
      await waitFor(() => expect(carregar).toHaveBeenCalled());
      const [caminho, fd] = apiForm.mock.calls[0] as [string, FormData];
      expect(caminho).toBe("/api/protocolos/9/numero-orgao");
      expect(fd.get("numero")).toBe("X-1");
      expect((fd.get("comprovante") as File).name).toBe("protocolo-orgao.pdf");
    });

    it("com o número já gravado, mandar só o comprovante não apaga o número", async () => {
      apiForm.mockResolvedValueOnce(ENVIADO);
      tela(ENVIADO);
      fireEvent.change(await screen.findByLabelText("Anexar o comprovante do órgão (PDF)"), { target: { files: [pdf()] } });
      fireEvent.click(screen.getByRole("button", { name: "Salvar" }));
      await waitFor(() => expect(apiForm).toHaveBeenCalled());
      expect((apiForm.mock.calls[0][1] as FormData).get("numero")).toBe("X-1");   // o campo vem preenchido com o gravado
    });

    it("enquanto envia, o Salvar fica travado (clique duplo não manda duas vezes) e o arquivo escolhido é limpo ao gravar", async () => {
      let terminar: (v: unknown) => void = () => {};
      apiForm.mockReturnValueOnce(new Promise(r => { terminar = r; }));
      tela(ENVIADO);
      const entrada = await screen.findByLabelText("Anexar o comprovante do órgão (PDF)") as HTMLInputElement;
      fireEvent.change(entrada, { target: { files: [pdf()] } });
      const salvar = screen.getByRole("button", { name: "Salvar" }) as HTMLButtonElement;
      fireEvent.click(salvar);
      await waitFor(() => expect(salvar.disabled).toBe(true));
      fireEvent.click(salvar);
      expect(apiForm).toHaveBeenCalledTimes(1);
      terminar(ENVIADO);
      await waitFor(() => expect(salvar.disabled).toBe(false));
      expect(entrada.value).toBe("");                 // escolher o mesmo arquivo de novo dispara onChange
    });

    it("sem arquivo escolhido, não manda o campo do comprovante", async () => {
      apiForm.mockResolvedValueOnce(ENVIADO);
      tela(ENVIADO);
      fireEvent.click(await screen.findByRole("button", { name: "Salvar" }));
      await waitFor(() => expect(apiForm).toHaveBeenCalled());
      expect((apiForm.mock.calls[0][1] as FormData).has("comprovante")).toBe(false);
    });

    it("com comprovante gravado, mostra o link para baixar na própria tela", async () => {
      tela({ ...ENVIADO, comprovante_arquivo: "protocolos/c.pdf" });
      const link = await screen.findByRole("link", { name: "Baixar o comprovante" });
      expect(link.getAttribute("href")).toBe("/api/protocolos/9/comprovante");
    });

    it("sem comprovante gravado, não mostra link", async () => {
      tela(ENVIADO);
      await screen.findByLabelText("Nº do protocolo no órgão");
      expect(screen.queryByRole("link", { name: "Baixar o comprovante" })).toBeNull();
    });

    it("mostra a recusa do servidor em português (arquivo que não é PDF ou grande demais)", async () => {
      const { ApiErro } = await import("./api");
      const e = new ApiErro(413, "");
      e.message = "Arquivo acima do limite de 10 MB";                 // o mock de ApiErro acima so' guarda a mensagem
      apiForm.mockRejectedValueOnce(e);
      tela(ENVIADO);
      fireEvent.change(await screen.findByLabelText("Anexar o comprovante do órgão (PDF)"), { target: { files: [pdf()] } });
      fireEvent.click(screen.getByRole("button", { name: "Salvar" }));
      expect(await screen.findByText("Arquivo acima do limite de 10 MB")).toBeTruthy();
    });
  });

  // issue #27: carta editada pede confirmação; protocolo enviado não prende a tela
  it("carta editada pede confirmação ao sair; protocolo enviado não prende a tela", () => {
    window.history.replaceState(null, "", "/obras/1/medicoes/5");
    const confirmar = vi.spyOn(window, "confirm").mockReturnValue(false);
    const tela = (situacao: string) => (
      <ProtocolosDaMedicao contratoId={1} medicaoId={5} dados={{ ...LISTA, protocolos: [{ ...PROT, situacao }] }}
        carregar={async () => {}} podeEditar aoMudar={() => {}} />);
    const { rerender } = render(tela("rascunho"));
    fireEvent.change(document.getElementById("carta-9")!, { target: { value: "Texto alterado  " } });
    ir({ tela: "avisos" });
    expect(confirmar).toHaveBeenCalledTimes(1);
    expect(window.location.pathname).toBe("/obras/1/medicoes/5");
    rerender(tela("enviado"));
    ir({ tela: "avisos" });
    expect(confirmar).toHaveBeenCalledTimes(1);
    expect(window.location.pathname).toBe("/avisos");
    vi.restoreAllMocks();
  });
});
