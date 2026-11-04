import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CartaoPlanilha, centavosDoTexto, dataDoEnvio, NovaPlanilhaCarta, rotuloVersao, seloDoEnvio, type DetalhePlanilha } from "./PlanilhaCarta";

const { api, apiForm } = vi.hoisted(() => ({ api: vi.fn(), apiForm: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api, apiForm }));

const SUGESTAO = { tipo: "execucao", numero: 4, numero_orgao: null, competencia: "2026-08", periodo_inicio: "2026-08-01",
  periodo_fim: "2026-08-31", vigente_centavos: 100_000_00, acumulado_anterior_centavos: 30_000_01, saldo_centavos: 69_999_99 };
const SOBREPOE = "O período se sobrepõe ao da 3ª medição, que vai até 05/08/2026";

const pdf = (nome: string) => new File(["%PDF-1.4"], nome, { type: "application/pdf" });

function anexar(rotulo: string, f: File) {
  fireEvent.change(screen.getByLabelText(rotulo), { target: { files: [f] } });
}

describe("Nova planilha/carta", () => {
  afterEach(() => { cleanup(); api.mockReset(); apiForm.mockReset(); });

  // a conferencia devolve o acumulado DO nº consultado: 10.000,00 por medicao anterior, contrato de 100.000,00
  function responder(avisos: (inicio: string) => string[] = () => []) {
    api.mockImplementation(async (url: string) => {
      if (url.startsWith("/api/contratos/9/planilhas/sugestao")) return SUGESTAO;
      if (url.startsWith("/api/contratos/9/planilhas/avisos")) {
        const q = new URLSearchParams(url.split("?")[1]);
        const acumulado = (Number(q.get("numero")) - 1) * 10_000_00;
        return { avisos: avisos(q.get("periodo_inicio") ?? ""), acumulado_anterior_centavos: acumulado,
          saldo_centavos: 100_000_00 - acumulado };
      }
      return {};
    });
  }

  it("sugere nº e período, mostra o acumulado anterior e o saldo, e o saldo depois do pedido", async () => {
    api.mockImplementation(async (url: string) => (url.includes("/sugestao") ? SUGESTAO : new Promise(() => {})));
    render(<NovaPlanilhaCarta contratoId={9} aoRegistrar={() => {}} />);
    expect(((await screen.findByLabelText("Nº da medição")) as HTMLInputElement).value).toBe("4");
    expect((screen.getByLabelText("Período: de") as HTMLInputElement).value).toBe("2026-08-01");
    expect((screen.getByLabelText("até") as HTMLInputElement).value).toBe("2026-08-31");
    const saldo = screen.getByText("Acumulado anterior").closest("dl")!;
    expect(saldo.textContent).toContain("R$ 30.000,01");
    expect(saldo.textContent).toContain("R$ 69.999,99");
    expect(within(saldo).queryByText("Saldo depois do pedido")).toBeNull();
    // centavo impar: 69.999,99 - 12.345,67 = 57.654,32, em centavos inteiros
    fireEvent.change(screen.getByLabelText("Valor pedido"), { target: { value: "12.345,67" } });
    expect(within(saldo).getByText("Saldo depois do pedido").nextElementSibling!.textContent).toBe("R$ 57.654,32");
  });

  it("avisa o período sobreposto enquanto a pessoa digita, e o aviso some quando corrige", async () => {
    responder(inicio => (inicio <= "2026-08-05" ? [SOBREPOE] : []));
    render(<NovaPlanilhaCarta contratoId={9} aoRegistrar={() => {}} />);
    expect(await screen.findByText(SOBREPOE)).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Período: de"), { target: { value: "2026-08-06" } });
    await waitFor(() => expect(screen.queryByText(SOBREPOE)).toBeNull());
    // a leitura e' so' de aviso: nada foi gravado
    expect(apiForm).not.toHaveBeenCalled();
  });

  it("sem o ofício ou a planilha não grava; com os dois, registra e devolve a medição", async () => {
    responder();
    apiForm.mockResolvedValue({ medicao_id: 77, versao: 1, estado: "planilha_gerada", avisos: [] });
    const aoRegistrar = vi.fn();
    render(<NovaPlanilhaCarta contratoId={9} aoRegistrar={aoRegistrar} />);
    await screen.findByLabelText("Nº da medição");
    fireEvent.change(screen.getByLabelText("Valor pedido"), { target: { value: "12.345,67" } });
    fireEvent.click(screen.getByRole("button", { name: "Registrar planilha/carta" }));
    expect(await screen.findByText("Anexe o ofício assinado.")).toBeTruthy();
    expect(screen.getByText("Anexe a planilha.")).toBeTruthy();
    expect(apiForm).not.toHaveBeenCalled();
    anexar("Ofício assinado (PDF)", pdf("oficio.pdf"));
    anexar("Planilha (.xlsx ou PDF)", new File(["PK"], "planilha.xlsx"));
    fireEvent.change(screen.getByLabelText("Nº no órgão"), { target: { value: "12" } });
    fireEvent.click(screen.getByRole("button", { name: "Registrar planilha/carta" }));
    await waitFor(() => expect(aoRegistrar).toHaveBeenCalledWith(expect.objectContaining({ medicao_id: 77 })));
    const [url, fd] = apiForm.mock.calls[0] as [string, FormData];
    expect(url).toBe("/api/contratos/9/planilhas");
    expect([fd.get("numero"), fd.get("tipo"), fd.get("competencia"), fd.get("periodo_inicio"), fd.get("periodo_fim"),
      fd.get("valor"), fd.get("numero_orgao")]).toEqual(["4", "execucao", "2026-08", "2026-08-01", "2026-08-31", "12.345,67", "12"]);
    expect((fd.get("oficio") as File).name).toBe("oficio.pdf");
    expect((fd.get("planilha") as File).name).toBe("planilha.xlsx");
  });

  it("a medição prevista entra com o nº e a competência dela, sem o nº do órgão de outro nº", async () => {
    responder();
    api.mockImplementation(async (url: string) => (url.includes("/sugestao") ? { ...SUGESTAO, numero_orgao: 9 } : { avisos: [] }));
    render(<NovaPlanilhaCarta contratoId={9} inicial={{ numero: 6, competencia: "2026-02" }} aoRegistrar={() => {}} />);
    expect(((await screen.findByLabelText("Nº da medição")) as HTMLInputElement).value).toBe("6");
    expect((screen.getByLabelText("Período: de") as HTMLInputElement).value).toBe("2026-02-01");
    expect((screen.getByLabelText("até") as HTMLInputElement).value).toBe("2026-02-28");
    // o 9 e' o do nº sugerido (4): na prevista o campo fica vazio e o servidor mantem o que ela ja' tem
    expect((screen.getByLabelText("Nº no órgão") as HTMLInputElement).value).toBe("");
  });

  it("trocar o nº troca o acumulado e o saldo pelos do nº digitado", async () => {
    responder();
    render(<NovaPlanilhaCarta contratoId={9} aoRegistrar={() => {}} />);
    const saldo = (await screen.findByText("Acumulado anterior")).closest("dl")!;
    await waitFor(() => expect(saldo.textContent).toContain("R$\u00a030.000,00"));
    fireEvent.change(screen.getByLabelText("Nº da medição"), { target: { value: "2" } });
    // antes da leitura do nº novo, nada de numero de outra medicao
    expect(saldo.textContent).not.toContain("R$\u00a030.000,00");
    await waitFor(() => expect(saldo.textContent).toContain("R$\u00a010.000,00"));
    expect(saldo.textContent).toContain("R$\u00a090.000,00");
  });
});

