import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Aviso } from "./Alertas";
import AvisosPagina from "./AvisosPagina";
import Inicio, { saudacao, type PainelInicio } from "./Inicio";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

const USUARIO = { id: 1, nome: "Leonardo Praeiro", email: "leonardo@lotufo.com", perfil: "admin" };

const MESES_12 = ["2025-11", "2025-12", "2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08",
  "2026-09", "2026-10"];
const RECEBIDO: Record<string, number> = { "2025-11": 120_000_000, "2026-03": 35_000_000, "2026-09": 240_000_000, "2026-10": 60_000_050 };

// #659: as 12 competencias da matriz terminam no mes anterior ao de hoje
const MESES_MATRIZ = ["2025-10", ...MESES_12.slice(0, 11)];
type Celula = PainelInicio["matriz"]["grupos"][number]["obras"][number]["celulas"][number];
const celulas = (ultimas: Celula[]): Celula[] => [...Array<Celula>(12 - ultimas.length).fill(null), ...ultimas];

const painel = (extra: Partial<PainelInicio> = {}): PainelInicio => ({
  hoje: "2026-10-09",
  notas_a_enviar: 3,
  certidoes: { vencidas: 1, vencendo: 1, itens: [] },
  reajustes: [],
  protocoladas: { obras_protocoladas: 2, obras_ativas: 18, ultima: "2026-09-30" },
  medido: { competencia: "2026-09", valor_centavos: 1_827_715_696, quantidade: 2, ultimo_lancamento: "2026-10-08" },
  recebido_ano: { valor_centavos: null, mes_centavos: 0, sem_data: 12, real_centavos: 18_785_640_866 },
  a_receber: { liberado: true, valor_centavos: 1_720_000_000, mais_60_centavos: 210_000_000 },
  prazos: [],
  espelhos: [{ espelho_id: 1, contrato_id: 7, medicao_id: 9, obra: "Obra A", titulo: "1ª Medição", situacao: "aprovado_mudou" }],
  ciclo: [
    { etapa: "em_analise", valor_centavos: 300_100, quantidade: 2, mais_antigo_dias: 20 },
    { etapa: "boletim", valor_centavos: 1_200_300, quantidade: 3, mais_antigo_dias: 1 },
    { etapa: "nota", valor_centavos: 600_100, quantidade: 1, mais_antigo_dias: 0 },
    { etapa: "protocolado", valor_centavos: 1_586_677_904, quantidade: 6, mais_antigo_dias: 100 },
    { etapa: "recebido_mes", valor_centavos: 12_000_200, quantidade: 2, mais_antigo_dias: null },
  ],
  recebido_12m: MESES_12.map(mes => ({ mes, valor_centavos: RECEBIDO[mes] ?? 0 })),
  previsao: {
    neste_mes: { valor_centavos: 500_000, quantidade: 2 },
    proximo_mes: { valor_centavos: 900_001, quantidade: 1 },
    atrasado: { valor_centavos: 800_100, quantidade: 2 },
    sem_previsao: { valor_centavos: 0, quantidade: 0 },
    depois: { valor_centavos: 1_584_477_803, quantidade: 1 },     // as cinco somam a etapa "Protocolado" do ciclo
  },
  matriz: {
    competencias: MESES_MATRIZ,
    grupos: [
      { contratante: "Contratante A", obras: [
        { contrato_id: 7, obra: "Obra A", celulas: celulas([{ etapa: "recebida", medicao_id: 81 }, { etapa: "atrasado", medicao_id: 82 },
          { etapa: "protocolado", medicao_id: 83 }, { etapa: "em_analise", medicao_id: 84 }]) },
        { contrato_id: 8, obra: "Obra B", celulas: celulas([{ etapa: "nota", medicao_id: 91 }, null, { etapa: "boletim", medicao_id: 92 }]) }] },
      { contratante: "Contratante B", obras: [{ contrato_id: 9, obra: "Obra C", celulas: celulas([]) }] },
    ],
  },
  notas_mes: { mes: "2026-10", valor_centavos: 1_522_295_618, notas: 5, obras: 2 },
  ...extra,
});

