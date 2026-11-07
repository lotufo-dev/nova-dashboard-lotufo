import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Usuario } from "./Login";
import MedicoesPagina from "./MedicoesPagina";
import type { LinhaResumo, ObraResumo, ResumoMedicoes, SerieObra } from "./resumoMedicoes";

const { api, apiForm } = vi.hoisted(() => ({ api: vi.fn(), apiForm: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api, apiForm }));

const usuario = { id: 1, nome: "Leonardo Praeiro", email: "l@l.com", perfil: "admin" } as Usuario;

const linha = (extra: Partial<LinhaResumo>): LinhaResumo => ({
  situacao: "enviar-nota", contrato_id: 12, obra: "Estações Alfa", contratante: "SINFRA", orgao_sub: null,
  medicao_id: 70, medicao_ids: [70], numero: 8, competencia: "2026-09", titulo: "8ª Medição", proximo_passo: "protocolar",
  valor_centavos: 1462998169, marco: "2026-11-07", dias: 0, passo: { numero: 5, nome: "Envio da nota" }, com_quem: "Lotufo", ...extra });

const SERIE: SerieObra = { aberta_id: null, aberta_numero: null, aberta_passo: null, ultima: null, prevista_id: null, prevista_numero: null,
  prevista_competencia: null };
const obra = (extra: Partial<ObraResumo>): ObraResumo => ({
  contrato_id: 1, obra: "Obra", contratante: "SINFRA", orgao_sub: null, aberta: false, prevista_id: null, projeto: null,
  encerramento: false, ultima: null, ha_dias: null, prevista: null, proxima: 1, proxima_tipo: "execucao", sem_no_mes: true,
  ultima_medicao: null, execucao: SERIE, ...extra });

const OBRAS = [
  obra({ contrato_id: 1, obra: "Cinco Bairros", proxima: 35,
    ultima_medicao: { numero: 34, tipo: "execucao", competencia: "2026-09", estado: "recebida", valor_centavos: 7458481 } }),
  obra({ contrato_id: 2, obra: "Integra Beta", proxima: 16 }),
  obra({ contrato_id: 3, obra: "Complexo Gama", contratante: "MTPAR", proxima: 24 }),
  obra({ contrato_id: 4, obra: "Maternidade Delta", contratante: "Pref. Várzea Grande", proxima: 3 }),
  obra({ contrato_id: 5, obra: "Já medida em novembro", sem_no_mes: false }),
];

const RESUMO: ResumoMedicoes = {
  hoje: "2026-11-07", mes: "2026-11",
  contagens: { "sem-medicao": 4, "planilha-gerada": 0, "planilha-enviada": 0, "boletim-recebido": 0, faturamento: 0, "aguardando-nota": 0,
    "enviar-nota": 2, "aguardando-pagamento": 1, iniciar: 4, "em-andamento": 3 },
  linhas: [
    linha({}),
    linha({ situacao: "planilha-enviada", contrato_id: 13, obra: "MT Epsilon", medicao_id: 71, medicao_ids: [71], numero: 29, titulo: "29ª Medição",
      proximo_passo: "registrar o boletim", passo: { numero: 2, nome: "Análise do órgão" }, com_quem: "Órgão", dias: 1, valor_centavos: 85604199 }),
    linha({ situacao: "aguardando-pagamento", contrato_id: 14, obra: "Complexo Zeta", contratante: "MTPAR", medicao_id: 72, medicao_ids: [72, 73],
      titulo: "24ª Medição + Reajuste", proximo_passo: "aguardando pagamento", passo: { numero: 6, nome: "Pagamento" }, com_quem: "Órgão",
      dias: 50, valor_centavos: 308126381 }),
  ],
  obras: OBRAS,
};