// ------------------------------------------------------------------------------------------------ cartao

const V1 = { id: 31, versao: 1, periodo_inicio: "2026-08-01", periodo_fim: "2026-08-31", valor_pedido_centavos: 12_345_67,
  acumulado_anterior_centavos: 0, motivo: null, criado_em: "2026-09-01 12:00:00", usuario: "Operação" };
function detalhe(extra: Partial<DetalhePlanilha> = {}, envio: Partial<DetalhePlanilha["envio_planilha"]> = {}): DetalhePlanilha {
  return { id: 5, contrato_id: 9, numero: 4, tipo: "execucao", competencia: "2026-08", estado: "planilha_gerada", planilha_enviada_em: null, planilha_envio_origem: null,
    planilhas: [V1], planilha_siga: null, ...extra,
    envio_planilha: { disponivel: true, motivo: null, envios: [], reserva: null, pecas: [], pecas_do_orgao: [], ...envio } };
}
const PREVIA = { numero_oficio: "CT-301-LT-2026", versao: 1, para: ["protocolo@exemplo.com.br"], copia: ["fiscal@exemplo.com.br"],
  assunto: "CT-301-LT-2026 - 4ª Medição (08_2026) - Obra Exemplo", corpo: "Encaminho arquivo para protocolo.",
  anexos: [{ nome: "CT-301-LT-2026.pdf", tamanho: 1200, sha256: "a".repeat(64) },
    { nome: "4a Medicao.zip", tamanho: 3400, sha256: "b".repeat(64) }], total: 4600, limite: 30_000_000, pendencias: [] };

