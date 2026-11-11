import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Inicio, { saudacao, type PainelInicio } from "./Inicio";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

const USUARIO = { id: 1, nome: "Leonardo Praeiro", email: "leonardo@lotufo.com", perfil: "admin" };

const MESES_12 = ["2025-11", "2025-12", "2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08",
  "2026-09", "2026-10"];
const RECEBIDO: Record<string, number> = { "2025-11": 120_000_000, "2026-03": 35_000_000, "2026-09": 240_000_000, "2026-10": 60_000_050 };

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
  notas_mes: { mes: "2026-10", valor_centavos: 1_522_295_618, notas: 5, obras: 2 },
  avisos_importantes: {
    reajustes: { total: 9, itens: [{ contrato_id: 9, obra: "Cultural", dias: null, tipo: "reajuste_nota_antes_do_apostilamento", nivel: "critico",
        competencias: ["2026-07", "2026-08", "2026-09"], datas_base: ["2024-06"] },
      { contrato_id: 7, obra: "MT-388", dias: -3, tipo: "reajuste_pleito", nivel: "acao" }, { contrato_id: 8, obra: "Leblon", dias: 4 }] },
    prazos: { total: 6, itens: [{ contrato_id: 3, obra: "Coxipó 3ª Etapa", tipo: "execucao", dias: -450 },
                                { contrato_id: 4, obra: "Deciolândia", tipo: "vigencia", dias: 20 }] },
    certidoes: { total: 11, itens: [
      { tipo: "FGTS", entidade: "Integra BRT", validade: "2026-10-14", dias: 5, vencida: false },
      { tipo: "Estadual", entidade: "Montante", validade: "2026-10-09", dias: 0, vencida: false },
      { tipo: "FGTS", entidade: "Encomind", validade: "2026-10-01", dias: -8, vencida: true }] },
  },
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
    const m = "minmax(var(--ini-faixa-min), ";
    expect(faixa?.style.getPropertyValue("--ini-faixa-colunas")).toBe(`${m}0fr) ${m}25fr) ${m}0fr) ${m}75fr) ${m}0fr)`);
    expect([...(regiao.querySelector(".ini-faixa__etapa")?.children ?? [])].map(limpo)).toEqual(["Em análise", "R$ 0,00", "0 medições"]);
  });

  it("faixa do ciclo sem nenhum valor: os cinco trechos com a mesma largura", async () => {
    api.mockResolvedValue(painel({ ciclo: painel().ciclo.map(e => ({ ...e, valor_centavos: 0, quantidade: 0, mais_antigo_dias: null })) }));
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    const regiao = await screen.findByRole("region", { name: CICLO });
    expect(regiao.querySelector<HTMLElement>(".ini-faixa")?.style.getPropertyValue("--ini-faixa-colunas"))
      .toBe(Array<string>(5).fill("minmax(var(--ini-faixa-min), 1fr)").join(" "));
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

  it("avisos importantes: três seções com contagem, itens e Ver todos levando à tela Avisos com a categoria", async () => {
    api.mockResolvedValue(painel());
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    const caixa = within(await screen.findByRole("complementary", { name: "Avisos importantes" }));
    const reaj = within(caixa.getByRole("region", { name: "Reajustes" }));
    expect(reaj.getByText("9")).toBeTruthy();
    expect(reaj.getByText("MT-388 · reajuste a pedir")).toBeTruthy();
    // issue #274: os avisos do motor de apostilamento entram na secao, cada um com o que diz
    expect(reaj.getByText("Cultural · nota antes do apostilamento (3 competências)")).toBeTruthy();
    expect(reaj.getByText("Leblon · reajuste a pedir")).toBeTruthy();
    const prazos = within(caixa.getByRole("region", { name: "Prazos" }));
    expect(prazos.getByText("vencido há 450 dias").className).toContain("ini-pilula--acao");
    expect(prazos.getByText("faltam 20 dias").className).toContain("ini-pilula--atencao");
    const cert = within(caixa.getByRole("region", { name: "Certidões" }));
    expect(cert.getByText("vence em 5 dias").className).toContain("ini-pilula--atencao");
    expect(cert.getByText("vence hoje")).toBeTruthy();
    expect(cert.getByText("vencido há 8 dias").className).toContain("ini-pilula--acao");
    expect(cert.getByText("FGTS · Integra BRT")).toBeTruthy();
    const hrefs = ["Reajustes", "Prazos", "Certidões"].map(
      t => caixa.getByRole("link", { name: `Ver todos: ${t}` }).getAttribute("href"));
    expect(hrefs).toEqual(["/avisos?familia=reajustes", "/avisos?familia=prazos", "/avisos?familia=certidoes"]);
  });

  it("seção Reajustes: detalhe do item com uma data-base, várias datas-base e várias competências", async () => {
    api.mockResolvedValue(painel({ avisos_importantes: { ...painel().avisos_importantes, reajustes: { total: 3, itens: [
      { contrato_id: 1, obra: "Alfa", dias: null, tipo: "reajuste_sem_resposta", nivel: "acao", competencias: ["2026-07"] },
      { contrato_id: 2, obra: "Beta", dias: null, tipo: "reajuste_sem_resposta", nivel: "acao", datas_base: ["2024-06", "2025-03"] },
      { contrato_id: 3, obra: "Gama", dias: null, tipo: "reajuste_sem_resposta", nivel: "acao", datas_base: ["2024-06"] }] } } }));
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    const caixa = within(await screen.findByRole("complementary", { name: "Avisos importantes" }));
    const reaj = within(caixa.getByRole("region", { name: "Reajustes" }));
    expect(reaj.getByText("Alfa · pedido de reajuste sem resposta (07/2026)")).toBeTruthy();
    expect(reaj.getByText("Beta · pedido de reajuste sem resposta (2 datas-base)")).toBeTruthy();
    expect(reaj.getByText("Gama · pedido de reajuste sem resposta")).toBeTruthy();
    expect(reaj.getByText("3")).toBeTruthy();
  });

  it("seção de avisos sem item mostra uma linha curta no lugar da lista", async () => {
    api.mockResolvedValue(painel({ avisos_importantes: {
      reajustes: { total: 0, itens: [] }, prazos: { total: 0, itens: [] }, certidoes: { total: 0, itens: [] } } }));
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    await screen.findByRole("complementary", { name: "Avisos importantes" });
    expect(screen.getByText("Nenhum aviso de reajuste.")).toBeTruthy();
    expect(screen.getByText("Nenhuma certidão vencendo.")).toBeTruthy();
  });

  it("saudação pela hora de Cuiabá", () => {
    expect(saudacao(new Date("2026-10-09T13:00:00Z"))).toBe("Bom dia");        // 09h em Cuiabá
    expect(saudacao(new Date("2026-10-09T17:00:00Z"))).toBe("Boa tarde");      // 13h
    expect(saudacao(new Date("2026-10-10T01:00:00Z"))).toBe("Boa noite");      // 21h
  });
});
