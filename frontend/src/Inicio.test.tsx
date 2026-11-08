import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Inicio, { saudacao, type PainelInicio } from "./Inicio";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

const USUARIO = { id: 1, nome: "Leonardo Praeiro", email: "leonardo@lotufo.com", perfil: "admin" };

const dias = (n: number, f: (i: number) => number) => Array.from({ length: n }, (_, i) => f(i));

const painel = (extra: Partial<PainelInicio> = {}): PainelInicio => ({
  hoje: "2026-10-09",
  notas_a_enviar: 3,
  certidoes: { vencidas: 1, vencendo: 1, itens: [] },
  reajustes: [],
  protocoladas: { obras_protocoladas: 2, obras_ativas: 18, ultima: "2026-09-30" },
  medido: { competencia: "2026-09", anterior_competencia: "2026-08", valor_centavos: 1_827_715_696,
            anterior_centavos: 2_140_000_000, quantidade: 2, ultimo_lancamento: "2026-10-08", variacao_pct: -14.6 },
  por_contratante: [{ contratante: "SINFRA", atual_centavos: 124_000_000, anterior_centavos: 100_000_000 }],
  recebido_ano: { valor_centavos: null, mes_centavos: 0, sem_data: 12, real_centavos: 18_785_640_866 },
  a_receber: { liberado: true, valor_centavos: 1_720_000_000, mais_60_centavos: 210_000_000 },
  prazos: [],
  espelhos: [{ espelho_id: 1, contrato_id: 7, medicao_id: 9, obra: "Obra A", titulo: "1ª Medição", situacao: "aprovado_mudou" }],
  protocolado_mes: {
    dia: 9,
    atual: { mes: "2026-10", ate_dia: 9, valor_centavos: 1_586_677_904, quantidade: 6,
             acumulado_centavos: dias(9, i => (i + 1) * 176_297_545) },
    anterior: { mes: "2026-09", ate_dia: 9, valor_centavos: 1_148_230_577, quantidade: 5,
                acumulado_centavos: dias(9, i => (i + 1) * 127_581_175) },
    variacao_pct: 38.2,
  },
  notas_mes: { mes: "2026-10", valor_centavos: 1_522_295_618, notas: 5, obras: 2, acumulado_centavos: dias(9, i => i * 100) },
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

describe("Início", () => {
  afterEach(() => { cleanup(); api.mockReset(); });

  it("destaque de medições protocoladas: mês atual contra o anterior no mesmo período, com variação e gráfico", async () => {
    api.mockResolvedValue(painel());
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    expect(api).toHaveBeenCalledWith("/api/inicio/painel");
    expect(screen.getByRole("heading", { level: 1 }).textContent).toMatch(/, Leonardo$/);
    const regiao = await screen.findByRole("region", { name: "Medições protocoladas" });
    const d = within(regiao);
    const texto = (regiao.textContent ?? "").replace(/\u00a0/g, " ");
    expect(texto).toContain("outubro × setembro, mesmo período (dias 1 a 9)");
    expect(texto).toContain("R$ 15.866.779,04");
    expect(texto).toContain("R$ 11.482.305,77");
    expect(texto).toContain("6 medições");
    expect(texto).toContain("5 medições");
    expect(texto).toContain("+38,2%");
    expect(d.getByRole("img", { name: /Protocolado acumulado por dia/ })).toBeTruthy();
    expect(d.getByText("outubro")).toBeTruthy();
    expect(d.getByText("setembro")).toBeTruthy();
  });

  it("três cartões: notas protocoladas, medido do mês fechado com variação e recebido no ano", async () => {
    api.mockResolvedValue(painel());
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    const regiao = await screen.findByRole("region", { name: "Números do mês" });
    const n = within(regiao);
    const t = (regiao.textContent ?? "").replace(/\u00a0/g, " ");
    expect(t).toContain("Notas fiscais protocoladas em outubro");
    expect(t).toContain("R$ 15.222.956,18");
    expect(t).toContain("5 notas · 2 obras");
    expect(t).toContain("Medido em setembro");
    expect(t).toContain("R$ 18.277.156,96");
    expect(t).toContain("mês fechado");
    expect(t).toContain("-14,6% vs. agosto");
    expect(t).toContain("Recebido em 2026");
    expect(t).toContain("R$ 187.856.408,66");
    expect(n.getByText("-14,6% vs. agosto").className).toContain("ini-variacao--atencao");
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

  it("seção de avisos sem item mostra uma linha curta no lugar da lista", async () => {
    api.mockResolvedValue(painel({ avisos_importantes: {
      reajustes: { total: 0, itens: [] }, prazos: { total: 0, itens: [] }, certidoes: { total: 0, itens: [] } } }));
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    await screen.findByRole("complementary", { name: "Avisos importantes" });
    expect(screen.getByText("Nenhum aviso de reajuste.")).toBeTruthy();
    expect(screen.getByText("Nenhuma certidão vencendo.")).toBeTruthy();
  });

  it("sem base de comparação não há selo de variação", async () => {
    api.mockResolvedValue(painel({ medido: { ...painel().medido, variacao_pct: null } }));
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    const n = await screen.findByRole("region", { name: "Números do mês" });
    expect(n.textContent).not.toContain("vs. agosto");
  });

  it("medido por contratante com os dois meses fechados; mês sem medição mostra o aviso e o botão", async () => {
    api.mockResolvedValue(painel());
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    const sec = within(await screen.findByRole("region", { name: "Medido por contratante" }));
    expect(sec.getByText("SINFRA")).toBeTruthy();
    expect(sec.queryByRole("status")).toBeNull();
    cleanup();
    api.mockResolvedValue(painel({
      medido: { competencia: "2026-09", anterior_competencia: "2026-08",
                valor_centavos: 0, anterior_centavos: 0, quantidade: 0, ultimo_lancamento: null, variacao_pct: null },
      por_contratante: [],
    }));
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    const aviso = await screen.findByRole("status");
    expect(aviso.textContent).toContain("Nenhuma medição da competência de setembro.");
    expect(within(aviso).getByRole("link", { name: /Lançar medição/ }).getAttribute("href")).toBe("/medicoes");
  });

  it("saudação pela hora de Cuiabá", () => {
    expect(saudacao(new Date("2026-10-09T13:00:00Z"))).toBe("Bom dia");        // 09h em Cuiabá
    expect(saudacao(new Date("2026-10-09T17:00:00Z"))).toBe("Boa tarde");      // 13h
    expect(saudacao(new Date("2026-10-10T01:00:00Z"))).toBe("Boa noite");      // 21h
  });
});