function responder(extra: (url: string, opcoes?: { method?: string }) => unknown = () => undefined, regraAtiva = true) {
  api.mockImplementation(async (url: string, opcoes?: { method?: string }) => {
    const x = extra(url, opcoes);
    if (x !== undefined) return x;
    if (url.startsWith("/api/medicoes/resumo")) return RESUMO;
    if (url.endsWith("/espelho")) return { regra: { situacao: regraAtiva ? "ativa" : "pendente" } };
    if (url.includes("/planilhas/sugestao")) return { numero: 35, numero_orgao: 401, competencia: "2026-11", periodo_inicio: "2026-11-01", periodo_fim: "2026-11-30" };
    return [];
  });
}

describe("Medições: Iniciar medição e Em andamento (#507)", () => {
  // só a data é falsa (os timers reais seguem): o mês inicial da tela é o de hoje
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-11-07T15:00:00Z"));
    window.history.replaceState(null, "", "/medicoes");
  });
  afterEach(() => { cleanup(); vi.useRealTimers(); api.mockReset(); apiForm.mockReset(); });

  it("Em andamento: uma linha por medição aberta, com o passo (número e nome), com quem está e o botão Abrir", async () => {
    responder();
    render(<MedicoesPagina aba="em-andamento" usuario={usuario} />);
    const tabela = await screen.findByRole("table");
    const linhas = within(tabela).getAllByRole("row").slice(1);
    expect(linhas).toHaveLength(3);
    expect(within(linhas[0]).getByText("5 · Envio da nota")).toBeTruthy();
    expect(within(linhas[0]).getByText("Lotufo")).toBeTruthy();
    expect(within(linhas[1]).getByText("2 · Análise do órgão")).toBeTruthy();
    expect(within(linhas[1]).getByText("Órgão")).toBeTruthy();
    expect(within(linhas[2]).getByText("24ª Medição + Reajuste")).toBeTruthy();
    expect(within(linhas[2]).getByText("6 · Pagamento")).toBeTruthy();
    expect(within(linhas[2]).getByText("50 dias")).toBeTruthy();
    // "Abrir" leva à página da medição, na etapa pendente
    expect(within(linhas[0]).getByRole("link", { name: /Abrir 8ª Medição de Estações Alfa/ }).getAttribute("href"))
      .toBe("/obras/12/medicoes/70#etapa-4");
    expect(within(linhas[1]).getByRole("link", { name: /Abrir/ }).getAttribute("href")).toBe("/obras/13/medicoes/71");
    // o contador ao lado do título é o do menu
    expect(screen.getByRole("heading", { name: /Em andamento/ }).textContent).toContain("3");
  });

  it("Em andamento sem medição: uma linha curta no lugar da tabela", async () => {
    responder(url => url.startsWith("/api/medicoes/resumo") ? { ...RESUMO, linhas: [] } : undefined);
    render(<MedicoesPagina aba="em-andamento" usuario={usuario} />);
    expect(await screen.findByText("Nenhuma medição em andamento.")).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("Iniciar: lista só as obras sem medição no mês, com a contagem 'N de M obras'", async () => {
    responder();
    render(<MedicoesPagina aba="iniciar" usuario={usuario} />);
    expect(await screen.findByText("4 de 4 obras")).toBeTruthy();
    expect(screen.queryByText("Já medida em novembro")).toBeNull();
    expect(screen.getByText("novembro de 2026")).toBeTruthy();
  });

  it("Iniciar: a busca filtra por trecho (sem acento), destaca o trecho e deixa as outras abaixo", async () => {
    responder();
    render(<MedicoesPagina aba="iniciar" usuario={usuario} />);
    await screen.findByText("4 de 4 obras");
    fireEvent.change(screen.getByRole("searchbox", { name: "Buscar obra" }), { target: { value: "bair" } });
    expect(screen.getByText("1 de 4 obras")).toBeTruthy();
    const achada = screen.getByText("Bair");
    expect(achada.tagName).toBe("MARK");
    expect(achada.closest("button")?.textContent).toContain("Cinco Bairros");
    const outras = screen.getByRole("heading", { name: "Outras obras sem medição" });
    const lista = outras.nextElementSibling as HTMLElement;
    expect(within(lista).getAllByRole("button").map(b => b.textContent)).toEqual(
      expect.arrayContaining([expect.stringContaining("Integra Beta"), expect.stringContaining("Complexo Gama"), expect.stringContaining("Maternidade Delta")]));
    // sem acento nem caixa
    fireEvent.change(screen.getByRole("searchbox", { name: "Buscar obra" }), { target: { value: "MATERNIDADE" } });
    expect(screen.getByText("1 de 4 obras")).toBeTruthy();
    fireEvent.change(screen.getByRole("searchbox", { name: "Buscar obra" }), { target: { value: "" } });
    expect(screen.queryByRole("heading", { name: "Outras obras sem medição" })).toBeNull();
  });

  it("Iniciar: os chips filtram por contratante (Todas e um por contratante)", async () => {
    responder();
    render(<MedicoesPagina aba="iniciar" usuario={usuario} />);
    await screen.findByText("4 de 4 obras");
    const chips = within(screen.getByRole("group", { name: "Contratante" })).getAllByRole("button").map(b => b.textContent);
    expect(chips).toEqual(["Todas", "SINFRA", "MTPAR", "Pref. Várzea Grande"]);
    fireEvent.click(screen.getByRole("button", { name: "MTPAR" }));
    expect(screen.getByText("1 de 1 obras")).toBeTruthy();
    expect(screen.getByText("Complexo Gama")).toBeTruthy();
    expect(screen.queryByText("Cinco Bairros")).toBeNull();
  });

  it("Iniciar: trocar o mês relê a lista pelo mês escolhido", async () => {
    responder();
    render(<MedicoesPagina aba="iniciar" usuario={usuario} />);
    await screen.findByText("4 de 4 obras");
    fireEvent.click(screen.getByRole("button", { name: "Mês anterior" }));
    expect(screen.getByText("outubro de 2026")).toBeTruthy();
    await waitFor(() => expect(api.mock.calls.map(c => c[0])).toContain("/api/medicoes/resumo?mes=2026-10"));
  });

  it("Iniciar: escolher a obra e iniciar manda a carta e a planilha e abre a página da medição", async () => {
    responder();
    apiForm.mockResolvedValue({ medicao_id: 99, versao: 1, estado: "planilha_gerada", avisos: [] });
    render(<MedicoesPagina aba="iniciar" usuario={usuario} />);
    await screen.findByText("4 de 4 obras");
    fireEvent.click(screen.getByRole("button", { name: /Cinco Bairros/ }));
    expect(screen.getByText(/Iniciar a 35ª medição · novembro de 2026 · SINFRA/)).toBeTruthy();
    // a última medição da obra
    expect(within(screen.getByRole("region", { name: "Última medição" })).getByText(/34ª · setembro de 2026 · R\$\s74\.584,81 · recebida/)).toBeTruthy();
    await screen.findByRole("heading", { name: "Planilha e carta" });
    expect((screen.getByLabelText("Número") as HTMLInputElement).value).toBe("35");
    await waitFor(() => expect((screen.getByLabelText("Nº da carta") as HTMLInputElement).value).toBe("401"));
    fireEvent.change(screen.getByLabelText("Valor pedido"), { target: { value: "209.051,81" } });
    // sem os arquivos não cria
    fireEvent.click(screen.getByRole("button", { name: "Iniciar medição" }));
    expect(await screen.findByText("Anexe a carta assinada.")).toBeTruthy();
    expect(screen.getByText("Anexe a planilha de medição.")).toBeTruthy();
    expect(apiForm).not.toHaveBeenCalled();
    const carta = new File(["%PDF-1.4"], "carta-401.pdf", { type: "application/pdf" });
    const planilha = new File(["PK"], "medicao-35.xlsx");
    fireEvent.change(screen.getByLabelText(/Carta assinada/), { target: { files: [carta] } });
    fireEvent.change(screen.getByLabelText(/Planilha de medição/), { target: { files: [planilha] } });
    fireEvent.click(screen.getByRole("button", { name: "Iniciar medição" }));
    await waitFor(() => expect(apiForm).toHaveBeenCalledTimes(1));
    const [url, fd] = apiForm.mock.calls[0] as [string, FormData];
    expect(url).toBe("/api/contratos/1/planilhas");
    expect(fd.get("numero")).toBe("35");
    expect(fd.get("competencia")).toBe("2026-11");
    expect(fd.get("periodo_inicio")).toBe("2026-11-01");
    expect(fd.get("periodo_fim")).toBe("2026-11-30");
    expect(fd.get("valor")).toBe("209.051,81");
    expect(fd.get("numero_orgao")).toBe("401");
    expect((fd.get("oficio") as File).name).toBe("carta-401.pdf");
    expect((fd.get("planilha") as File).name).toBe("medicao-35.xlsx");
    await waitFor(() => expect(window.location.pathname).toBe("/obras/1/medicoes/99"));
  });

  it("Iniciar: a obra sem planilha e carta (MTPAR) lança a medição e abre a página dela", async () => {
    responder(() => undefined, false);
    api.mockImplementationOnce(async () => RESUMO);   // a leitura da lista
    render(<MedicoesPagina aba="iniciar" usuario={usuario} />);
    await screen.findByText("4 de 4 obras");
    responder(url => url === "/api/contratos/3/medicoes" ? { id: 55 } : undefined, false);
    fireEvent.click(screen.getByRole("button", { name: /Complexo Gama/ }));
    await screen.findByRole("heading", { name: "Espelho" });
    expect(screen.queryByText("Carta assinada (PDF)")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Iniciar medição" }));
    await waitFor(() => expect(window.location.pathname).toBe("/obras/3/medicoes/55"));
    const chamada = api.mock.calls.find(c => c[0] === "/api/contratos/3/medicoes");
    expect(JSON.parse((chamada![1] as { body: string }).body)).toEqual({ numero: 24, tipo: "execucao", competencia: "2026-11" });
  });

  it("Iniciar: erro do servidor aparece no formulário e a medição não abre", async () => {
    responder();
    apiForm.mockRejectedValue(new Error("A 35ª Medição já existe neste contrato"));
    render(<MedicoesPagina aba="iniciar" usuario={usuario} />);
    await screen.findByText("4 de 4 obras");
    fireEvent.click(screen.getByRole("button", { name: /Cinco Bairros/ }));
    await screen.findByRole("heading", { name: "Planilha e carta" });
    fireEvent.change(screen.getByLabelText("Valor pedido"), { target: { value: "1,00" } });
    fireEvent.change(screen.getByLabelText(/Carta assinada/), { target: { files: [new File(["%PDF"], "c.pdf")] } });
    fireEvent.change(screen.getByLabelText(/Planilha de medição/), { target: { files: [new File(["PK"], "p.xlsx")] } });
    fireEvent.click(screen.getByRole("button", { name: "Iniciar medição" }));
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(window.location.pathname).toBe("/medicoes");
  });

  it("Iniciar: a diretoria vê as obras, mas não o formulário de iniciar", async () => {
    responder();
    render(<MedicoesPagina aba="iniciar" usuario={{ ...usuario, perfil: "diretoria" }} />);
    await screen.findByText("4 de 4 obras");
    fireEvent.click(screen.getByRole("button", { name: /Cinco Bairros/ }));
    expect(screen.queryByRole("button", { name: "Iniciar medição" })).toBeNull();
  });

  it("falha ao ler as medições: mensagem em português", async () => {
    api.mockRejectedValue(new Error("falhou"));
    render(<MedicoesPagina aba="iniciar" usuario={usuario} />);
    expect(await screen.findByRole("alert")).toBeTruthy();
  });
});
