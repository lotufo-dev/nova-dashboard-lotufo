import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Medicao } from "./Medicoes";
import { ApiErro } from "./api";
import PassoAnalise from "./PassoAnalise";
import type { DetalhePlanilha } from "./PlanilhaCarta";

const { api } = vi.hoisted(() => ({ api: vi.fn(async (_caminho: string, _opts?: RequestInit): Promise<unknown> => ({ processos: [] })) }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

const M = { id: 5, numero: 7, tipo: "execucao", competencia: "2026-07", estado: "boletim_recebido",
  valor_protocolado_centavos: 1234567, valor_protocolado_origem: "manual", valor_atestado_centavos: 1200001,
  valor_atestado_origem: "manual", atestado_em: "2026-08-10", nf_emitida_em: null, recebida_em: null, congelada: 0,
  protocolos: [], boletins: [{ id: 9, tem_arquivo: true, valor_centavos: 1200001, atestado_em: "2026-08-10" }] } as Medicao;
const agir = vi.fn(async () => true);
const abrir = (m: Medicao) => render(<PassoAnalise m={m} planilha={null} podeEditar salvando={false} agir={agir} aoMudarSiga={() => {}} />);
const aprovacao = () => screen.getByLabelText("Aprovação");

describe("Diferença do boletim no passo 2 (issue #288)", () => {
  afterEach(() => cleanup());

  it("aprovado abaixo do pedido: a diferença aparece com o botão de aceitar", () => {
    abrir(M);
    expect(within(aprovacao()).getByText("Diferença")).toBeTruthy();
    expect(aprovacao().textContent).toMatch(/−R\$\s345,66/);
    expect(screen.getByRole("button", { name: "Aceitar a diferença" })).toBeTruthy();
  });

  it("sem diferença abaixo do pedido, ou já aceita, a linha não aparece", () => {
    const { unmount } = abrir({ ...M, valor_atestado_centavos: 1234567 });
    expect(within(aprovacao()).queryByText("Diferença")).toBeNull();
    unmount();
    abrir({ ...M, diferenca_aceita: { atesto_id: 9, justificativa: "glosa de itens", usuario: "Eng",
      criado_em: "2026-11-08 10:00:00", diferenca_centavos: -34566 } });
    expect(within(aprovacao()).queryByText("Diferença")).toBeNull();
    expect(screen.getByText("Diferença aceita")).toBeTruthy();
  });
});

describe("Link de acompanhamento do SIGA no passo de análise (issue #668)", () => {
  afterEach(() => { cleanup(); api.mockReset(); api.mockImplementation(async () => ({ processos: [] })); });

  const ENVIADA = { ...M, estado: "planilha_enviada", planilha_enviada_em: "2026-10-20", boletins: [] } as Medicao;
  const PLANILHA = { planilha_enviada_em: "2026-10-20", planilha_siga: { data: "2026-10-20", numero: "ORGAO-PRO-2026/00077" },
    planilhas: [] } as unknown as DetalhePlanilha;
  const SEM_NUMERO = { ...PLANILHA, planilha_siga: null } as unknown as DetalhePlanilha;
  const PROCESSO = { id: 3, codigo: "AbCdEf1234", link: "https://siga.exemplo.com.br/acompanhar?n=AbCdEf1234",
    numero: "ORGAO-PRO-2026/00077", medicao_id: 5, setor: "COFIN", com_quem: "Fulano", desde: "2026-10-22 09:00:00",
    dias_uteis: 4, movimentacoes: [] };
  const ver = (planilha: DetalhePlanilha, podeEditar = true) => render(
    <PassoAnalise m={ENVIADA} planilha={planilha} podeEditar={podeEditar} salvando={false} agir={agir} aoMudarSiga={() => {}} />);
  const acao = () => screen.findByRole("button", { name: "Colar o link de acompanhamento" });
  async function colar(link: string) {
    fireEvent.click(await acao());
    fireEvent.change(screen.getByRole("textbox", { name: "Link de acompanhamento" }), { target: { value: link } });
    fireEvent.click(screen.getByRole("button", { name: "Gravar" }));
  }

  it("com número do SIGA e sem processo, oferece colar o link; sem número, não", async () => {
    const { unmount } = ver(PLANILHA);
    expect(await acao()).toBeTruthy();
    expect(screen.queryByRole("textbox", { name: "Link de acompanhamento" })).toBeNull();
    unmount();
    ver(SEM_NUMERO);
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/siga"));
    expect(screen.queryByRole("button", { name: "Colar o link de acompanhamento" })).toBeNull();
  });

  it("colar um link válido grava na medição e o passo mostra o setor e desde quando", async () => {
    let gravado = false;
    api.mockImplementation(async (caminho: string) => {
      if (caminho === "/api/siga/medicoes/5/link") { gravado = true; return { id: 3 }; }
      return caminho === "/api/siga" ? { processos: gravado ? [PROCESSO] : [] } : [];
    });
    ver(PLANILHA);
    await colar(` ${PROCESSO.link} `);
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/siga/medicoes/5/link",
      { method: "POST", body: JSON.stringify({ link: PROCESSO.link }) }));
    expect(await screen.findByText("COFIN")).toBeTruthy();
    expect(screen.getByText("Fulano desde 22/10")).toBeTruthy();
    expect(screen.getByRole("link", { name: /Abrir no SIGA/ }).getAttribute("href")).toBe(PROCESSO.link);
    expect(screen.queryByRole("button", { name: "Colar o link de acompanhamento" })).toBeNull();
  });

  it("link recusado pelo servidor: o erro aparece no campo, que continua aberto", async () => {
    api.mockImplementation(async (caminho: string) => {
      if (caminho === "/api/siga/medicoes/5/link") throw new ApiErro(422, "Link do SIGA inválido: cole o link que o órgão mandou");
      return caminho === "/api/siga" ? { processos: [] } : [];
    });
    ver(PLANILHA);
    await colar("https://outro.exemplo.com.br/x");
    const erro = await screen.findByRole("alert");
    expect(erro.textContent).toBe("Link do SIGA inválido: cole o link que o órgão mandou");
    const campo = screen.getByRole("textbox", { name: "Link de acompanhamento" });
    expect(campo.getAttribute("aria-invalid")).toBe("true");
    expect(campo.getAttribute("aria-describedby")).toBe(erro.id);
  });

  it("quem só consulta não vê a ação nem o campo", async () => {
    ver(PLANILHA, false);
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/siga"));
    expect(screen.queryByRole("button", { name: "Colar o link de acompanhamento" })).toBeNull();
    expect(screen.queryByRole("textbox", { name: "Link de acompanhamento" })).toBeNull();
  });

  it("com o processo já ligado à medição, a ação não aparece", async () => {
    api.mockImplementation(async (caminho: string) => caminho === "/api/siga" ? { processos: [PROCESSO] } : []);
    ver(PLANILHA);
    expect(await screen.findByText("COFIN")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Colar o link de acompanhamento" })).toBeNull();
  });
});

describe("Respostas do órgão por e-mail (issue #644)", () => {
  afterEach(() => { cleanup(); api.mockReset(); api.mockImplementation(async () => ({ processos: [] })); });

  const R = (id: number, recebida_em: string, trecho: string) => ({ id, medicao_id: 5, remetente: "fiscal@orgao-a.exemplo.com.br",
    remetente_nome: id === 1 ? "Fiscal do contrato" : null, recebida_em, assunto: "RES: medição", trecho, anexos: [] });

  it("lista remetente, data e trecho, na ordem que o servidor mandou (da mais nova para a mais antiga)", async () => {
    api.mockImplementation(async (caminho: string) => caminho === "/api/medicoes/5/respostas-orgao"
      ? [R(2, "2026-11-11T13:00:00Z", "Segue o parecer."), R(1, "2026-11-10T14:00:00Z", "Recebido.")] : { processos: [] });
    abrir({ ...M, estado: "planilha_enviada" });
    const itens = within(await screen.findByRole("list", { name: "Respostas do órgão por e-mail" })).getAllByRole("listitem");
    expect(itens).toHaveLength(2);
    expect(itens[0].textContent).toContain("fiscal@orgao-a.exemplo.com.br");
    expect(itens[0].textContent).toContain("11/11");
    expect(itens[0].textContent).toContain("Segue o parecer.");
    expect(itens[1].textContent).toContain("Fiscal do contrato");
    expect(itens[1].textContent).toContain("Recebido.");
  });

  it("sem resposta registrada a lista não aparece; chega uma leitura nova e a lista é relida", async () => {
    abrir({ ...M, estado: "planilha_enviada" });
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/medicoes/5/respostas-orgao"));
    expect(screen.queryByRole("list", { name: "Respostas do órgão por e-mail" })).toBeNull();
    api.mockImplementation(async (caminho: string) => caminho === "/api/medicoes/5/respostas-orgao"
      ? [R(1, "2026-11-10T14:00:00Z", "Recebido.")] : { processos: [] });
    act(() => { window.dispatchEvent(new Event("respostas-orgao-lidas")); });
    expect(await screen.findByText("Recebido.")).toBeTruthy();
  });
});
