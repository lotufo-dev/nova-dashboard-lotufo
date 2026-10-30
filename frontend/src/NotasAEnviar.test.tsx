import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiErro } from "./api";
import NotasAEnviar from "./NotasAEnviar";

const { api, apiForm, baixarArquivo } = vi.hoisted(() => ({ api: vi.fn(), apiForm: vi.fn(), baixarArquivo: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api, apiForm, baixarArquivo }));

const envio = (chave: string, obra: string, grupo: string, extra: Record<string, unknown> = {}) => ({
  chave, contrato_id: 12, obra, orgao: grupo, orgao_sub: null, familia: "sinfra", grupo, a_pedido: false,
  medicao_ids: [637], descricao: "14ª medição", notas: [{ numero: "2340", natureza: "execucao", valor_centavos: 241890633 }],
  valor_centavos: 241890633, emitida_em: "2026-10-08", dias: 1, situacao: "pronto", aviso: null, protocolo_id: null,
  itens: [{ chave: "notas", rotulo: "Notas fiscais (1)", detalhe: "NFS 2340", estado: "ok" }], ...extra });

const CERTIDOES = { itens: [
  { entidade_id: 1, entidade: "Rivoli", tipo: "Federal", chave: "federal", situacao: "ok", validade: "2027-01-12", dias: 90 },
  { entidade_id: 1, entidade: "Rivoli", tipo: "Municipal", chave: "municipal", situacao: "vencendo", validade: "2026-10-22", dias: 6 }] };

function responder(lista: unknown, certidoes: unknown = CERTIDOES) {
  api.mockImplementation(async (url: string) => (url.startsWith("/api/contratos/") ? certidoes : lista));
}

