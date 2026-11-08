import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiErro } from "./api";
import type { Usuario } from "./Login";
import MedicaoPagina from "./MedicaoPagina";

const { api, apiForm } = vi.hoisted(() => ({ api: vi.fn(), apiForm: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api, apiForm }));
// Cada cartao tem fluxo proprio; aqui so' importa que, ao avisar a pagina, ela releia o que os outros mostram.
vi.mock("./Espelho", () => ({
  default: ({ parte, abrirForm, referencias }: { parte?: string; abrirForm?: boolean; referencias?: Record<number, unknown> }) =>
    <div data-espelho={parte} data-abre-form={String(!!abrirForm)} data-referencias={referencias ? JSON.stringify(referencias) : undefined} />,
}));
// issue #289: a planilha/carta tem teste proprio (PlanilhaCarta.test.tsx); aqui so' importa onde ela aparece
vi.mock("./PlanilhaCarta", async () => ({
  ...(await vi.importActual<typeof import("./PlanilhaCarta")>("./PlanilhaCarta")),
  NovaPlanilhaCarta: ({ inicial }: { inicial?: { numero: number } }) => <div data-nova-planilha={inicial?.numero} />,
  CartaoPlanilha: ({ medicaoId, podeEditar, aoRevisaoPendente, aoEnvioReservado }: { medicaoId: number; podeEditar: boolean;
    aoRevisaoPendente?: (p: boolean | null) => void; aoEnvioReservado?: (r: boolean) => void }) =>
    <div data-cartao-planilha={medicaoId} data-pode-editar={String(podeEditar)}>
      <button type="button" onClick={() => aoEnvioReservado?.(false)}>Sem reserva (teste)</button>
      <button type="button" onClick={() => aoEnvioReservado?.(true)}>Envio reservado (teste)</button>
      <button type="button" onClick={() => aoRevisaoPendente?.(false)}>Sem revisão (teste)</button>
      <button type="button" onClick={() => aoRevisaoPendente?.(null)}>Falha ao conferir (teste)</button>
      <button type="button" onClick={() => aoRevisaoPendente?.(true)}>Revisão pendente (teste)</button>
    </div>,
}));
vi.mock("./Frc", () => ({
  FrcConsorcio: ({ medicaoId }: { medicaoId: number }) => <div data-frc={medicaoId} />,
}));
vi.mock("./Notas", () => ({
  Notas: ({ aoMudar, rotulo, medicao, podeDesfazer }: { aoMudar: () => void; rotulo?: string; medicao: { id: number }; podeDesfazer?: boolean }) =>
    <div data-medicao={medicao.id} data-desfazer={String(!!podeDesfazer)}>{rotulo}<button type="button" onClick={aoMudar}>Anexar nota (teste)</button></div>,
}));
vi.mock("./Protocolo", async () => {
  const real = await vi.importActual<typeof import("./Protocolo")>("./Protocolo");
  return {
    ...real,
    ProtocolosDaMedicao: ({ aoMudar, children }: { aoMudar: () => void; children?: React.ReactNode }) =>
      <div><button type="button" onClick={aoMudar}>Enviar protocolo (teste)</button>{children}</div>,
  };
});

const usuario = { id: 1, nome: "Leonardo Praeiro", email: "l@l.com", perfil: "admin" } as Usuario;
const MEDICAO = { id: 5, numero: 23, tipo: "execucao", competencia: "2026-09", estado: "protocolada",
  valor_protocolado_centavos: 1000000, valor_protocolado_origem: null, valor_atestado_centavos: null,
  valor_atestado_origem: null, atestado_em: null, nf_emitida_em: null, recebida_em: null, congelada: 0,
  protocolos: [], notas: [], documentos: [] };
const LISTA = { familia: "ses", etapas: [], pecas: [], medicoes: [], protocolos: [] };
// #508: o detalhe da medicao que a pagina le para conferir a revisao da planilha/carta (passos 1 e 2)
const V1 = { id: 31, versao: 1, periodo_inicio: "2026-09-01", periodo_fim: "2026-09-30", valor_pedido_centavos: 1000000,
  acumulado_anterior_centavos: 0, motivo: null, criado_em: "2026-10-01 12:00:00", usuario: "Operação" };
const detalhePlanilha = (estado: string, extra: Record<string, unknown> = {}) => ({ id: 5, contrato_id: 1, numero: 23,
  tipo: "execucao", competencia: "2026-09", estado, planilha_enviada_em: estado === "planilha_gerada" ? null : "2026-11-05",
  planilha_envio_origem: "externo", planilhas: [V1], planilha_siga: null,
  envio_planilha: { disponivel: false, motivo: null, envios: [], reserva: null, pecas: [], pecas_do_orgao: [] }, ...extra });

const leituras = (caminho: string) => api.mock.calls.filter(c => c[0] === caminho && !c[1]);
// a pagina abre na etapa da vez; a ancora (#etapa-N) abre outra
const abrirEtapa = (n: number) => window.history.replaceState(null, "", `/obras/1/medicoes/5#etapa-${n}`);
const pagina = (perfil: Usuario["perfil"] = "admin", id = 5) =>
  render(<MedicaoPagina contratoId={1} medicaoId={id} usuario={{ ...usuario, perfil }} origem={null} />);

function responder(extra: Record<string, unknown> = {}) {
  api.mockImplementation(async (url: string) => {
    if (url in extra) return extra[url];
    if (url.endsWith("/cabecalho")) return { obra: "Hospital", orgao: "SES", instrumento: "CT 1/2026", percentual_lotufo_bp: 10000 };
    if (url === "/api/contratos/1/medicoes") return [MEDICAO];
    if (url === "/api/contratos/1/protocolos") return LISTA;
    if (url.startsWith("/api/medicoes/andamento")) return [];
    if (url === "/api/contratos/1/espelho") return { espelhos: [] };
    if (url === "/api/notas/a-enviar") return { envios: [], contadores: {} };
    return {};
  });
}

