import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AvisosPagina from "./AvisosPagina";
import { useRota } from "./rota";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

// Os Avisos têm página própria (#805): a página lê a fila do servidor (GET /api/inicio), a mesma da Início, e a
// organiza em contagens pelo prazo, abas por assunto, a Agenda e os Vencidos por obra. Dados fictícios.
const aviso = (extra: Record<string, unknown> = {}) => ({
  tipo: "execucao_vencendo", nivel: "atencao", publico: ["operacao"], contrato_id: 7, obra: "Granito", dias: 20,
  valor_centavos: null, mensagem: "Granito: execução termina", destino: { tela: "contrato", id: 7, aba: "prazos" },
  data: "2026-11-26", sentido: "prazo", ...extra });
const reajuste = (extra: Record<string, unknown> = {}) => aviso({ tipo: "reajuste_sem_resposta", sentido: "desde",
  mensagem: "Granito: reajuste sem resposta", destino: { tela: "contrato", id: 7, aba: "reajuste" }, ...extra });
const certidao = (extra: Record<string, unknown> = {}) => aviso({ tipo: "documentos_empresa", contrato_id: null, obra: null,
  entidade_id: 3, entidade: "Construtora Alfa", mensagem: "Construtora Alfa: FGTS vence", destino: { tela: "documentos" }, ...extra });

const OBRAS = [
  { id: 7, orgao: "SINFRA - SUEF II", contratante: "SINFRA", numero_instrumento: "IC 7/2026", nome_curto: "Granito", estado: "ativo" },
  { id: 8, orgao: "MTPAR", contratante: "MTPAR", numero_instrumento: "IC 8/2026", nome_curto: "Maternidade", estado: "ativo" },
];

function Pagina() {
  const { busca } = useRota();
  return <AvisosPagina busca={busca} />;
}

let fila: unknown[] | Error = [];
let obras: unknown[] | Error = OBRAS;

async function abrir(url: string, avisos: unknown[] | Error) {
  fila = avisos;
  window.history.replaceState(null, "", url);
  const tela = render(<Pagina />);
  await act(async () => {});
  return tela;
}

const limpo = (e: Element | null | undefined) => (e?.textContent ?? "").replace(/ /g, " ");
const numeros = () => [...document.querySelectorAll(".avs-numero")].map(n => [...n.children].map(limpo).join(" · "));
const abas = () => within(screen.getByRole("navigation", { name: "Assunto dos avisos" })).getAllByRole("link");
const bloco = (nome: string) => screen.getByRole("heading", { level: 2, name: nome }).closest("section")!;
const linhasDe = (e: Element) => [...e.querySelectorAll(".avs-linha")].map(l => [...l.children].map(limpo));
const grupos = () => [...document.querySelectorAll("tr.avs-vencido")].map(l => [...l.children].map(limpo));

