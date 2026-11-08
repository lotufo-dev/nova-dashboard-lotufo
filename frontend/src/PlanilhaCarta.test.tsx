import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CartaoPlanilha, centavosDoTexto, dataDoEnvio, NovaPlanilhaCarta, revisaoPendente, rotuloVersao, seloDoEnvio, type DetalhePlanilha } from "./PlanilhaCarta";

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
    // sem reajuste digitado, a planilha/carta nao leva o campo
    expect(fd.get("reajuste_valor")).toBeNull();
  });

  // issue #276: o reajuste da competencia vem preenchido com a sugestao e a origem
  const BASE = { data_base_mes: "2024-06", aplica_a: "", ciclo: 2026, valor_centavos: 1_300_01, origem: "apostilamento",
    origem_texto: "apostilado no termo 001/2026" };
  function responderReajuste(reajuste: object) {
    api.mockImplementation(async (url: string) => {
      if (url.startsWith("/api/contratos/9/reajuste/sugestao")) return reajuste;
      if (url.startsWith("/api/contratos/9/planilhas/sugestao")) return SUGESTAO;
      return { avisos: [], acumulado_anterior_centavos: 0, saldo_centavos: 0 };
    });
  }

  it("o reajuste vem com o valor apostilado e a origem, e vai junto no registro", async () => {
    responderReajuste({ competencia: "2026-08", data_base_mes: "2024-06", bases: [BASE] });
    apiForm.mockResolvedValue({ medicao_id: 77, versao: 1, estado: "planilha_gerada", avisos: [] });
    render(<NovaPlanilhaCarta contratoId={9} aoRegistrar={() => {}} />);
    await waitFor(() => expect((screen.getByLabelText("Reajuste") as HTMLInputElement).value).toBe("1.300,01"));
    expect(screen.getByText("apostilado no termo 001/2026")).toBeTruthy();
    expect(api).toHaveBeenCalledWith("/api/contratos/9/reajuste/sugestao?competencia=2026-08&numero=4");
    expect(screen.queryByLabelText("Data-base")).toBeNull();      // uma base so': nada a escolher
    fireEvent.change(screen.getByLabelText("Valor pedido"), { target: { value: "12.345,67" } });
    anexar("Ofício assinado (PDF)", pdf("oficio.pdf"));
    anexar("Planilha (.xlsx ou PDF)", new File(["PK"], "planilha.xlsx"));
    fireEvent.click(screen.getByRole("button", { name: "Registrar planilha/carta" }));
    await waitFor(() => expect(apiForm).toHaveBeenCalled());
    const fd = apiForm.mock.calls[0][1] as FormData;
    expect([fd.get("reajuste_valor"), fd.get("reajuste_data_base")]).toEqual(["1.300,01", "2024-06"]);
  });

  it("sem previsão o reajuste fica vazio; contrato sem data-base não mostra o campo", async () => {
    responderReajuste({ competencia: "2026-08", data_base_mes: "2024-06", bases: [{ ...BASE, valor_centavos: null, origem: null, origem_texto: null }] });
    render(<NovaPlanilhaCarta contratoId={9} aoRegistrar={() => {}} />);
    expect(((await screen.findByLabelText("Reajuste")) as HTMLInputElement).value).toBe("");
    expect(screen.queryByText(/apostilado|previsto/)).toBeNull();
    cleanup();
    responderReajuste({ competencia: "2026-08", data_base_mes: null, bases: [] });
    render(<NovaPlanilhaCarta contratoId={9} aoRegistrar={() => {}} />);
    await screen.findByLabelText("Nº da medição");
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/contratos/9/reajuste/sugestao?competencia=2026-08&numero=4"));
    expect(screen.queryByLabelText("Reajuste")).toBeNull();
  });

  it("duas datas-base: a escolha troca a sugestão pela da base escolhida", async () => {
    responderReajuste({ competencia: "2026-08", data_base_mes: null, bases: [
      { ...BASE, data_base_mes: "2024-04", aplica_a: "itens SICRO", valor_centavos: 500_03, origem: "pleito", origem_texto: "previsto no pleito" },
      { ...BASE, valor_centavos: null, origem: null, origem_texto: null }] });
    render(<NovaPlanilhaCarta contratoId={9} aoRegistrar={() => {}} />);
    const base = await screen.findByLabelText("Data-base") as HTMLSelectElement;
    expect(base.value).toBe("");
    expect([...base.options].map(o => o.textContent)).toEqual(["—", "04/2024 (itens SICRO)", "06/2024"]);
    expect((screen.getByLabelText("Reajuste") as HTMLInputElement).value).toBe("");
    fireEvent.change(base, { target: { value: "2024-04" } });
    expect((screen.getByLabelText("Reajuste") as HTMLInputElement).value).toBe("500,03");
    expect(screen.getByText("previsto no pleito")).toBeTruthy();
  });

  it("a planilha/carta de projeto não tem o campo de reajuste", async () => {
    responderReajuste({ competencia: "2026-08", data_base_mes: "2024-06", bases: [BASE] });
    render(<NovaPlanilhaCarta contratoId={9} tipo="projeto" aoRegistrar={() => {}} />);
    await screen.findByLabelText("Nº da medição");
    expect(screen.queryByLabelText("Reajuste")).toBeNull();
  });

  it("o valor digitado para uma competência não vai para outra, nem para a outra data-base (gate Sol)", async () => {
    api.mockImplementation(async (url: string) => {
      if (url.startsWith("/api/contratos/9/reajuste/sugestao?competencia=2026-08")) return { competencia: "2026-08", data_base_mes: "2024-06", bases: [BASE] };
      if (url.startsWith("/api/contratos/9/reajuste/sugestao")) return { competencia: "2026-09", data_base_mes: null, bases: [
        { ...BASE, data_base_mes: "2024-04", aplica_a: "itens SICRO", valor_centavos: 500_03, origem: "pleito", origem_texto: "previsto no pleito" },
        { ...BASE, valor_centavos: null, origem: null, origem_texto: null }] };
      if (url.startsWith("/api/contratos/9/planilhas/sugestao")) return SUGESTAO;
      return { avisos: [], acumulado_anterior_centavos: 0, saldo_centavos: 0 };
    });
    render(<NovaPlanilhaCarta contratoId={9} aoRegistrar={() => {}} />);
    await waitFor(() => expect((screen.getByLabelText("Reajuste") as HTMLInputElement).value).toBe("1.300,01"));
    fireEvent.change(screen.getByLabelText("Reajuste"), { target: { value: "2.222,22" } });
    expect(screen.queryByText("apostilado no termo 001/2026")).toBeNull();
    fireEvent.change(screen.getByLabelText("Competência"), { target: { value: "092026" } });
    const base = await screen.findByLabelText("Data-base") as HTMLSelectElement;
    expect((screen.getByLabelText("Reajuste") as HTMLInputElement).value).toBe("");
    fireEvent.change(base, { target: { value: "2024-04" } });
    expect((screen.getByLabelText("Reajuste") as HTMLInputElement).value).toBe("500,03");
    fireEvent.change(screen.getByLabelText("Reajuste"), { target: { value: "7,00" } });
    fireEvent.change(base, { target: { value: "2024-06" } });
    expect((screen.getByLabelText("Reajuste") as HTMLInputElement).value).toBe("");
  });

  it("o aviso do servidor aparece no lugar da origem: já pedido em outra medição", async () => {
    responderReajuste({ competencia: "2026-08", data_base_mes: "2024-06", bases: [
      { ...BASE, valor_centavos: null, origem: null, origem_texto: null, aviso: "já pedido na medição 6 de reajuste" }] });
    render(<NovaPlanilhaCarta contratoId={9} aoRegistrar={() => {}} />);
    expect(await screen.findByText("já pedido na medição 6 de reajuste")).toBeTruthy();
    expect((screen.getByLabelText("Reajuste") as HTMLInputElement).value).toBe("");
  });

  it("a leitura da sugestão que falha esconde o campo e não manda o valor de outra competência (code-review)", async () => {
    api.mockImplementation(async (url: string) => {
      if (url.startsWith("/api/contratos/9/reajuste/sugestao?competencia=2026-08")) return { competencia: "2026-08", data_base_mes: "2024-06", bases: [BASE] };
      if (url.startsWith("/api/contratos/9/reajuste/sugestao")) throw new Error("falhou");
      if (url.startsWith("/api/contratos/9/planilhas/sugestao")) return SUGESTAO;
      return { avisos: [], acumulado_anterior_centavos: 0, saldo_centavos: 0 };
    });
    apiForm.mockResolvedValue({ medicao_id: 77, versao: 1, estado: "planilha_gerada", avisos: [] });
    render(<NovaPlanilhaCarta contratoId={9} aoRegistrar={() => {}} />);
    await waitFor(() => expect((screen.getByLabelText("Reajuste") as HTMLInputElement).value).toBe("1.300,01"));
    fireEvent.change(screen.getByLabelText("Competência"), { target: { value: "092026" } });
    await waitFor(() => expect(screen.queryByLabelText("Reajuste")).toBeNull());
    fireEvent.change(screen.getByLabelText("Valor pedido"), { target: { value: "1,00" } });
    anexar("Ofício assinado (PDF)", pdf("oficio.pdf"));
    anexar("Planilha (.xlsx ou PDF)", new File(["PK"], "planilha.xlsx"));
    fireEvent.click(screen.getByRole("button", { name: "Registrar planilha/carta" }));
    await waitFor(() => expect(apiForm).toHaveBeenCalled());
    const fd = apiForm.mock.calls[0][1] as FormData;
    expect([fd.get("competencia"), fd.get("reajuste_valor")]).toEqual(["2026-09", null]);
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

  it("só a competência veio da janela Iniciar processo (#151): nº sugerido, período no mês civil dela", async () => {
    api.mockImplementation(async (url: string) => (url.includes("/sugestao") ? { ...SUGESTAO, numero_orgao: 9 } : { avisos: [] }));
    render(<NovaPlanilhaCarta contratoId={9} inicial={{ competencia: "2026-10" }} aoRegistrar={() => {}} />);
    expect(((await screen.findByLabelText("Nº da medição")) as HTMLInputElement).value).toBe("4");
    expect((screen.getByLabelText("Período: de") as HTMLInputElement).value).toBe("2026-10-01");
    expect((screen.getByLabelText("até") as HTMLInputElement).value).toBe("2026-10-31");
    // o nº e' o sugerido, entao o nº do orgao sugerido vale
    expect((screen.getByLabelText("Nº no órgão") as HTMLInputElement).value).toBe("9");
  });

  it("issue #567: sem tipo, o servidor escolhe pelo da última medição e o campo Tipo vem com ele", async () => {
    // obra só de projeto (Terminais BRT): a sugestão vem de projeto, 3ª, competência seguinte, acumulado das duas
    const PROJETO = { ...SUGESTAO, tipo: "projeto", numero: 3, competencia: "2026-10", periodo_inicio: "2026-10-01",
      periodo_fim: "2026-10-31", acumulado_anterior_centavos: 35_693_13, saldo_centavos: null };
    api.mockImplementation(async (url: string) => (url.includes("/sugestao")
      ? (url.includes("tipo=execucao") ? SUGESTAO : PROJETO) : new Promise(() => {})));
    apiForm.mockResolvedValue({ medicao_id: 78, versao: 1, estado: "planilha_gerada", avisos: [] });
    render(<NovaPlanilhaCarta contratoId={9} aoRegistrar={() => {}} />);
    expect(((await screen.findByLabelText("Nº da medição")) as HTMLInputElement).value).toBe("3");
    expect(api.mock.calls[0]![0]).toBe("/api/contratos/9/planilhas/sugestao");
    const tipo = screen.getByLabelText("Tipo") as HTMLSelectElement;
    expect(tipo.value).toBe("projeto");
    expect(Array.from(tipo.options).map(o => o.textContent)).toEqual(["Execução", "Projeto"]);
    expect((screen.getByLabelText("Período: de") as HTMLInputElement).value).toBe("2026-10-01");
    expect(screen.getByText("Acumulado anterior").closest("dl")!.textContent).toContain("R$\u00a035.693,13");
    // registrar vai com o tipo do campo
    fireEvent.change(screen.getByLabelText("Valor pedido"), { target: { value: "1,01" } });
    anexar("Ofício assinado (PDF)", pdf("oficio.pdf"));
    anexar("Planilha (.xlsx ou PDF)", new File(["PK"], "planilha.xlsx"));
    fireEvent.click(screen.getByRole("button", { name: "Registrar planilha/carta" }));
    await waitFor(() => expect(apiForm).toHaveBeenCalled());
    expect((apiForm.mock.calls[0] as [string, FormData])[1].get("tipo")).toBe("projeto");
  });

  it("issue #567: trocar o tipo pede a sugestão desse tipo e troca nº, competência e período", async () => {
    const PROJETO = { ...SUGESTAO, tipo: "projeto", numero: 3, competencia: "2026-10", periodo_inicio: "2026-10-01",
      periodo_fim: "2026-10-31" };
    api.mockImplementation(async (url: string) => (url.includes("/sugestao")
      ? (url.includes("tipo=execucao") ? SUGESTAO : PROJETO) : new Promise(() => {})));
    render(<NovaPlanilhaCarta contratoId={9} aoRegistrar={() => {}} />);
    expect(((await screen.findByLabelText("Nº da medição")) as HTMLInputElement).value).toBe("3");
    fireEvent.change(screen.getByLabelText("Tipo"), { target: { value: "execucao" } });
    await waitFor(() => expect((screen.getByLabelText("Nº da medição") as HTMLInputElement).value).toBe("4"));
    expect(api.mock.calls.some(c => c[0] === "/api/contratos/9/planilhas/sugestao?tipo=execucao")).toBe(true);
    expect((screen.getByLabelText("Período: de") as HTMLInputElement).value).toBe("2026-08-01");
    expect((screen.getByLabelText("Tipo") as HTMLSelectElement).value).toBe("execucao");
  });

  it("issue #567: logo depois de trocar o tipo, o acumulado do tipo anterior não aparece", async () => {
    const PROJETO = { ...SUGESTAO, tipo: "projeto", numero: 3, acumulado_anterior_centavos: 35_693_13, saldo_centavos: null };
    api.mockImplementation(async (url: string) => (url.includes("tipo=execucao") ? new Promise(() => {})
      : url.includes("/sugestao") ? PROJETO : new Promise(() => {})));
    render(<NovaPlanilhaCarta contratoId={9} aoRegistrar={() => {}} />);
    const saldo = (await screen.findByText("Acumulado anterior")).closest("dl")!;
    expect(saldo.textContent).toContain("R$\u00a035.693,13");
    fireEvent.change(screen.getByLabelText("Tipo"), { target: { value: "execucao" } });
    expect(saldo.textContent).not.toContain("35.693,13");
    // nº e competência ainda são os de projeto: não grava até a sugestão de execução chegar
    expect((screen.getByRole("button", { name: "Registrar planilha/carta" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("issue #567: os avisos do tipo anterior somem ao trocar o tipo", async () => {
    const PROJETO = { ...SUGESTAO, tipo: "projeto", numero: 3 };
    api.mockImplementation(async (url: string) => {
      if (url.includes("/sugestao")) return url.includes("tipo=execucao") ? new Promise(() => {}) : PROJETO;
      if (url.includes("tipo=projeto")) return { avisos: [SOBREPOE], acumulado_anterior_centavos: 0, saldo_centavos: null };
      return new Promise(() => {});
    });
    render(<NovaPlanilhaCarta contratoId={9} aoRegistrar={() => {}} />);
    expect(await screen.findByText(SOBREPOE)).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Tipo"), { target: { value: "execucao" } });
    expect(screen.queryByText(SOBREPOE)).toBeNull();
  });

  it("issue #567: falha na sugestão depois de trocar o tipo não apaga o formulário", async () => {
    const PROJETO = { ...SUGESTAO, tipo: "projeto", numero: 3 };
    api.mockImplementation(async (url: string) => {
      if (url.includes("/sugestao")) {
        if (url.includes("tipo=execucao")) throw new Error("Servidor fora do ar");
        return PROJETO;
      }
      return new Promise(() => {});
    });
    render(<NovaPlanilhaCarta contratoId={9} aoRegistrar={() => {}} />);
    await screen.findByLabelText("Nº da medição");
    fireEvent.change(screen.getByLabelText("Valor pedido"), { target: { value: "1,01" } });
    fireEvent.change(screen.getByLabelText("Tipo"), { target: { value: "execucao" } });
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect((screen.getByLabelText("Valor pedido") as HTMLInputElement).value).toBe("1,01");
  });

  it("issue #567: a medição prevista promovida mantém o tipo dela (campo travado)", async () => {
    api.mockImplementation(async (url: string) => (url.includes("/sugestao") ? { ...SUGESTAO, tipo: "projeto" } : { avisos: [] }));
    render(<NovaPlanilhaCarta contratoId={9} tipo="projeto" tipoFixo inicial={{ numero: 6, competencia: "2026-02" }} aoRegistrar={() => {}} />);
    await screen.findByLabelText("Nº da medição");
    expect(api.mock.calls[0]![0]).toBe("/api/contratos/9/planilhas/sugestao?tipo=projeto");
    const tipo = screen.getByLabelText("Tipo") as HTMLSelectElement;
    expect(tipo.value).toBe("projeto");
    expect(tipo.disabled).toBe(true);
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
    // issue #508: o pacote do envio lista a carta e a planilha da versao vigente (a tabela de versoes so' com revisao)
    const pacote = screen.getByRole("list", { name: "Carta e planilha" });
    expect(within(pacote).getByRole("link", { name: "Carta assinada" }).getAttribute("href")).toBe("/api/medicoes/5/planilhas/31/oficio");
    expect(within(pacote).getByRole("link", { name: "Planilha da 4ª medição · original" }).getAttribute("href")).toBe("/api/medicoes/5/planilhas/31/planilha");
    expect(screen.queryByRole("table", { name: "Versões da planilha/carta" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Enviar ao órgão" }));
    fireEvent.change(screen.getByLabelText("Nº do ofício (CT)"), { target: { value: "301" } });
    fireEvent.click(screen.getByRole("button", { name: "Prévia do e-mail" }));
    expect(((await screen.findByLabelText("Assunto")) as HTMLInputElement).value).toBe(PREVIA.assunto);
    const anexos = screen.getByRole("list", { name: "Anexos" });
    expect(within(anexos).getByText("CT-301-LT-2026.pdf")).toBeTruthy();
    expect(within(anexos).getByText("4a Medicao.zip")).toBeTruthy();
    expect(screen.getByText("Encaminho arquivo para protocolo.")).toBeTruthy();
    expect(api.mock.calls.find(c => c[0] === "/api/medicoes/5/envio-planilha/previa")![1].body).toBe(JSON.stringify({ numero_oficio: "301" }));
    fireEvent.click(screen.getByRole("button", { name: "Enviar ao órgão" }));
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
    expect(screen.queryByRole("button", { name: "Enviar ao órgão" })).toBeNull();
    expect(screen.getByRole("textbox", { name: "Nº do SIGA" })).toBeTruthy();
  });

  it("planilha não lida por grupo: o cartão avisa a diferença; lida, não avisa nada", async () => {
    const aviso = "Planilha não lida: diferença de R$ 6,90 entre a soma dos grupos da planilha (R$ 20.693,10) e o valor pedido da medição (R$ 20.700,00)";
    api.mockImplementation(async (url: string) => (url === "/api/medicoes/5"
      ? detalhe({ leitura_planilha: { situacao: "recusada", aviso } }) : []));
    render(<CartaoPlanilha medicaoId={5} podeEditar aoMudar={() => {}} />);
    expect(await screen.findByText(aviso)).toBeTruthy();
    cleanup();
    api.mockImplementation(async (url: string) => (url === "/api/medicoes/5"
      ? detalhe({ leitura_planilha: { situacao: "lida", aviso: null } }) : []));
    render(<CartaoPlanilha medicaoId={5} podeEditar aoMudar={() => {}} />);
    expect(await screen.findByText("Gerada")).toBeTruthy();
    expect(screen.queryByText(/Planilha não lida/)).toBeNull();
  });

  it("envio com pendência pede a justificativa antes de sair", async () => {
    api.mockImplementation(async (url: string) => {
      if (url === "/api/medicoes/5") return detalhe();
      if (url === "/api/medicoes/5/envio-planilha/previa") return { ...PREVIA, pendencias: [{ codigo: "peca", mensagem: "Falta a peça que o órgão exige: Memória de cálculo" }] };
      return [];
    });
    render(<CartaoPlanilha medicaoId={5} podeEditar aoMudar={() => {}} />);
    fireEvent.click(await screen.findByRole("button", { name: "Enviar ao órgão" }));
    fireEvent.change(screen.getByLabelText("Nº do ofício (CT)"), { target: { value: "301" } });
    fireEvent.click(screen.getByRole("button", { name: "Prévia do e-mail" }));
    expect(await screen.findByText("Falta a peça que o órgão exige: Memória de cálculo")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Enviar ao órgão" }));
    expect(await screen.findByText("Escreva a justificativa, com pelo menos 10 caracteres.")).toBeTruthy();
    expect(api.mock.calls.some(c => c[0] === "/api/medicoes/5/envio-planilha")).toBe(false);
  });

  it("peça que vai no ofício assinado mostra o selo e não tem Anexar; a sem a marca continua com Anexar (issue #462)", async () => {
    // a memoria foi anexada antes de receber a marca: nao vai no e-mail, entao nao aparece como Anexada
    const antiga = { id: 7, tipo: "boletim", nome: "memoria.pdf", tamanho: 10, ext: "pdf", sha256: "c".repeat(64), criado_em: "2026-11-01" };
    api.mockResolvedValue(detalhe({}, { pecas: [antiga], pecas_do_orgao: [
      { tipo: "boletim", rotulo: "Memória de cálculo", exigida: true, no_oficio: true },
      { tipo: "fotos", rotulo: "Registro fotográfico", exigida: false, no_oficio: false }] }));
    render(<CartaoPlanilha medicaoId={5} podeEditar aoMudar={() => {}} />);
    const tabela = await screen.findByRole("table", { name: "Peças da planilha/carta" });
    const memoria = within(tabela).getByRole("rowheader", { name: /^Memória de cálculo/ }).closest("tr")!;
    expect(within(memoria).getByText("memoria.pdf")).toBeTruthy();        // ainda se remove
    expect(within(memoria).getByText("No ofício assinado")).toBeTruthy();
    expect(within(memoria).queryByText("Falta")).toBeNull();
    expect(within(memoria).queryByText("Anexada")).toBeNull();
    expect(within(memoria).queryByLabelText("Anexar Memória de cálculo")).toBeNull();
    const fotos = within(tabela).getByRole("rowheader", { name: "Registro fotográfico" }).closest("tr")!;
    expect(within(fotos).getByText("Opcional")).toBeTruthy();
    expect(within(fotos).getByLabelText("Anexar Registro fotográfico")).toBeTruthy();
  });

  it("onde o sistema não envia (MT-PAR), o motivo aparece e fica o registro por fora", async () => {
    const motivo = "Na MT-PAR não há envio da planilha/carta: o ofício vai com a nota";
    api.mockResolvedValue(detalhe({}, { disponivel: false, motivo }));
    apiForm.mockResolvedValue({ medicao_id: 5, estado: "planilha_enviada", versao: 1 });
    render(<CartaoPlanilha medicaoId={5} podeEditar aoMudar={() => {}} />);
    expect(await screen.findByText(motivo)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Enviar ao órgão" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Já enviei por fora" }));
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

  it("na SES e nas prefeituras, o motivo do órgão aparece, fica o registro por fora e somem o envio e as peças (issue #463)", async () => {
    const motivo = "Na SES-MT não há envio da planilha/carta: a medição vai com a nota";
    // o servidor nao manda peca do orgao onde nao ha' envio (planilha_envio.situacao)
    api.mockResolvedValue(detalhe({}, { disponivel: false, motivo, pecas_do_orgao: [] }));
    render(<CartaoPlanilha medicaoId={5} podeEditar aoMudar={() => {}} />);
    expect(await screen.findByText(motivo)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Enviar ao órgão" })).toBeNull();
    expect(screen.queryByText("Documentos que o órgão exige")).toBeNull();
    expect(screen.getByRole("button", { name: "Já enviei por fora" })).toBeTruthy();
  });

  it("a revisão pede o motivo; com ele, grava a versão nova (Rev01)", async () => {
    api.mockImplementation(async (url: string) => (url.startsWith("/api/contratos/9/planilhas/avisos") ? { avisos: [SOBREPOE] }
      : detalhe({ estado: "planilha_enviada", planilha_enviada_em: "2026-09-03" }, { disponivel: false, motivo: "já enviada" })));
    apiForm.mockResolvedValue({ medicao_id: 5, versao: 2, estado: "planilha_enviada", avisos: [] });
    render(<CartaoPlanilha medicaoId={5} podeEditar aoMudar={() => {}} />);
    fireEvent.click(await screen.findByRole("button", { name: "Registrar revisão da planilha" }));
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

  it("revisão registrada e não enviada é pendente; enviada (por fora serve), deixa de ser; e o cartão avisa a página", async () => {
    const env = (versao: number, origem: "sistema" | "externo") =>
      ({ planilha_id: 30 + versao, versao, numero_oficio: null, enviado_em: "2026-09-02", usuario: null, origem });
    const rev = { estado: "planilha_enviada", planilha_enviada_em: "2026-09-02", planilhas: [V1, { ...V1, id: 32, versao: 2, motivo: "Rev01" }] };
    expect(revisaoPendente(detalhe(rev, { envios: [env(1, "sistema")] }))).toBe(true);
    // sem envio listado (historico), a 1a conta como enviada
    expect(revisaoPendente(detalhe(rev, { envios: [] }))).toBe(true);
    expect(revisaoPendente(detalhe(rev, { envios: [env(1, "sistema"), env(2, "externo")] }))).toBe(false);
    expect(revisaoPendente(detalhe({ estado: "planilha_enviada", planilha_enviada_em: "2026-09-02" }, { envios: [] }))).toBe(false);
    api.mockResolvedValue(detalhe(rev, { envios: [env(1, "sistema")] }));
    const aoRevisaoPendente = vi.fn();
    render(<CartaoPlanilha medicaoId={5} podeEditar aoMudar={() => {}} aoRevisaoPendente={aoRevisaoPendente} />);
    await waitFor(() => expect(aoRevisaoPendente).toHaveBeenCalledWith(true));
  });

  it("estado muda de gerada para enviada: o cartão relê e avisa a página de novo, mesmo sem mudar o valor (issue #384)", async () => {
    const gerada = detalhe({ estado: "planilha_gerada", planilhas: [V1] }, { envios: [] });
    api.mockResolvedValue(gerada);
    const primeiro = vi.fn();
    const { rerender } = render(<CartaoPlanilha medicaoId={5} estado="planilha_gerada" podeEditar aoMudar={() => {}} aoRevisaoPendente={primeiro} />);
    await waitFor(() => expect(primeiro).toHaveBeenCalledWith(false));
    api.mockResolvedValue(detalhe({ estado: "planilha_enviada", planilha_enviada_em: "2026-09-02", planilhas: [V1] }, { envios: [] }));
    const segundo = vi.fn();
    rerender(<CartaoPlanilha medicaoId={5} estado="planilha_enviada" podeEditar aoMudar={() => {}} aoRevisaoPendente={segundo} />);
    await waitFor(() => expect(segundo).toHaveBeenCalledWith(false));
  });

  it("avisa a página se o envio da planilha/carta está reservado (gate Sol, PR #528)", async () => {
    api.mockResolvedValue(detalhe({}, { reserva: { id: 3, envio_reservado_em: "2026-09-02 10:00:00", reservado_por: "Maria" } }));
    const aoEnvioReservado = vi.fn();
    const { rerender } = render(<CartaoPlanilha medicaoId={5} estado="planilha_gerada" podeEditar aoMudar={() => {}} aoEnvioReservado={aoEnvioReservado} />);
    await waitFor(() => expect(aoEnvioReservado).toHaveBeenCalledWith(true));
    api.mockResolvedValue(detalhe({}, { reserva: null }));
    const livre = vi.fn();
    rerender(<CartaoPlanilha medicaoId={6} estado="planilha_gerada" podeEditar aoMudar={() => {}} aoEnvioReservado={livre} />);
    await waitFor(() => expect(livre).toHaveBeenCalledWith(false));
  });

  it("consulta do cartão falha: avisa a página com null (issue #384)", async () => {
    api.mockRejectedValue(new Error("falhou"));
    const aoRevisaoPendente = vi.fn();
    render(<CartaoPlanilha medicaoId={5} podeEditar aoMudar={() => {}} aoRevisaoPendente={aoRevisaoPendente} />);
    await waitFor(() => expect(aoRevisaoPendente).toHaveBeenCalledWith(null));
  });

  it("medição sem planilha/carta registrada: o cartão não aparece", async () => {
    api.mockResolvedValue(detalhe({ planilhas: [] }));
    const { container } = render(<CartaoPlanilha medicaoId={5} podeEditar aoMudar={() => {}} />);
    await waitFor(() => expect(api).toHaveBeenCalled());
    expect(container.innerHTML).toBe("");
  });

  // issue #508: o pacote do envio conta o que esta' pronto, mostra o tamanho de cada peca e o medidor contra o limite
  it("pacote do envio: “N de M”, o tamanho da carta e da planilha, o que falta e o medidor", async () => {
    api.mockResolvedValue(detalhe({ pacote_planilha: { carta: 400 * 1024, planilha: 8 * 1024 * 1024, pecas: 0,
      total: 8 * 1024 * 1024 + 400 * 1024, limite: 25 * 1024 * 1024 } }, { pecas_do_orgao: [
      { tipo: "boletim", rotulo: "Diário de obras", exigida: true, no_oficio: false },
      { tipo: "fotos", rotulo: "Relatório fotográfico", exigida: false, no_oficio: false }] }));
    render(<CartaoPlanilha medicaoId={5} podeEditar aoMudar={() => {}} />);
    const titulo = await screen.findByRole("heading", { name: /Pacote do envio/ });
    expect(titulo.textContent).toContain("2 de 3");     // carta e planilha prontas; falta o diario (o opcional nao conta)
    cleanup();
    // a opcional anexada nao muda a conta (code-review): continua "2 de 3"
    api.mockResolvedValue(detalhe({}, { pecas: [{ id: 8, tipo: "fotos", nome: "fotos.pdf", tamanho: 10 }], pecas_do_orgao: [
      { tipo: "boletim", rotulo: "Diário de obras", exigida: true, no_oficio: false },
      { tipo: "fotos", rotulo: "Relatório fotográfico", exigida: false, no_oficio: false }] }));
    render(<CartaoPlanilha medicaoId={5} podeEditar aoMudar={() => {}} />);
    expect((await screen.findByRole("heading", { name: /Pacote do envio/ })).textContent).toContain("2 de 3");
    cleanup();
    api.mockResolvedValue(detalhe({ pacote_planilha: { carta: 400 * 1024, planilha: 8 * 1024 * 1024, pecas: 0,
      total: 8 * 1024 * 1024 + 400 * 1024, limite: 25 * 1024 * 1024 } }, { pecas_do_orgao: [
      { tipo: "boletim", rotulo: "Diário de obras", exigida: true, no_oficio: false },
      { tipo: "fotos", rotulo: "Relatório fotográfico", exigida: false, no_oficio: false }] }));
    render(<CartaoPlanilha medicaoId={5} podeEditar aoMudar={() => {}} />);
    await screen.findByRole("heading", { name: /Pacote do envio/ });
    const pacote = screen.getByRole("list", { name: "Carta e planilha" });
    expect(pacote.textContent).toContain("400 KB");
    expect(pacote.textContent).toContain("8,0 MB");
    const diario = within(screen.getByRole("table", { name: "Peças da planilha/carta" })).getByRole("rowheader", { name: "Diário de obras" }).closest("tr")!;
    expect(within(diario).getByText("Falta")).toBeTruthy();
    expect(screen.getByRole("meter", { name: "Tamanho dos anexos" }).getAttribute("aria-valuetext")).toBe("8,4 MB de 25,0 MB");
  });

  it("acima do limite o medidor fica vermelho; com revisão, a tabela das versões aparece", async () => {
    api.mockResolvedValue(detalhe({ planilhas: [V1, { ...V1, id: 32, versao: 2, motivo: "Rev01" }],
      pacote_planilha: { carta: 1, planilha: 30 * 1024 * 1024, pecas: 0, total: 30 * 1024 * 1024 + 1, limite: 25 * 1024 * 1024 } }));
    const { container } = render(<CartaoPlanilha medicaoId={5} podeEditar aoMudar={() => {}} />);
    expect(await screen.findByRole("table", { name: "Versões da planilha/carta" })).toBeTruthy();
    expect(container.querySelector(".medidor--acima")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Planilha da 4ª medição · rev01" }).getAttribute("href")).toBe("/api/medicoes/5/planilhas/32/planilha");
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