describe("Página da medição: o trilho, a etapa aberta e a coluna da direita", () => {
  beforeEach(() => window.history.replaceState(null, "", "/obras/1/medicoes/5"));
  afterEach(() => { cleanup(); api.mockReset(); });

  it("abre só a etapa da vez; as outras abrem no lugar dela, com a faixa para voltar", async () => {
    responder({ "/api/contratos/1/medicoes": [{ ...MEDICAO, estado: "nota_emitida" }] });
    const { container } = pagina();
    await screen.findByRole("heading", { name: "Envio da nota", level: 2 });
    expect(container.querySelectorAll(".med-passo")).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "Voltar ao passo atual" })).toBeNull();
    // 100% da Lotufo: o cabecalho nao fala de cota nem de "valores cheios"
    expect(container.querySelector(".med-meta")!.textContent).not.toMatch(/cota|valores cheios/);
    const trilho = screen.getByRole("navigation", { name: "Passos da medição" });
    expect(trilho.querySelector("[aria-current='step']")!.textContent).toContain("Envio da nota");
    fireEvent.click(within(trilho).getByRole("button", { name: /Passo 2: Notas/ }));
    expect(screen.getByRole("heading", { name: "Notas", level: 2 })).toBeTruthy();
    expect(container.querySelectorAll(".med-passo")).toHaveLength(1);
    expect(screen.getByText(/Você está vendo o passo 2, já feito/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Voltar ao passo atual" }));
    expect(screen.getByRole("heading", { name: "Envio da nota", level: 2 })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Voltar ao passo atual" })).toBeNull();
    // etapa que ainda não começou: abre, so' com o selo de que libera depois (o corpo nao repete)
    fireEvent.click(within(trilho).getByRole("button", { name: /Passo 4: Pagamento/ }));
    expect(screen.getByRole("button", { name: "Voltar ao passo atual" })).toBeTruthy();
    expect(screen.getByText("Libera depois do passo 3")).toBeTruthy();
    expect(screen.queryByText("Libera depois do passo 3.")).toBeNull();
  });

  it("a âncora #etapa-N abre a etapa; as âncoras antigas (#notas) abrem a etapa 3", async () => {
    responder();
    abrirEtapa(2);
    pagina();
    expect(await screen.findByRole("heading", { name: "Espelhos", level: 2 })).toBeTruthy();
    cleanup();
    window.history.replaceState(null, "", "/obras/1/medicoes/5#notas");
    pagina();
    expect(await screen.findByRole("heading", { name: "Notas", level: 2 })).toBeTruthy();
  });

  it("o caminho do topo: Medições volta à aba onde a medição está e a obra leva à página da obra", async () => {
    responder({ "/api/contratos/1/medicoes": [{ ...MEDICAO, estado: "nota_emitida" }] });
    pagina();
    const caminho = await screen.findByRole("navigation", { name: "Você está em" });
    await waitFor(() => expect(within(caminho).getByRole("link", { name: "Hospital" })).toBeTruthy());
    expect(within(caminho).getByRole("link", { name: "Medições" }).getAttribute("href")).toBe("/medicoes/em-andamento");
    expect(within(caminho).getByRole("link", { name: "Hospital" }).getAttribute("href")).toBe("/obras/1");
  });

  it("título “Nª Medição + Reajuste”, valores somados e a coluna com Resumo e Linha do tempo", async () => {
    const REAJ = { ...MEDICAO, id: 6, tipo: "reajuste", valor_protocolado_centavos: 50000 };
    responder({ "/api/contratos/1/medicoes": [MEDICAO, REAJ] });
    pagina();
    expect(await screen.findByRole("heading", { name: "Hospital", level: 1 })).toBeTruthy();
    const lateral = screen.getByRole("complementary", { name: "Resumo e linha do tempo" });
    expect(within(lateral).getByText("Resumo da medição")).toBeTruthy();
    expect(within(lateral).getByText("Linha do tempo")).toBeTruthy();
    expect(within(lateral).getByText("Total").closest("div")!.textContent).toContain("10.500,00");
  });

  it("“Mais ações” só tem atestado, boletim, assinatura, medição final, cancelar, desistir e liberar envio preso", async () => {
    responder({ "/api/contratos/1/medicoes": [{ ...MEDICAO, estado: "prevista" }] });
    pagina();
    fireEvent.click(await screen.findByRole("button", { name: /Mais ações/ }));
    const itens = within(screen.getByRole("menu")).getAllByRole("menuitem").map(x => x.textContent);
    // #290: sem boletim ainda, a assinatura (do boletim, no DocuSign) nao aparece
    expect(itens).toEqual(["Definir o atestado", "Registrar boletim", "Marcar como medição final", "Cancelar a medição", "Registrar desistência"]);
    fireEvent.click(screen.getByRole("menuitem", { name: "Cancelar a medição" }));
    expect(screen.getByRole("heading", { name: "Cancelar a medição", level: 2 })).toBeTruthy();
  });

  it("#568: o próximo passo “Registrar o boletim” é um botão que abre o registro do boletim", async () => {
    api.mockImplementation(async (url: string) => {
      if (url.startsWith("/api/medicoes/andamento")) return [{ id: 5, proximo_passo: "registrar o boletim", desde: "2026-11-01" }];
      if (url.endsWith("/cabecalho")) return { obra: "Hospital", orgao: "SES", instrumento: "CT 1/2026", percentual_lotufo_bp: 10000 };
      if (url === "/api/contratos/1/medicoes") return [{ ...MEDICAO, estado: "prevista" }];
      if (url === "/api/contratos/1/protocolos") return LISTA;
      if (url === "/api/contratos/1/espelho") return { espelhos: [] };
      if (url === "/api/notas/a-enviar") return { envios: [], contadores: {} };
      return {};
    });
    pagina();
    fireEvent.click(await screen.findByRole("button", { name: "Registrar o boletim" }));
    expect(await screen.findByText(/Registrar o boletim da 23ª medição/)).toBeTruthy();
  });

  it("quem só consulta não vê “Mais ações”", async () => {
    responder();
    pagina("diretoria");
    await screen.findByRole("heading", { level: 1 });
    expect(screen.queryByRole("button", { name: /Mais ações/ })).toBeNull();
  });

  const ENVIO_COMECADO = { chave: "m5", contrato_id: 1, medicao_ids: [5], protocolo_id: 3, notas: [], itens: [], situacao: "pronto",
    descricao: "23ª medição", valor_centavos: 1, familia: "sinfra", aviso: null };

  it("“Liberar envio preso” não aparece com o envio só começado, sem reserva", async () => {
    responder({ "/api/contratos/1/medicoes": [{ ...MEDICAO, estado: "nota_emitida" }],
      "/api/notas/a-enviar": { envios: [{ ...ENVIO_COMECADO, envio_reservado_em: null }], contadores: {} } });
    pagina();
    fireEvent.click(await screen.findByRole("button", { name: /Mais ações/ }));
    expect(screen.queryByRole("menuitem", { name: "Liberar envio preso" })).toBeNull();
  });

  it("“Liberar envio preso” aparece só com a reserva de fato e abre a liberação", async () => {
    responder({ "/api/contratos/1/medicoes": [{ ...MEDICAO, estado: "nota_emitida" }],
      "/api/notas/a-enviar": { envios: [{ ...ENVIO_COMECADO, envio_reservado_em: "2026-10-16T10:05:00-04:00" }], contadores: {} } });
    pagina();
    fireEvent.click(await screen.findByRole("button", { name: /Mais ações/ }));
    await waitFor(() => expect(screen.getByRole("menuitem", { name: "Liberar envio preso" })).toBeTruthy());
    fireEvent.click(screen.getByRole("menuitem", { name: "Liberar envio preso" }));
    expect(screen.getByRole("button", { name: "Liberar envio" })).toBeTruthy();
  });

  it("#359: o aprovado mudou depois do espelho avisa, sem dizer glosa, e leva ao espelho", async () => {
    responder({ "/api/contratos/1/medicoes": [{ ...MEDICAO, estado: "espelho_enviado", espelho_desatualizado: "aprovado_mudou" }] });
    const { container } = pagina();
    const link = await screen.findByRole("link", { name: "gere o espelho de novo" });
    expect(link.getAttribute("href")).toBe("/obras/1/medicoes/5#espelho");
    const caixa = link.closest(".aviso")!;
    expect(caixa.textContent).toContain("O aprovado mudou depois do espelho");
    expect(container.textContent).not.toMatch(/glosa/i);
  });

  it("#359: o link do aviso abre o espelho mesmo com a âncora #espelho já na página", async () => {
    window.history.replaceState(null, "", "/obras/1/medicoes/5#espelho");
    responder({ "/api/contratos/1/medicoes": [{ ...MEDICAO, estado: "espelho_enviado", espelho_desatualizado: "aprovado_mudou" }] });
    pagina();
    await screen.findByRole("heading", { name: "Espelhos", level: 2 });
    fireEvent.click(within(screen.getByRole("navigation", { name: "Passos da medição" })).getByRole("button", { name: /Passo 2: Notas/ }));
    await screen.findByRole("heading", { name: "Notas", level: 2 });
    fireEvent.click(screen.getByRole("link", { name: "gere o espelho de novo" }));
    expect(await screen.findByRole("heading", { name: "Espelhos", level: 2 })).toBeTruthy();
  });

  it("#359: na nota emitida o aviso fica e leva às notas, sem pedir o espelho", async () => {
    responder({ "/api/contratos/1/medicoes": [{ ...MEDICAO, estado: "nota_emitida", espelho_desatualizado: "nota_emitida" }] });
    pagina();
    const link = await screen.findByRole("link", { name: "ver as notas" });
    expect(link.getAttribute("href")).toBe("/obras/1/medicoes/5#notas");
    expect(link.closest(".aviso")!.textContent).toContain("O aprovado mudou depois do espelho e a nota já foi emitida");
    expect(screen.queryByRole("link", { name: "gere o espelho de novo" })).toBeNull();
  });

  it("#359: o espelho antigo que não se confere não diz que o aprovado mudou", async () => {
    responder({ "/api/contratos/1/medicoes": [{ ...MEDICAO, estado: "espelho_enviado", espelho_desatualizado: "nao_conferido" }] });
    pagina();
    const link = await screen.findByRole("link", { name: "gere o espelho de novo" });
    expect(link.closest(".aviso")!.textContent).toContain("Não foi possível conferir o valor do espelho antigo");
    expect(screen.queryByText(/O aprovado mudou/)).toBeNull();
  });

  it("#359: no par, uma linha por medição: a nota emitida da execução não esconde o “gere de novo” do reajuste", async () => {
    const EXE = { ...MEDICAO, estado: "nota_emitida", espelho_desatualizado: "nota_emitida" };
    const REAJ = { ...MEDICAO, id: 6, tipo: "reajuste", estado: "espelho_enviado", espelho_desatualizado: "aprovado_mudou" };
    responder({ "/api/contratos/1/medicoes": [EXE, REAJ] });
    pagina();
    await screen.findByRole("heading", { name: "Hospital", level: 1 });
    const gerar = screen.getByRole("link", { name: "gere o espelho de novo" });
    expect(gerar.closest(".aviso")!.textContent).toContain("Reajuste da 23ª Medição: o aprovado mudou depois do espelho, ");
    const notas = screen.getByRole("link", { name: "ver as notas" });
    expect(notas.closest(".aviso")!.textContent).toContain("23ª Medição: o aprovado mudou depois do espelho e a nota já foi emitida, ");
    expect(document.querySelectorAll(".aviso")).toHaveLength(2);
  });

  it("#359: sem o aprovado mudado, nada de aviso do espelho", async () => {
    responder({ "/api/contratos/1/medicoes": [{ ...MEDICAO, estado: "espelho_enviado", espelho_desatualizado: null }] });
    pagina();
    await screen.findByRole("heading", { level: 1 });
    expect(screen.queryByText(/O aprovado mudou depois do espelho/)).toBeNull();
  });
});

