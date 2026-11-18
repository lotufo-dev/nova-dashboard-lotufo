import { act, cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Aviso } from "./Alertas";
import AvisosPagina from "./AvisosPagina";
import Inicio, { saudacao, type PainelInicio } from "./Inicio";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

const USUARIO = { id: 1, nome: "Admin Exemplo", email: "admin@exemplo.com.br", perfil: "admin" };

const MESES_12 = ["2025-11", "2025-12", "2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08",
  "2026-09", "2026-10"];
const RECEBIDO: Record<string, number> = { "2025-11": 120_000_000, "2026-03": 35_000_000, "2026-09": 240_000_000, "2026-10": 60_000_050 };

// #659: as 12 competencias da matriz terminam no mes anterior ao de hoje
const MESES_MATRIZ = ["2025-10", ...MESES_12.slice(0, 11)];
type Celula = PainelInicio["matriz"]["grupos"][number]["obras"][number]["celulas"][number];
const celulas = (ultimas: Celula[]): Celula[] => [...Array<Celula>(12 - ultimas.length).fill(null), ...ultimas];

const painel = (extra: Partial<PainelInicio> = {}): PainelInicio => ({
  hoje: "2026-10-09",
  protocoladas: { obras_protocoladas: 2, obras_ativas: 18, ultima: "2026-09-30" },
  medido: { competencia: "2026-09", valor_centavos: 1_827_715_696, quantidade: 2, ultimo_lancamento: "2026-10-08",
    anterior: null, ano_anterior: null },
  a_receber: { liberado: true, valor_centavos: 1_720_000_000, mais_60_centavos: 210_000_000,
    a_parte: { ano_inicial: "2025", valor_centavos: 0, anterior_centavos: 0, sem_atualizacao_centavos: 0, sem_atualizacao_desde: null } },
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
  notas_mes: { mes: "2026-10", valor_centavos: 1_522_295_618, notas: 5, obras: 2, anterior: null },
  ...extra,
});

/** O texto do elemento com espaco simples no lugar do espaco inseparavel do valor em reais. */
const limpo = (el: Element | null | undefined) => (el?.textContent ?? "").replace(/\s/g, " ");

// #721: a base ("cota da Lotufo") saiu do titulo de cada painel e e' dita uma vez, no titulo do grupo
const CICLO = "Ciclo da medição";
const REGIAO_RECEBIDO = "Recebido em 12 meses";
const REGIAO_PREVISAO = "Previsão de entrada";

