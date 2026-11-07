import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import AvisosPagina from "./AvisosPagina";

// Os Avisos moram dentro de Obras (#159) e, desde o redesenho #511, são organizados pelo tempo: o painel recebe os
// avisos já carregados e o recorte da lista.
const aviso = (extra: Record<string, unknown> = {}) => ({
  tipo: "execucao_vencendo", nivel: "atencao", publico: ["operacao"], contrato_id: 7, obra: "Granito", dias: 20,
  valor_centavos: null, mensagem: "Granito: execução termina", destino: { tela: "contrato", id: 7, aba: "prazos" },
  data: "2026-11-26", sentido: "prazo", ...extra });

const painel = (avisos: unknown, extra: Record<string, unknown> = {}) =>
  render(<AvisosPagina busca={{ c: "todas", avisos: "1" }} avisos={avisos as never} nome="Todas as obras" onFechar={() => {}} {...extra} />);

const secao = (nome: RegExp) => screen.getByRole("heading", { name: nome }).closest("section")!;

describe("Avisos: o que vence quando", () => {
  afterEach(() => { cleanup(); });

  it("cada aviso cai em uma seção só: vencido há 3 dias, 5 dias, 20 dias, 60 dias e sem data", () => {
    painel([
      aviso({ obra: "Vencida", mensagem: "Vencida: garantia vencida", dias: -3, data: "2026-11-04" }),
      aviso({ obra: "Semana", mensagem: "Semana: FGTS vence", dias: 5, data: "2026-11-12" }),
      aviso({ obra: "Mes", dias: 20, data: "2026-11-27" }),
      aviso({ obra: "Longe", dias: 60, data: "2027-01-06" }),
      aviso({ obra: "Parada", tipo: "nota_divergente", dias: null, data: null, sentido: null, destino: null, mensagem: "Parada: nota divergente" }),
    ]);
    const nomes = screen.getAllByRole("heading", { level: 3 }).map(h => h.textContent);
    expect(nomes).toEqual(["VENCIDO · 1", "ESTA SEMANA · 1", "ESTE MÊS · 1", "DEPOIS · 1", "SEM DATA · 1"]);
    expect(within(secao(/^VENCIDO/)).getByText("Vencida")).toBeTruthy();
    expect(within(secao(/^ESTA SEMANA/)).getByText("Semana")).toBeTruthy();
    expect(within(secao(/^ESTE MÊS/)).getByText("Mes")).toBeTruthy();
    expect(within(secao(/^DEPOIS/)).getByText("Longe")).toBeTruthy();
    expect(within(secao(/^SEM DATA/)).getByText("Parada")).toBeTruthy();
    // a data do fato, a obra em coluna própria e os dias
    const vencido = within(secao(/^VENCIDO/));
    expect(vencido.getByText("04/11/2026")).toBeTruthy();
    expect(vencido.getByText("há 3 dias")).toBeTruthy();
    expect(within(secao(/^ESTA SEMANA/)).getByText("5 dias")).toBeTruthy();
    expect(vencido.getByRole("link", { name: /garantia vencida/  }).getAttribute("href")).toContain("/obras/7");
  });

  it("sem aviso sem data, a seção 'Sem data' não aparece; as quatro do tempo aparecem sempre", () => {
    painel([aviso()]);
    expect(screen.getAllByRole("heading", { level: 3 }).map(h => h.textContent))
      .toEqual(["VENCIDO · 0", "ESTA SEMANA · 0", "ESTE MÊS · 1", "DEPOIS · 0"]);
  });

  it("o vencido mostra os primeiros, do mais antigo, e '… e mais N' abre o resto", () => {
    const vencidos = Array.from({ length: 9 }, (_, i) => aviso({ obra: `Obra ${i}`, dias: -(i + 1), data: `2026-10-${String(20 - i).padStart(2, "0")}` }));
    painel(vencidos);
    const vencido = secao(/^VENCIDO/);
    expect(within(vencido).getAllByRole("listitem")).toHaveLength(6);
    expect(within(vencido).getAllByRole("listitem")[0].textContent).toContain("Obra 8");
    fireEvent.click(within(vencido).getByRole("button", { name: "… e mais 3" }));
    expect(within(vencido).getAllByRole("listitem")).toHaveLength(9);
  });

  it("a vencer, o mais próximo primeiro", () => {
    painel([aviso({ obra: "B", dias: 6, data: "2026-11-13" }), aviso({ obra: "A", dias: 2, data: "2026-11-09" })]);
    const linhas = within(secao(/^ESTA SEMANA/)).getAllByRole("listitem");
    expect(linhas.map(l => l.querySelector(".aviso-linha__obra")?.textContent)).toEqual(["A", "B"]);
  });

  it("o filtro por categoria da rota esconde as outras (o Início manda ?familia=reajustes)", () => {
    const lista = [aviso({ obra: "DePrazo" }),
      aviso({ obra: "DeReajuste", tipo: "reajuste_apostilamento", destino: { tela: "contrato", id: 7, aba: "reajuste" } })];
    const { container } = painel(lista, { busca: { c: "todas", avisos: "1", familia: "reajustes" } });
    expect(container.textContent).toContain("DeReajuste");
    expect(container.textContent).not.toContain("DePrazo");
    cleanup();
    const todas = painel(lista);
    expect(todas.container.textContent).toContain("DePrazo");
    expect(todas.container.textContent).toContain("DeReajuste");
  });

  it("traz o título, o subtítulo e a legenda da cor, e o botão fecha os avisos", () => {
    const fechar = vi.fn();
    painel([aviso()], { nome: "SINFRA", onFechar: fechar });
    expect(screen.getByRole("heading", { name: "Avisos · SINFRA" })).toBeTruthy();
    expect(screen.getByText("o que vence quando")).toBeTruthy();
    expect(screen.getByRole("list", { name: "Legenda das cores" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Fechar os avisos" }));
    expect(fechar).toHaveBeenCalledTimes(1);
  });

  it("só mostra os avisos das obras do recorte (e os sem obra só em 'Todas as obras'); a empresa vem na coluna da obra", () => {
    const lista = [aviso({ contrato_id: 7, obra: "Granito" }),
      aviso({ contrato_id: 8, obra: "Maternidade" }),
      aviso({ tipo: "documento_vencendo", contrato_id: null, obra: null, entidade_id: 3, entidade: "Construtora Alfa", dias: 3,
        mensagem: "Construtora Alfa: certidão vence", destino: { tela: "documentos" } })];
    const { container } = painel(lista, { escopo: new Set([7]) });
    expect(container.textContent).toContain("Granito");
    expect(container.textContent).not.toContain("Maternidade");
    expect(container.textContent).not.toContain("Construtora Alfa");
    cleanup();
    const todas = painel(lista);
    expect(todas.container.textContent).toContain("Maternidade");
    expect(within(secao(/^ESTA SEMANA/)).getByText("Construtora Alfa")).toBeTruthy();
    expect(screen.getByRole("link", { name: /certidão vence/ })).toBeTruthy();
  });

  it("filtro por uma obra sem aviso: uma linha curta", () => {
    painel([aviso()], { busca: { c: "todas", avisos: "1", obra: "99" } });
    expect(screen.getByText("Nenhum aviso com esses filtros.")).toBeTruthy();
  });

  it("sem aviso, uma linha curta; com falha, não afirma isso", () => {
    painel([]);
    expect(screen.getByText("Nenhum aviso.")).toBeTruthy();
    cleanup();
    painel(null);
    expect(screen.getByRole("alert").textContent).toContain("Não foi possível verificar os avisos");
    expect(screen.queryByText("Nenhum aviso.")).toBeNull();
  });
});
