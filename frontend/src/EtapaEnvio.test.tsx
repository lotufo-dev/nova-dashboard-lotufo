import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiErro } from "./api";
import { EtapaEnvio } from "./EtapaEnvio";
import type { Envio } from "./NotasAEnviar";

const { api, apiForm } = vi.hoisted(() => ({ api: vi.fn(), apiForm: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api, apiForm }));
// o e-mail montado tem os proprios testes (EnviarNota.test.tsx)
vi.mock("./EnviarNota", () => ({ default: ({ protocoloId }: { protocoloId: number }) => <div>E-mail do envio {protocoloId}</div> }));

const envio = (extra: Partial<Envio> = {}): Envio => ({
  chave: "c20:m631", contrato_id: 20, obra: "MT-401", orgao: "SINFRA", orgao_sub: null, familia: "sinfra", grupo: "SINFRA", a_pedido: false,
  medicao_ids: [631], descricao: "7ª medição", notas: [{ numero: "2322", natureza: "execucao", valor_centavos: 100 }],
  valor_centavos: 123456, emitida_em: "2026-10-08", dias: 2, situacao: "pronto", aviso: null, protocolo_id: null, itens: [], ...extra });

function montar(envios: Envio[], extra: Partial<Parameters<typeof EtapaEnvio>[0]> = {}) {
  const props = { medicaoId: 631, envios, erro: "", recarregarEnvios: vi.fn(async () => {}), podeEditar: true, versaoDocs: 0, aoAnexarItem: vi.fn(),
    aoMudar: vi.fn(), pronta: null, orgao: "SINFRA", aoSemAOutra: vi.fn(), ...extra };
  render(<EtapaEnvio {...props} />);
  return props;
}

