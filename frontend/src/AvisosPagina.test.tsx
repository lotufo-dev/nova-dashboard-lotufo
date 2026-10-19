import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import AvisosPagina from "./AvisosPagina";

// Os Avisos moram dentro de Obras (#159): o painel recebe os avisos já carregados e o recorte da lista.
const aviso = (extra: Record<string, unknown> = {}) => ({
  tipo: "execucao_vencendo", nivel: "atencao", publico: ["operacao"], contrato_id: 7, obra: "Granito", dias: 20,
  valor_centavos: null, mensagem: "execução termina em 20 dias (20/10/2026)",
  destino: { tela: "contrato", id: 7, aba: "prazos" }, data: "2026-10-20", sentido: "prazo", ...extra });

const painel = (avisos: unknown, extra: Record<string, unknown> = {}) =>
  render(<AvisosPagina busca={{ c: "todas", avisos: "1" }} perfil="admin" avisos={avisos as never} nome="Todas as obras" onFechar={() => {}} {...extra} />);

describe("Avisos dentro de Obras", () => {
  afterEach(() => { cleanup(); });

  it("o resumo da Atenção traz a obra em negrito, lida do campo e não do texto (#23)", async () => {
    const { container } = painel([aviso()]);
    await screen.findByText(/o mais urgente/);
    const resumo = container.querySelector("summary")!;
    expect(resumo.querySelector(".forte")?.textContent).toBe("Granito");
    expect(resumo.textContent).toContain("Granito: execução termina em 20 dias");
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

  it("agrupa por tipo ou por obra, com o 'onde se resolve' de cada aviso", () => {
    const { container } = painel([aviso({ nivel: "critico" })]);
    expect(container.querySelector("a[aria-current='true']")?.textContent).toBe("por tipo");
    expect(screen.getByRole("link", { name: "por obra" }).getAttribute("href")).toBe("/obras?c=todas&avisos=1&agrupar=obra");
    expect(screen.getByRole("columnheader", { name: "Onde se resolve" })).toBeTruthy();
    expect(container.querySelector("tbody a")?.getAttribute("href")).toContain("/obras/7");
  });

  it("sem aviso, diz que está tudo em dia; com falha, não afirma isso", () => {
    painel([]);
    expect(screen.getByText("Nenhum aviso. Tudo em dia.")).toBeTruthy();
    cleanup();
    painel(null);
    expect(screen.getByRole("alert").textContent).toContain("Não foi possível verificar os avisos");
    expect(screen.queryByText("Nenhum aviso. Tudo em dia.")).toBeNull();
  });
});
