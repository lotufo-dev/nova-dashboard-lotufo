import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ResumoDasMedicoes, { type RespostaResumo } from "./ResumoDasMedicoes";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

// Dados sinteticos, com os nomes do cadastro de exemplo. A etapa, as datas e os valores (na cota) vem prontos do
// servidor; a tela so' mostra.
type Linha = RespostaResumo["grupos"][number]["linhas"][number];
type EtapaDaLinha = Linha["etapas"][number];
const e = (etapa: EtapaDaLinha["etapa"], situacao: EtapaDaLinha["situacao"], data: string | null = null): EtapaDaLinha => ({ etapa, situacao, data });
const linha = (x: Partial<Linha> & Pick<Linha, "contrato_id" | "obra" | "medicao_id" | "titulo" | "etapa" | "etapas">): Linha => ({
  contratante: "Secretaria de Exemplo", medicao_ids: [x.medicao_id], numero: 1, tipo: "execucao", competencia: "2026-10",
  valor_centavos: null, ...x,
});

const PROPRIA = linha({
  contrato_id: 7, obra: "Obra Própria", medicao_id: 71, titulo: "12ª Medição + Reajuste", medicao_ids: [71, 72], etapa: "protocolado",
  valor_centavos: 10_100_001,
  etapas: [e("em_analise", "feito", "2026-11-03"), e("boletim", "feito"), e("nota", "feito", "2026-11-09"),
    e("protocolado", "atual", "2026-11-10"), e("recebido", "futuro")],
});
// familia sem planilha/carta: a obra nao tem a etapa "em analise"
const CONSORCIO = linha({
  contrato_id: 8, obra: "Obra Consórcio", contratante: "Companhia de Exemplo", medicao_id: 81, titulo: "3ª Medição", etapa: "boletim",
  valor_centavos: 333_300, etapas: [e("boletim", "atual"), e("nota", "futuro"), e("protocolado", "futuro"), e("recebido", "futuro")],
});
const REAJUSTE = linha({
  contrato_id: 8, obra: "Obra Consórcio", contratante: "Companhia de Exemplo", medicao_id: 82, titulo: "Reajuste da 3ª Medição", tipo: "reajuste",
  etapa: "recebido", valor_centavos: 50_000,
  etapas: [e("boletim", "feito", "2026-11-02"), e("nota", "feito", "2026-11-04"), e("protocolado", "feito", "2026-11-05"), e("recebido", "feito", "2026-11-12")],
});
const ANTIGA = linha({
  contrato_id: 7, obra: "Obra Própria", medicao_id: 61, titulo: "11ª Medição", competencia: "2025-12", etapa: "em_analise", valor_centavos: 0,
  etapas: [e("em_analise", "atual", "2026-01-08"), e("boletim", "futuro"), e("nota", "futuro"), e("protocolado", "futuro"), e("recebido", "futuro")],
});
const RESUMO: RespostaResumo = {
  hoje: "2026-11-16", mes: "2026-10", em_trabalho: "2026-10",
  atualizacao: { ultimo_lancamento: "2026-11-14 18:40:00", rm_lido_em: "2026-11-16 11:00:00" },
  etapas: [
    { etapa: "antes", medicoes: 0, valor_centavos: 0 }, { etapa: "em_analise", medicoes: 0, valor_centavos: 0 },
    { etapa: "boletim", medicoes: 1, valor_centavos: 333_300 }, { etapa: "nota", medicoes: 0, valor_centavos: 0 },
    { etapa: "protocolado", medicoes: 2, valor_centavos: 10_100_001 }, { etapa: "recebido", medicoes: 1, valor_centavos: 50_000 },
  ],
  grupos: [{ contratante: "Companhia de Exemplo", linhas: [CONSORCIO, REAJUSTE] }, { contratante: "Secretaria de Exemplo", linhas: [PROPRIA] }],
  sem_medicao: [
    { contrato_id: 9, obra: "Obra Terceira", contratante: "Secretaria de Exemplo",
      ultima: { medicao_id: 91, titulo: "5ª Medição", competencia: "2026-09", etapa: "protocolado" } },
    { contrato_id: 10, obra: "Obra Nova", contratante: null, ultima: null },
  ],
  anteriores: [{ competencia: "2025-12", linhas: [ANTIGA] }],
};
const VAZIO: RespostaResumo = {
  ...RESUMO, mes: "2026-09", atualizacao: { ultimo_lancamento: null, rm_lido_em: null },
  etapas: RESUMO.etapas.map(x => ({ ...x, medicoes: 0, valor_centavos: 0 })), grupos: [], sem_medicao: [], anteriores: [],
};