// Medições › Enviar nota (#157, 16/10/2026): a aba só mostra o que vai junto e o que falta, e leva à etapa 4 da medição
describe("Aba Enviar nota", () => {
  afterEach(() => { cleanup(); api.mockReset(); apiForm.mockReset(); });

  it("lista à esquerda com o selo de cada nota e o detalhe da escolhida à direita; bloqueado não leva ao envio", async () => {
    responder({
      envios: [
        envio("c12:m637", "MT-388 Porto Esperidião/Cáceres", "SINFRA", {
          situacao: "bloqueado", aviso: "certidão federal da Rivoli vencida",
          itens: [{ chave: "certidoes:rivoli", rotulo: "Certidões Rivoli (4 de 5)", detalhe: "Federal vencida", estado: "vencida" }] }),
        envio("c20:m700", "Complexo Xtreme", "MTPAR", { medicao_ids: [700], contrato_id: 20 }),
      ],
      contadores: { Todas: 2 },
    }, { itens: [] });   // sem certidões carregadas o resumo "Vencida" fica fixo; com elas ele é trocado pela lista, e o teste ficava dependente da ordem das respostas
    render(<NotasAEnviar busca={{}} podeEditar />);
    // as pilulas de filtro sao so' o rotulo, sem contador
    expect((await screen.findByRole("link", { name: "Todas" })).textContent).toBe("Todas");
    expect(screen.getByRole("link", { name: "Com pendência" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "MTPAR" }).textContent).toContain("Pronto");
    const painel = screen.getByRole("complementary", { name: "Envio selecionado" });
    expect(within(painel).getByRole("heading").textContent).toContain("MT-388");
    expect(within(painel).getByText("Vencida")).toBeTruthy();
    expect(within(painel).getByText(/Envio bloqueado: certidão federal da Rivoli vencida/)).toBeTruthy();
    expect((within(painel).getByRole("button", { name: /Enviar a nota/ }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("não envia, não anexa nem registra por fora na aba: o botão leva à etapa 4 da medição", async () => {
    responder({ envios: [envio("c20:m700", "Complexo Xtreme", "MTPAR", { medicao_ids: [700], contrato_id: 20, itens: [
      { chave: "frc:700", rotulo: "FRC assinada", estado: "falta", acao: "anexar_frc", medicao_id: 700, frc_gerada: 13,
        detalhe: "falta · a FRC nº 13 já foi gerada" }] })], contadores: { Todas: 1 } });
    render(<NotasAEnviar busca={{}} podeEditar />);
    const painel = await screen.findByRole("complementary", { name: "Envio selecionado" });
    expect(within(painel).getByRole("link", { name: /Enviar a nota/ }).getAttribute("href")).toBe("/obras/20/medicoes/700#etapa-4");
    expect(within(painel).getByRole("link", { name: "Abrir a medição" }).getAttribute("href")).toBe("/obras/20/medicoes/700");
    // a FRC que falta: o link leva aonde se anexa, em vez de oferecer o anexo
    expect(within(painel).getByRole("link", { name: "Anexar na etapa 4" }).getAttribute("href")).toBe("/obras/20/medicoes/700#etapa-4");
    expect(within(painel).getByRole("link", { name: /Baixar a FRC gerada \(nº 13\)/ })).toBeTruthy();
    expect(within(painel).queryByLabelText(/Anexar/)).toBeNull();
    expect(within(painel).queryByText(/Registrar envio feito por fora/)).toBeNull();
    // sem frase de onde fazer nem motivo que so' repete o selo
    expect(within(painel).queryByText(/se fazem na etapa 4/)).toBeNull();
    expect(within(painel).queryByText(/veja na etapa 4|anexe na etapa 4|ou envie assim/)).toBeNull();
    expect(screen.getByRole("region", { name: "MTPAR" }).textContent).toContain("Falta FRC assinada");
    expect(api.mock.calls.some(c => c[1]?.method === "POST")).toBe(false);
  });

  it("a FRC gerada baixa pelo download que mostra a recusa do servidor (issue #169)", async () => {
    responder({ envios: [envio("c20:m700", "Complexo Xtreme", "MTPAR", { medicao_ids: [700], contrato_id: 20, itens: [
      { chave: "frc:700", rotulo: "FRC assinada", estado: "falta", acao: "anexar_frc", medicao_id: 700, frc_gerada: 13, detalhe: "falta" }] })],
      contadores: { Todas: 1 } });
    baixarArquivo.mockRejectedValueOnce(new ApiErro(409, "A FRC ficou desatualizada: gere de novo"));
    render(<NotasAEnviar busca={{}} podeEditar />);
    fireEvent.click(await screen.findByRole("link", { name: /Baixar a FRC gerada/ }));
    expect(baixarArquivo).toHaveBeenCalledWith("/api/medicoes/700/frc/pdf", "FRC.pdf");
    expect((await screen.findByRole("alert")).textContent).toContain("A FRC ficou desatualizada");
  });

  it("no que vai junto, a certidão em dia não mostra data; a que vence mostra", async () => {
    responder({ envios: [envio("c12:m637", "MT-388", "SINFRA", { itens: [
      { chave: "certidoes:rivoli", rotulo: "Certidões Rivoli (5)", detalhe: "municipal vence em 6 dias", estado: "aviso" }] })],
      contadores: { Todas: 1 } });
    render(<NotasAEnviar busca={{}} podeEditar />);
    const painel = await screen.findByRole("complementary", { name: "Envio selecionado" });
    expect(await within(painel).findByText(/vence em 22\/10\/2026/)).toBeTruthy();
    expect(within(painel).queryByText(/12\/01\/2027/)).toBeNull();
    expect(within(painel).queryByText(/vence em 6 dias|conferidas hoje/)).toBeNull();
    expect(within(painel).queryByText("Certidões Rivoli (5)")).toBeNull();   // o resumo cede lugar à lista
    // a certidão que só avisa não tira o envio de "Prontas" nem ganha frase
    expect(screen.getByRole("region", { name: "SINFRA" }).textContent).toContain("Pronto");
    expect(within(painel).queryByText(/Certidão vencida/)).toBeNull();
  });

  it("certidão vencida: a frase com o link para Documentos aparece só com ela", async () => {
    responder({ envios: [envio("c12:m637", "MT-388", "SINFRA")], contadores: { Todas: 1 } }, { itens: [
      { entidade_id: 1, entidade: "Rivoli", tipo: "Federal", chave: "federal", situacao: "pendente", validade: null, dias: null }] });
    render(<NotasAEnviar busca={{}} podeEditar />);
    const painel = await screen.findByRole("complementary", { name: "Envio selecionado" });
    expect((await within(painel).findByText(/Certidão vencida: emita a nova em/)).textContent).toBe("Certidão vencida: emita a nova em Documentos.");
    expect(within(painel).getByRole("link", { name: "Documentos" }).getAttribute("href")).toBe("/documentos");
  });

  it("painel: só órgão e data das notas; a pedido do órgão vira selo", async () => {
    responder({ envios: [envio("c12:m637", "Obra C", "Pref. Cuiabá", { a_pedido: true, dias: 5,
      notas: [{ numero: "1", natureza: "execucao", valor_centavos: 100 }, { numero: "2", natureza: "execucao", valor_centavos: 200 }] })],
      contadores: { Todas: 1 } });
    render(<NotasAEnviar busca={{}} podeEditar />);
    const painel = await screen.findByRole("complementary", { name: "Envio selecionado" });
    expect(painel.querySelector(".nota-painel__meta")?.textContent).toBe("Pref. Cuiabá · 08/10/2026");
    expect(within(painel).getByRole("heading").textContent).toContain("A pedido do órgão");
    expect(within(painel).queryByText(/Soma das|parada há|2 notas de/)).toBeNull();
    expect(screen.getByRole("region", { name: "Pref. Cuiabá" }).querySelector(".nota-grupo__titulo .selo")?.textContent).toBe("A pedido do órgão");
    expect(screen.getByRole("button", { name: /Obra C/ }).textContent).toContain("NF 1, 2");
    expect(screen.getByRole("button", { name: /Obra C/ }).textContent).not.toContain("emitida");
  });

  it("filtra pela situação e pelo órgão", async () => {
    responder({ envios: [envio("a", "Obra A", "SINFRA"), envio("b", "Obra B", "MTPAR", { situacao: "esperando", espera: { tipo: "reajuste", texto: "x" } })],
      contadores: {} });
    render(<NotasAEnviar busca={{ situacao: "pendencia" }} podeEditar />);
    expect(await screen.findByRole("region", { name: "MTPAR" })).toBeTruthy();
    expect(screen.queryByRole("region", { name: "SINFRA" })).toBeNull();
    expect(screen.getByRole("link", { name: /Com pendência/ }).getAttribute("aria-current")).toBe("true");
    expect(screen.getByRole("combobox", { name: "Órgão" })).toBeTruthy();
  });

  it("diretoria vê o que vai junto, sem o botão de enviar nem de anexar", async () => {
    responder({ envios: [envio("c20:m700", "Complexo Xtreme", "MTPAR", { itens: [
      { chave: "regularidade:lotufo", rotulo: "Regularidade mensal", detalhe: "O DP ainda não enviou", estado: "falta",
        acao: "anexar_regularidade", entidade_id: 1, competencia: "2026-08" }] })], contadores: { Todas: 1 } });
    render(<NotasAEnviar busca={{}} podeEditar={false} />);
    const painel = await screen.findByRole("complementary", { name: "Envio selecionado" });
    expect(within(painel).getByText("Regularidade mensal")).toBeTruthy();
    expect(within(painel).queryByRole("link", { name: /Enviar a nota/ })).toBeNull();
    expect(within(painel).queryByRole("button", { name: /Enviar a nota/ })).toBeNull();
    expect(within(painel).queryByLabelText(/Anexar/)).toBeNull();
  });

  // issue #188: na SINFRA a medicao e o reajuste vao juntos; sem as notas do reajuste, o envio da medicao espera
  it("envio esperando as notas do reajuste: aviso e caminho para a saída de emergência, sem botão de enviar", async () => {
    responder({ envios: [envio("c12:m637", "MT-388", "SINFRA", { situacao: "esperando", aviso: "Esperando as notas do reajuste",
      espera: { medicao_id: 638, titulo: "Reajuste da 14ª Medição", tipo: "reajuste", texto: "esperando as notas do reajuste" } })],
      contadores: { Todas: 1 } });
    render(<NotasAEnviar busca={{}} podeEditar />);
    const painel = await screen.findByRole("complementary", { name: "Envio selecionado" });
    expect(screen.getByRole("region", { name: "SINFRA" }).textContent).toContain("Esperando o reajuste");
    // uma frase so', com o link da etapa 4 (e nao repetida no rodape)
    expect(within(painel).getByText(/Esperando as notas do reajuste; para enviar sem ele, abra a/)).toBeTruthy();
    expect(within(painel).getAllByText(/Esperando as notas do reajuste/)).toHaveLength(1);
    expect(within(painel).queryByText(/no mesmo e-mail/)).toBeNull();
    expect(within(painel).getAllByRole("link", { name: "etapa 4 da medição" })[0].getAttribute("href")).toContain("637#etapa-4");
    expect(within(painel).queryByRole("button", { name: /Enviar a nota/ })).toBeNull();
    expect(within(painel).queryByRole("link", { name: /Enviar a nota/ })).toBeNull();
  });

  it("vazio: uma linha curta, sem explicação", async () => {
    api.mockResolvedValue({ envios: [], contadores: { Todas: 0 } });
    render(<NotasAEnviar busca={{}} podeEditar />);
    expect(await screen.findByText("Nenhuma nota a enviar.")).toBeTruthy();
    expect(screen.queryByText(/sincronização com o RM/)).toBeNull();
  });

  it("escolher outra nota troca o detalhe", async () => {
    responder({ envios: [envio("a", "Obra A", "SINFRA"), envio("b", "Obra B", "SINFRA", { medicao_ids: [9] })], contadores: {} });
    render(<NotasAEnviar busca={{}} podeEditar />);
    await screen.findByRole("complementary", { name: "Envio selecionado" });
    fireEvent.click(screen.getByRole("button", { name: /Obra B/ }));
    expect(within(screen.getByRole("complementary", { name: "Envio selecionado" })).getByRole("heading").textContent).toContain("Obra B");
  });
});