describe("Cartão da planilha/carta", () => {
  afterEach(() => { cleanup(); api.mockReset(); apiForm.mockReset(); });

  it("Enviar para protocolo abre o e-mail com assunto, corpo e anexos; depois do envio o cartão mostra Enviada em dd/mm", async () => {
    let atual = detalhe();
    api.mockImplementation(async (url: string, opts?: RequestInit) => {
      if (url === "/api/medicoes/5") return atual;
      if (url === "/api/medicoes/5/envio-planilha/previa") return PREVIA;
      if (url === "/api/medicoes/5/envio-planilha" && opts?.method === "POST") {
        atual = detalhe({ estado: "planilha_enviada", planilha_enviada_em: "2026-09-03", planilha_envio_origem: "sistema" },
          { disponivel: false, motivo: "A versão 1 da planilha/carta já foi enviada: para enviar de novo, registre uma revisão" });
        return { envio_id: 1 };
      }
      return [];
    });
    const aoMudar = vi.fn();
    render(<CartaoPlanilha medicaoId={5} podeEditar aoMudar={aoMudar} />);
    expect(await screen.findByText("Gerada")).toBeTruthy();
    const versoes = screen.getByRole("table", { name: "Versões da planilha/carta" });
    expect(within(versoes).getByText("Original")).toBeTruthy();
    expect(versoes.textContent).toContain("R$ 12.345,67");
    fireEvent.click(screen.getByRole("button", { name: "Enviar para protocolo" }));
    fireEvent.change(screen.getByLabelText("Nº do ofício (CT)"), { target: { value: "301" } });
    fireEvent.click(screen.getByRole("button", { name: "Prévia do e-mail" }));
    expect(((await screen.findByLabelText("Assunto")) as HTMLInputElement).value).toBe(PREVIA.assunto);
    const anexos = screen.getByRole("list", { name: "Anexos" });
    expect(within(anexos).getByText("CT-301-LT-2026.pdf")).toBeTruthy();
    expect(within(anexos).getByText("4a Medicao.zip")).toBeTruthy();
    expect(screen.getByText("Encaminho arquivo para protocolo.")).toBeTruthy();
    expect(api.mock.calls.find(c => c[0] === "/api/medicoes/5/envio-planilha/previa")![1].body).toBe(JSON.stringify({ numero_oficio: "301" }));
    fireEvent.click(screen.getByRole("button", { name: "Enviar para protocolo" }));
    expect(await screen.findByText("Enviada em 03/09")).toBeTruthy();
    expect(screen.getByText(/^Planilha\/carta enviada às \d{2}:\d{2}\.$/)).toBeTruthy();
    const envio = api.mock.calls.find(c => c[0] === "/api/medicoes/5/envio-planilha")!;
    const corpo = JSON.parse(envio[1].body);
    expect(corpo.numero_oficio).toBe("CT-301-LT-2026");
    expect(corpo.para).toEqual(["protocolo@exemplo.com.br"]);
    expect(corpo.assunto).toBe(PREVIA.assunto);
    expect(corpo.anexos_previa).toEqual(PREVIA.anexos);
    expect(aoMudar).toHaveBeenCalled();
    // enviada a versao vigente, o envio pelo sistema some ate' a revisao; o nº do SIGA aparece para digitar
    expect(screen.queryByRole("button", { name: "Enviar para protocolo" })).toBeNull();
    expect(screen.getByRole("textbox", { name: "Nº do SIGA" })).toBeTruthy();
  });

  it("envio com pendência pede a justificativa antes de sair", async () => {
    api.mockImplementation(async (url: string) => {
      if (url === "/api/medicoes/5") return detalhe();
      if (url === "/api/medicoes/5/envio-planilha/previa") return { ...PREVIA, pendencias: [{ codigo: "peca", mensagem: "Falta a peça que o órgão exige: Memória de cálculo" }] };
      return [];
    });
    render(<CartaoPlanilha medicaoId={5} podeEditar aoMudar={() => {}} />);
    fireEvent.click(await screen.findByRole("button", { name: "Enviar para protocolo" }));
    fireEvent.change(screen.getByLabelText("Nº do ofício (CT)"), { target: { value: "301" } });
    fireEvent.click(screen.getByRole("button", { name: "Prévia do e-mail" }));
    expect(await screen.findByText("Falta a peça que o órgão exige: Memória de cálculo")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Enviar para protocolo" }));
    expect(await screen.findByText("Escreva a justificativa, com pelo menos 10 caracteres.")).toBeTruthy();
    expect(api.mock.calls.some(c => c[0] === "/api/medicoes/5/envio-planilha")).toBe(false);
  });

  it("onde o sistema não envia (MT-PAR), o motivo aparece e fica o registro por fora", async () => {
    const motivo = "Na MT-PAR não há envio da planilha/carta: o ofício vai com a nota";
    api.mockResolvedValue(detalhe({}, { disponivel: false, motivo }));
    apiForm.mockResolvedValue({ medicao_id: 5, estado: "planilha_enviada", versao: 1 });
    render(<CartaoPlanilha medicaoId={5} podeEditar aoMudar={() => {}} />);
    expect(await screen.findByText(motivo)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Enviar para protocolo" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Registrar envio por fora" }));
    fireEvent.change(screen.getByLabelText("Data do envio"), { target: { value: "2026-09-02" } });
    fireEvent.change(screen.getByLabelText("Meio"), { target: { value: "Balcão do protocolo" } });
    fireEvent.change(screen.getByLabelText("Nº do protocolo"), { target: { value: "SIGA 123/2026" } });
    fireEvent.click(screen.getByRole("button", { name: "Registrar envio" }));
    await waitFor(() => expect(apiForm).toHaveBeenCalled());
    const [url, fd] = apiForm.mock.calls[0] as [string, FormData];
    expect(url).toBe("/api/medicoes/5/planilhas/envio-externo");
    expect([fd.get("enviado_em"), fd.get("meio"), fd.get("numero_protocolo")]).toEqual(["2026-09-02", "Balcão do protocolo", "SIGA 123/2026"]);
    expect(await screen.findByText("Envio por fora registrado.")).toBeTruthy();
  });

  it("a revisão pede o motivo; com ele, grava a versão nova (Rev01)", async () => {
    api.mockImplementation(async (url: string) => (url.startsWith("/api/contratos/9/planilhas/avisos") ? { avisos: [SOBREPOE] }
      : detalhe({ estado: "planilha_enviada", planilha_enviada_em: "2026-09-03" }, { disponivel: false, motivo: "já enviada" })));
    apiForm.mockResolvedValue({ medicao_id: 5, versao: 2, estado: "planilha_enviada", avisos: [] });
    render(<CartaoPlanilha medicaoId={5} podeEditar aoMudar={() => {}} />);
    fireEvent.click(await screen.findByRole("button", { name: "Registrar revisão" }));
    const form = screen.getByRole("form", { name: "Registrar revisão Rev01" });
    // a revisao parte do periodo e do valor da versao vigente
    expect((within(form).getByLabelText("Valor pedido") as HTMLInputElement).value).toBe("12.345,67");
    anexar("Ofício assinado (PDF)", pdf("oficio-rev01.pdf"));
    anexar("Planilha (.xlsx ou PDF)", new File(["PK"], "planilha-rev01.xlsx"));
    fireEvent.click(within(form).getByRole("button", { name: "Registrar revisão" }));
    expect(await screen.findByText("Informe o motivo da revisão.")).toBeTruthy();
    // a revisao avisa o periodo sobreposto como a 1a versao
    expect(await screen.findByText(SOBREPOE)).toBeTruthy();
    expect(apiForm).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Motivo (obrigatório)"), { target: { value: "Supervisora pediu ajuste no item 3" } });
    fireEvent.click(within(form).getByRole("button", { name: "Registrar revisão" }));
    await waitFor(() => expect(apiForm).toHaveBeenCalled());
    const [url, fd] = apiForm.mock.calls[0] as [string, FormData];
    expect(url).toBe("/api/medicoes/5/planilhas");
    expect([fd.get("motivo"), fd.get("periodo_inicio"), fd.get("periodo_fim"), fd.get("valor")])
      .toEqual(["Supervisora pediu ajuste no item 3", "2026-08-01", "2026-08-31", "12.345,67"]);
    expect(await screen.findByText("Revisão registrada.")).toBeTruthy();
  });

  it("diretoria vê as versões e o selo, sem nenhum botão", async () => {
    api.mockResolvedValue(detalhe({ estado: "planilha_enviada", planilha_enviada_em: "2026-09-03",
      planilha_siga: { data: "2026-09-03", numero: "SIGA 55" } }, { disponivel: true }));
    render(<CartaoPlanilha medicaoId={5} podeEditar={false} aoMudar={() => {}} />);
    expect(await screen.findByText("Enviada em 03/09")).toBeTruthy();
    expect(screen.getByText("SIGA 55")).toBeTruthy();
    expect(screen.queryAllByRole("button")).toHaveLength(0);
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("a lista de envios traz o do sistema no dia de Cuiabá e o de fora com o selo", async () => {
    api.mockResolvedValue(detalhe({ estado: "planilha_enviada", planilha_enviada_em: "2026-09-02",
      planilhas: [V1, { ...V1, id: 32, versao: 2, motivo: "Rev01" }] }, { disponivel: false, envios: [
      { planilha_id: 31, versao: 1, numero_oficio: null, enviado_em: "2026-09-02", usuario: "Operação", origem: "externo" },
      { planilha_id: 32, versao: 2, numero_oficio: "CT-302-LT-2026", enviado_em: "2026-09-04 01:30:00", usuario: "Operação", origem: "sistema" }] }));
    render(<CartaoPlanilha medicaoId={5} podeEditar aoMudar={() => {}} />);
    const original = (await screen.findByText(/^Original enviada em/)).closest("li")!;
    expect(original.textContent).toContain("02/09/2026");
    expect(within(original).getByText("Fora do sistema")).toBeTruthy();
    const rev = screen.getByText(/^Rev01 enviada em/).closest("li")!;
    expect(rev.textContent).toContain("03/09/2026");
    expect(within(rev).queryByText("Fora do sistema")).toBeNull();
  });

  it("medição sem planilha/carta registrada: o cartão não aparece", async () => {
    api.mockResolvedValue(detalhe({ planilhas: [] }));
    const { container } = render(<CartaoPlanilha medicaoId={5} podeEditar aoMudar={() => {}} />);
    await waitFor(() => expect(api).toHaveBeenCalled());
    expect(container.innerHTML).toBe("");
  });
});

describe("Ajudantes da planilha/carta", () => {
  it("centavos inteiros, rótulo da versão e selo do envio", () => {
    expect(centavosDoTexto("12.345,67")).toBe(1234567);
    expect(centavosDoTexto("")).toBeNull();
    expect([rotuloVersao(1), rotuloVersao(2), rotuloVersao(11)]).toEqual(["Original", "Rev01", "Rev10"]);
    expect(seloDoEnvio("2026-09-03")).toBe("Enviada em 03/09");
    expect(seloDoEnvio(null)).toBeNull();
    // gate Sol (PR #382): o envio pelo sistema as 21h30 em Cuiaba (01h30 UTC do dia seguinte) e' do dia 03
    const base = { planilha_id: 1, versao: 1, numero_oficio: null, usuario: null };
    expect(dataDoEnvio({ ...base, enviado_em: "2026-09-04 01:30:00", origem: "sistema" })).toBe("03/09/2026");
    expect(dataDoEnvio({ ...base, enviado_em: "2026-09-02", origem: "externo" })).toBe("02/09/2026");
  });
});