const texto = (el: Element | null) => (el?.textContent ?? "").replace(/\s+/g, " ").trim();
const celulas = (l: HTMLElement) => within(l).getAllByRole("cell").map(texto);

describe("Resumo das medições (#749)", () => {
  afterEach(() => { cleanup(); api.mockReset(); window.history.replaceState(null, "", "/"); });

  it("abre na competência em trabalho e diz de quando é o dado", async () => {
    api.mockResolvedValue(RESUMO);
    render(<ResumoDasMedicoes ir={() => {}} />);
    expect(await screen.findByRole("heading", { name: "Outubro de 2026" })).toBeTruthy();
    expect(api).toHaveBeenCalledWith("/api/resumo-medicoes");
    expect(screen.getByText("Competência em trabalho")).toBeTruthy();
    // os carimbos do banco (UTC) saem no horario de Cuiaba
    expect(screen.getByText(/Valores na cota da Lotufo\. Último lançamento em 14\/11\/2026 às 14:40; recebimentos lidos do RM em 16\/11\/2026 às 07:00\./)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Voltar à competência em trabalho/ })).toBeNull();
    expect(screen.getByRole("link", { name: /Exportar CSV/ }).getAttribute("href")).toBe("/api/resumo-medicoes.csv?mes=2026-10");
  });

  it("a faixa conta as medições de cada etapa, com o valor, e as obras sem medição; zero vira traço", async () => {
    api.mockResolvedValue(RESUMO);
    render(<ResumoDasMedicoes ir={() => {}} />);
    const faixa = await screen.findByRole("list", { name: "Medições de outubro de 2026 por etapa" });
    expect(within(faixa).getAllByRole("listitem").map(texto)).toEqual([
      "Em análise—", "Boletim1 mediçãoR$ 3.333,00", "Nota—", "Protocolado2 mediçõesR$ 101.000,01",
      "Recebido1 mediçãoR$ 500,00", "Sem medição2 obras"]);
  });

  it("uma linha por obra, por órgão: a etapa alcançada com a data registrada, a que falta vazia e só as etapas do fluxo da obra", async () => {
    api.mockResolvedValue(RESUMO);
    render(<ResumoDasMedicoes ir={() => {}} />);
    const tabela = await screen.findByRole("table", { name: /Etapa da medição de cada obra em outubro de 2026/ });
    expect(within(tabela).getAllByRole("columnheader").map(texto)).toEqual(["Obra", "Em análise", "Boletim", "Nota", "Protocolado", "Recebido", "Medido"]);
    expect(within(tabela).getAllByRole("rowheader").map(texto)).toEqual([
      "Companhia de Exemplo", "Obra Consórcio3ª Medição", "Obra ConsórcioReajuste da 3ª Medição",
      "Secretaria de Exemplo", "Obra Própria12ª Medição + Reajuste"]);
    const [, , consorcio, reajuste, , propria] = within(tabela).getAllByRole("row");
    // sem "em analise" no fluxo; no boletim, sem data registrada: o traço, nunca uma data estimada
    expect(celulas(consorcio)).toEqual(["a obra não tem esta etapa", "BoletimEtapa atual, desde —sem data registrada", "ainda não", "ainda não", "ainda não", "R$ 3.333,00"]);
    expect(celulas(propria)).toEqual(["Em análiseFeito em 03/11/26", "BoletimFeito em —sem data registrada", "NotaFeito em 09/11/26",
      "ProtocoladoEtapa atual, desde 10/11/26", "ainda não", "R$ 101.000,01"]);
    // a situacao tem forma alem da cor: o visto no que passou, o meio circulo na etapa atual
    const [, boletim, , protocolado] = within(propria).getAllByRole("cell");
    expect(boletim.querySelector(".glifo--feito")).not.toBeNull();
    expect(protocolado.querySelector(".glifo--andamento")).not.toBeNull();
    expect(protocolado.getAttribute("aria-current")).toBe("step");
    expect(within(reajuste).getAllByRole("cell").at(-2)?.querySelector(".glifo--feito")).not.toBeNull();     // recebida: tudo feito
    // a obra e a medicao abrem; a obra repetida na linha de baixo nao e' link de novo
    expect(within(propria).getByRole("link", { name: "Obra Própria" }).getAttribute("href")).toBe("/obras/7/medicoes");
    expect(within(propria).getByRole("link", { name: "12ª Medição + Reajuste" }).getAttribute("href")).toBe("/obras/7/medicoes/71");
    expect(within(reajuste).queryByRole("link", { name: "Obra Consórcio" })).toBeNull();
    // o contador do painel e' de medicoes (a linha de execucao + reajuste conta duas)
    expect(texto(screen.getByRole("heading", { name: "Por obra" }).parentElement)).toBe("Por obra44 medições");
  });

  it("obras sem medição no mês, com a última medição de cada uma", async () => {
    api.mockResolvedValue(RESUMO);
    render(<ResumoDasMedicoes ir={() => {}} />);
    const tabela = await screen.findByRole("table", { name: /Obras ativas sem medição em outubro de 2026/ });
    const [, terceira, nova] = within(tabela).getAllByRole("row");
    expect(texto(within(terceira).getByRole("rowheader"))).toBe("Obra Terceira");
    expect(celulas(terceira)).toEqual(["Secretaria de Exemplo", "5ª Medição09/2026", "Protocolado"]);
    expect(within(terceira).getByRole("link", { name: "5ª Medição" }).getAttribute("href")).toBe("/obras/9/medicoes/91");
    expect(celulas(nova)).toEqual(["—", "—", "—"]);
  });

  it("meses anteriores em aberto, por competência", async () => {
    api.mockResolvedValue(RESUMO);
    render(<ResumoDasMedicoes ir={() => {}} />);
    const tabela = await screen.findByRole("table", { name: /competências anteriores a outubro de 2026 ainda não recebidas/ });
    expect(within(tabela).getAllByRole("rowheader").map(texto)).toEqual(["Dezembro de 2025", "Obra Própria11ª Medição"]);
    // a data curta leva o ano (a lista atravessa o ano); o valor zero vira traço
    expect(celulas(within(tabela).getAllByRole("row")[2])).toEqual(["Em análiseEtapa atual, desde 08/01/26", "ainda não", "ainda não", "ainda não", "ainda não", "—"]);
  });

  it("troca a competência, guarda o mês na URL e volta à competência em trabalho", async () => {
    api.mockImplementation(async (caminho: string) => (caminho.endsWith("mes=2026-09") ? VAZIO : RESUMO));
    render(<ResumoDasMedicoes ir={() => {}} />);
    fireEvent.click(await screen.findByRole("button", { name: "Mês anterior" }));
    expect(await screen.findByRole("heading", { name: "Setembro de 2026" })).toBeTruthy();
    expect(api).toHaveBeenLastCalledWith("/api/resumo-medicoes?mes=2026-09");
    expect(window.location.search).toBe("?mes=2026-09");
    expect(screen.getByText("Competência")).toBeTruthy();
    // sem lancamento e sem leitura do RM, a frase diz so' o que o sistema tem; listas vazias viram uma linha curta
    expect(screen.getByText("Valores na cota da Lotufo. Nenhum lançamento registrado.")).toBeTruthy();
    expect(screen.getByText("Nenhuma medição em setembro de 2026.")).toBeTruthy();
    expect(screen.getByText("Nenhuma obra sem medição.")).toBeTruthy();
    expect(screen.getByText("Nenhuma medição aberta de meses anteriores.")).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.getByRole("link", { name: /Exportar CSV/ }).getAttribute("href")).toBe("/api/resumo-medicoes.csv?mes=2026-09");
    fireEvent.click(screen.getByRole("button", { name: "Voltar à competência em trabalho" }));
    expect(await screen.findByRole("heading", { name: "Outubro de 2026" })).toBeTruthy();
    expect(api).toHaveBeenLastCalledWith("/api/resumo-medicoes");
    expect(window.location.search).toBe("");
  });

  it("abre no mês que veio na URL; mês inválido cai na competência em trabalho", async () => {
    api.mockResolvedValue(VAZIO);
    render(<ResumoDasMedicoes ir={() => {}} busca={{ mes: "2026-09" }} />);
    await screen.findByRole("heading", { name: "Setembro de 2026" });
    expect(api).toHaveBeenCalledWith("/api/resumo-medicoes?mes=2026-09");
    cleanup(); api.mockClear(); api.mockResolvedValue(RESUMO);
    render(<ResumoDasMedicoes ir={() => {}} busca={{ mes: "2026-13" }} />);
    await screen.findByRole("heading", { name: "Outubro de 2026" });
    expect(api).toHaveBeenCalledWith("/api/resumo-medicoes");
  });

  it("variante B (?variante=b): a trilha, o selo da etapa atual e só a data dela", async () => {
    api.mockResolvedValue({ ...RESUMO, grupos: [...RESUMO.grupos, { contratante: "Secretaria de Exemplo 2", linhas: [
      linha({ contrato_id: 11, obra: "Obra Quarta", medicao_id: 111, titulo: "1ª Medição", etapa: "antes", valor_centavos: 9_000,
        etapas: [e("em_analise", "futuro"), e("boletim", "futuro"), e("nota", "futuro"), e("protocolado", "futuro"), e("recebido", "futuro")] })] }] });
    render(<ResumoDasMedicoes ir={() => {}} busca={{ variante: "b" }} />);
    const tabela = await screen.findByRole("table", { name: /Etapa da medição de cada obra em outubro de 2026/ });
    expect(within(tabela).getAllByRole("columnheader").map(texto)).toEqual(["Obra", "Etapa", "Desde", "Medido"]);
    const linhas = within(tabela).getAllByRole("row");
    expect(celulas(linhas[2])).toEqual(["Boletim", "—sem data registrada", "R$ 3.333,00"]);
    expect(celulas(linhas[3])).toEqual(["Recebido", "12/11/2026", "R$ 500,00"]);
    expect(celulas(linhas[5])).toEqual(["Protocolado", "10/11/2026", "R$ 101.000,01"]);
    expect(celulas(linhas[7])).toEqual(["Planilha/carta a enviar", "—", "R$ 90,00"]);
    // o selo leva a forma da situacao; a trilha tem uma celula por etapa, sem cor na que a obra nao tem
    expect(linhas[3].querySelector(".selo--feito .glifo--feito")).not.toBeNull();
    expect(linhas[5].querySelector(".selo--andamento .glifo--andamento")).not.toBeNull();
    expect([...linhas[2].querySelectorAll(".rdm-trilha__celula")].map(c => c.className.replace("rdm-trilha__celula ", ""))).toEqual(
      ["rdm-trilha__celula--fora", "rdm-cor--boletim", "rdm-cor--vazia", "rdm-cor--vazia", "rdm-cor--vazia"]);
  });

  it("na variante A, a planilha/carta ainda não enviada fica dita na linha e na faixa", async () => {
    api.mockResolvedValue({ ...RESUMO,
      etapas: RESUMO.etapas.map(x => (x.etapa === "antes" ? { ...x, medicoes: 1, valor_centavos: 9_000 } : x)),
      grupos: [{ contratante: "Secretaria de Exemplo", linhas: [
        linha({ contrato_id: 11, obra: "Obra Quarta", medicao_id: 111, titulo: "1ª Medição", etapa: "antes", valor_centavos: 9_000,
          etapas: [e("em_analise", "futuro"), e("boletim", "futuro"), e("nota", "futuro"), e("protocolado", "futuro"), e("recebido", "futuro")] })] }] });
    render(<ResumoDasMedicoes ir={() => {}} />);
    const tabela = await screen.findByRole("table", { name: /Etapa da medição de cada obra/ });
    expect(texto(within(tabela).getAllByRole("rowheader")[1])).toBe("Obra Quarta1ª MediçãoPlanilha/carta a enviar");
    expect(texto(within(screen.getByRole("list", { name: /por etapa/ })).getAllByRole("listitem")[0])).toBe("Planilha/carta a enviar1 mediçãoR$ 90,00");
  });

  it("erro ao carregar vira aviso com o que fazer", async () => {
    api.mockRejectedValue(new Error("sem resposta do servidor"));
    render(<ResumoDasMedicoes ir={() => {}} />);
    await waitFor(() => expect(screen.getByRole("alert").textContent).toMatch(/Não foi possível carregar o resumo das medições/));
  });
});