/** O texto do elemento com espaco simples no lugar do espaco inseparavel do valor em reais. */
const limpo = (el: Element | null | undefined) => (el?.textContent ?? "").replace(/\s/g, " ");

const CICLO = "Ciclo da medição (cota da Lotufo)";

describe("Início", () => {
  afterEach(() => { cleanup(); api.mockReset(); });

  it("faixa do ciclo: cinco etapas na ordem, cada uma com valor, quantidade e idade do mais antigo", async () => {
    api.mockResolvedValue(painel());
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    expect(api).toHaveBeenCalledWith("/api/inicio/painel");
    expect(screen.getByRole("heading", { level: 1 }).textContent).toMatch(/, Leonardo$/);
    const regiao = await screen.findByRole("region", { name: CICLO });
    const etapas = [...regiao.querySelectorAll(".ini-faixa__etapa")];
    expect(etapas.map(e => [...e.children].map(limpo))).toEqual([
      ["Em análise", "R$ 3.001,00", "2 medições", "mais antiga há 20 dias"],
      ["Boletim", "R$ 12.003,00", "3 medições", "mais antiga há 1 dia"],
      ["Nota", "R$ 6.001,00", "1 medição", "mais antiga de hoje"],
      ["Protocolado", "R$ 15.866.779,04", "6 medições", "mais antiga há 100 dias"],
      ["Recebido no mês", "R$ 120.002,00", "2 notas"],          // sem idade
    ]);
    // cor da informacao: as quatro etapas abertas em andamento (azul); o recebido, feito (verde)
    expect(etapas.map(e => e.className.replace("ini-faixa__etapa ", ""))).toEqual(
      [...Array<string>(4).fill("ini-faixa__etapa--andamento"), "ini-faixa__etapa--feito"]);
    expect(screen.getByRole("list", { name: "Legenda das cores" })).toBeTruthy();
  });

  it("faixa do ciclo: tabela equivalente para leitor de tela", async () => {
    api.mockResolvedValue(painel());
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    const regiao = await screen.findByRole("region", { name: CICLO });
    const tabela = within(regiao).getByRole("table", { name: "Ciclo da medição por etapa, na cota da Lotufo" });
    // PR #676: `sr-only` na propria <table> nao recorta (tabela ignora largura e overflow) e a pagina ganhava rolagem
    // horizontal no celular; quem recorta e' o div em volta
    expect(tabela.className).toBe("");
    expect(tabela.parentElement?.tagName).toBe("DIV");
    expect(tabela.parentElement?.className).toBe("sr-only");
    expect(regiao.querySelector("table.sr-only")).toBeNull();
    expect(regiao.querySelector(".ini-faixa")?.getAttribute("aria-hidden")).toBe("true");
    const linhas = within(tabela).getAllByRole("row").map(l => [...l.children].map(limpo));
    expect(linhas).toEqual([
      ["Etapa", "Valor", "Quantidade", "Mais antiga"],
      ["Em análise", "R$ 3.001,00", "2 medições", "20 dias"],
      ["Boletim", "R$ 12.003,00", "3 medições", "1 dia"],
      ["Nota", "R$ 6.001,00", "1 medição", "0 dias"],
      ["Protocolado", "R$ 15.866.779,04", "6 medições", "100 dias"],
      ["Recebido no mês", "R$ 120.002,00", "2 notas", "—"],
    ]);
  });

  it("faixa do ciclo: largura de cada trecho proporcional ao valor, com mínimo; etapa vazia não mostra idade", async () => {
    api.mockResolvedValue(painel({ ciclo: [
      { etapa: "em_analise", valor_centavos: 0, quantidade: 0, mais_antigo_dias: null },
      { etapa: "boletim", valor_centavos: 100, quantidade: 1, mais_antigo_dias: 3 },
      { etapa: "nota", valor_centavos: 0, quantidade: 0, mais_antigo_dias: null },
      { etapa: "protocolado", valor_centavos: 300, quantidade: 1, mais_antigo_dias: 9 },
      { etapa: "recebido_mes", valor_centavos: 0, quantidade: 0, mais_antigo_dias: null },
    ] }));
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    const regiao = await screen.findByRole("region", { name: CICLO });
    const faixa = regiao.querySelector<HTMLElement>(".ini-faixa");
    // o minimo de cada trecho e' o proprio valor numa linha (`min-content`); a proporcao vale para o que sobra
    const m = "minmax(min-content, ";
    expect(faixa?.style.getPropertyValue("--ini-faixa-colunas")).toBe(`${m}0fr) ${m}25fr) ${m}0fr) ${m}75fr) ${m}0fr)`);
    expect([...(regiao.querySelector(".ini-faixa__etapa")?.children ?? [])].map(limpo)).toEqual(["Em análise", "R$ 0,00", "0 medições"]);
  });

  it("faixa do ciclo sem nenhum valor: os cinco trechos com a mesma largura", async () => {
    api.mockResolvedValue(painel({ ciclo: painel().ciclo.map(e => ({ ...e, valor_centavos: 0, quantidade: 0, mais_antigo_dias: null })) }));
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    const regiao = await screen.findByRole("region", { name: CICLO });
    expect(regiao.querySelector<HTMLElement>(".ini-faixa")?.style.getPropertyValue("--ini-faixa-colunas"))
      .toBe(Array<string>(5).fill("minmax(min-content, 1fr)").join(" "));
  });

  it("#652: recebido em 12 meses, uma barra por mês até o mês corrente, com a altura proporcional ao maior", async () => {
    api.mockResolvedValue(painel());
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    const regiao = await screen.findByRole("region", { name: "Recebido em 12 meses (cota da Lotufo)" });
    const meses = [...regiao.querySelectorAll<HTMLElement>(".ini-rec__mes")];
    expect(meses.map(m => limpo(m.querySelector(".ini-rec__rotulo")))).toEqual(
      ["nov/25", "dez/25", "jan/26", "fev/26", "mar/26", "abr/26", "mai/26", "jun/26", "jul/26", "ago/26", "set/26", "out/26"]);
    expect(meses.map(m => limpo(m.querySelector(".ini-rec__valor")))).toEqual(
      ["1,2 mi", "—", "—", "—", "350 mil", "—", "—", "—", "—", "—", "2,4 mi", "600 mil"]);
    expect(meses.map(m => m.style.getPropertyValue("--ini-rec-tamanho"))).toEqual(
      ["50%", "0%", "0%", "0%", "15%", "0%", "0%", "0%", "0%", "0%", "100%", "25%"]);
    expect(regiao.querySelector(".ini-rec")?.getAttribute("aria-hidden")).toBe("true");
  });

  it("#652: recebido em 12 meses tem a tabela equivalente, dentro de um div sr-only", async () => {
    api.mockResolvedValue(painel());
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    const regiao = await screen.findByRole("region", { name: "Recebido em 12 meses (cota da Lotufo)" });
    const tabela = within(regiao).getByRole("table", { name: "Recebido por mês, na cota da Lotufo" });
    expect(tabela.className).toBe("");
    expect(tabela.parentElement?.tagName).toBe("DIV");
    expect(tabela.parentElement?.className).toBe("sr-only");
    const linhas = within(tabela).getAllByRole("row").map(l => [...l.children].map(limpo));
    expect(linhas).toHaveLength(13);
    expect(linhas[0]).toEqual(["Mês", "Recebido"]);
    expect(linhas[1]).toEqual(["11/2025", "R$ 1.200.000,00"]);
    expect(linhas[2]).toEqual(["12/2025", "R$ 0,00"]);
    expect(linhas[12]).toEqual(["10/2026", "R$ 600.000,50"]);
  });

  it("#652: recebido em 12 meses sem nenhuma baixa não divide por zero", async () => {
    api.mockResolvedValue(painel({ recebido_12m: MESES_12.map(mes => ({ mes, valor_centavos: 0 })) }));
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    const regiao = await screen.findByRole("region", { name: "Recebido em 12 meses (cota da Lotufo)" });
    expect([...regiao.querySelectorAll<HTMLElement>(".ini-rec__mes")].map(m => m.style.getPropertyValue("--ini-rec-tamanho")))
      .toEqual(Array<string>(12).fill("0%"));
  });

  it("#652: previsão de entrada com as cinco linhas, valor e quantidade; só o atrasado com valor fica vermelho", async () => {
    api.mockResolvedValue(painel());
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    const regiao = await screen.findByRole("region", { name: "Previsão de entrada (cota da Lotufo)" });
    const linhas = within(regiao).getAllByRole("listitem");
    expect(linhas.map(l => [...l.children].map(limpo))).toEqual([
      ["Neste mês", "R$ 5.000,00", "2 medições"],
      ["No próximo mês", "R$ 9.000,01", "1 medição"],
      ["Depois", "R$ 15.844.778,03", "1 medição"],
      ["Atrasado", "R$ 8.001,00", "2 medições"],
      ["Sem previsão", "R$ 0,00", "0 medições"],
    ]);
    expect(linhas.map(l => l.className.includes("--critico"))).toEqual([false, false, false, true, false]);
  });

  it("#652: as cinco linhas da previsão fecham com a etapa Protocolado da faixa do ciclo, em quantidade e valor", async () => {
    api.mockResolvedValue(painel());
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    const regiao = await screen.findByRole("region", { name: "Previsão de entrada (cota da Lotufo)" });
    const centavos = (t: string) => Number(t.replace(/\D/g, ""));
    const linhas = within(regiao).getAllByRole("listitem").map(l => [...l.children].map(limpo));
    expect(linhas).toHaveLength(5);
    const protocolado = [...document.querySelectorAll(".ini-faixa__etapa")].map(e => [...e.children].map(limpo))
      .find(e => e[0] === "Protocolado");
    expect(linhas.reduce((s, l) => s + parseInt(l[2] ?? "", 10), 0)).toBe(parseInt(protocolado?.[2] ?? "", 10));
    expect(linhas.reduce((s, l) => s + centavos(l[1] ?? ""), 0)).toBe(centavos(protocolado?.[1] ?? ""));
  });

  it("#652: linha da previsão sem medição continua no lugar, zerada", async () => {
    const zero = { valor_centavos: 0, quantidade: 0 };
    api.mockResolvedValue(painel({ previsao: { neste_mes: zero, proximo_mes: zero, atrasado: zero, sem_previsao: zero, depois: zero } }));
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    const regiao = await screen.findByRole("region", { name: "Previsão de entrada (cota da Lotufo)" });
    expect(within(regiao).getAllByRole("listitem").map(l => [...l.children].map(limpo))).toEqual(
      ["Neste mês", "No próximo mês", "Depois", "Atrasado", "Sem previsão"].map(r => [r, "R$ 0,00", "0 medições"]));
  });

  it("#652: sem medição atrasada a linha Atrasado fica na cor padrão", async () => {
    api.mockResolvedValue(painel({ previsao: { ...painel().previsao, atrasado: { valor_centavos: 0, quantidade: 0 } } }));
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    const regiao = await screen.findByRole("region", { name: "Previsão de entrada (cota da Lotufo)" });
    expect(regiao.querySelector("[class*='--critico']")).toBeNull();
  });

  const MATRIZ = "Medições por obra e competência";

  it("#659: matriz com uma linha por obra, agrupada por contratante, 12 competências e a legenda das etapas", async () => {
    api.mockResolvedValue(painel());
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    const regiao = await screen.findByRole("region", { name: MATRIZ });
    const legenda = within(regiao).getByRole("list", { name: "Legenda das etapas" });
    expect([...legenda.children].map(li => [limpo(li), li.querySelector("span")?.className])).toEqual([
      ["Em análise", "ini-matriz__cor ini-matriz__cor--em_analise"], ["Boletim", "ini-matriz__cor ini-matriz__cor--boletim"],
      ["Nota", "ini-matriz__cor ini-matriz__cor--nota"], ["Protocolado", "ini-matriz__cor ini-matriz__cor--protocolado"],
      ["Recebido", "ini-matriz__cor ini-matriz__cor--recebida"], ["Atrasado", "ini-matriz__cor ini-matriz__cor--atrasado"]]);
    // o cabecalho: o mes em cada coluna; o ano so' na primeira e em janeiro
    expect([...regiao.querySelectorAll(".ini-matriz__mes")].map(m => [...m.children].map(limpo).join(" "))).toEqual(
      ["out 25", "nov", "dez", "jan 26", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set"]);
    expect(within(regiao).getAllByRole("heading", { level: 3 }).map(limpo)).toEqual(["Contratante A", "Contratante B"]);
    const linhas = [...regiao.querySelectorAll(".ini-matriz__linha--obra")];
    expect(linhas.map(l => limpo(l.querySelector(".ini-matriz__obra")))).toEqual(["Obra A", "Obra B", "Obra C"]);
    expect(linhas.map(l => l.querySelectorAll(".ini-matriz__celula").length)).toEqual([12, 12, 12]);
  });

  it("#659: cada célula pintada tem a cor da etapa, nome acessível e é um link para a medição; a vazia não", async () => {
    api.mockResolvedValue(painel());
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    const regiao = await screen.findByRole("region", { name: MATRIZ });
    const links = within(regiao).getAllByRole("link");
    expect(links.map(a => [a.getAttribute("aria-label"), a.getAttribute("href"), a.className.replace("ini-matriz__celula ", "")])).toEqual([
      ["Obra A, 06/2026: Recebido", "/obras/7/medicoes/81", "ini-matriz__celula--recebida"],
      ["Obra A, 07/2026: Atrasado", "/obras/7/medicoes/82", "ini-matriz__celula--atrasado"],
      ["Obra A, 08/2026: Protocolado", "/obras/7/medicoes/83", "ini-matriz__celula--protocolado"],
      ["Obra A, 09/2026: Em análise", "/obras/7/medicoes/84", "ini-matriz__celula--em_analise"],
      ["Obra B, 07/2026: Nota", "/obras/8/medicoes/91", "ini-matriz__celula--nota"],
      ["Obra B, 09/2026: Boletim", "/obras/8/medicoes/92", "ini-matriz__celula--boletim"],
    ]);
    expect(links.every(a => a.getAttribute("title") === a.getAttribute("aria-label"))).toBe(true);
    const vazias = [...regiao.querySelectorAll(".ini-matriz__celula:not(a)")];
    expect(vazias).toHaveLength(36 - 6);
    expect(vazias.every(v => v.className === "ini-matriz__celula" && v.getAttribute("aria-hidden") === "true")).toBe(true);
  });

  it("#659: matriz tem a tabela equivalente, dentro de um div sr-only", async () => {
    api.mockResolvedValue(painel());
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    const regiao = await screen.findByRole("region", { name: MATRIZ });
    const tabela = within(regiao).getByRole("table", { name: "Etapa da medição de cada obra por competência" });
    expect(tabela.className).toBe("");
    expect(tabela.parentElement?.tagName).toBe("DIV");
    expect(tabela.parentElement?.className).toBe("sr-only");
    expect(regiao.querySelector("table.sr-only")).toBeNull();
    const t = "—";
    expect(within(tabela).getAllByRole("row").map(l => [...l.children].map(limpo))).toEqual([
      ["Obra", "Contratante", "10/2025", "11/2025", "12/2025", "01/2026", "02/2026", "03/2026", "04/2026", "05/2026", "06/2026",
        "07/2026", "08/2026", "09/2026"],
      ["Obra A", "Contratante A", t, t, t, t, t, t, t, t, "Recebido", "Atrasado", "Protocolado", "Em análise"],
      ["Obra B", "Contratante A", t, t, t, t, t, t, t, t, t, "Nota", t, "Boletim"],
      ["Obra C", "Contratante B", t, t, t, t, t, t, t, t, t, t, t, t],
    ]);
  });

  it("#659: sem obra ativa, uma linha curta no lugar da matriz", async () => {
    api.mockResolvedValue(painel({ matriz: { competencias: MESES_MATRIZ, grupos: [] } }));
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    const regiao = await screen.findByRole("region", { name: MATRIZ });
    expect(within(regiao).getByText("Nenhuma obra ativa.")).toBeTruthy();
    expect(regiao.querySelector(".ini-matriz__grade, table")).toBeNull();
  });

  it("dois cartões só com rótulo e valor: notas protocoladas e medido do mês (#652: o recebido no ano virou as barras)", async () => {
    api.mockResolvedValue(painel());
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    const regiao = await screen.findByRole("region", { name: "Números do mês" });
    expect([...regiao.children].map(c => [...c.children].map(limpo))).toEqual([
      ["Notas fiscais protocoladas em outubro", "R$ 15.222.956,18"],
      ["Medido em setembro", "R$ 18.277.156,96"],
    ]);
    expect(document.body.textContent).not.toContain("Recebido em 2026");
  });

  it("#642: saíram a curva diária, a variação, as barras por contratante, a barra verde e o selo de mês fechado", async () => {
    api.mockResolvedValue(painel());
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    await screen.findByRole("region", { name: "Números do mês" });
    expect(screen.queryByRole("region", { name: "Medições protocoladas" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Medido por contratante" })).toBeNull();
    expect(screen.queryByRole("img")).toBeNull();
    expect(document.querySelector(".ini-mini, .ini-grafico, .ini-barra, .ini-barras, .ini-variacao")).toBeNull();
    const tudo = document.body.textContent ?? "";
    for (const velho of ["mesmo período", "mês fechado", "vs.", "%", "Medido por contratante", "até dia"])
      expect(tudo).not.toContain(velho);
  });

  it("os cartões e a tabela antigos não existem mais", async () => {
    api.mockResolvedValue(painel());
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    await screen.findByRole("region", { name: "Números do mês" });
    expect(screen.queryByRole("region", { name: "O que fazer agora" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Prazos chegando" })).toBeNull();
    const tudo = document.body.textContent ?? "";
    for (const velho of ["notas a enviar", "espelho a conferir", "espelhos a conferir", "A receber", "Obras protocoladas em", "Prazos chegando"])
      expect(tudo).not.toContain(velho);
  });

  // #666: a caixa le a MESMA fila da tela Avisos (GET /api/inicio) e aplica a mesma regra de secao (`avisos.ts`)
  const aviso = (extra: Partial<Aviso> = {}): Aviso => ({
    tipo: "execucao_vencendo", nivel: "atencao", publico: ["operacao"], contrato_id: 7, obra: "Obra A", dias: 20,
    valor_centavos: null, mensagem: "Obra A: execução termina", destino: { tela: "contrato", id: 7, aba: "prazos" },
    data: "2026-10-29", sentido: "prazo", ...extra });
  const FILA: Aviso[] = [
    aviso({ obra: "Obra B", contrato_id: 8, mensagem: "Obra B: execução vencida", dias: -450, data: "2025-07-16",
      destino: { tela: "contrato", id: 8, aba: "prazos" } }),
    aviso({ obra: "Obra C", contrato_id: 9, tipo: "nota_parada", mensagem: "Obra C: nota sem envio", dias: 12, data: "2026-09-27", sentido: "desde",
      destino: { tela: "contrato", id: 9, aba: "notas" }, medicao_id: 31 }),
    aviso({ obra: null, contrato_id: null, tipo: "certidao_vencendo", entidade_id: 4, entidade: "Empresa X", mensagem: "Empresa X: FGTS vence",
      dias: 0, data: "2026-10-09", destino: { tela: "documentos" } }),
    aviso({ obra: "Obra A", mensagem: "Obra A: vigência termina", dias: 5, data: "2026-10-14" }),
    aviso({ obra: "Obra A", mensagem: "Obra A: execução termina", dias: 20 }),
    aviso({ obra: "Obra D", contrato_id: 10, dias: 60, data: "2026-12-08" }),                       // Depois: fora da caixa
    aviso({ obra: "Obra E", contrato_id: 11, dias: 120, data: "2027-02-06" }),                      // além de 90 dias
    aviso({ obra: "Obra F", contrato_id: 12, tipo: "nota_divergente", mensagem: "Obra F: nota divergente", dias: null, data: null, sentido: null }),
  ];
  const servir = (fila: Aviso[] | Error = FILA) => api.mockImplementation(async (caminho: string) => {
    if (caminho !== "/api/inicio") return painel();
    if (fila instanceof Error) throw fila;
    return { avisos: fila, resumo: {} };
  });
  const linhasDe = (secao: HTMLElement) => within(secao).queryAllByRole("link").map(l => [...l.children].map(limpo));

  it("#666: avisos em três seções pelo tempo (Vencido, Esta semana, Este mês), com a contagem, os itens e o selo de dias", async () => {
    servir();
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    const caixa = within(await screen.findByRole("complementary", { name: "Avisos importantes" }));
    expect(api).toHaveBeenCalledWith("/api/inicio");
    await caixa.findByRole("region", { name: "Vencido" });
    expect(caixa.getAllByRole("heading", { level: 3 }).map(limpo)).toEqual(["Vencido", "Esta semana", "Este mês"]);
    const vencido = caixa.getByRole("region", { name: "Vencido" });
    // o mais antigo primeiro; o fato parado "desde" 12 dias é passado
    expect(linhasDe(vencido)).toEqual([["Obra B · execução vencida", "há 450 dias"], ["Obra C · nota sem envio", "há 12 dias"]]);
    expect(within(vencido).getByText("há 450 dias").className).toContain("ini-pilula--acao");
    const semana = caixa.getByRole("region", { name: "Esta semana" });
    expect(linhasDe(semana)).toEqual([["Empresa X · FGTS vence", "hoje"], ["Obra A · vigência termina", "em 5 dias"]]);
    expect(within(semana).getByText("em 5 dias").className).toContain("ini-pilula--atencao");
    const mes = caixa.getByRole("region", { name: "Este mês" });
    expect(linhasDe(mes)).toEqual([["Obra A · execução termina", "em 20 dias"]]);
    expect([vencido, semana, mes].map(s => limpo(s.querySelector(".ini-aviso__conta")))).toEqual(["2", "2", "1"]);
    // cada item leva ao lugar do aviso, como na tela Avisos
    expect(within(vencido).getAllByRole("link").map(l => l.getAttribute("href"))).toEqual(["/obras/8/prazos", "/obras/9/medicoes/31#notas"]);
    expect(within(semana).getAllByRole("link")[0]?.getAttribute("href")).toBe("/documentos/4");
  });

  it("#666: a contagem da caixa é a soma de Vencido, Esta semana e Este mês da tela Avisos, com a mesma fila", async () => {
    servir();
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    const caixa = await screen.findByRole("complementary", { name: "Avisos importantes" });
    await within(caixa).findByRole("region", { name: "Vencido" });
    const total = limpo(caixa.querySelector(".ini-avisos__total"));
    cleanup();
    render(<AvisosPagina busca={{}} avisos={FILA} nome="Todas as obras" onFechar={() => {}} />);
    const naTela = screen.getAllByRole("heading", { level: 3 }).map(limpo);
    expect(naTela).toEqual(["VENCIDO · 2", "ESTA SEMANA · 2", "ESTE MÊS · 1", "DEPOIS · 1"]);
    expect(total).toBe(String(2 + 2 + 1));
  });

  it("#666: aviso sem data, além de 90 dias ou da seção Depois não conta nem aparece na caixa", async () => {
    servir();
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    const caixa = await screen.findByRole("complementary", { name: "Avisos importantes" });
    await within(caixa).findByRole("region", { name: "Vencido" });
    expect(caixa.textContent).not.toMatch(/Obra D|Obra E|Obra F|Depois|Sem data/);
    expect(within(caixa).queryByRole("region", { name: "Depois" })).toBeNull();
  });

  it("#666: cada seção mostra os três primeiros itens; a contagem é de todos", async () => {
    servir([1, 2, 3, 4, 5].map(n => aviso({ obra: `Obra ${n}`, contrato_id: n, mensagem: `Obra ${n}: execução vencida`, dias: -n, data: `2026-10-0${9 - n}` })));
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    const caixa = within(await screen.findByRole("complementary", { name: "Avisos importantes" }));
    const vencido = await caixa.findByRole("region", { name: "Vencido" });
    expect(linhasDe(vencido).map(l => l[0])).toEqual(["Obra 5 · execução vencida", "Obra 4 · execução vencida", "Obra 3 · execução vencida"]);
    expect(limpo(vencido.querySelector(".ini-aviso__conta"))).toBe("5");
    expect(limpo(document.querySelector(".ini-avisos__total"))).toBe("5");
    // seção sem aviso: a contagem zero, sem lista
    const semana = caixa.getByRole("region", { name: "Esta semana" });
    expect(limpo(semana.querySelector(".ini-aviso__conta"))).toBe("0");
    expect(semana.querySelector("ul")).toBeNull();
  });

  it("#666: Ver todos abre a tela Avisos, sem filtro de categoria; as seções por assunto saíram", async () => {
    servir();
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    const caixa = within(await screen.findByRole("complementary", { name: "Avisos importantes" }));
    await caixa.findByRole("region", { name: "Vencido" });
    expect(caixa.getAllByRole("link", { name: "Ver todos os avisos" }).map(l => l.getAttribute("href"))).toEqual(["/avisos"]);
    for (const velha of ["Reajustes", "Prazos", "Certidões"]) expect(caixa.queryByRole("region", { name: velha })).toBeNull();
  });

  it("#666: fila sem aviso na agenda mostra uma linha curta; falha ao ler a fila vira erro na caixa, sem derrubar a página", async () => {
    servir([]);
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    const caixa = within(await screen.findByRole("complementary", { name: "Avisos importantes" }));
    expect(await caixa.findByText("Nenhum aviso.")).toBeTruthy();
    expect(limpo(document.querySelector(".ini-avisos__total"))).toBe("0");
    expect(caixa.queryByRole("region")).toBeNull();
    cleanup();
    servir(new Error("falhou"));
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    const comErro = within(await screen.findByRole("complementary", { name: "Avisos importantes" }));
    expect((await comErro.findByRole("alert")).textContent).toBe("Não foi possível verificar os avisos. Recarregue a página para tentar de novo.");
    expect(screen.getByRole("region", { name: "Números do mês" })).toBeTruthy();
  });

  it("saudação pela hora de Cuiabá", () => {
    expect(saudacao(new Date("2026-10-09T13:00:00Z"))).toBe("Bom dia");        // 09h em Cuiabá
    expect(saudacao(new Date("2026-10-09T17:00:00Z"))).toBe("Boa tarde");      // 13h
    expect(saudacao(new Date("2026-10-10T01:00:00Z"))).toBe("Boa noite");      // 21h
  });
});