describe("Página da medição: as etapas se atualizam entre si", () => {
  beforeEach(() => abrirEtapa(3));
  afterEach(() => { cleanup(); api.mockReset(); });

  // issue #71 (revisor na PR #202): desfazer o vinculo da nota so' para o admin e so' em medicao aberta
  it.each([["protocolada", "true"], ["recebida", "false"], ["cancelada", "false"], ["desistida", "false"]])(
    "medição %s: desfazer vínculo da nota = %s", async (estado, esperado) => {
      responder({ "/api/contratos/1/medicoes": [{ ...MEDICAO, estado }] });
      const { container } = pagina();
      await waitFor(() => expect(container.querySelector("[data-medicao='5']")).not.toBeNull());
      expect(container.querySelector("[data-medicao='5']")!.getAttribute("data-desfazer")).toBe(esperado);
    });

  it("engenharia não desfaz vínculo de nota", async () => {
    responder();
    const { container } = pagina("engenharia");
    await waitFor(() => expect(container.querySelector("[data-medicao='5']")).not.toBeNull());
    expect(container.querySelector("[data-medicao='5']")!.getAttribute("data-desfazer")).toBe("false");
  });

  it("depois de anexar ou vincular nota, os protocolos, os envios e a medição são lidos de novo", async () => {
    responder();
    pagina();
    fireEvent.click(await screen.findByRole("button", { name: "Anexar nota (teste)" }));
    await waitFor(() => expect(leituras("/api/contratos/1/protocolos")).toHaveLength(2));
    await waitFor(() => expect(leituras("/api/contratos/1/medicoes")).toHaveLength(2));
    await waitFor(() => expect(leituras("/api/notas/a-enviar")).toHaveLength(2));
  });

  it("a FRC é de cada medição: uma por bloco quando o órgão tem medição e reajuste", async () => {
    const REAJ = { ...MEDICAO, id: 6, tipo: "reajuste" };
    const metade = (id: number, tipo: string) => ({ medicao_id: id, tipo, titulo: "x", estado: "protocolada", faltam: 0, esperadas: [],
      completa: true, espera: null, liberacao: null });
    responder({ "/api/contratos/1/medicoes": [MEDICAO, REAJ],
      "/api/medicoes/5/par": { junta: false, orgao: "MTPAR", metades: [metade(5, "execucao"), metade(6, "reajuste")] } });
    const { container } = pagina();
    await waitFor(() => expect(container.querySelector("[data-frc='6']")).not.toBeNull());
    expect(container.querySelector("[data-frc='5']")).not.toBeNull();
  });

  // issue #208: o espelho misto que ficou vigente para outra medicao (superado para esta) nao e' o espelho dela
  it("a etapa do espelho mostra a versão mais nova da medição, não o misto superado", async () => {
    abrirEtapa(1);
    const esp = (id: number, versao: number, superado: boolean) => ({ id, numero: 23, versao, situacao: "vigente",
      criado_em: `2026-10-1${versao + 3} 16:00:00`, criado_por_nome: null, envio: null,
      medicoes: [{ id: 5, tipo: "execucao", superado }] });
    responder({ "/api/contratos/1/espelho": { espelhos: [esp(7, 1, true), esp(8, 2, false)] } });
    pagina();
    // o selo da etapa leva a data do espelho vigente (versao 2, de 15/10); sem a linha "nº · versão · por"
    expect(await screen.findByText(/Gerado em 15\/10/)).toBeTruthy();
    expect(screen.queryByText(/Gerado em 14\/10/)).toBeNull();
    expect(screen.queryByText(/nº 23 · versão/)).toBeNull();
  });

  it("etapa 1 é o Espelho e a 2 o Faturamento: o mesmo cartão, uma parte em cada etapa", async () => {
    abrirEtapa(1);
    responder();
    const { container, unmount } = pagina();
    await waitFor(() => expect(container.querySelector("[data-espelho='espelho']")).not.toBeNull());
    unmount();
    abrirEtapa(2);
    const outra = pagina();
    await waitFor(() => expect(outra.container.querySelector("[data-espelho='faturamento']")).not.toBeNull());
  });

  it("depois de enviar um protocolo (etapa 4 já feita), a medição é lida de novo", async () => {
    abrirEtapa(4);
    responder();
    pagina();
    fireEvent.click(await screen.findByRole("button", { name: "Enviar protocolo (teste)" }));
    await waitFor(() => expect(leituras("/api/contratos/1/medicoes")).toHaveLength(2));
  });

  const REGISTRADO = { id: 9, data: "2026-10-10", numero_oficio: "360/2026", numero_processo: null, origem: "manual", protocolo_id: null };

  it("etapa 4 já feita: o protocolo registrado fora mostra o campo do nº do órgão", async () => {
    abrirEtapa(4);
    responder({ "/api/contratos/1/medicoes": [{ ...MEDICAO, protocolos: [REGISTRADO] }] });
    pagina();
    expect(await screen.findByText("Fora do sistema")).toBeTruthy();
    expect(screen.queryByText(/registrado fora do sistema/)).toBeNull();
    fireEvent.change(screen.getByLabelText("Nº do protocolo no órgão"), { target: { value: "2026.10.004512" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/notas/5/numero-orgao", { method: "POST", body: JSON.stringify({ numero: "2026.10.004512" }) }));
  });

  // o reprotocolo: outro protocolo feito fora numa medição já protocolada, com a conferência das certidões
  it("etapa 4 já feita: “Registrar protocolo feito fora” confere as certidões e grava com a justificativa das pendências", async () => {
    abrirEtapa(4);
    responder({ "/api/contratos/1/medicoes": [{ ...MEDICAO, protocolos: [REGISTRADO] }],
      "/api/contratos/1/checklist-protocolo?natureza=execucao": { entidade: "Lotufo", pronto: false,
        itens: [{ entidade_id: 1, entidade: "Lotufo", tipo: "CND Federal", situacao: "pendente" }] } });
    pagina();
    fireEvent.click(await screen.findByRole("button", { name: "Registrar protocolo feito fora" }));
    fireEvent.change(await screen.findByLabelText("Data do protocolo"), { target: { value: "2026-10-14" } });
    fireEvent.click(await screen.findByLabelText(/Protocolar apesar das pendências/));
    fireEvent.change(screen.getByLabelText("Justificativa"), { target: { value: "órgão aceita a CND em até 5 dias" } });
    fireEvent.click(screen.getByRole("button", { name: "Registrar protocolo" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/medicoes/5/protocolo", { method: "POST", body: JSON.stringify({
      data: "2026-10-14", numero_oficio: null, numero_processo: null, apesar_das_pendencias: true, justificativa: "órgão aceita a CND em até 5 dias" }) }));
  });

  // issue #328: o mesmo campo "Link do SIGA" no registro por fora; o servidor extrai o código e recusa o resto
  it("“Registrar protocolo feito fora” tem o campo “Link do SIGA” e manda o link", async () => {
    abrirEtapa(4);
    responder({ "/api/contratos/1/medicoes": [{ ...MEDICAO, protocolos: [REGISTRADO] }],
      "/api/contratos/1/checklist-protocolo?natureza=execucao": { entidade: "Lotufo", pronto: true, itens: [] } });
    pagina();
    fireEvent.click(await screen.findByRole("button", { name: "Registrar protocolo feito fora" }));
    fireEvent.change(await screen.findByLabelText("Data do protocolo"), { target: { value: "2026-10-14" } });
    fireEvent.change(screen.getByLabelText(/Link do SIGA/), { target: { value: " https://siga.exemplo.com.br/acompanhar?n=AbCdEf1234 " } });
    fireEvent.click(screen.getByRole("button", { name: "Registrar protocolo" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/medicoes/5/protocolo", { method: "POST", body: JSON.stringify({
      data: "2026-10-14", numero_oficio: null, numero_processo: null, link_siga: "https://siga.exemplo.com.br/acompanhar?n=AbCdEf1234" }) }));
  });

  it("a linha do tempo mostra “Processo no SIGA registrado”, do protocolo enviado e do registro por fora", async () => {
    const ENVIADO = { id: 9, etapa: "unico", etapa_rotulo: "Protocolo", numero_oficio: "CT-301", situacao: "enviado",
      criado_em: "2026-10-18 10:00:00", enviado_em: "2026-10-19 10:00:00", enviado_por: "Engenharia",
      medicoes: [{ id: 5, titulo: "23ª Medição" }], pendencias: [], numero_orgao: null,
      siga: { codigo: "AbCdEf1234", link: null, setor: null, com_quem: null, dias_uteis: null, lido_em: null, registrado_em: "2026-10-20 12:00:00" } };
    responder({ "/api/contratos/1/protocolos": { ...LISTA, protocolos: [ENVIADO] } });
    pagina();
    const lateral = await screen.findByRole("complementary", { name: "Resumo e linha do tempo" });
    await waitFor(() => expect(within(lateral).getByText("Processo no SIGA registrado")).toBeTruthy());
    cleanup();
    responder({ "/api/contratos/1/medicoes": [{ ...MEDICAO, protocolos: [REGISTRADO], siga_registrado_em: "2026-10-21 12:00:00" }] });
    pagina();
    expect(within(await screen.findByRole("complementary", { name: "Resumo e linha do tempo" })).getByText("Processo no SIGA registrado")).toBeTruthy();
  });

  it("quem só consulta não vê “Registrar protocolo feito fora”", async () => {
    abrirEtapa(4);
    responder();
    pagina("diretoria");
    await screen.findByRole("heading", { name: "Envio da nota", level: 2 });
    expect(screen.queryByRole("button", { name: "Registrar protocolo feito fora" })).toBeNull();
  });

  // MTPAR/SES: medição e reajuste têm o SIGA próprio; só onde o órgão junta o número vale para os dois
  const REAJ = { ...MEDICAO, id: 6, tipo: "reajuste", protocolos: [{ ...REGISTRADO, id: 10, numero_processo: "SIGA-REAJ" }] };
  const metade = (id: number, tipo: string) => ({ medicao_id: id, tipo, titulo: "x", estado: "protocolada", faltam: 0, esperadas: [],
    completa: true, espera: null, liberacao: null });
  const par = (junta: boolean) => ({ junta, orgao: "MTPAR", metades: [metade(5, "execucao"), metade(6, "reajuste")] });

  it("MTPAR com dois registros por fora: um campo por envio, cada um com o número da sua medição", async () => {
    abrirEtapa(4);
    responder({ "/api/contratos/1/medicoes": [{ ...MEDICAO, protocolos: [{ ...REGISTRADO, numero_processo: "SIGA-MED" }] }, REAJ],
      "/api/medicoes/5/par": par(false) });
    pagina();
    const med = await screen.findByLabelText(/Nº do protocolo no órgão · 23ª Medição/) as HTMLInputElement;
    const rea = screen.getByLabelText(/Nº do protocolo no órgão · Reajuste da 23ª Medição/) as HTMLInputElement;
    expect([med.value, rea.value]).toEqual(["SIGA-MED", "SIGA-REAJ"]);
    fireEvent.change(med, { target: { value: "SIGA-NOVO" } });
    fireEvent.click(screen.getAllByRole("button", { name: "Salvar" })[0]);
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/notas/5/numero-orgao", { method: "POST", body: JSON.stringify({ numero: "SIGA-NOVO" }) }));
    expect(api.mock.calls.some(c => c[0] === "/api/notas/6/numero-orgao")).toBe(false);   // o SIGA do reajuste nao e' sobrescrito
  });

  it("onde o órgão junta, um campo só grava o número nas duas medições; falha no meio diz qual já ficou", async () => {
    abrirEtapa(4);
    responder({ "/api/contratos/1/medicoes": [{ ...MEDICAO, protocolos: [REGISTRADO] }, { ...REAJ, protocolos: [{ ...REGISTRADO, id: 10 }] }],
      "/api/medicoes/5/par": par(true) });
    pagina();
    fireEvent.change(await screen.findByLabelText("Nº do protocolo no órgão"), { target: { value: "SEI-1" } });
    const base = api.getMockImplementation()!;
    api.mockImplementation(async (url: string, o?: unknown) => {
      if (url === "/api/notas/6/numero-orgao") throw new ApiErro(422, "Medição sem envio registrado");
      return base(url, o);
    });
    fireEvent.click(screen.getByRole("button", { name: "Salvar" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/notas/5/numero-orgao", { method: "POST", body: JSON.stringify({ numero: "SEI-1" }) }));
    expect((await screen.findByText(/O número já ficou na 23ª Medição/)).textContent).toContain("Medição sem envio registrado");
    await waitFor(() => expect(leituras("/api/contratos/1/medicoes").length).toBeGreaterThan(1));   // recarregou
  });
});

// rodada 2 do revisor: a falha parcial do registro fora nao some com a janela quando a pagina passa da etapa 4 para a 5
describe("Página da medição: registrar fora com falha parcial (MTPAR)", () => {
  beforeEach(() => window.history.replaceState(null, "", "/obras/1/medicoes/5"));
  afterEach(() => { cleanup(); api.mockReset(); apiForm.mockReset(); });

  it("a medição vira protocolada depois do primeiro envio e o segundo falha: o alerta fica até a pessoa fechar", async () => {
    const REAJ = { ...MEDICAO, id: 6, tipo: "reajuste", estado: "nota_emitida" };
    const EXEC = { ...MEDICAO, estado: "nota_emitida" };
    const envio = (chave: string, id: number, desc: string) => ({ chave, contrato_id: 1, medicao_ids: [id], protocolo_id: null, notas: [], itens: [],
      situacao: "pronto", descricao: desc, valor_centavos: 1, familia: "mtpar", aviso: null, irmas: [] });
    const metade = (id: number, tipo: string, estado: string) => ({ medicao_id: id, tipo, titulo: "x", estado, faltam: 0, esperadas: [], completa: true,
      espera: null, liberacao: null });
    let protocolada = false;
    api.mockImplementation(async (url: string) => {
      if (url === "/api/contratos/1/medicoes") return [protocolada ? { ...MEDICAO } : EXEC, REAJ];
      if (url === "/api/medicoes/5/par") return { junta: false, orgao: "MTPAR", metades: [metade(5, "execucao", protocolada ? "protocolada" : "nota_emitida"), metade(6, "reajuste", "nota_emitida")] };
      if (url === "/api/notas/a-enviar") return { envios: protocolada ? [envio("b", 6, "Reajuste da 23ª medição")]
        : [envio("a", 5, "23ª medição"), envio("b", 6, "Reajuste da 23ª medição")], contadores: {} };
      if (url.endsWith("/cabecalho")) return { obra: "Hospital", orgao: "SES", instrumento: "CT 1/2026", percentual_lotufo_bp: 10000 };
      if (url === "/api/contratos/1/protocolos") return LISTA;
      if (url.startsWith("/api/contratos/1/checklist")) return { itens: [] };
      if (url === "/api/contratos/1/espelho") return { espelhos: [] };
      return [];
    });
    apiForm.mockImplementationOnce(async () => { protocolada = true; return { ok: true }; })
      .mockRejectedValueOnce(new ApiErro(422, "Medição 6 não está com a nota emitida"));
    pagina();
    fireEvent.click(await screen.findByText("Já enviei por fora"));
    fireEvent.click(screen.getAllByRole("checkbox")[1]);
    fireEvent.change(screen.getByLabelText("Como e para quem a nota foi enviada"), { target: { value: "Pelo Outlook" } });
    fireEvent.click(screen.getByRole("button", { name: "Registrar" }));
    const alerta = await screen.findByRole("alert");
    expect(alerta.textContent).toContain("Já registrados: 23ª medição");
    // a pagina nao foi relida: o erro continua a' vista, ainda na etapa 4
    await new Promise(r => setTimeout(r, 50));
    expect(screen.getByRole("alert").textContent).toContain("Já registrados");
    expect(screen.getByRole("heading", { name: "Envio da nota", level: 2 })).toBeTruthy();
    const antes = leituras("/api/contratos/1/medicoes").length;
    fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));
    await waitFor(() => expect(leituras("/api/contratos/1/medicoes").length).toBeGreaterThan(antes));
  });
});

