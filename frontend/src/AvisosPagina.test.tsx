import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import AvisosPagina from "./AvisosPagina";

// Os Avisos moram dentro de Obras (#159): o painel recebe os avisos já carregados e o recorte da lista.
const aviso = (extra: Record<string, unknown> = {}) => ({
  tipo: "execucao_vencendo", nivel: "atencao", publico: ["operacao"], contrato_id: 7, obra: "Granito", dias: 20,
  valor_centavos: null, mensagem: "execução termina em 20 dias (20/10/2026)",
  destino: { tela: "contrato", id: 7, aba: "prazos" }, data: "2026-10-20", sentido: "prazo", ...extra });

const painel = (avisos: unknown, extra: Record<string, unknown> = {}) =>
  render(<AvisosPagina busca={{ c: "todas", avisos: "1" }} avisos={avisos as never} nome="Todas as obras" onFechar={() => {}} {...extra} />);

describe("Avisos dentro de Obras", () => {
  afterEach(() => { cleanup(); });

  it("a Atenção recolhida só diz 'Atenção'; a linha traz a obra em negrito, lida do campo e não do texto (#23)", () => {
    const { container } = painel([aviso()]);
    const resumo = container.querySelector("summary")!;
    expect(resumo.textContent).toBe("Atenção");
    const fato = container.querySelector("td.aviso__fato")!;
    expect(fato.querySelector(".forte")?.textContent).toBe("Granito");
    expect(fato.textContent).toContain("Granito: execução termina em 20 dias");
    // sem a meta do cabeçalho, a contagem por nível e a contagem ao lado de cada tipo
    expect(container.textContent).not.toMatch(/da operação|\d\sde\satenção|o mais urgente/);
    expect(screen.getByRole("link", { name: "Prazo" })).toBeTruthy();
  });

  it("o título diz o recorte e o botão fecha os avisos", () => {
    const fechar = vi.fn();
    painel([aviso()], { nome: "SINFRA", onFechar: fechar });
    expect(screen.getByRole("heading", { name: "Avisos · SINFRA" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Fechar os avisos" }));
    expect(fechar).toHaveBeenCalledTimes(1);
  });

  it("só mostra os avisos das obras do recorte (e os sem obra só em 'Todas as obras')", () => {
    const lista = [aviso({ contrato_id: 7, obra: "Granito" }),
      aviso({ contrato_id: 8, obra: "Maternidade", mensagem: "execução termina em 5 dias (10/10/2026)" }),
      aviso({ tipo: "documento_vencendo", contrato_id: null, obra: null, entidade_id: 3, entidade: "Construtora Alfa", mensagem: "Construtora Alfa: certidão vence em 3 dias" })];
    const { container } = painel(lista, { escopo: new Set([7]) });
    expect(container.textContent).toContain("Granito");
    expect(container.textContent).not.toContain("Maternidade");
    expect(container.textContent).not.toContain("Construtora Alfa");
    cleanup();
    const todas = painel(lista);
    expect(todas.container.textContent).toContain("Maternidade");
    expect(todas.container.textContent).toContain("Construtora Alfa");
  });

  it("agrupa por tipo ou por obra, e cada aviso tem o link Abrir para o destino, sem a frase 'onde se resolve'", () => {
    const { container } = painel([aviso({ nivel: "critico" })]);
    expect(container.querySelector("a[aria-current='true']")?.textContent).toBe("por tipo");
    expect(screen.getByRole("link", { name: "por obra" }).getAttribute("href")).toBe("/obras?c=todas&avisos=1&agrupar=obra");
    expect(screen.queryByRole("columnheader", { name: "Onde se resolve" })).toBeNull();
    const abrir = within(container.querySelector("tbody")!).getByRole("link", { name: "Abrir" });
    expect(abrir.getAttribute("href")).toContain("/obras/7");
    expect(container.textContent).not.toContain("Prazos · ");
  });

  it("por obra, a linha do grupo traz só o nome", () => {
    const { container } = painel([aviso({ nivel: "critico" })], { busca: { c: "todas", avisos: "1", agrupar: "obra" } });
    const grupo = container.querySelector("tr.grupo")!;
    expect(grupo.textContent).toBe("Granito");
  });

  it("filtro por uma obra sem aviso: sem a frase de recorte", () => {
    painel([aviso()], { busca: { c: "todas", avisos: "1", obra: "99" } });
    expect(screen.queryByText(/não tem avisos/)).toBeNull();
    expect(screen.queryByText(/ver de todas as obras/)).toBeNull();
    expect(screen.getByText("Nenhum aviso com esses filtros.")).toBeTruthy();
  });

  it("sem aviso, uma linha curta; com falha, não afirma isso", () => {
    painel([]);
    expect(screen.getByText("Nenhum aviso.")).toBeTruthy();
    expect(screen.queryByText(/Tudo em dia/)).toBeNull();
    cleanup();
    painel(null);
    expect(screen.getByRole("alert").textContent).toContain("Não foi possível verificar os avisos");
    expect(screen.queryByText("Nenhum aviso.")).toBeNull();
  });
});