describe("Início", () => {
  afterEach(() => { cleanup(); api.mockReset(); });

  it("ciclo da medição: cinco etapas na ordem, cada uma com valor, quantidade e idade do mais antigo", async () => {
    api.mockResolvedValue(painel());
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    expect(api).toHaveBeenCalledWith("/api/inicio/painel");
    expect(screen.getByRole("heading", { level: 1 }).textContent).toMatch(/, Admin$/);
    const regiao = await screen.findByRole("region", { name: CICLO });
    const etapas = [...regiao.querySelectorAll(".ini-etapa")];
    expect(etapas.map(e => [...e.children].map(limpo))).toEqual([
      ["Em análise", "R$ 3.001,00", "2 medições", "mais antiga há 20 dias"],
      ["Boletim", "R$ 12.003,00", "3 medições", "mais antiga há 1 dia"],
      ["Nota", "R$ 6.001,00", "1 medição", "mais antiga de hoje"],
      ["Protocolado", "R$ 15.866.779,04", "6 medições", "mais antiga há 100 dias"],
      ["Recebido no mês", "R$ 120.002,00", "2 notas"],          // sem idade
    ]);
    // #721: cada etapa tem a cor dela (as quatro abertas, do azul claro ao escuro; o recebido, verde): a classe e' a
    // chave da etapa
    expect(etapas.map(e => e.className.replace("ini-etapa ", ""))).toEqual(
      ["ini-etapa--em_analise", "ini-etapa--boletim", "ini-etapa--nota", "ini-etapa--protocolado", "ini-etapa--recebido_mes"]);
    expect(screen.getByRole("list", { name: "Legenda das cores" })).toBeTruthy();
  });

  it("o em aberto antigo e o sem atualização do RM aparecem numa linha própria, no painel do ciclo, fora das etapas", async () => {
    api.mockResolvedValue(painel({ a_receber: { liberado: true, valor_centavos: 1_461_164_155, mais_60_centavos: 88_504_531,
      a_parte: { ano_inicial: "2025", valor_centavos: 179_846_324, anterior_centavos: 159_906_581,
        sem_atualizacao_centavos: 19_939_743, sem_atualizacao_desde: "2026-09-25" } } }));
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    const ciclo = await screen.findByRole("region", { name: "Ciclo da medição" });
    const bloco = within(ciclo).getByLabelText("Em aberto fora do total");
    expect((bloco.textContent ?? "").replace(/\u00a0/g, " ")).toContain("Em aberto de competências anteriores a 2025R$ 1.599.065,81");
    expect((bloco.textContent ?? "").replace(/\u00a0/g, " ")).toContain("Sem atualização do RM desde 25/09/2026R$ 199.397,43");
    // a etapa "Protocolado" continua com o valor que o servidor mandou: a linha à parte não entra nela
    expect(ciclo.querySelector(".ini-etapa--protocolado .ini-etapa__valor")?.textContent?.replace(/\u00a0/g, " ")).toBe("R$ 15.866.779,04");
  });

  it("sem nada à parte, ou sem o total liberado, o painel do ciclo não ganha linha", async () => {
    api.mockResolvedValue(painel());
    const { unmount } = render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    const ciclo = await screen.findByRole("region", { name: "Ciclo da medição" });
    expect(within(ciclo).queryByLabelText("Em aberto fora do total")).toBeNull();
    unmount();
    api.mockResolvedValue(painel({ a_receber: { liberado: false, valor_centavos: null, mais_60_centavos: null, a_parte: null } }));
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    expect(within(await screen.findByRole("region", { name: "Ciclo da medição" })).queryByLabelText("Em aberto fora do total")).toBeNull();
  });

  it("#721: a tela na ordem montada pelo dono, com a cota dita uma vez, no título do grupo", async () => {
    servir();
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    await screen.findByRole("region", { name: CICLO });
    expect(screen.getAllByRole("heading", { level: 2 }).map(limpo)).toEqual(
      ["Cota da Lotufo", "Ciclo da medição", "Previsão de entrada", "Recebido em 12 meses", "Avisos importantes", "Medições por obra e competência"]);
    // a saudacao com a legenda e os dois numeros do mes vem antes de tudo
    const grade = document.querySelector(".ini-grade")!;
    expect([...grade.children].map(b => b.className)).toEqual(["ini-saudacao", "ini-numeros", "ini-cota", "cartao ini-painel ini-ciclo",
      "cartao ini-painel ini-previsao", "cartao ini-painel ini-recebido", "cartao ini-painel ini-avisos", "cartao ini-painel ini-matriz"]);
    expect(grade.firstElementChild!.querySelector("h1")).not.toBeNull();
    expect(grade.firstElementChild!.querySelector(".legenda-cor")).not.toBeNull();
    // fora do que e' so' de leitor de tela (as legendas das tabelas equivalentes), "cota" aparece uma vez
    const visivel = document.body.cloneNode(true) as HTMLElement;
    visivel.querySelectorAll(".sr-only").forEach(e => e.remove());
    expect((visivel.textContent ?? "").match(/cota/gi)).toEqual(["Cota"]);
  });

  it("ciclo da medição: tabela equivalente para leitor de tela", async () => {
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
    expect(regiao.querySelector(".ini-etapas")?.getAttribute("aria-hidden")).toBe("true");
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

  // #721: a faixa deixou de ser a largura do trecho (fracao do total, com o conteudo como minimo) e passou a ser uma
  // barra por etapa, com o comprimento na fracao da etapa de MAIOR valor
  const fracoes = (regiao: HTMLElement) =>
    [...regiao.querySelectorAll<HTMLElement>(".ini-etapa")].map(e => e.style.getPropertyValue("--ini-etapa-fracao"));

  it("ciclo da medição: a faixa de cada etapa é proporcional ao valor da maior; etapa vazia não tem faixa nem idade", async () => {
    api.mockResolvedValue(painel({ ciclo: [
      { etapa: "em_analise", valor_centavos: 0, quantidade: 0, mais_antigo_dias: null },
      { etapa: "boletim", valor_centavos: 100, quantidade: 1, mais_antigo_dias: 3 },
      { etapa: "nota", valor_centavos: 0, quantidade: 0, mais_antigo_dias: null },
      { etapa: "protocolado", valor_centavos: 300, quantidade: 1, mais_antigo_dias: 9 },
      { etapa: "recebido_mes", valor_centavos: 0, quantidade: 0, mais_antigo_dias: null },
    ] }));
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    const regiao = await screen.findByRole("region", { name: CICLO });
    expect(fracoes(regiao)).toEqual(["0%", "33%", "0%", "100%", "0%"]);
    expect([...(regiao.querySelector(".ini-etapa")?.children ?? [])].map(limpo)).toEqual(["Em análise", "R$ 0,00", "0 medições"]);
  });

  it("ciclo da medição com os dados do painel: a maior etapa tem a faixa inteira e a etapa com valor pequeno não some", async () => {
    api.mockResolvedValue(painel());
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    const regiao = await screen.findByRole("region", { name: CICLO });
    // em analise, boletim e nota nao chegam a 0,1% do protocolado cada uma: o minimo de 1% mantem a faixa na tela
    expect(fracoes(regiao)).toEqual(["1%", "1%", "1%", "100%", "1%"]);
  });

  it("ciclo da medição sem nenhum valor: nenhuma faixa, sem dividir por zero", async () => {
    api.mockResolvedValue(painel({ ciclo: painel().ciclo.map(e => ({ ...e, valor_centavos: 0, quantidade: 0, mais_antigo_dias: null })) }));
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    const regiao = await screen.findByRole("region", { name: CICLO });
    expect(fracoes(regiao)).toEqual(Array<string>(5).fill("0%"));
  });

  it("#652: recebido em 12 meses, uma barra por mês até o mês corrente, com a altura proporcional ao maior", async () => {
    api.mockResolvedValue(painel());
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    const regiao = await screen.findByRole("region", { name: REGIAO_RECEBIDO });
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
    const regiao = await screen.findByRole("region", { name: REGIAO_RECEBIDO });
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
    const regiao = await screen.findByRole("region", { name: REGIAO_RECEBIDO });
    expect([...regiao.querySelectorAll<HTMLElement>(".ini-rec__mes")].map(m => m.style.getPropertyValue("--ini-rec-tamanho")))
      .toEqual(Array<string>(12).fill("0%"));
  });

  it("#652: previsão de entrada com as cinco linhas, valor e quantidade; só o atrasado com valor fica vermelho", async () => {
    api.mockResolvedValue(painel());
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    const regiao = await screen.findByRole("region", { name: REGIAO_PREVISAO });
    const linhas = within(regiao).getAllByRole("listitem");
    expect(linhas.map(l => [...l.children].map(limpo))).toEqual([
      ["Neste mês", "R$ 5.000,00", "2 medições"],
      ["No próximo mês", "R$ 9.000,01", "1 medição"],
      ["Depois", "R$ 15.844.778,03", "1 medição"],
      ["Atrasado", "R$ 8.001,00", "2 medições"],
      ["Sem previsão", "R$ 0,00", "0 medições"],
    ]);
    expect(linhas.map(l => l.className.includes("--critico"))).toEqual([false, false, false, true, false]);
    // #721: o critico tem cor E forma: o simbolo da situacao antes do rotulo, so' na linha atrasada
    expect(linhas.map(l => l.querySelector(".glifo")?.className ?? null)).toEqual([null, null, null, "glifo glifo--critico", null]);
    // cada linha leva a chave de cor dela (a mesma do trecho da faixa)
    expect(linhas.map(l => l.className.split(" ")[1])).toEqual(["ini-previsao__linha--neste_mes", "ini-previsao__linha--proximo_mes",
      "ini-previsao__linha--depois", "ini-previsao__linha--atrasado", "ini-previsao__linha--sem_previsao"]);
  });

  it("#721: previsão de entrada com a faixa proporcional, um trecho por linha que tem valor, na ordem das linhas", async () => {
    api.mockResolvedValue(painel({ previsao: {
      neste_mes: { valor_centavos: 250, quantidade: 1 }, proximo_mes: { valor_centavos: 500, quantidade: 1 },
      depois: { valor_centavos: 0, quantidade: 0 }, atrasado: { valor_centavos: 150, quantidade: 1 },
      sem_previsao: { valor_centavos: 100, quantidade: 1 } } }));
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    const regiao = await screen.findByRole("region", { name: REGIAO_PREVISAO });
    const faixa = regiao.querySelector(".ini-previsao__faixa")!;
    expect(faixa.getAttribute("aria-hidden")).toBe("true");        // desenho: os numeros estao nas linhas
    // a linha zerada ("Depois") nao tem trecho; os outros, a fracao do total
    expect([...faixa.children].map(s => [s.className.replace("ini-previsao__seg ", ""), s.getAttribute("title"), (s as HTMLElement).style.flexGrow])).toEqual([
      ["ini-previsao__seg--neste_mes", "Neste mês", "0.25"], ["ini-previsao__seg--proximo_mes", "No próximo mês", "0.5"],
      ["ini-previsao__seg--atrasado", "Atrasado", "0.15"], ["ini-previsao__seg--sem_previsao", "Sem previsão", "0.1"]]);
    expect(within(regiao).getAllByRole("listitem")).toHaveLength(5);
  });

  it("#652: as cinco linhas da previsão fecham com a etapa Protocolado do ciclo, em quantidade e valor", async () => {
    api.mockResolvedValue(painel());
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    const regiao = await screen.findByRole("region", { name: REGIAO_PREVISAO });
    const centavos = (t: string) => Number(t.replace(/\D/g, ""));
    const linhas = within(regiao).getAllByRole("listitem").map(l => [...l.children].map(limpo));
    expect(linhas).toHaveLength(5);
    const protocolado = [...document.querySelectorAll(".ini-etapa")].map(e => [...e.children].map(limpo))
      .find(e => e[0] === "Protocolado");
    expect(protocolado).toEqual(["Protocolado", "R$ 15.866.779,04", "6 medições", "mais antiga há 100 dias"]);
    expect(linhas.reduce((s, l) => s + parseInt(l[2] ?? "", 10), 0)).toBe(parseInt(protocolado?.[2] ?? "", 10));
    expect(linhas.reduce((s, l) => s + centavos(l[1] ?? ""), 0)).toBe(centavos(protocolado?.[1] ?? ""));
  });

  it("#652: linha da previsão sem medição continua no lugar, zerada", async () => {
    const zero = { valor_centavos: 0, quantidade: 0 };
    api.mockResolvedValue(painel({ previsao: { neste_mes: zero, proximo_mes: zero, atrasado: zero, sem_previsao: zero, depois: zero } }));
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    const regiao = await screen.findByRole("region", { name: REGIAO_PREVISAO });
    expect(within(regiao).getAllByRole("listitem").map(l => [...l.children].map(limpo))).toEqual(
      ["Neste mês", "No próximo mês", "Depois", "Atrasado", "Sem previsão"].map(r => [r, "R$ 0,00", "0 medições"]));
    // #721: sem nenhum valor nao ha' o que a faixa proporcional desenhar
    expect(regiao.querySelector(".ini-previsao__faixa")).toBeNull();
  });

  it("#652: sem medição atrasada a linha Atrasado fica na cor padrão", async () => {
    api.mockResolvedValue(painel({ previsao: { ...painel().previsao, atrasado: { valor_centavos: 0, quantidade: 0 } } }));
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    const regiao = await screen.findByRole("region", { name: REGIAO_PREVISAO });
    expect(regiao.querySelector("[class*='--critico']")).toBeNull();
    // #721: sem valor atrasado a faixa tambem nao tem o trecho vermelho
    expect(regiao.querySelector(".ini-previsao__faixa")).not.toBeNull();
    expect(regiao.querySelector(".ini-previsao__seg--atrasado")).toBeNull();
  });

  const MATRIZ = "Medições por obra e competência";

  it("#659: matriz com uma linha por obra, agrupada por contratante, 12 competências e a legenda das etapas", async () => {
    api.mockResolvedValue(painel());
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    const regiao = await screen.findByRole("region", { name: MATRIZ });
    const legenda = within(regiao).getByRole("list", { name: "Legenda das etapas" });
    // #805: a chave de cor de cada etapa e' a peca MarcaEtapa, a mesma do cabecalho das colunas do Fechamento
    expect([...legenda.children].map(li => [limpo(li), li.querySelector(".marca-etapa__cor")?.className])).toEqual([
      ["Em análise", "marca-etapa__cor marca-etapa__cor--em_analise"], ["Boletim", "marca-etapa__cor marca-etapa__cor--boletim"],
      ["Nota", "marca-etapa__cor marca-etapa__cor--nota"], ["Protocolado", "marca-etapa__cor marca-etapa__cor--protocolado"],
      ["Recebido", "marca-etapa__cor marca-etapa__cor--recebido"], ["Atrasado", "marca-etapa__cor marca-etapa__cor--atrasado"]]);
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

  it("dois números só com rótulo e valor: notas protocoladas e medido do mês (#652: o recebido no ano virou as barras)", async () => {
    api.mockResolvedValue(painel());
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    const regiao = await screen.findByRole("region", { name: "Números do mês" });
    // #721: os dois numeros sairam dos cartoes e subiram para o alto, numa lista de rotulo e valor (dl)
    const numeros = [...regiao.querySelectorAll(".ini-numero")];
    expect(numeros.map(c => [...c.children].map(limpo))).toEqual([
      ["Notas fiscais protocoladas em outubro", "R$ 15.222.956,18"],
      ["Medido em setembro", "R$ 18.277.156,96"],
    ]);
    expect(numeros.map(c => [...c.children].map(e => e.tagName))).toEqual([["DT", "DD"], ["DT", "DD"]]);
    expect(numeros.every(c => c.parentElement?.tagName === "DL" && c.parentElement.parentElement === regiao)).toBe(true);
    expect(limpo(regiao)).toBe("Notas fiscais protocoladas em outubroR$ 15.222.956,18Medido em setembroR$ 18.277.156,96");
    expect(document.body.textContent).not.toContain("Recebido em 2026");
  });

  it("#805: a variação dos dois números contra as referências do servidor, com a referência escrita", async () => {
    // hoje e' 09/10/2026: as notas de outubro contra setembro ate' o dia 9; o medido de setembro contra agosto e
    // contra setembro de 2025. Valores inventados
    const base = painel();
    api.mockResolvedValue(painel({
      notas_mes: { ...base.notas_mes, valor_centavos: 112_400_000, anterior: { mes: "2026-09", ate_dia: 9, valor_centavos: 100_000_000 } },
      medido: { ...base.medido, valor_centavos: 919_000_000,
        anterior: { competencia: "2026-08", valor_centavos: 1_000_000_000 },
        ano_anterior: { competencia: "2025-09", valor_centavos: 915_000_000 } },
    }));
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    const regiao = await screen.findByRole("region", { name: "Números do mês" });
    const [notas, medido] = [...regiao.querySelectorAll(".ini-numero")];
    const variacoes = (c: Element) => [...c.querySelectorAll(".variacao")].map(v =>
      [v.className, [...v.querySelectorAll(".variacao__parte")].map(limpo).join(" "), limpo(v.querySelector(".sr-only"))]);
    expect(variacoes(notas)).toEqual([
      ["variacao variacao--bom", "▲ +12,4% × set até o dia 9", "subiu 12,4% em relação a setembro até o dia 9"]]);
    expect(variacoes(medido)).toEqual([
      ["variacao variacao--ruim", "▼ \u22128,1% × ago", "caiu 8,1% em relação a agosto"],
      ["variacao variacao--estavel", "● estável × set/25", "estável em relação a setembro de 2025"]]);
    // o numero continua em tinta, no dd dele; as variacoes vem num dd proprio, logo abaixo
    expect([...medido.children].map(e => [e.tagName, e.className])).toEqual(
      [["DT", "ini-numero__rotulo"], ["DD", "ini-numero__valor"], ["DD", "ini-numero__variacoes"]]);
    expect(limpo(medido.querySelector(".ini-numero__valor"))).toBe("R$ 9.190.000,00");
  });

  it("#805: só a referência que existe aparece; a de outro ano leva o ano no rótulo", async () => {
    // em janeiro, a competencia do cartao e' dezembro: a anterior e' novembro, do mesmo ano; nas notas de janeiro, o
    // mes anterior e' dezembro do ano passado
    const base = painel();
    api.mockResolvedValue(painel({
      hoje: "2027-01-31",
      notas_mes: { ...base.notas_mes, mes: "2027-01", valor_centavos: 50_000_000, anterior: { mes: "2026-12", ate_dia: 31, valor_centavos: 100_000_000 } },
      medido: { ...base.medido, competencia: "2026-12", valor_centavos: 500_000_000,
        anterior: { competencia: "2026-11", valor_centavos: 400_000_000 }, ano_anterior: null },
    }));
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    const regiao = await screen.findByRole("region", { name: "Números do mês" });
    expect([...regiao.querySelectorAll(".variacao")].map(v => [...v.querySelectorAll(".variacao__parte")].map(limpo).join(" "))).toEqual(
      ["▼ \u221250,0% × dez/26 até o dia 31", "▲ +25,0% × nov"]);
    expect(limpo(regiao.querySelector(".variacao .sr-only"))).toBe("caiu 50,0% em relação a dezembro de 2026 até o dia 31");
  });

  it("#642 e #805: sem referência não há variação nem percentual; a curva diária, as barras por contratante e o selo de mês fechado não voltaram", async () => {
    api.mockResolvedValue(painel());
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    await screen.findByRole("region", { name: "Números do mês" });
    expect(screen.queryByRole("region", { name: "Medições protocoladas" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Medido por contratante" })).toBeNull();
    expect(screen.queryByRole("img")).toBeNull();
    expect(document.querySelector(".ini-mini, .ini-grafico, .ini-barra, .ini-barras, .ini-variacao, .variacao, .ini-numero__variacoes")).toBeNull();
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
  // cada item e' um link com dois filhos: o nome (obra, " · " so' de leitor de tela, mensagem) e o selo de dias
  const linhasDe = (secao: HTMLElement) => within(secao).queryAllByRole("link").map(l => [...l.children].map(limpo));
  // #721: as contagens sao a peca Contador. A da caixa (ao lado do titulo) tem o numero desenhado, fora da leitura, e o
  // rotulo so' de leitor de tela; a de cada secao e' o numero ao lado do titulo dela
  const contadorDaCaixa = () => document.querySelector(".ini-avisos > .ini-painel__cab .contador");
  const totalDaCaixa = () => limpo(contadorDaCaixa()?.querySelector("[aria-hidden='true']"));
  const contadorDe = (secao: Element) => secao.querySelector(".ini-aviso__topo .contador");

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
    // #721: o selo de dias e' a peca Selo, na situacao da secao: vencido = critico (era a pilula "acao", vermelha)
    expect(within(vencido).getByText("há 450 dias").closest(".selo")!.className).toBe("selo selo--critico");
    const semana = caixa.getByRole("region", { name: "Esta semana" });
    expect(linhasDe(semana)).toEqual([["Empresa X · FGTS vence", "hoje"], ["Obra A · vigência termina", "em 5 dias"]]);
    // o que vence na semana ou no mes = vence em breve (era a pilula "atencao", ambar)
    expect(within(semana).getByText("em 5 dias").closest(".selo")!.className).toBe("selo selo--breve");
    const mes = caixa.getByRole("region", { name: "Este mês" });
    expect(linhasDe(mes)).toEqual([["Obra A · execução termina", "em 20 dias"]]);
    expect(within(mes).getByText("em 20 dias").closest(".selo")!.className).toBe("selo selo--breve");
    expect([vencido, semana, mes].map(s => limpo(contadorDe(s)))).toEqual(["2", "2", "1"]);
    // cada item leva ao lugar do aviso, como na tela Avisos
    expect(within(vencido).getAllByRole("link").map(l => l.getAttribute("href"))).toEqual(["/obras/8/prazos", "/obras/9/medicoes/31#notas"]);
    expect(within(semana).getAllByRole("link")[0]?.getAttribute("href")).toBe("/documentos/4");
  });

  it("#721: contadores e selos dos avisos são as peças da fundação, com cor e forma; o sentido de cada seção não muda", async () => {
    servir();
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    const caixa = within(await screen.findByRole("complementary", { name: "Avisos importantes" }));
    const secoes = ["Vencido", "Esta semana", "Este mês"].map(n => caixa.getByRole("region", { name: n }));
    // o contador de cada secao: critico no vencido, vence em breve nas outras, cada um com o simbolo da situacao
    expect(secoes.map(s => contadorDe(s)?.className)).toEqual(["contador contador--critico", "contador contador--breve", "contador contador--breve"]);
    expect(secoes.map(s => contadorDe(s)?.querySelector(".glifo")?.className)).toEqual(["glifo glifo--critico", "glifo glifo--breve", "glifo glifo--breve"]);
    // todo selo de uma secao tem a situacao dela, com o simbolo antes do texto; o `nivel` do aviso nao muda a cor
    expect(secoes.map(s => [...new Set([...s.querySelectorAll(".selo")].map(e => e.className))])).toEqual(
      [["selo selo--critico"], ["selo selo--breve"], ["selo selo--breve"]]);
    expect([...document.querySelectorAll(".ini-avisos .selo")].every(e => e.firstElementChild?.classList.contains("glifo"))).toBe(true);
    // o contador da caixa e' neutro (sem simbolo): o numero desenhado e o rotulo so' de leitor de tela, sem aria-label
    const total = contadorDaCaixa()!;
    expect(total.className).toBe("contador");
    expect(total.querySelector(".glifo")).toBeNull();
    expect(total.getAttribute("aria-label")).toBeNull();
    expect([...total.children].map(c => [c.className, c.getAttribute("aria-hidden"), c.textContent])).toEqual([["", "true", "5"], ["sr-only", null, "5 avisos"]]);
    // a obra em destaque e a mensagem em elementos separados; o " · " entre as duas so' para o leitor de tela
    const item = within(secoes[0]).getAllByRole("link")[0];
    expect([...item.querySelector(".ini-aviso__nome")!.children].map(c => [c.className, c.textContent])).toEqual(
      [["ini-aviso__obra", "Obra B"], ["sr-only", " · "], ["ini-aviso__msg", "execução vencida"]]);
    // as classes proprias do vocabulario antigo de tres niveis sairam
    expect(document.querySelector("[class*='ini-pilula'], [class*='ini-aviso--'], .ini-aviso__conta, .ini-avisos__total")).toBeNull();
  });

  it("#666: a contagem da caixa é a soma de Vencido, Esta semana e Este mês da tela Avisos, com a mesma fila", async () => {
    servir();
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    const caixa = await screen.findByRole("complementary", { name: "Avisos importantes" });
    await within(caixa).findByRole("region", { name: "Vencido" });
    const total = totalDaCaixa();
    cleanup();
    render(<AvisosPagina busca={{}} />);
    await act(async () => {});
    // na tela Avisos as contagens ficam no alto da página, com a mesma fila e a mesma regra de seção
    const naTela = [...document.querySelectorAll(".avs-numero")].map(n => `${limpo(n.querySelector("dt"))} · ${limpo(n.querySelector(".avs-numero__valor"))}`);
    expect(naTela).toEqual(["Vencidos · 2", "Esta semana · 2", "Este mês · 1", "Próximos 90 dias · 1"]);
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
    expect(limpo(contadorDe(vencido))).toBe("5");
    expect(totalDaCaixa()).toBe("5");
    // seção sem aviso: a contagem zero, neutra (sem situação nem símbolo), sem lista
    const semana = caixa.getByRole("region", { name: "Esta semana" });
    expect(limpo(contadorDe(semana))).toBe("0");
    expect(contadorDe(semana)?.className).toBe("contador");
    expect(contadorDe(semana)?.querySelector(".glifo")).toBeNull();
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
    expect(totalDaCaixa()).toBe("0");
    expect(limpo(contadorDaCaixa()?.querySelector(".sr-only"))).toBe("0 avisos");
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