// issue #188: a execucao e o reajuste da mesma competencia na mesma pagina; onde o orgao junta os dois no mesmo
// e-mail, a metade pronta espera a outra (opcao A: a espera fica na tela e no envio, nao no estado)
describe("Página da medição: medição e reajuste", () => {
  beforeEach(() => window.history.replaceState(null, "", "/obras/1/medicoes/5"));
  afterEach(() => { cleanup(); api.mockReset(); });

  const REAJ = { ...MEDICAO, id: 6, tipo: "reajuste", estado: "espelho_enviado", valor_protocolado_centavos: 50000 };
  const metade = (id: number, tipo: string, extra: Record<string, unknown> = {}) => ({
    medicao_id: id, tipo, titulo: tipo === "execucao" ? "23ª Medição" : "Reajuste da 23ª Medição", estado: "nota_emitida",
    faltam: 0, esperadas: [], completa: true, espera: null, liberacao: null, ...extra });
  const ESPERA = { medicao_id: 6, titulo: "Reajuste da 23ª Medição", tipo: "reajuste", texto: "esperando as notas do reajuste" };
  const ENVIO_ESPERANDO = { chave: "m5-m6", contrato_id: 1, medicao_ids: [5, 6], protocolo_id: null, notas: [], itens: [], situacao: "esperando",
    descricao: "23ª medição + reajuste", valor_centavos: 1, familia: "sinfra", aviso: "esperando as notas do reajuste", irmas: [] };

  function comPar(par: unknown, extra: Record<string, unknown> = {}) {
    responder({ "/api/contratos/1/medicoes": [{ ...MEDICAO, estado: "nota_emitida" }, REAJ], "/api/medicoes/5/par": par,
      "/api/notas/a-enviar": { envios: [ENVIO_ESPERANDO], contadores: {} }, ...extra });
  }
  const SINFRA = { junta: true, orgao: "SINFRA", metades: [metade(5, "execucao", { espera: ESPERA }),
    metade(6, "reajuste", { estado: "espelho_enviado", completa: false, faltam: 2 })] };

  it("órgão que junta: dois blocos na etapa 3, o que falta por bloco e o aviso", async () => {
    abrirEtapa(3);
    comPar(SINFRA);
    const { container } = pagina();
    expect(await screen.findByRole("region", { name: "Execução · 23ª Medição" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "Reajuste da 23ª Medição" })).toBeTruthy();
    expect(container.querySelector("[data-medicao='6']")).toBeTruthy();       // a nota do reajuste vai para o reajuste
    // a espera ja' esta' no trilho e no proximo passo: a etapa 3 nao explica a regra do orgao nem resume o par
    expect(container.textContent).not.toContain("faltam 2 notas");
    expect(container.textContent).not.toContain("vão no mesmo e-mail");
  });

  it("órgão que junta, esperando o reajuste: a etapa 4 é a da vez, em espera, e a saída de emergência está na linha do envio", async () => {
    comPar(SINFRA);
    pagina();
    const botao = await screen.findByRole("button", { name: "Enviar a medição sem o reajuste…" });
    const trilho = screen.getByRole("navigation", { name: "Passos da medição" });
    expect(trilho.querySelector(".passo--espera")!.textContent).toContain("Envio da nota");
    expect(screen.queryByRole("button", { name: "Enviar a nota" })).toBeNull();    // nada a iniciar: falta a outra metade
    // o próximo passo, "Esperando as notas do reajuste", leva à etapa 4 (onde a espera e a saída de emergência moram)
    expect(screen.getByRole("link", { name: "Esperando as notas do reajuste" }).getAttribute("href")).toBe("/obras/1/medicoes/5#etapa-4");
    fireEvent.click(botao);
    const enviar = screen.getByRole("button", { name: "Liberar o envio só da medição" }) as HTMLButtonElement;
    expect(enviar.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Justificativa (obrigatória)"), { target: { value: "notas do reajuste presas no faturamento" } });
    fireEvent.click(enviar);
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/medicoes/5/envio-sem-a-outra",
      { method: "POST", body: JSON.stringify({ justificativa: "notas do reajuste presas no faturamento" }) }));
  });

  it("na página do reajuste que falta: a etapa da vez é a 3, e a etapa 4 mostra a saída de emergência", async () => {
    window.history.replaceState(null, "", "/obras/1/medicoes/6#etapa-4");
    comPar(SINFRA, { "/api/medicoes/6/par": SINFRA });
    pagina("admin", 6);
    expect(await screen.findByRole("button", { name: "Enviar a medição sem o reajuste…" })).toBeTruthy();
    const trilho = screen.getByRole("navigation", { name: "Passos da medição" });
    expect(trilho.querySelector(".passo--espera")).toBeNull();
    expect(trilho.querySelector("[aria-current='step']")!.textContent).toContain("Notas");
  });

  it("a justificativa da liberação aparece na linha do tempo e some a saída de emergência", async () => {
    comPar({ ...SINFRA, metades: [metade(5, "execucao", { liberacao: { justificativa: "notas presas no faturamento",
      em: "2026-10-15 13:00:00", por: "Engenharia" } }), SINFRA.metades[1]] }, { "/api/notas/a-enviar": { envios: [], contadores: {} } });
    pagina();
    expect(await screen.findByText(/Envio liberado sem o reajuste por Engenharia\. Justificativa: “notas presas no faturamento”/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Enviar a medição sem o reajuste…" })).toBeNull();
  });

  it("órgão que separa: um trilho só, sem espera e sem saída de emergência; um envio por linha", async () => {
    comPar({ junta: false, orgao: "MTPAR", metades: [metade(5, "execucao"),
      metade(6, "reajuste", { estado: "espelho_enviado", completa: false, faltam: 1 })] }, { "/api/notas/a-enviar": { envios: [
        { ...ENVIO_ESPERANDO, chave: "m5", medicao_ids: [5], situacao: "pronto", aviso: null, descricao: "23ª medição", familia: "mtpar" }], contadores: {} } });
    const { container } = pagina();
    await screen.findByRole("button", { name: "Enviar a nota" });
    expect(screen.getAllByRole("navigation", { name: "Passos da medição" })).toHaveLength(1);
    expect(container.querySelector(".passo--espera")).toBeNull();
    expect(screen.queryByRole("button", { name: /sem o reajuste/ })).toBeNull();
  });

  it("medição sem reajuste: um bloco só e o título da medição", async () => {
    abrirEtapa(3);
    responder({ "/api/medicoes/5/par": { junta: true, orgao: "SINFRA", metades: [] } });
    const { container } = pagina();
    expect(await screen.findByRole("heading", { name: "Hospital", level: 1 })).toBeTruthy();
    await waitFor(() => expect(container.querySelectorAll("[data-medicao]")).toHaveLength(1));
    expect(screen.queryByRole("region", { name: "Execução · 23ª Medição" })).toBeNull();
  });
});

// issue #53 (decisao do dono, 15/10/2026): o recebimento a mao e' so' do admin; a engenharia espera o RM
describe("Página da medição: pagamento (etapa 5)", () => {
  beforeEach(() => window.history.replaceState(null, "", "/obras/1/medicoes/5"));
  afterEach(() => { cleanup(); api.mockReset(); });

  it("o admin vê “Registrar recebimento” na medição protocolada e ele abre a janela", async () => {
    responder();
    pagina();
    fireEvent.click(await screen.findByRole("button", { name: "Registrar recebimento" }));
    expect(screen.getByLabelText("Motivo")).toBeTruthy();
  });

  it("a engenharia não vê o botão; a linha só tem o selo, sem explicar o RM", async () => {
    responder();
    pagina("engenharia");
    expect(await screen.findByText("Aguardando o órgão")).toBeTruthy();
    expect(screen.queryByText(/O RM marca a baixa sozinho/)).toBeNull();
    expect(screen.queryByRole("button", { name: "Registrar recebimento" })).toBeNull();
  });

  it("sem o nº do protocolo no órgão, a linha leva a registrá-lo na etapa 4", async () => {
    responder({ "/api/contratos/1/medicoes": [{ ...MEDICAO, protocolos: [{ id: 9, data: "2026-10-10", numero_oficio: null,
      numero_processo: null, origem: "manual", protocolo_id: null }] }] });
    pagina();
    const link = await screen.findByRole("link", { name: "Registrar o protocolo" });
    expect(link.getAttribute("href")).toBe("/obras/1/medicoes/5#etapa-4");
  });
});

// issue #289: a etapa 1 começa pela planilha/carta (execução e projeto); o espelho vem depois do boletim
describe("Página da medição: a planilha/carta na etapa 1", () => {
  beforeEach(() => window.history.replaceState(null, "", "/obras/1/medicoes/5"));
  afterEach(() => { cleanup(); api.mockReset(); });

  it("medição prevista de execução abre a Nova planilha/carta, sem o formulário do espelho", async () => {
    responder({ "/api/contratos/1/espelho": { espelhos: [], regra: { situacao: "ativa" } }, "/api/contratos/1/medicoes": [{ ...MEDICAO, estado: "prevista" }] });
    const { container } = pagina();
    await waitFor(() => expect(container.querySelector("[data-nova-planilha='23']")).not.toBeNull());
    expect(container.querySelector("[data-espelho]")).toBeNull();
    expect(container.querySelector("[data-cartao-planilha]")).toBeNull();
  });

  it("planilha/carta só gerada (#460): o cartão dela, o aviso do envio não registrado e o formulário do espelho", async () => {
    responder({ "/api/contratos/1/espelho": { espelhos: [], regra: { situacao: "ativa" } }, "/api/contratos/1/medicoes": [{ ...MEDICAO, estado: "planilha_gerada" }] });
    const { container } = pagina();
    await waitFor(() => expect(container.querySelector("[data-cartao-planilha='5']")).not.toBeNull());
    // espera o cartao dizer que nao ha' envio saindo pelo sistema (gate Sol, PR #528); a revisao nao e' conferida
    expect(container.querySelector("[data-espelho]")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Sem reserva (teste)" }));
    expect(container.querySelector("[data-espelho='espelho']")!.getAttribute("data-abre-form")).toBe("true");
    expect(screen.getByText("Envio da planilha/carta não registrado.")).toBeTruthy();
  });

  it("planilha/carta só gerada com o envio saindo pelo sistema: sem o espelho e sem o aviso (gate Sol, PR #528)", async () => {
    responder({ "/api/contratos/1/espelho": { espelhos: [], regra: { situacao: "ativa" } }, "/api/contratos/1/medicoes": [{ ...MEDICAO, estado: "planilha_gerada" }] });
    const { container } = pagina();
    await waitFor(() => expect(container.querySelector("[data-cartao-planilha='5']")).not.toBeNull());
    fireEvent.click(screen.getByRole("button", { name: "Envio reservado (teste)" }));
    expect(container.querySelector("[data-espelho]")).toBeNull();
    expect(screen.queryByText(/Envio da planilha\/carta não registrado/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Sem reserva (teste)" }));
    expect(container.querySelector("[data-espelho='espelho']")).not.toBeNull();
    // releitura que falha depois de uma certa: o espelho some e a tela avisa
    fireEvent.click(screen.getByRole("button", { name: "Falha ao conferir (teste)" }));
    expect(screen.getByText(/Não foi possível conferir a planilha\/carta/)).toBeTruthy();
    expect(container.querySelector("[data-espelho]")).toBeNull();
  });

  // #508: com a planilha/carta enviada a vez e' do passo 2 (Analise do orgao); a pagina confere a revisao lendo o
  // detalhe da medicao, como o cartao (que mora no passo 1)
  const ATIVA = { espelhos: [], regra: { situacao: "ativa" } };
  const enviadaEm = (estado: string) => [{ ...MEDICAO, estado, planilha_enviada_em: "2026-11-05", dias_uteis_no_orgao: 1, com_envio_planilha: true }];

  it("planilha/carta enviada: o passo 2 é o da vez, sem o aviso do envio não registrado (#460)", async () => {
    responder({ "/api/contratos/1/espelho": ATIVA, "/api/contratos/1/medicoes": enviadaEm("planilha_enviada"),
      "/api/medicoes/5": detalhePlanilha("planilha_enviada") });
    pagina();
    expect(await screen.findByRole("heading", { name: "Com o órgão há 1 dia útil" })).toBeTruthy();
    const barra = screen.getByRole("navigation", { name: "Passos da medição" });
    expect(barra.querySelector("[aria-current='step']")!.textContent).toContain("Análise do órgão");
    expect(within(barra).getByRole("button", { name: "Passo 1: Planilha e carta, feito em 05/11" })).toBeTruthy();
    expect(screen.queryByText(/Envio da planilha\/carta não registrado/)).toBeNull();
  });

  it("com a planilha/carta enviada, o espelho sem o boletim sai do passo 2; depois do boletim, o passo 3 já abre o formulário", async () => {
    responder({ "/api/contratos/1/espelho": ATIVA, "/api/contratos/1/medicoes": enviadaEm("planilha_enviada"),
      "/api/medicoes/5": detalhePlanilha("planilha_enviada") });
    const { container } = pagina();
    fireEvent.click(await screen.findByRole("button", { name: "Gerar o espelho sem o boletim" }));
    expect(container.querySelector("[data-espelho='espelho']")!.getAttribute("data-abre-form")).toBe("true");
    cleanup();
    responder({ "/api/contratos/1/espelho": ATIVA, "/api/contratos/1/medicoes": enviadaEm("boletim_recebido"),
      "/api/medicoes/5": detalhePlanilha("boletim_recebido") });
    const segundo = pagina();
    await waitFor(() => expect(segundo.container.querySelector("[data-espelho='espelho']")).not.toBeNull());
    expect(segundo.container.querySelector("[data-espelho='espelho']")!.getAttribute("data-abre-form")).toBe("true");
    expect(screen.getByRole("heading", { name: "Espelhos", level: 2 })).toBeTruthy();
    expect(segundo.container.querySelector("[data-nova-planilha]")).toBeNull();
  });

  it("com revisão registrada e não enviada, a vez volta ao passo 1 e o espelho não aparece (rodada extra, PR #382)", async () => {
    const pendente = detalhePlanilha("planilha_enviada", { planilhas: [V1, { ...V1, id: 32, versao: 2, motivo: "Rev01" }],
      envio_planilha: { ...detalhePlanilha("planilha_enviada").envio_planilha,
        envios: [{ planilha_id: 31, versao: 1, numero_oficio: null, enviado_em: "2026-11-05", usuario: "Operação", origem: "externo" }] } });
    responder({ "/api/contratos/1/espelho": ATIVA, "/api/contratos/1/medicoes": enviadaEm("planilha_enviada"), "/api/medicoes/5": pendente });
    const { container } = pagina();
    await waitFor(() => expect(container.querySelector("[data-cartao-planilha='5']")).not.toBeNull());
    const barra = screen.getByRole("navigation", { name: "Passos da medição" });
    expect(barra.querySelector("[aria-current='step']")!.textContent).toContain("Planilha e carta");
    expect(container.querySelector("[data-espelho]")).toBeNull();
    expect(screen.queryByRole("button", { name: "Gerar o espelho sem o boletim" })).toBeNull();
    // o orgao pode aprovar a versao que recebeu: sem o passo 2 aberto, o boletim volta a Mais acoes (revisor, PR #553)
    fireEvent.click(screen.getByRole("button", { name: /Mais ações/ }));
    expect(screen.getByRole("menuitem", { name: "Registrar boletim" })).toBeTruthy();
  });

  it("no passo 2 (sem revisão pendente) o boletim mora em “Aprovou a medição”, não em Mais ações", async () => {
    responder({ "/api/contratos/1/espelho": ATIVA, "/api/contratos/1/medicoes": enviadaEm("planilha_enviada"),
      "/api/medicoes/5": detalhePlanilha("planilha_enviada") });
    pagina();
    await screen.findByRole("button", { name: "Gerar o espelho sem o boletim" });
    expect(screen.getByRole("button", { name: "Aprovou a medição" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Mais ações/ }));
    expect(screen.queryByRole("menuitem", { name: "Registrar boletim" })).toBeNull();
  });

  it("planilha/carta enviada: o espelho não aparece antes de a página conferir a revisão (issue #384)", async () => {
    responder({ "/api/contratos/1/espelho": ATIVA, "/api/contratos/1/medicoes": enviadaEm("planilha_enviada"),
      "/api/medicoes/5": new Promise(() => {}) });
    pagina();
    await screen.findByRole("heading", { name: "Com o órgão há 1 dia útil" });
    expect(screen.queryByRole("button", { name: "Gerar o espelho sem o boletim" })).toBeNull();
  });

  it("planilha/carta enviada: se não consegue conferir, o espelho fica oculto e a tela avisa; Tentar de novo confere de novo (issue #384)", async () => {
    let falha = true;
    responder({ "/api/contratos/1/espelho": ATIVA, "/api/contratos/1/medicoes": enviadaEm("planilha_enviada") });
    const base = api.getMockImplementation()!;
    api.mockImplementation(async (url: string, opts?: RequestInit) => {
      if (url === "/api/medicoes/5") { if (falha) throw new Error("caiu"); return detalhePlanilha("planilha_enviada"); }
      return base(url, opts);
    });
    pagina();
    expect(await screen.findByText(/Não foi possível conferir a planilha\/carta/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Gerar o espelho sem o boletim" })).toBeNull();
    falha = false;
    fireEvent.click(screen.getByRole("button", { name: "Tentar de novo" }));
    expect(await screen.findByRole("button", { name: "Gerar o espelho sem o boletim" })).toBeTruthy();
    expect(screen.queryByText(/Não foi possível conferir a planilha/)).toBeNull();
  });

  it("reajuste em planilha_enviada não tem cartão: o espelho não espera conferência (issue #384)", async () => {
    responder({ "/api/contratos/1/espelho": ATIVA, "/api/contratos/1/medicoes": [{ ...MEDICAO, tipo: "reajuste", estado: "planilha_enviada" }] });
    const { container } = pagina();
    await waitFor(() => expect(container.querySelector("[data-espelho='espelho']")).not.toBeNull());
    expect(container.querySelector("[data-cartao-planilha]")).toBeNull();
  });

  it("trocar de medição reinicia a conferência: o espelho some até a nova responder (issue #384)", async () => {
    responder({ "/api/contratos/1/espelho": ATIVA,
      "/api/contratos/1/medicoes": [...enviadaEm("planilha_enviada"), { ...enviadaEm("planilha_enviada")[0], id: 6, numero: 24 }],
      "/api/medicoes/5": detalhePlanilha("planilha_enviada"), "/api/medicoes/6": new Promise(() => {}) });
    const { rerender } = pagina();
    expect(await screen.findByRole("button", { name: "Gerar o espelho sem o boletim" })).toBeTruthy();
    rerender(<MedicaoPagina contratoId={1} medicaoId={6} usuario={usuario} origem={null} />);
    await waitFor(() => expect(screen.queryByRole("button", { name: "Gerar o espelho sem o boletim" })).toBeNull());
  });

  it("depois do boletim: o espelho espera a conferência e aparece no passo 3", async () => {
    responder({ "/api/contratos/1/espelho": ATIVA, "/api/contratos/1/medicoes": enviadaEm("boletim_recebido"),
      "/api/medicoes/5": new Promise(() => {}) });
    const { container } = pagina();
    await screen.findByRole("heading", { name: "Espelhos", level: 2 });
    expect(container.querySelector("[data-espelho]")).toBeNull();
    // o cartao da planilha/carta, quando confere, tambem libera
    cleanup();
    responder({ "/api/contratos/1/espelho": ATIVA, "/api/contratos/1/medicoes": enviadaEm("boletim_recebido") });
    window.history.replaceState(null, "", "/obras/1/medicoes/5#passo-1");
    const segundo = pagina();
    await waitFor(() => expect(segundo.container.querySelector("[data-cartao-planilha='5']")).not.toBeNull());
    fireEvent.click(screen.getByRole("button", { name: "Sem revisão (teste)" }));
    fireEvent.click(screen.getByRole("button", { name: "Voltar ao passo atual" }));
    expect(segundo.container.querySelector("[data-espelho='espelho']")).not.toBeNull();
  });

  it("obra fora do fluxo do espelho: a prevista continua pelo espelho, sem o formulário (gate Sol, PR #382)", async () => {
    responder({ "/api/contratos/1/medicoes": [{ ...MEDICAO, estado: "prevista" }] });
    const { container } = pagina();
    await waitFor(() => expect(container.querySelector("[data-espelho='espelho']")).not.toBeNull());
    expect(container.querySelector("[data-nova-planilha]")).toBeNull();
  });

  it("reajuste previsto continua pelo espelho", async () => {
    responder({ "/api/contratos/1/espelho": ATIVA, "/api/contratos/1/medicoes": [{ ...MEDICAO, tipo: "reajuste", estado: "prevista" }] });
    const { container } = pagina();
    await waitFor(() => expect(container.querySelector("[data-espelho='espelho']")).not.toBeNull());
    expect(container.querySelector("[data-nova-planilha]")).toBeNull();
  });

  it("diretoria: sem o formulário (vê o espelho só para ler); o cartão abre só para ler; o passo 2 sem resposta", async () => {
    responder({ "/api/contratos/1/espelho": ATIVA, "/api/contratos/1/medicoes": [{ ...MEDICAO, estado: "prevista" }] });
    const { container } = pagina("diretoria");
    await waitFor(() => expect(container.querySelector("[data-espelho='espelho']")).not.toBeNull());
    expect(container.querySelector("[data-nova-planilha]")).toBeNull();
    cleanup();
    responder({ "/api/contratos/1/espelho": ATIVA, "/api/contratos/1/medicoes": enviadaEm("planilha_enviada"),
      "/api/medicoes/5": detalhePlanilha("planilha_enviada") });
    pagina("diretoria");
    expect(await screen.findByText("Aguardando a resposta do órgão")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Aprovou a medição" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Gerar o espelho sem o boletim" })).toBeNull();
    fireEvent.click(within(screen.getByRole("navigation", { name: "Passos da medição" })).getByRole("button", { name: /Passo 1: Planilha e carta/ }));
    expect(document.querySelector("[data-cartao-planilha='5']")!.getAttribute("data-pode-editar")).toBe("false");
    cleanup();
    // gate Sol (PR #528): na planilha/carta so' gerada a diretoria ve o espelho para ler, sem o formulario aberto
    responder({ "/api/contratos/1/espelho": ATIVA, "/api/contratos/1/medicoes": [{ ...MEDICAO, estado: "planilha_gerada" }] });
    const terceiro = pagina("diretoria");
    await waitFor(() => expect(terceiro.container.querySelector("[data-cartao-planilha='5']")).not.toBeNull());
    fireEvent.click(screen.getByRole("button", { name: "Sem reserva (teste)" }));
    expect(terceiro.container.querySelector("[data-espelho='espelho']")!.getAttribute("data-abre-form")).toBe("false");
  });
});

describe("Boletim do órgão na página da medição (issue #290)", () => {
  beforeEach(() => window.history.replaceState(null, "", "/obras/1/medicoes/5"));
  afterEach(() => { cleanup(); api.mockReset(); apiForm.mockReset(); });

  const COM_BOLETIM = { ...MEDICAO, estado: "boletim_recebido", valor_protocolado_centavos: 1234567,
    valor_atestado_centavos: 1200001, atestado_em: "2026-08-10",
    boletins: [{ id: 9, tem_arquivo: true, valor_centavos: 1200001, atestado_em: "2026-08-10", meio: "smo", numero_orgao: "7" }],
    edicoes_valor: [
      { data: "2026-08-03T10:00:00", texto: "Planilha/carta enviada por fora em 03/08/2026 (E-mail ao protocolo) por Admin" },
      { data: "2026-08-11T09:00:00", boletim_id: 9,
        texto: "Boletim nº 7 (SMO) de 10/08/2026: aprovado R$ 12.000,01, pedido R$ 12.345,67, diferença -R$ 345,66 por Admin" },
      { data: "2026-08-12", texto: "Boletim assinado no DocuSign em 12/08/2026 por Admin" },
    ] };

  it("a planilha enviada tem o boletim no passo 2 (“Aprovou a medição”); arrastar a capa preenche e aceitar grava", async () => {
    responder({ "/api/contratos/1/medicoes": [{ ...MEDICAO, estado: "planilha_enviada", valor_protocolado_centavos: 1234567, com_envio_planilha: true }],
      "/api/medicoes/5": detalhePlanilha("planilha_enviada") });
    apiForm.mockImplementation(async (url: string) => url.endsWith("/boletim/leitura")
      ? { lido: true, fonte: "texto", avisos: [], campos: { numero_orgao: "7", data: "2026-08-10", valor_centavos: 1200001 } }
      : { id: 9 });
    pagina();
    fireEvent.click(await screen.findByRole("button", { name: "Aprovou a medição" }));
    const janela = screen.getByRole("form", { name: "Registrar boletim" });
    const pdf = new File(["%PDF-1.4"], "boletim.pdf", { type: "application/pdf" });
    fireEvent.drop(within(janela).getByTestId("soltar-boletim"), { dataTransfer: { files: [pdf] } });
    await waitFor(() => expect((within(janela).getByLabelText(/Nº no órgão/) as HTMLInputElement).value).toBe("7"));
    expect((within(janela).getByLabelText(/Data do boletim/) as HTMLInputElement).value).toBe("2026-08-10");
    expect((within(janela).getByLabelText(/Valor aprovado/) as HTMLInputElement).value).toBe("12.000,01");
    expect(within(janela).getAllByText("Lido da capa")).toHaveLength(3);
    fireEvent.click(within(janela).getByRole("button", { name: "Aceitar e registrar o boletim" }));
    await waitFor(() => expect(apiForm.mock.calls.some(c => c[0] === "/api/medicoes/5/boletim")).toBe(true));
    const fd = apiForm.mock.calls.find(c => c[0] === "/api/medicoes/5/boletim")![1] as FormData;
    expect([fd.get("numero_orgao"), fd.get("data"), fd.get("valor"), fd.get("meio")]).toEqual(
      ["7", "2026-08-10", "12.000,01", "smo"]);
  });

  it("a linha do tempo mostra Planilha/carta, Boletim (pedido, aprovado, diferença e o PDF) e Assinatura", async () => {
    responder({ "/api/contratos/1/medicoes": [COM_BOLETIM] });
    pagina();
    const lateral = await screen.findByRole("complementary", { name: "Resumo e linha do tempo" });
    const tempo = within(lateral).getByText("Linha do tempo").closest("section")!;
    await waitFor(() => expect(tempo.textContent).toContain("Boletim nº 7"));
    const itens = [...tempo.querySelectorAll("li")].map(li => li.textContent ?? "").reverse();
    expect(itens.findIndex(t => t.includes("Planilha/carta enviada"))).toBeLessThan(itens.findIndex(t => t.includes("Boletim nº 7")));
    expect(itens.findIndex(t => t.includes("Boletim nº 7"))).toBeLessThan(itens.findIndex(t => t.includes("assinado no DocuSign")));
    const boletim = itens.find(t => t.includes("Boletim nº 7"))!;
    expect(boletim).toContain("aprovado R$ 12.000,01");
    expect(boletim).toContain("pedido R$ 12.345,67");
    expect(boletim).toContain("diferença -R$ 345,66");
    expect(within(tempo).getByRole("link", { name: "Ver o boletim" }).getAttribute("href")).toBe("/api/medicoes/5/boletins/9");
  });

  it("“Registrar assinatura” aparece depois do boletim; o atestado não se edita mais à mão", async () => {
    responder({ "/api/contratos/1/medicoes": [COM_BOLETIM] });
    pagina();
    fireEvent.click(await screen.findByRole("button", { name: /Mais ações/ }));
    const itens = within(screen.getByRole("menu")).getAllByRole("menuitem").map(x => x.textContent);
    expect(itens).toContain("Registrar assinatura");
    expect(itens).toContain("Registrar boletim novo");
    expect(itens).not.toContain("Editar o atestado");
  });

  it("sem o passo 2 (MT-PAR), “Aceitar a diferença” fica em Mais ações até a diferença ser aceita (issue #288)", async () => {
    responder({ "/api/contratos/1/medicoes": [{ ...COM_BOLETIM, com_envio_planilha: false }] });
    const p = pagina();
    fireEvent.click(await screen.findByRole("button", { name: /Mais ações/ }));
    fireEvent.click(within(screen.getByRole("menu")).getByRole("menuitem", { name: "Aceitar a diferença" }));
    expect(screen.getByRole("form", { name: "Aceitar a diferença" })).toBeTruthy();
    p.unmount();
    responder({ "/api/contratos/1/medicoes": [{ ...COM_BOLETIM, com_envio_planilha: false, diferenca_aceita: { atesto_id: 9,
      justificativa: "glosa de itens", usuario: "Eng", criado_em: "2026-11-08 10:00:00", diferenca_centavos: -34566 } }] });
    pagina();
    fireEvent.click(await screen.findByRole("button", { name: /Mais ações/ }));
    expect(within(screen.getByRole("menu")).getAllByRole("menuitem").map(x => x.textContent)).not.toContain("Aceitar a diferença");
  });

  it("a capa do SMO divergente do cadastro aparece no detalhe e se aceita em Mais ações (issue #286)", async () => {
    const frase = "Acumulado a preços iniciais até a 7ª medição: capa do SMO diz R$ 10.001,01, soma das medições diz R$ 10.001,00";
    responder({ "/api/contratos/1/medicoes": [{ ...COM_BOLETIM, com_envio_planilha: false, valor_atestado_centavos: 1234567,
      capa_divergencias: [frase] }] });
    const p = pagina();
    expect(await screen.findByText(frase)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Mais ações/ }));
    expect(within(screen.getByRole("menu")).getAllByRole("menuitem").map(x => x.textContent)).toContain("Aceitar a diferença");
    p.unmount();
    responder({ "/api/contratos/1/medicoes": [{ ...COM_BOLETIM, com_envio_planilha: false, valor_atestado_centavos: 1234567,
      capa_divergencias: [] }] });
    pagina();
    fireEvent.click(await screen.findByRole("button", { name: /Mais ações/ }));
    expect(screen.queryByText(frase)).toBeNull();
    expect(within(screen.getByRole("menu")).getAllByRole("menuitem").map(x => x.textContent)).not.toContain("Aceitar a diferença");
  });
});

// issue #508: a pagina da obra em medicao -- cabecalho, barra de passos e os passos 1 e 2
describe("Página da obra em medição: barra de passos (issue #508)", () => {
  beforeEach(() => window.history.replaceState(null, "", "/obras/1/medicoes/5"));
  afterEach(() => { cleanup(); api.mockReset(); apiForm.mockReset(); });
  const ATIVA = { espelhos: [], regra: { situacao: "ativa" } };
  const SINFRA = { ...MEDICAO, com_envio_planilha: true, planilha_enviada_em: "2026-11-05" };
  const nomes = () => [...screen.getByRole("navigation", { name: "Passos da medição" }).querySelectorAll(".passo__nome")].map(x => x.textContent);
  const daVez = () => screen.getByRole("navigation", { name: "Passos da medição" }).querySelector("[aria-current='step'] .passo__nome")!.textContent;

  it("cabeçalho: a obra, a medição, o mês por extenso, o órgão e o valor grande", async () => {
    responder({ "/api/contratos/1/medicoes": [{ ...MEDICAO, estado: "nota_emitida" }] });
    const { container } = pagina();
    expect(await screen.findByRole("heading", { name: "Hospital", level: 1 })).toBeTruthy();
    await waitFor(() => expect([...container.querySelectorAll(".med-meta span")].map(x => x.textContent)).toEqual(["23ª Medição", "setembro de 2026", "SES"]));
    expect(container.querySelector(".med-valor")!.textContent).toBe("R$ 10.000,00");
  });

  it("a barra marca o passo da vez pelo estado da medição, com os seis passos onde a planilha/carta vai ao órgão", async () => {
    const casos: [string, string][] = [["planilha_gerada", "Planilha e carta"], ["planilha_enviada", "Análise do órgão"],
      ["boletim_recebido", "Espelhos"], ["espelho_gerado", "Espelhos"], ["espelho_enviado", "Notas"],
      ["nota_emitida", "Envio da nota"], ["protocolada", "Pagamento"]];
    for (const [estado, passo] of casos) {
      responder({ "/api/contratos/1/espelho": ATIVA, "/api/contratos/1/medicoes": [{ ...SINFRA, estado }],
        "/api/medicoes/5": detalhePlanilha(estado) });
      pagina();
      await waitFor(() => expect(daVez()).toBe(passo));
      expect(nomes()).toEqual(["Planilha e carta", "Análise do órgão", "Espelhos", "Notas", "Envio da nota", "Pagamento"]);
      cleanup();
    }
  });

  it("o passo feito leva o check e a data; o futuro fica cinza, sem data", async () => {
    responder({ "/api/contratos/1/espelho": { espelhos: [{ id: 3, numero: 1, versao: 1, situacao: "vigente", criado_em: "2026-11-10 12:00:00",
      criado_por_nome: null, medicoes: [{ id: 5, tipo: "execucao" }], envio: { enviado_em: "2026-11-11 15:00:00", remetente: "x" } }], regra: { situacao: "ativa" } },
      "/api/contratos/1/medicoes": [{ ...SINFRA, estado: "espelho_enviado", atestado_em: "2026-11-09",
        boletins: [{ id: 9, tem_arquivo: true, atestado_em: "2026-11-09" }] }] });
    pagina();
    const barra = await screen.findByRole("navigation", { name: "Passos da medição" });
    await waitFor(() => expect(within(barra).getByRole("button", { name: "Passo 1: Planilha e carta, feito em 05/11" })).toBeTruthy());
    expect(within(barra).getByRole("button", { name: "Passo 2: Análise do órgão, feito em 09/11" })).toBeTruthy();
    expect(within(barra).getByRole("button", { name: "Passo 3: Espelhos, feito em 11/11" })).toBeTruthy();
    expect(within(barra).getByRole("button", { name: "Passo 4: Notas" }).closest("li")!.className).toContain("passo--atual");
    expect(within(barra).getByRole("button", { name: "Passo 6: Pagamento" }).closest("li")!.className).toContain("passo--futuro");
  });

  it("na MT-PAR a barra começa em Espelhos, com 4 passos, e a planilha/carta mora no passo dos espelhos", async () => {
    responder({ "/api/contratos/1/espelho": ATIVA, "/api/contratos/1/medicoes": [{ ...MEDICAO, estado: "prevista", com_envio_planilha: false }] });
    const { container } = pagina();
    await waitFor(() => expect(container.querySelector("[data-nova-planilha='23']")).not.toBeNull());
    expect(nomes()).toEqual(["Espelhos", "Notas", "Envio da nota", "Pagamento"]);
    expect(daVez()).toBe("Espelhos");
    expect(within(screen.getByRole("navigation", { name: "Passos da medição" })).getByRole("button", { name: "Passo 1: Espelhos" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Espelhos", level: 2 })).toBeTruthy();
  });

  it("clicar num passo feito mostra ele no lugar do atual, com a faixa “Você está vendo o passo N, já feito”", async () => {
    responder({ "/api/contratos/1/espelho": ATIVA, "/api/contratos/1/medicoes": [{ ...SINFRA, estado: "planilha_enviada", dias_uteis_no_orgao: 3 }],
      "/api/medicoes/5": detalhePlanilha("planilha_enviada") });
    const { container } = pagina();
    await screen.findByRole("heading", { name: "Com o órgão há 3 dias úteis" });
    expect(screen.queryByRole("button", { name: "Voltar ao passo atual" })).toBeNull();
    fireEvent.click(within(screen.getByRole("navigation", { name: "Passos da medição" })).getByRole("button", { name: /Passo 1: Planilha e carta/ }));
    expect(screen.getByText(/Você está vendo o passo 1, já feito/)).toBeTruthy();
    expect(container.querySelector("[data-cartao-planilha='5']")).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Voltar ao passo atual" }));
    expect(screen.getByRole("heading", { name: "Com o órgão há 3 dias úteis" })).toBeTruthy();
    expect(screen.queryByText(/Você está vendo o passo/)).toBeNull();
  });

  it("depois do boletim, a falha da conferência avisa no passo 3, com Tentar de novo (code-review)", async () => {
    responder({ "/api/contratos/1/espelho": ATIVA, "/api/contratos/1/medicoes": [{ ...SINFRA, estado: "boletim_recebido" }],
      "/api/medicoes/5": Promise.reject(new Error("caiu")) });
    const { container } = pagina();
    await screen.findByRole("heading", { name: "Espelhos", level: 2 });
    expect(await screen.findByText(/Não foi possível conferir a planilha\/carta/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Tentar de novo" })).toBeTruthy();
    expect(container.querySelector("[data-espelho]")).toBeNull();
  });

  it("a conferência da revisão que chega depois não descarta o passo aberto pela âncora (code-review)", async () => {
    window.history.replaceState(null, "", "/obras/1/medicoes/5#passo-2");
    let soltar: (v: unknown) => void = () => {};
    const pendente = detalhePlanilha("planilha_enviada", { planilhas: [V1, { ...V1, id: 32, versao: 2, motivo: "Rev01" }] });
    responder({ "/api/contratos/1/espelho": ATIVA, "/api/contratos/1/medicoes": [{ ...SINFRA, estado: "planilha_enviada" }],
      "/api/medicoes/5": new Promise(r => { soltar = r; }) });
    pagina();
    await screen.findByRole("heading", { name: /^Com o órgão/ });
    soltar(pendente);
    // a vez passa ao passo 1 (revisao a enviar), mas a pagina continua no passo 2 que o link pediu (agora futuro)
    await waitFor(() => expect(daVez()).toBe("Planilha e carta"));
    expect(screen.getByRole("heading", { name: "Análise do órgão", level: 2 })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Voltar ao passo atual" })).toBeTruthy();
  });

  it("a âncora antiga #etapa-4 abre o Envio da nota; a nova #passo-2 abre a Análise do órgão", async () => {
    window.history.replaceState(null, "", "/obras/1/medicoes/5#etapa-4");
    responder({ "/api/contratos/1/medicoes": [{ ...MEDICAO, estado: "protocolada" }] });
    pagina();
    expect(await screen.findByRole("heading", { name: "Envio da nota", level: 2 })).toBeTruthy();
    cleanup();
    window.history.replaceState(null, "", "/obras/1/medicoes/5#passo-2");
    responder({ "/api/contratos/1/espelho": ATIVA, "/api/contratos/1/medicoes": [{ ...SINFRA, estado: "espelho_gerado" }] });
    pagina();
    expect(await screen.findByRole("heading", { name: "Análise do órgão", level: 2 })).toBeTruthy();
    expect(screen.getByText(/Você está vendo o passo 2, já feito/)).toBeTruthy();
  });
});

describe("Página da obra em medição: passo 2, análise do órgão (issue #508)", () => {
  beforeEach(() => window.history.replaceState(null, "", "/obras/1/medicoes/5"));
  afterEach(() => { cleanup(); api.mockReset(); apiForm.mockReset(); });
  const ENVIADA = { ...MEDICAO, estado: "planilha_enviada", com_envio_planilha: true, planilha_enviada_em: "2026-11-05",
    dias_uteis_no_orgao: 1, valor_protocolado_centavos: 219815879 };
  const PROC = { id: 4, codigo: "c", link: "https://siga.exemplo.com.br/p/4", numero: "PRO-2026/0001", nome: null, contrato_id: 1,
    obra: "Hospital", medicao_id: 5, medicao_titulo: "23ª Medição", protocolo_id: null, situacao: null, setor: "Fiscalização",
    caixa_entrada: false, com_quem: "fiscal do contrato", desde: "2026-11-06T13:20:00Z", dias_uteis: 1, hoje: 0, ultima: null, protocolado_em: null,
    movimentacoes: [
      { data: "2026-11-05T19:53:00Z", evento: "Protocolo recebido", cad_lotacao: "PROT/ORGAO", cad_pessoa: "", at_lotacao: "PROT/ORGAO", at_pessoa: "" },
      { data: "2026-11-06T13:20:00Z", evento: "Em análise", cad_lotacao: "FISC/ORGAO", cad_pessoa: "", at_lotacao: "FISC/ORGAO", at_pessoa: "Fiscal do contrato" },
      { data: "2026-11-05T21:10:00Z", evento: "Encaminhado", cad_lotacao: "PROT/ORGAO", cad_pessoa: "", at_lotacao: "FISC/ORGAO", at_pessoa: "" },
      { data: "2026-11-05T12:00:00Z", evento: "Aberto", cad_lotacao: "PROT/ORGAO", cad_pessoa: "", at_lotacao: "PROT/ORGAO", at_pessoa: "" }] };
  const SIGA = { lido_em: "2026-11-07T18:17:00Z", atrasado: false, processos: [{ ...PROC, id: 3, medicao_id: 99, numero: "OUTRO" }, PROC],
    pode_atualizar: true, robo: { estado: "parado", rodada: null, pedidos: [], avisos: [] } };

  it("com o órgão há N dias úteis, a data do envio, o processo SIGA com o link e onde está o processo", async () => {
    responder({ "/api/contratos/1/espelho": { espelhos: [], regra: { situacao: "ativa" } }, "/api/contratos/1/medicoes": [ENVIADA],
      "/api/medicoes/5": detalhePlanilha("planilha_enviada", { planilha_siga: { data: "2026-11-05", numero: "PRO-2026/0001" } }), "/api/siga": SIGA });
    pagina();
    const faixa = (await screen.findByRole("heading", { name: "Com o órgão há 1 dia útil" })).closest("section")!;
    expect(within(faixa).getByText("Enviada em").nextElementSibling!.textContent).toBe("05/11/2026");
    expect(within(faixa).getByText("Processo SIGA").nextElementSibling!.textContent).toBe("PRO-2026/0001");
    expect(within(faixa).getByText("Valor pedido").nextElementSibling!.textContent).toBe("R$ 2.198.158,79");
    await waitFor(() => expect(within(faixa).getByRole("link", { name: /Abrir no SIGA/ }).getAttribute("href")).toBe(PROC.link));
    const onde = screen.getByRole("heading", { name: "Onde está o processo" }).closest("section")!;
    expect(within(onde).getByText("Fiscalização")).toBeTruthy();
    expect(within(onde).getByText("fiscal do contrato desde 06/11")).toBeTruthy();
    // as tres mais recentes, da mais nova para a mais velha
    const movs = within(within(onde).getByRole("list", { name: "Últimas movimentações" })).getAllByRole("listitem").map(li => li.textContent);
    expect(movs).toHaveLength(3);
    expect(movs[0]).toContain("06/11 09:20");
    expect(movs[0]).toContain("Em análise");
    expect(movs[2]).toContain("Protocolo recebido");
    expect(within(onde).getByText(/Lido do SIGA às/).textContent).toContain("14:17");
  });

  it("revisão enviada: “Enviada em” e a data do passo 1 são as do envio mais recente (gate Sol, PR #553)", async () => {
    responder({ "/api/contratos/1/espelho": { espelhos: [], regra: { situacao: "ativa" } },
      "/api/contratos/1/medicoes": [{ ...ENVIADA, planilha_enviada_em: "2026-10-01", planilha_ultimo_envio_em: "2026-11-05" }],
      "/api/medicoes/5": detalhePlanilha("planilha_enviada", { planilha_enviada_em: "2026-10-01" }), "/api/siga": SIGA });
    pagina();
    const faixa = (await screen.findByRole("heading", { name: "Com o órgão há 1 dia útil" })).closest("section")!;
    expect(within(faixa).getByText("Enviada em").nextElementSibling!.textContent).toBe("05/11/2026");
    expect(within(screen.getByRole("navigation", { name: "Passos da medição" }))
      .getByRole("button", { name: "Passo 1: Planilha e carta, feito em 05/11" })).toBeTruthy();
  });

  it("sem processo no SIGA, o passo pede o nº do SIGA no lugar de onde está o processo", async () => {
    responder({ "/api/contratos/1/espelho": { espelhos: [], regra: { situacao: "ativa" } }, "/api/contratos/1/medicoes": [ENVIADA],
      "/api/medicoes/5": detalhePlanilha("planilha_enviada"), "/api/siga": { ...SIGA, processos: [] } });
    pagina();
    const onde = (await screen.findByRole("heading", { name: "Onde está o processo" })).closest("section")!;
    expect(within(onde).getByRole("textbox", { name: "Nº do SIGA" })).toBeTruthy();
  });

  it("“Pediu revisão” grava a nova versão da planilha pela mesma rota da revisão", async () => {
    responder({ "/api/contratos/1/espelho": { espelhos: [], regra: { situacao: "ativa" } }, "/api/contratos/1/medicoes": [ENVIADA],
      "/api/medicoes/5": detalhePlanilha("planilha_enviada"), "/api/siga": SIGA });
    apiForm.mockResolvedValue({ ok: true });
    pagina();
    fireEvent.click(await screen.findByRole("button", { name: /^Pediu revisão/ }));
    const form = screen.getByRole("form", { name: "Registrar revisão Rev01" });
    fireEvent.change(within(form).getByLabelText("Motivo (obrigatório)"), { target: { value: "Fiscal pediu ajuste" } });
    fireEvent.change(within(form).getByLabelText("Ofício assinado (PDF)"), { target: { files: [new File(["%PDF-1.4"], "o.pdf", { type: "application/pdf" })] } });
    fireEvent.change(within(form).getByLabelText("Planilha (.xlsx ou PDF)"), { target: { files: [new File(["PK"], "p.xlsx")] } });
    fireEvent.click(within(form).getByRole("button", { name: "Registrar revisão" }));
    await waitFor(() => expect(apiForm).toHaveBeenCalled());
    const [url, fd] = apiForm.mock.calls[0] as [string, FormData];
    expect(url).toBe("/api/medicoes/5/planilhas");
    expect(fd.get("motivo")).toBe("Fiscal pediu ajuste");
    expect(await screen.findByText("Revisão registrada.")).toBeTruthy();
  });

  it("depois de gravar a revisão, nada se oferece até o detalhe novo chegar (gate Sol, PR #553)", async () => {
    let leituras = 0;
    responder({ "/api/contratos/1/espelho": { espelhos: [], regra: { situacao: "ativa" } }, "/api/contratos/1/medicoes": [ENVIADA],
      "/api/siga": SIGA });
    const base = api.getMockImplementation()!;
    api.mockImplementation(async (url: string, opts?: RequestInit) => {
      if (url === "/api/medicoes/5") return ++leituras === 1 ? detalhePlanilha("planilha_enviada") : new Promise(() => {});
      return base(url, opts);
    });
    apiForm.mockResolvedValue({ ok: true });
    pagina();
    await screen.findByRole("button", { name: "Gerar o espelho sem o boletim" });
    fireEvent.click(screen.getByRole("button", { name: /^Pediu revisão/ }));
    const form = screen.getByRole("form", { name: "Registrar revisão Rev01" });
    fireEvent.change(within(form).getByLabelText("Motivo (obrigatório)"), { target: { value: "Fiscal pediu ajuste" } });
    fireEvent.change(within(form).getByLabelText("Ofício assinado (PDF)"), { target: { files: [new File(["%PDF-1.4"], "o.pdf", { type: "application/pdf" })] } });
    fireEvent.change(within(form).getByLabelText("Planilha (.xlsx ou PDF)"), { target: { files: [new File(["PK"], "p.xlsx")] } });
    fireEvent.click(within(form).getByRole("button", { name: "Registrar revisão" }));
    expect(await screen.findByText("Revisão registrada.")).toBeTruthy();
    await waitFor(() => expect(leituras).toBeGreaterThanOrEqual(2));
    expect(screen.queryByRole("button", { name: /^Pediu revisão/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Gerar o espelho sem o boletim" })).toBeNull();
  });
});

describe("Página da obra em medição: passos 3 a 6 (issue #514)", () => {
  beforeEach(() => window.history.replaceState(null, "", "/obras/1/medicoes/5"));
  afterEach(() => { cleanup(); api.mockReset(); });

  it("passo Espelhos: a tabela num cartão e “Enviar ao faturamento” no outro; o total se confere com o aprovado (senão o pedido)", async () => {
    responder({ "/api/contratos/1/medicoes": [{ ...MEDICAO, estado: "espelho_gerado", valor_atestado_centavos: 999999 },
      { ...MEDICAO, id: 6, tipo: "reajuste", estado: "espelho_gerado", valor_protocolado_centavos: 50001 }] });
    const { container } = pagina();
    await screen.findByRole("region", { name: "Enviar ao faturamento" });
    const espelhos = container.querySelector("#espelhos-titulo")!.closest("section")!;
    const refs = JSON.parse(espelhos.querySelector("[data-espelho='espelho']")!.getAttribute("data-referencias")!);
    expect(refs).toEqual({ 5: { valor: 999999, fonte: "aprovado" }, 6: { valor: 50001, fonte: "pedido" } });
    const fat = screen.getByRole("region", { name: "Enviar ao faturamento" });
    expect(fat.querySelector("[data-espelho='faturamento']")).not.toBeNull();
    expect(container.querySelector(".med-etapa")).toBeNull();          // sem o cartao "Passo N" de antes
  });

  it("passo Notas: a nota de cada espelho num cartão e a fatura do consórcio ao lado", async () => {
    responder({ "/api/contratos/1/medicoes": [{ ...MEDICAO, estado: "espelho_enviado" }] });
    const { container } = pagina();
    const notas = await screen.findByRole("region", { name: "Notas fiscais" });
    expect(notas.querySelector("[data-medicao='5']")).not.toBeNull();
    expect(container.querySelector("[data-frc='5']")).not.toBeNull();
  });

  it("passo Pagamento: a cota da Lotufo no consórcio, sem botão para a engenharia", async () => {
    responder({ "/api/contratos/1/medicoes": [{ ...MEDICAO, notas: [{ nota_id: 1, coligada: 1, numero: "2351", serie: null, emissao: null,
        valor_centavos: 400001, recebido_centavos: 0, devido_centavos: 368001, falta_centavos: 368001, da_lotufo: true, da_cota: true,
        recebido_em: null, origem: "rm", regra: null }], notas_faltam: 0,
        pagamento_cota: { notas_faltam: 0, completo: true, total_centavos: 368001, recebido_centavos: 0, falta_centavos: 368001, parcial: false } }],
      "/api/contratos/1/cabecalho": { obra: "Integra", orgao: "SINFRA", instrumento: "CT 1", percentual_lotufo_bp: 4000 } });
    pagina("engenharia");
    expect(await screen.findByText("A receber · cota da Lotufo")).toBeTruthy();
    expect(screen.getByLabelText("A receber: R$ 3.680,01")).toBeTruthy();       // o titulo (liquido), nao o bruto
    expect(screen.queryByRole("button", { name: "Registrar recebimento" })).toBeNull();
  });

  it("par com o reajuste cancelado: o grupo é só a medição, que mostra “Recebida” e o total dela (#557)", async () => {
    responder({ "/api/contratos/1/medicoes": [{ ...MEDICAO, estado: "recebida", recebida_em: "2026-11-20" },
      { ...MEDICAO, id: 6, tipo: "reajuste", estado: "cancelada", valor_protocolado_centavos: 50001 }] });
    pagina();
    const numeros = (await screen.findByText("Total da medição")).closest(".pag-numeros")!;
    expect(within(numeros as HTMLElement).getByText("R$ 10.000,00")).toBeTruthy();
    expect(within(numeros as HTMLElement).getByText("Recebida")).toBeTruthy();
    expect(within(numeros as HTMLElement).getByText("20/11/2026")).toBeTruthy();
    expect(screen.getByLabelText(/^Valor: R\$\s10\.000,00$/)).toBeTruthy();       // o valor grande, sem o reajuste cancelado
  });
});