describe("Etapa 4: o envio ao órgão", () => {
  afterEach(() => { cleanup(); api.mockReset(); apiForm.mockReset(); });

  it("uma linha por envio, com as notas, o valor, o selo dos documentos e “Enviar a nota” ativo", async () => {
    api.mockResolvedValue({ itens: [] });
    montar([envio({ chave: "a", descricao: "7ª medição" }), envio({ chave: "b", descricao: "Reajuste da 7ª medição", medicao_ids: [632],
      notas: [{ numero: "2323", natureza: "reajuste", valor_centavos: 1 }] })]);
    const linhas = screen.getAllByRole("row").slice(1);
    expect(linhas).toHaveLength(2);
    expect(within(linhas[0]).getByText("NF 2322")).toBeTruthy();
    expect(within(linhas[0]).getByText("Completo")).toBeTruthy();
    expect(within(linhas[1]).getByText("Reajuste da 7ª medição")).toBeTruthy();
    expect((within(linhas[0]).getByRole("button", { name: "Enviar a nota" }) as HTMLButtonElement).disabled).toBe(false);
    expect(screen.getByText(/em ofícios e e-mails separados/)).toBeTruthy();
  });

  it("com documento faltando, “Enviar a nota” segue ativo e o motivo vem ao lado; só o bloqueio desabilita", async () => {
    api.mockResolvedValue({ itens: [] });
    montar([envio({ chave: "a", itens: [{ chave: "frc:631", rotulo: "FRC assinada", estado: "falta", acao: "anexar_frc" }] }),
      envio({ chave: "b", situacao: "bloqueado", aviso: "certidão trabalhista vencida" })]);
    const [faltando, bloqueado] = screen.getAllByRole("row").slice(1);
    expect(within(faltando).getByText("Falta FRC assinada: anexe no envio, ou envie assim.")).toBeTruthy();
    expect((within(faltando).getByRole("button", { name: "Enviar a nota" }) as HTMLButtonElement).disabled).toBe(false);
    expect(within(bloqueado).getByText(/Envio bloqueado: certidão trabalhista vencida/)).toBeTruthy();
    expect((within(bloqueado).getByRole("button", { name: "Enviar a nota" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("“Enviar a nota” de um envio já começado abre o e-mail na mesma página e “Fechar o envio” o fecha", async () => {
    api.mockResolvedValue({ itens: [] });
    montar([envio({ protocolo_id: 3 })]);
    fireEvent.click(screen.getByRole("button", { name: "Enviar a nota" }));
    expect(screen.getByText("E-mail do envio 3")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Fechar o envio" }));
    expect(screen.queryByText("E-mail do envio 3")).toBeNull();
  });

  it("SINFRA: inicia o envio sem pedir o ofício; MTPAR e SES pedem o nº do ofício numa janela", async () => {
    api.mockImplementation(async (url: string) => (url === "/api/notas/envio/iniciar" ? { protocolo_id: 8 } : { itens: [] }));
    const p = montar([envio({ familia: "mtpar", grupo: "MTPAR" })]);
    fireEvent.click(screen.getByRole("button", { name: "Enviar a nota" }));
    const ofi = screen.getByLabelText("Nº do ofício");
    expect((screen.getByRole("button", { name: "Começar o envio" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(ofi, { target: { value: "361" } });
    fireEvent.click(screen.getByRole("button", { name: "Começar o envio" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/notas/envio/iniciar",
      { method: "POST", body: JSON.stringify({ contrato_id: 20, medicao_ids: [631], numero_oficio: "361" }) }));
    await waitFor(() => expect(p.recarregarEnvios).toHaveBeenCalled());
  });

  it("SINFRA começa direto, sem ofício", async () => {
    api.mockImplementation(async (url: string) => (url === "/api/notas/envio/iniciar" ? { protocolo_id: 8 } : { itens: [] }));
    montar([envio()]);
    fireEvent.click(screen.getByRole("button", { name: "Enviar a nota" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/notas/envio/iniciar",
      { method: "POST", body: JSON.stringify({ contrato_id: 20, medicao_ids: [631] }) }));
    expect(screen.queryByLabelText("Nº do ofício")).toBeNull();
  });

  it("quem só consulta vê a tabela, sem botão de enviar nem de registrar fora", async () => {
    api.mockResolvedValue({ itens: [] });
    montar([envio()], { podeEditar: false });
    expect(screen.getByText("NF 2322")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Enviar a nota" })).toBeNull();
    expect(screen.queryByText("Registrar envio feito fora do sistema")).toBeNull();
  });

  it("envio esperando a outra metade: a linha tem a saída de emergência em vez de “Enviar a nota”", async () => {
    api.mockResolvedValue({ itens: [] });
    const p = montar([envio({ situacao: "esperando", aviso: "esperando as notas do reajuste" })],
      { pronta: { medicao_id: 631, tipo: "execucao", titulo: "7ª Medição", estado: "nota_emitida", faltam: 0, esperadas: [], completa: true, espera: null, liberacao: null } });
    expect(screen.queryByRole("button", { name: "Enviar a nota" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Enviar a medição sem o reajuste…" }));
    expect(p.aoSemAOutra).toHaveBeenCalled();
    // esperando a outra metade, o registro por fora também espera
    expect(screen.queryByText("Registrar envio feito fora do sistema")).toBeNull();
  });

  it("as certidões vêm com a validade de cada uma", async () => {
    api.mockResolvedValue({ itens: [
      { entidade_id: 1, entidade: "Lotufo", tipo: "FGTS", chave: "fgts", situacao: "ok", validade: "2026-11-30", dias: 40 },
      { entidade_id: 1, entidade: "Lotufo", tipo: "Municipal", chave: "municipal", situacao: "vencendo", validade: "2026-10-22", dias: 6 }] });
    montar([envio()]);
    expect(await screen.findByText(/válida até 30\/11\/2026/)).toBeTruthy();
    expect(screen.getByText(/válida até 22\/10\/2026 · vence em 6 dias/)).toBeTruthy();
  });

  it("erro ao ler os envios e medição fora de Notas a enviar dizem o que houve", () => {
    montar([], { erro: "servidor fora" });
    expect(screen.getByRole("alert").textContent).toContain("servidor fora");
    cleanup();
    montar([]);
    expect(screen.getByText(/não aparece em Notas a enviar/)).toBeTruthy();
  });
});

// 16/10/2026: "Registrar envio feito por fora" e "Registrar protocolo feito fora" viraram uma ação só, na etapa 4
describe("Etapa 4: registrar envio feito fora do sistema", () => {
  afterEach(() => { cleanup(); api.mockReset(); apiForm.mockReset(); });
  const irmas = [{ medicao_id: 632, titulo: "Reajuste da 7ª Medição", tipo: "reajuste" }];
  const COMO = "Como e para quem a nota foi enviada";

  async function abrir(envios: Envio[]) {
    api.mockResolvedValue({ itens: [] });
    apiForm.mockResolvedValue({ ok: true });
    const p = montar(envios);
    fireEvent.click(screen.getByText("Registrar envio feito fora do sistema"));
    return p;
  }
  const dois = () => [envio({ chave: "a" }), envio({ chave: "b", medicao_ids: [632], descricao: "Reajuste da 7ª medição" })];

  it("data, ofício, processo e .eml opcionais; a irmã vem marcada e o registro leva as duas medições", async () => {
    const p = await abrir([envio({ irmas })]);
    expect((screen.getByLabelText("Incluir também o Reajuste da 7ª Medição (saiu no mesmo e-mail)") as HTMLInputElement).checked).toBe(true);
    expect(screen.getByLabelText("Nº do ofício (opcional)")).toBeTruthy();
    expect(screen.getByLabelText("Nº do processo no órgão (opcional)")).toBeTruthy();
    expect(screen.getByLabelText("E-mail enviado (.eml, opcional)")).toBeTruthy();
    fireEvent.change(screen.getByLabelText(COMO), { target: { value: "Pelo Outlook" } });
    fireEvent.click(screen.getByRole("button", { name: "Registrar" }));
    await waitFor(() => expect(p.aoMudar).toHaveBeenCalledWith(
      "Envio registrado: esta nota e a do Reajuste da 7ª Medição foram para Aguardando pagamento."));
    const [caminho, fd] = apiForm.mock.calls[0] as [string, FormData];
    expect(caminho).toBe("/api/notas/envio-externo");
    expect([fd.getAll("medicao_ids"), fd.getAll("irma_ids")]).toEqual([["631"], ["632"]]);
    expect(api.mock.calls.some(c => c[0] === "/api/notas/envio/iniciar")).toBe(false);
  });

  it("a observação é obrigatória (vira a justificativa na auditoria) e não há texto padrão", async () => {
    await abrir([envio()]);
    const botao = screen.getByRole("button", { name: "Registrar" }) as HTMLButtonElement;
    expect(botao.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText(COMO), { target: { value: "   " } });
    expect(botao.disabled).toBe(true);
    expect(apiForm).not.toHaveBeenCalled();
  });

  it("o ofício vai no campo próprio (issue #231), a observação sai sem ele e o processo vai no nº do órgão da medição", async () => {
    const p = await abrir([envio()]);
    fireEvent.change(screen.getByLabelText("Nº do ofício (opcional)"), { target: { value: "360/2026" } });
    fireEvent.change(screen.getByLabelText("Nº do processo no órgão (opcional)"), { target: { value: "0001234-56.2026" } });
    fireEvent.change(screen.getByLabelText(COMO), { target: { value: "Pelo Outlook" } });
    fireEvent.click(screen.getByRole("button", { name: "Registrar" }));
    await waitFor(() => expect(p.aoMudar).toHaveBeenCalled());
    const fd = apiForm.mock.calls[0][1] as FormData;
    expect([fd.get("numero_oficio"), fd.get("observacao")]).toEqual(["360/2026", "Pelo Outlook"]);
    expect(api).toHaveBeenCalledWith("/api/notas/631/numero-orgao", { method: "POST", body: JSON.stringify({ numero: "0001234-56.2026" }) });
  });

  it("com mais de um envio marcado, o ofício fica fechado e não vai (cada envio tem o seu, como o processo)", async () => {
    const p = await abrir(dois());
    fireEvent.change(screen.getByLabelText("Nº do ofício (opcional)"), { target: { value: "360" } });
    fireEvent.click(screen.getByLabelText(/Reajuste da 7ª medição/));
    const campo = screen.getByLabelText("Nº do ofício (opcional)") as HTMLInputElement;
    expect([campo.disabled, campo.value]).toEqual([true, ""]);
    fireEvent.change(screen.getByLabelText(COMO), { target: { value: "Pelo Outlook" } });
    fireEvent.click(screen.getByRole("button", { name: "Registrar" }));
    await waitFor(() => expect(p.aoMudar).toHaveBeenCalled());
    expect(apiForm.mock.calls.map(c => (c[1] as FormData).has("numero_oficio"))).toEqual([false, false]);
  });

  it("sem ofício, o registro não manda o campo e a observação vai como digitada", async () => {
    const p = await abrir([envio()]);
    // o mesmo teto do servidor (o do ofício no envio pelo sistema)
    expect((screen.getByLabelText("Nº do ofício (opcional)") as HTMLInputElement).maxLength).toBe(40);
    fireEvent.change(screen.getByLabelText("Nº do ofício (opcional)"), { target: { value: "   " } });
    fireEvent.change(screen.getByLabelText(COMO), { target: { value: "Pelo Outlook" } });
    fireEvent.click(screen.getByRole("button", { name: "Registrar" }));
    await waitFor(() => expect(p.aoMudar).toHaveBeenCalled());
    const fd = apiForm.mock.calls[0][1] as FormData;
    expect([fd.has("numero_oficio"), fd.get("observacao")]).toEqual([false, "Pelo Outlook"]);
  });

  it("se o nº do processo não entrar, o envio já gravado não se perde: avisa e manda registrá-lo na etapa 4", async () => {
    const p = await abrir([envio()]);
    api.mockRejectedValueOnce(new ApiErro(422, "Medição sem envio registrado"));
    fireEvent.change(screen.getByLabelText("Nº do processo no órgão (opcional)"), { target: { value: "123" } });
    fireEvent.change(screen.getByLabelText(COMO), { target: { value: "Pelo Outlook" } });
    fireEvent.click(screen.getByRole("button", { name: "Registrar" }));
    await waitFor(() => expect(p.aoMudar).toHaveBeenCalled());
    expect((p.aoMudar as ReturnType<typeof vi.fn>).mock.calls[0][0]).toContain("O nº do processo não foi gravado");
  });

  it("MTPAR, dois envios: só o da medição da página começa marcado; o processo só vale com um envio marcado", async () => {
    await abrir(dois());
    const [medicao, reajuste] = screen.getAllByRole("checkbox") as HTMLInputElement[];
    expect([medicao.checked, reajuste.checked]).toEqual([true, false]);
    const processo = screen.getByLabelText("Nº do processo no órgão (opcional)") as HTMLInputElement;
    expect(processo.disabled).toBe(false);
    fireEvent.click(reajuste);
    expect(processo.disabled).toBe(true);
    expect(screen.getByText(/Cada envio tem o seu/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText(COMO), { target: { value: "Pelo Outlook" } });
    fireEvent.click(screen.getByRole("button", { name: "Registrar" }));
    await waitFor(() => expect(apiForm).toHaveBeenCalledTimes(2));
  });

  it("falha no segundo envio: o primeiro fica dito como registrado e a página só lê de novo ao fechar a janela", async () => {
    const p = await abrir(dois());
    fireEvent.click(screen.getAllByRole("checkbox")[1]);
    fireEvent.change(screen.getByLabelText(COMO), { target: { value: "Pelo Outlook" } });
    apiForm.mockResolvedValueOnce({ ok: true }).mockRejectedValueOnce(new ApiErro(422, "Medição 632 não está com a nota emitida"));
    fireEvent.click(screen.getByRole("button", { name: "Registrar" }));
    const alerta = await screen.findByRole("alert");
    expect(alerta.textContent).toContain("não está com a nota emitida");
    expect(alerta.textContent).toContain("Já registrados: 7ª medição");
    expect(p.aoMudar).not.toHaveBeenCalled();   // recarregar agora trocaria a etapa e levaria o erro junto
    fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));
    expect(p.aoMudar).toHaveBeenCalledTimes(1);
    expect((p.aoMudar as ReturnType<typeof vi.fn>).mock.calls[0]).toEqual([]);
  });

  it("o nº do processo digitado é limpo quando passa a haver mais de um envio marcado", async () => {
    await abrir(dois());
    const processo = screen.getByLabelText("Nº do processo no órgão (opcional)") as HTMLInputElement;
    fireEvent.change(processo, { target: { value: "0001234" } });
    fireEvent.click(screen.getAllByRole("checkbox")[1]);
    expect(processo.value).toBe("");
    fireEvent.click(screen.getAllByRole("checkbox")[1]);
    expect(processo.value).toBe("");
    expect(processo.disabled).toBe(false);
  });

  it("desmarcada a irmã, o registro leva só a medição do envio", async () => {
    await abrir([envio({ irmas })]);
    fireEvent.click(screen.getByLabelText("Incluir também o Reajuste da 7ª Medição (saiu no mesmo e-mail)"));
    fireEvent.change(screen.getByLabelText(COMO), { target: { value: "Pelo Outlook" } });
    fireEvent.click(screen.getByRole("button", { name: "Registrar" }));
    await waitFor(() => expect(apiForm).toHaveBeenCalled());
    expect((apiForm.mock.calls[0][1] as FormData).getAll("irma_ids")).toEqual([]);
  });

  it("erro do servidor fica na janela e nada é dado como registrado", async () => {
    const p = await abrir([envio()]);
    apiForm.mockRejectedValueOnce(new ApiErro(422, "Medição 631 não está com a nota emitida"));
    fireEvent.change(screen.getByLabelText(COMO), { target: { value: "Pelo Outlook" } });
    fireEvent.click(screen.getByRole("button", { name: "Registrar" }));
    expect((await screen.findByRole("alert")).textContent).toContain("não está com a nota emitida");
    expect(p.aoMudar).not.toHaveBeenCalled();
  });

  // issue #230: o registro por fora segue a regra do envio (#213): o que falta pede a confirmação, não bloqueia
  const FALTA = ["FRC assinada: Falta a FRC assinada", "Certidões Lotufo (5): federal vencida em 10/09"];
  const pedeConfirmacao = (pendencias = FALTA) => new ApiErro(422, "ATENÇÃO: falta documento neste envio",
    { codigo: "CONFIRMAR_PENDENCIAS", mensagem: "ATENÇÃO: falta documento neste envio", pendencias });

  it("com documento faltando, abre o “ATENÇÃO” com a lista; Cancelar não registra nada", async () => {
    const p = await abrir([envio()]);
    apiForm.mockRejectedValueOnce(pedeConfirmacao());
    fireEvent.change(screen.getByLabelText(COMO), { target: { value: "Pelo Outlook" } });
    fireEvent.click(screen.getByRole("button", { name: "Registrar" }));
    const aviso = await screen.findByRole("alertdialog");
    expect(aviso.textContent).toContain("ATENÇÃO");
    for (const x of FALTA) expect(within(aviso).getByText(x)).toBeTruthy();
    expect(within(aviso).getByText("Deseja continuar com o registro do envio?")).toBeTruthy();
    expect(within(aviso).queryByRole("button", { name: "Continuar com o envio" })).toBeNull();
    fireEvent.click(within(aviso).getByRole("button", { name: "Cancelar" }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(apiForm).toHaveBeenCalledTimes(1);
    expect(p.aoMudar).not.toHaveBeenCalled();
    expect((screen.getByRole("button", { name: "Registrar" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("Esc no aviso só fecha o aviso: a janela do registro (<dialog>) não recebe o Esc", async () => {
    await abrir([envio()]);
    apiForm.mockRejectedValueOnce(pedeConfirmacao());
    fireEvent.change(screen.getByLabelText(COMO), { target: { value: "Pelo Outlook" } });
    fireEvent.click(screen.getByRole("button", { name: "Registrar" }));
    const aviso = await screen.findByRole("alertdialog");
    // sem o preventDefault, o navegador fecharia o <dialog> da janela junto (pedido de fechar do Esc)
    expect(fireEvent.keyDown(aviso, { key: "Escape" })).toBe(false);
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(screen.getByText("Registrar envio feito fora do sistema", { selector: "h2" })).toBeTruthy();
  });

  it("“Continuar com o registro” manda a lista confirmada e registra", async () => {
    const p = await abrir([envio()]);
    apiForm.mockRejectedValueOnce(pedeConfirmacao());
    fireEvent.change(screen.getByLabelText(COMO), { target: { value: "Pelo Outlook" } });
    fireEvent.click(screen.getByRole("button", { name: "Registrar" }));
    fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Continuar com o registro" }));
    await waitFor(() => expect(p.aoMudar).toHaveBeenCalled());
    expect(apiForm).toHaveBeenCalledTimes(2);
    const [primeiro, segundo] = apiForm.mock.calls.map(c => c[1] as FormData);
    expect(primeiro.getAll("confirmadas")).toEqual([]);
    expect(segundo.getAll("confirmadas")).toEqual(FALTA);
    expect(String(segundo.get("observacao"))).toBe("Pelo Outlook");     // a observação continua indo
  });

  it("a lista mudou depois da confirmação: o aviso abre de novo com a lista de agora", async () => {
    await abrir([envio()]);
    apiForm.mockRejectedValueOnce(pedeConfirmacao()).mockRejectedValueOnce(pedeConfirmacao([FALTA[0]]));
    fireEvent.change(screen.getByLabelText(COMO), { target: { value: "Pelo Outlook" } });
    fireEvent.click(screen.getByRole("button", { name: "Registrar" }));
    fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Continuar com o registro" }));
    await waitFor(() => expect(screen.getByText(/O que falta mudou desde a sua confirmação/)).toBeTruthy());
    const aviso = screen.getByRole("alertdialog");
    expect(within(aviso).getByText(FALTA[0])).toBeTruthy();
    expect(within(aviso).queryByText(FALTA[1])).toBeNull();
  });

  it("dois envios e só o segundo com falta: confirmado, o primeiro não é registrado de novo", async () => {
    const p = await abrir(dois());
    fireEvent.click(screen.getAllByRole("checkbox")[1]);
    fireEvent.change(screen.getByLabelText(COMO), { target: { value: "Pelo Outlook" } });
    apiForm.mockResolvedValueOnce({ ok: true }).mockRejectedValueOnce(pedeConfirmacao());
    fireEvent.click(screen.getByRole("button", { name: "Registrar" }));
    fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Continuar com o registro" }));
    await waitFor(() => expect(p.aoMudar).toHaveBeenCalled());
    const medicoes = apiForm.mock.calls.map(c => (c[1] as FormData).getAll("medicao_ids"));
    expect(medicoes).toEqual([["631"], ["632"], ["632"]]);
    expect((apiForm.mock.calls[2][1] as FormData).getAll("confirmadas")).toEqual(FALTA);
    // os dois foram registrados: o aviso final fala dos envios, não só do último
    expect(p.aoMudar).toHaveBeenCalledWith("Envios registrados: as notas foram para Aguardando pagamento.");
  });

  it("Cancelar depois de uma confirmação recusada: o próximo Registrar pergunta de novo, sem a lista antiga", async () => {
    await abrir([envio()]);
    apiForm.mockRejectedValueOnce(pedeConfirmacao()).mockRejectedValueOnce(pedeConfirmacao([FALTA[0]]))
      .mockRejectedValueOnce(pedeConfirmacao([FALTA[0]]));
    fireEvent.change(screen.getByLabelText(COMO), { target: { value: "Pelo Outlook" } });
    fireEvent.click(screen.getByRole("button", { name: "Registrar" }));
    fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Continuar com o registro" }));
    await waitFor(() => expect(screen.getByText(/O que falta mudou/)).toBeTruthy());
    fireEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Cancelar" }));
    fireEvent.click(screen.getByRole("button", { name: "Registrar" }));
    await waitFor(() => expect(apiForm).toHaveBeenCalledTimes(3));
    expect((apiForm.mock.calls[2][1] as FormData).getAll("confirmadas")).toEqual([]);
    const aviso = await screen.findByRole("alertdialog");
    expect(within(aviso).queryByText(/O que falta mudou/)).toBeNull();
  });

  it("mudar a irmã descarta a confirmação: a lista confirmada era de outra composição", async () => {
    await abrir([envio({ irmas })]);
    apiForm.mockRejectedValueOnce(pedeConfirmacao()).mockRejectedValueOnce(new ApiErro(0, "Sem conexão com o servidor."))
      .mockResolvedValueOnce({ ok: true });
    fireEvent.change(screen.getByLabelText(COMO), { target: { value: "Pelo Outlook" } });
    fireEvent.click(screen.getByRole("button", { name: "Registrar" }));
    fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Continuar com o registro" }));
    expect((await screen.findByRole("alert")).textContent).toContain("Sem conexão");
    fireEvent.click(screen.getByLabelText("Incluir também o Reajuste da 7ª Medição (saiu no mesmo e-mail)"));
    fireEvent.click(screen.getByRole("button", { name: "Registrar" }));
    await waitFor(() => expect(apiForm).toHaveBeenCalledTimes(3));
    expect((apiForm.mock.calls[2][1] as FormData).getAll("confirmadas")).toEqual([]);
  });

  it("envio bloqueado não oferece o registro", async () => {
    api.mockResolvedValue({ itens: [] });
    montar([envio({ situacao: "bloqueado", aviso: "Federal vencida" })]);
    expect(screen.queryByText("Registrar envio feito fora do sistema")).toBeNull();
  });
});
