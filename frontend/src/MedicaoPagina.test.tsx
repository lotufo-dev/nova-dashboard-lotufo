import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiErro } from "./api";
import type { Usuario } from "./Login";
import MedicaoPagina from "./MedicaoPagina";

const { api, apiForm } = vi.hoisted(() => ({ api: vi.fn(), apiForm: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api, apiForm }));
// Cada cartao tem fluxo proprio; aqui so' importa que, ao avisar a pagina, ela releia o que os outros mostram.
vi.mock("./Espelho", () => ({
  default: ({ parte }: { parte?: string }) => <div data-espelho={parte} />,
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
    await screen.findByRole("heading", { name: "Envio ao órgão", level: 2 });
    expect(container.querySelectorAll(".med-etapa")).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "Voltar à etapa atual" })).toBeNull();
    // 100% da Lotufo: o cabecalho nao fala de cota nem de "valores cheios"
    expect(container.querySelector(".med-meta")!.textContent).not.toMatch(/cota|valores cheios/);
    const trilho = screen.getByRole("navigation", { name: "Etapas da medição" });
    expect(trilho.querySelector("[aria-current='step']")!.textContent).toContain("Envio ao órgão");
    fireEvent.click(within(trilho).getByRole("button", { name: /Etapa 3: Nota fiscal/ }));
    expect(screen.getByRole("heading", { name: "Nota fiscal", level: 2 })).toBeTruthy();
    expect(container.querySelectorAll(".med-etapa")).toHaveLength(1);
    expect(screen.queryByText(/Você está vendo a etapa/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Voltar à etapa atual" }));
    expect(screen.getByRole("heading", { name: "Envio ao órgão", level: 2 })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Voltar à etapa atual" })).toBeNull();
    // etapa que ainda não começou: abre, so' com o selo de que libera depois (o corpo nao repete)
    fireEvent.click(within(trilho).getByRole("button", { name: /Etapa 5: Pagamento/ }));
    expect(screen.getByRole("button", { name: "Voltar à etapa atual" })).toBeTruthy();
    expect(screen.getByText("Libera depois da etapa 4")).toBeTruthy();
    expect(screen.queryByText("Libera depois da etapa 4.")).toBeNull();
  });

  it("a âncora #etapa-N abre a etapa; as âncoras antigas (#notas) abrem a etapa 3", async () => {
    responder();
    abrirEtapa(2);
    pagina();
    expect(await screen.findByRole("heading", { name: "Faturamento", level: 2 })).toBeTruthy();
    cleanup();
    window.history.replaceState(null, "", "/obras/1/medicoes/5#notas");
    pagina();
    expect(await screen.findByRole("heading", { name: "Nota fiscal", level: 2 })).toBeTruthy();
  });

  it("o caminho do topo: Medições volta à aba onde a medição está e a obra leva à página da obra", async () => {
    responder({ "/api/contratos/1/medicoes": [{ ...MEDICAO, estado: "nota_emitida" }] });
    pagina();
    const caminho = await screen.findByRole("navigation", { name: "Você está em" });
    await waitFor(() => expect(within(caminho).getByRole("link", { name: "Hospital" })).toBeTruthy());
    expect(within(caminho).getByRole("link", { name: "Medições" }).getAttribute("href")).toBe("/medicoes/enviar-nota");
    expect(within(caminho).getByRole("link", { name: "Hospital" }).getAttribute("href")).toBe("/obras/1");
  });

  it("título “Nª Medição + Reajuste”, valores somados e a coluna com Resumo e Linha do tempo", async () => {
    const REAJ = { ...MEDICAO, id: 6, tipo: "reajuste", valor_protocolado_centavos: 50000 };
    responder({ "/api/contratos/1/medicoes": [MEDICAO, REAJ] });
    pagina();
    expect(await screen.findByRole("heading", { name: "23ª Medição + Reajuste", level: 1 })).toBeTruthy();
    const lateral = screen.getByRole("complementary", { name: "Resumo e linha do tempo" });
    expect(within(lateral).getByText("Resumo da medição")).toBeTruthy();
    expect(within(lateral).getByText("Linha do tempo")).toBeTruthy();
    expect(within(lateral).getByText("Total").closest("div")!.textContent).toContain("10.500,00");
  });

  it("“Mais ações” só tem atestado, assinatura, medição final, cancelar, desistir e liberar envio preso", async () => {
    responder({ "/api/contratos/1/medicoes": [{ ...MEDICAO, estado: "prevista" }] });
    pagina();
    fireEvent.click(await screen.findByRole("button", { name: /Mais ações/ }));
    const itens = within(screen.getByRole("menu")).getAllByRole("menuitem").map(x => x.textContent);
    expect(itens).toEqual(["Definir o atestado", "Registrar assinatura", "Marcar como medição final", "Cancelar a medição", "Registrar desistência"]);
    fireEvent.click(screen.getByRole("menuitem", { name: "Cancelar a medição" }));
    expect(screen.getByRole("heading", { name: "Cancelar a medição", level: 2 })).toBeTruthy();
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

  it("quem só consulta não vê “Registrar protocolo feito fora”", async () => {
    abrirEtapa(4);
    responder();
    pagina("diretoria");
    await screen.findByRole("heading", { name: "Envio ao órgão", level: 2 });
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
    fireEvent.click(await screen.findByText("Registrar envio feito fora do sistema"));
    fireEvent.click(screen.getAllByRole("checkbox")[1]);
    fireEvent.change(screen.getByLabelText("Como e para quem a nota foi enviada"), { target: { value: "Pelo Outlook" } });
    fireEvent.click(screen.getByRole("button", { name: "Registrar" }));
    const alerta = await screen.findByRole("alert");
    expect(alerta.textContent).toContain("Já registrados: 23ª medição");
    // a pagina nao foi relida: o erro continua a' vista, ainda na etapa 4
    await new Promise(r => setTimeout(r, 50));
    expect(screen.getByRole("alert").textContent).toContain("Já registrados");
    expect(screen.getByRole("heading", { name: "Envio ao órgão", level: 2 })).toBeTruthy();
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
    expect(container.querySelector(".med-etapa__cabeca")!.textContent).not.toContain("faltam 2 notas");
    expect(container.textContent).not.toContain("vão no mesmo e-mail");
  });

  it("órgão que junta, esperando o reajuste: a etapa 4 é a da vez, em espera, e a saída de emergência está na linha do envio", async () => {
    comPar(SINFRA);
    pagina();
    const botao = await screen.findByRole("button", { name: "Enviar a medição sem o reajuste…" });
    const trilho = screen.getByRole("navigation", { name: "Etapas da medição" });
    expect(trilho.querySelector(".seta--espera")!.textContent).toContain("Envio ao órgão");
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
    const trilho = screen.getByRole("navigation", { name: "Etapas da medição" });
    expect(trilho.querySelector(".seta--espera")).toBeNull();
    expect(trilho.querySelector("[aria-current='step']")!.textContent).toContain("Nota fiscal");
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
    expect(screen.getAllByRole("navigation", { name: "Etapas da medição" })).toHaveLength(1);
    expect(container.querySelector(".seta--espera")).toBeNull();
    expect(screen.queryByRole("button", { name: /sem o reajuste/ })).toBeNull();
  });

  it("medição sem reajuste: um bloco só e o título da medição", async () => {
    abrirEtapa(3);
    responder({ "/api/medicoes/5/par": { junta: true, orgao: "SINFRA", metades: [] } });
    const { container } = pagina();
    expect(await screen.findByRole("heading", { name: "23ª Medição", level: 1 })).toBeTruthy();
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