describe("Avisos: página própria, por data e por assunto", () => {
  beforeEach(() => {
    obras = OBRAS;
    api.mockImplementation(async (caminho: string) => {
      if (caminho === "/api/inicio") { if (fila instanceof Error) throw fila; return { avisos: fila }; }
      if (caminho === "/api/contratos") { if (obras instanceof Error) throw obras; return obras; }
      throw new Error(`chamada inesperada: ${caminho}`);
    });
  });
  afterEach(() => { cleanup(); api.mockReset(); window.history.replaceState(null, "", "/"); });

  const FILA = [
    aviso({ mensagem: "Granito: execução vencida", dias: -3, data: "2026-11-04" }),
    reajuste({ dias: 400, data: "2025-10-03" }),
    reajuste({ contrato_id: 8, obra: "Maternidade", mensagem: "Maternidade: reajuste sem resposta", dias: 90, data: "2026-08-09",
      destino: { tela: "contrato", id: 8, aba: "reajuste" } }),
    certidao({ mensagem: "Construtora Alfa: FGTS vencida", dias: -10, data: "2026-10-28" }),
    certidao({ dias: 0, data: "2026-11-07" }),
    aviso({ tipo: "vigencia_vencendo", contrato_id: 8, obra: "Maternidade", mensagem: "Maternidade: vigência termina", dias: 5, data: "2026-11-12",
      destino: { tela: "contrato", id: 8, aba: "prazos" } }),
    aviso({ dias: 20, data: "2026-11-27" }),
    aviso({ tipo: "vigencia_vencendo", mensagem: "Granito: vigência termina", dias: 60, data: "2027-01-06" }),
    // a garantia abre Documentos, como a certidão, e o aprovado abaixo do pedido vem com o destino padrão (a aba
    // Medições da obra): o assunto de cada um sai do tipo
    aviso({ tipo: "garantia_aquem_execucao", nivel: "critico", mensagem: "Granito: garantia não cobre o fim da execução", dias: -30,
      data: "2026-10-08", destino: { tela: "documentos" }, entidade_id: 3 }),
    aviso({ tipo: "aprovado_abaixo_do_pedido", nivel: "acao", contrato_id: 8, obra: "Maternidade", sentido: "desde", dias: 15, data: "2026-10-23",
      mensagem: "Maternidade: 3ª Medição: aprovado abaixo do pedido", destino: { tela: "contrato", id: 8, aba: "medicoes" }, medicao_id: 31 }),
    aviso({ obra: "Distante", contrato_id: 9, dias: 120, data: "2027-03-07" }),                                   // além de 90 dias
    aviso({ obra: "Parada", contrato_id: 10, tipo: "nota_divergente", dias: null, data: null, sentido: null,      // sem data
      mensagem: "Parada: nota divergente", destino: { tela: "contrato", id: 10, aba: "notas" } }),
  ];

  it("as contagens do alto são as seções do tempo: os vencidos dizem em quantas obras e empresas; sem data e além de 90 dias ficam fora (#656)", async () => {
    const { container } = await abrir("/avisos", FILA);
    expect(api).toHaveBeenCalledWith("/api/inicio");
    expect(api).not.toHaveBeenCalledWith("/api/contratos");       // sem recorte, a lista de obras não é lida
    expect(numeros()).toEqual(["Vencidos · 6 · em 2 obras e 1 empresa", "Esta semana · 2", "Este mês · 1", "Próximos 90 dias · 1"]);
    // a situação vai no símbolo ao lado do rótulo (cor e forma); o que vence depois de 30 dias é neutro
    expect([...document.querySelectorAll(".avs-numero dt")].map(d => d.querySelector(".glifo")?.className ?? null))
      .toEqual(["glifo glifo--critico", "glifo glifo--breve", "glifo glifo--breve", null]);
    expect(container.textContent).not.toMatch(/Parada|Distante|Sem data/);
    expect(screen.getByRole("list", { name: "Legenda das cores" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Fechar os avisos" })).toBeNull();
  });

  it("contagem sem aviso fica neutra, sem símbolo; os vencidos só de obras dizem 'em N obras'", async () => {
    await abrir("/avisos", [aviso({ dias: -3, data: "2026-11-04" }), aviso({ contrato_id: 8, obra: "Maternidade", dias: -9, data: "2026-10-29" })]);
    expect(numeros()).toEqual(["Vencidos · 2 · em 2 obras", "Esta semana · 0", "Este mês · 0", "Próximos 90 dias · 0"]);
    expect(document.querySelectorAll(".avs-numero dt .glifo")).toHaveLength(1);
  });

  it("as abas são os assuntos aprovados (Prazos, Reajustes, Garantias, Certidões, Medições), com a quantidade, e ficam no endereço", async () => {
    await abrir("/avisos", FILA);
    expect(abas().map(a => [limpo(a), a.getAttribute("href"), a.getAttribute("aria-current")])).toEqual([
      ["Tudo 10", "/avisos", "true"], ["Prazos 4", "/avisos?familia=prazos", null], ["Reajustes 2", "/avisos?familia=reajustes", null],
      ["Garantias 1", "/avisos?familia=garantias", null], ["Certidões 2", "/avisos?familia=certidoes", null],
      ["Medições 1", "/avisos?familia=medicoes", null]]);
    await act(async () => { fireEvent.click(abas()[2]); });
    expect(window.location.pathname + window.location.search).toBe("/avisos?familia=reajustes");
    expect(abas()[2].getAttribute("aria-current")).toBe("true");
    // os dois blocos mostram só o assunto; as contagens do alto continuam as da página
    expect(grupos().map(g => g[0])).toEqual(["GranitoReajustes", "MaternidadeReajustes"]);
    expect(bloco("Agenda").textContent).toContain("Nada a vencer em 90 dias.");
    expect(numeros()[0]).toBe("Vencidos · 6 · em 2 obras e 1 empresa");
    // a garantia e o aviso de medição têm aba própria: não caem com a certidão nem em "Outros"
    await act(async () => { fireEvent.click(abas()[3]); });
    expect(grupos()).toEqual([["GranitoGarantias", "1", "há 30 dias"]]);
    await act(async () => { fireEvent.click(abas()[5]); });
    expect(grupos()).toEqual([["MaternidadeMedições", "1", "há 15 dias"]]);
  });

  it("tipo de aviso que o mapa não conhece aparece na aba Outros, que só existe quando há um", async () => {
    await abrir("/avisos", [aviso({ dias: -3, data: "2026-11-04" }), aviso({ tipo: "tipo_que_o_servidor_inventou", dias: 4, data: "2026-11-11" })]);
    expect(abas().map(limpo)).toEqual(["Tudo 2", "Prazos 1", "Outros 1"]);
    expect(linhasDe(bloco("Agenda"))).toEqual([["em 4 dias", "GranitoGranito: execução termina", "Outros"]]);
  });

  it("?familia= dos links de antes abre a aba equivalente; assunto sem aviso no endereço aparece para dizer o filtro", async () => {
    const aberta = () => abas().find(a => a.getAttribute("aria-current") === "true")?.textContent;
    for (const [antes, aba] of [["reajustes", "Reajustes 2"], ["reajuste", "Reajustes 2"], ["prazo", "Prazos 4"], ["certidoes", "Certidões 2"],
      ["documentos", "Certidões 2"], ["nota", "Medições 1"], ["valor-desconhecido", "Tudo 10"]]) {
      await abrir(`/avisos?familia=${antes}`, FILA);
      expect(aberta(), antes).toBe(aba);
      cleanup();
    }
    await abrir("/avisos?familia=siga", FILA);
    expect(abas().map(limpo)).toEqual(["Tudo 10", "Prazos 4", "Reajustes 2", "Garantias 1", "Certidões 2", "Medições 1", "SIGA 0"]);
    expect(screen.getByText("Nenhum aviso com esse filtro.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Limpar o filtro" }).getAttribute("href")).toBe("/avisos");
    expect(screen.queryByRole("heading", { level: 2, name: "Agenda" })).toBeNull();
  });

  it("Agenda: o que ainda vai vencer, em ordem de data, com os dias, a obra ou a empresa, o que é e o assunto", async () => {
    await abrir("/avisos", FILA);
    const agenda = bloco("Agenda");
    expect(limpo(agenda.querySelector(".cartao__cabeca .contador"))).toBe("44 avisos");
    expect(within(agenda).getAllByRole("heading", { level: 3 }).map(h => `${limpo(h)} ${limpo(h.parentElement!.querySelector(".contador [aria-hidden='true']:not(.glifo)"))}`))
      .toEqual(["Esta semana 2", "Este mês 1", "Próximos 90 dias 1"]);
    expect(linhasDe(agenda)).toEqual([
      ["hoje", "Construtora AlfaConstrutora Alfa: FGTS vence", "Certidões"],
      ["em 5 dias", "MaternidadeMaternidade: vigência termina", "Prazos"],
      ["em 20 dias", "GranitoGranito: execução termina", "Prazos"],
      ["em 60 dias", "GranitoGranito: vigência termina", "Prazos"],
    ]);
    // vence em até 30 dias = vence em breve, com forma além da cor; depois disso, neutro e sem símbolo
    expect([...agenda.querySelectorAll(".avs-linha > .selo")].map(s => [s.className, s.querySelector(".glifo")?.className ?? null])).toEqual([
      ["selo selo--breve avs-dias", "glifo glifo--breve"], ["selo selo--breve avs-dias", "glifo glifo--breve"],
      ["selo selo--breve avs-dias", "glifo glifo--breve"], ["selo avs-dias", null]]);
    // a obra em linha própria e a mensagem sem o "Nome: " do começo (que fica só para o leitor de tela, no link)
    const primeira = agenda.querySelector(".avs-linha")!;
    expect(primeira.querySelector(".avs-linha__obra")!.textContent).toBe("Construtora Alfa");
    expect([...primeira.querySelector(".avs-linha__link")!.childNodes].map(n => n.textContent)).toEqual(["Construtora Alfa: ", "FGTS vence"]);
    // cada linha leva ao lugar do aviso (`destinoDoAviso`)
    expect([...agenda.querySelectorAll(".avs-linha__link")].map(l => l.getAttribute("href")))
      .toEqual(["/documentos/3", "/obras/8/prazos", "/obras/7/prazos", "/obras/7/prazos"]);
  });

  it("Vencidos por obra: uma linha por obra ou empresa, da maior idade para a menor, com os assuntos, a quantidade e o mais antigo", async () => {
    await abrir("/avisos", FILA);
    const vencidos = bloco("Vencidos por obra");
    expect(vencidos.querySelector(".cartao__cabeca .contador")!.className).toBe("contador contador--critico");
    expect(limpo(vencidos.querySelector(".cartao__cabeca .contador"))).toBe("66 avisos");
    expect(within(vencidos).getAllByRole("columnheader").map(limpo)).toEqual(["Obra ou empresa", "Avisos", "Mais antigo"]);
    // o resumo da linha usa os nomes das abas, na ordem delas
    expect(grupos()).toEqual([
      ["GranitoPrazos · Reajustes · Garantias", "3", "há 400 dias"], ["MaternidadeReajustes · Medições", "2", "há 90 dias"],
      ["Construtora AlfaCertidões", "1", "há 10 dias"]]);
    expect([...vencidos.querySelectorAll("tr.avs-vencido .selo")].every(s => s.className === "selo selo--critico avs-dias")).toBe(true);
    // fechado: os avisos da obra só aparecem ao abrir a linha, ali mesmo, do mais antigo ao mais novo, cada um com o destino dele
    expect(vencidos.querySelectorAll(".avs-linha")).toHaveLength(0);
    const botao = within(vencidos).getByRole("button", { name: "Granito" });
    expect(botao.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(botao);
    expect(botao.getAttribute("aria-expanded")).toBe("true");
    const itens = document.getElementById(botao.getAttribute("aria-controls")!)!;
    expect(linhasDe(itens)).toEqual([["há 400 dias", "reajuste sem resposta", "Reajustes"],
      ["há 30 dias", "garantia não cobre o fim da execução", "Garantias"], ["há 3 dias", "execução vencida", "Prazos"]]);
    expect(itens.querySelector(".avs-linha__obra")).toBeNull();          // o grupo já diz a obra
    expect([...itens.querySelectorAll(".avs-linha__link")].map(l => l.getAttribute("href")))
      .toEqual(["/obras/7/reajuste", "/documentos/3/garantia", "/obras/7/prazos"]);
    // a linha inteira também abre e fecha
    fireEvent.click(vencidos.querySelectorAll("tr.avs-vencido")[1].querySelector("td")!);
    expect(within(vencidos).getByRole("button", { name: "Maternidade" }).getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(botao);
    expect(botao.getAttribute("aria-expanded")).toBe("false");
    expect(linhasDe(vencidos)).toEqual([["há 90 dias", "reajuste sem resposta", "Reajustes"],
      ["há 15 dias", "3ª Medição: aprovado abaixo do pedido", "Medições"]]);
  });

  it("todo vencido aparece, sem limite de idade nem corte '… e mais N' (#656): só deixa de ser lista corrida", async () => {
    const muitos = Array.from({ length: 30 }, (_, i) => aviso({ contrato_id: 1 + (i % 6), obra: `Obra ${1 + (i % 6)}`,
      mensagem: `Obra ${1 + (i % 6)}: execução vencida`, dias: -(i + 1) * 40, data: "2024-01-01" }));
    await abrir("/avisos", muitos);
    expect(numeros()[0]).toBe("Vencidos · 30 · em 6 obras");
    expect(grupos().map(g => `${g[0]} ${g[1]} ${g[2]}`)).toEqual([
      "Obra 6Prazos 5 há 1.200 dias", "Obra 5Prazos 5 há 1.160 dias", "Obra 4Prazos 5 há 1.120 dias", "Obra 3Prazos 5 há 1.080 dias",
      "Obra 2Prazos 5 há 1.040 dias", "Obra 1Prazos 5 há 1.000 dias"]);
    for (const b of within(bloco("Vencidos por obra")).getAllByRole("button")) fireEvent.click(b);
    expect(bloco("Vencidos por obra").querySelectorAll(".avs-linha")).toHaveLength(30);
    expect(screen.getAllByRole("columnheader").map(limpo)[0]).toBe("Obra");
  });

  it("?obra= mostra só os avisos da obra, com o nome dela e o link que limpa o filtro; os vencidos dela já vêm abertos", async () => {
    const { container } = await abrir("/avisos?obra=7&familia=prazo", FILA);
    expect(api).toHaveBeenCalledWith("/api/contratos");
    expect(screen.getByRole("heading", { level: 2, name: "Avisos · Granito" })).toBeTruthy();
    expect(numeros()).toEqual(["Vencidos · 3 · em 1 obra", "Esta semana · 0", "Este mês · 1", "Próximos 90 dias · 1"]);
    expect(container.textContent).not.toMatch(/Maternidade|Construtora Alfa/);
    expect(abas().map(limpo)).toEqual(["Tudo 5", "Prazos 3", "Reajustes 1", "Garantias 1"]);
    expect(abas().map(a => a.getAttribute("href")))
      .toEqual(["/avisos?obra=7", "/avisos?obra=7&familia=prazos", "/avisos?obra=7&familia=reajustes", "/avisos?obra=7&familia=garantias"]);
    expect(within(bloco("Vencidos por obra")).getByRole("button", { name: "Granito" }).getAttribute("aria-expanded")).toBe("true");
    expect(linhasDe(bloco("Vencidos por obra"))).toEqual([["há 3 dias", "execução vencida", "Prazos"]]);
    const limpar = screen.getByRole("link", { name: "Todos os avisos" });
    expect(limpar.getAttribute("href")).toBe("/avisos?familia=prazo");
    await act(async () => { fireEvent.click(limpar); });
    expect(screen.queryByRole("heading", { level: 2, name: /Avisos ·/ })).toBeNull();
    expect(abas().map(limpo)).toEqual(["Tudo 10", "Prazos 4", "Reajustes 2", "Garantias 1", "Certidões 2", "Medições 1"]);
  });

  it("?obra= de uma obra sem aviso: o nome vem da lista de obras, e uma linha curta no lugar dos blocos", async () => {
    await abrir("/avisos?obra=8", [aviso()]);
    expect(screen.getByRole("heading", { level: 2, name: "Avisos · Maternidade" })).toBeTruthy();
    expect(screen.getByText("Nenhum aviso com esse filtro.")).toBeTruthy();
    cleanup();
    // sem a lista de obras, o nome é o que o aviso traz; sem nem isso, a página não inventa nome
    obras = new Error("fora do ar");
    await abrir("/avisos?obra=7", [aviso()]);
    expect(screen.getByRole("heading", { level: 2, name: "Avisos · Granito" })).toBeTruthy();
    cleanup();
    await abrir("/avisos?obra=99", [aviso()]);
    expect(screen.getByRole("heading", { level: 2, name: "Avisos · Obra filtrada" })).toBeTruthy();
  });

  it("?c= (o contratante do link de antes) mostra só os avisos das obras dele; o aviso sem obra fica fora", async () => {
    const { container } = await abrir("/avisos?c=MTPAR", FILA);
    expect(screen.getByRole("heading", { level: 2, name: "Avisos · MTPAR" })).toBeTruthy();
    expect(numeros()).toEqual(["Vencidos · 2 · em 1 obra", "Esta semana · 1", "Este mês · 0", "Próximos 90 dias · 0"]);
    expect(container.textContent).not.toMatch(/Granito|Construtora Alfa/);
    expect(screen.getByRole("link", { name: "Todos os avisos" }).getAttribute("href")).toBe("/avisos");
    cleanup();
    // sem a lista de obras não dá para saber quais são do contratante: a página diz que falhou, não mostra tudo
    obras = new Error("fora do ar");
    await abrir("/avisos?c=MTPAR", FILA);
    expect(screen.getByRole("alert").textContent).toContain("Não foi possível verificar os avisos");
    expect(document.querySelector(".avs-numeros")).toBeNull();
  });

  it("certidão vencida que vem com data e sem dias entra em Vencidos pela data de validade (#656)", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-11-11T15:00:00Z"));
    try {
      await abrir("/avisos", [aviso({ dias: -2, data: "2026-11-09" }),
        certidao({ nivel: "critico", dias: null, data: "2026-11-01", mensagem: "Construtora Alfa: FGTS vencida" }),
        certidao({ entidade_id: 4, entidade: "Construtora Beta", dias: null, data: "2026-11-20", mensagem: "Construtora Beta: FGTS vence" })]);
      expect(grupos()).toEqual([["Construtora AlfaCertidões", "1", "há 10 dias"], ["GranitoPrazos", "1", "há 2 dias"]]);
      expect(linhasDe(bloco("Agenda"))).toEqual([["em 9 dias", "Construtora BetaConstrutora Beta: FGTS vence", "Certidões"]]);
    } finally { vi.useRealTimers(); }
  });

  it("sem aviso, uma linha curta; só fora da agenda também; com falha, não afirma isso", async () => {
    await abrir("/avisos", []);
    expect(screen.getByText("Nenhum aviso.")).toBeTruthy();
    expect(numeros()).toEqual(["Vencidos · 0", "Esta semana · 0", "Este mês · 0", "Próximos 90 dias · 0"]);
    expect(screen.queryByRole("link", { name: "Limpar o filtro" })).toBeNull();
    cleanup();
    await abrir("/avisos", [aviso({ dias: null, data: null, sentido: null }), aviso({ dias: 200, data: "2027-05-30" })]);
    expect(screen.getByText("Nenhum aviso.")).toBeTruthy();
    cleanup();
    await abrir("/avisos", new Error("fora do ar"));
    expect(screen.getByRole("alert").textContent).toContain("Não foi possível verificar os avisos");
    expect(screen.queryByText("Nenhum aviso.")).toBeNull();
    expect(document.querySelector(".avs-numeros")).toBeNull();
  });

  it("enquanto a fila não chega, diz que está carregando e não mostra contagem", () => {
    api.mockImplementation(() => new Promise(() => {}));
    window.history.replaceState(null, "", "/avisos");
    render(<Pagina />);
    expect(screen.getByRole("status").textContent).toBe("Carregando os avisos…");
    expect(document.querySelector(".avs-numeros")).toBeNull();
  });
});
