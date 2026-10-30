import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import AbaAguardandoNota from "./AbaAguardandoNota";
import type { LinhaResumo } from "./resumoMedicoes";

// #156: aba Aguardando nota (prototipo aprovado pelo Leo em 14/10/2026).
const linha = (extra: Partial<LinhaResumo>): LinhaResumo => ({
  situacao: "aguardando-nota", contrato_id: 5, obra: "Integra BRT", contratante: "SINFRA", orgao_sub: null,
  medicao_id: 40, medicao_ids: [40], numero: 16, competencia: "2026-09", titulo: "16ª Medição", proximo_passo: "anexar as notas",
  valor_centavos: 787288979, marco: "2026-10-10", dias: 4, ...extra });

const LINHAS = [
  linha({}),
  linha({ contrato_id: 6, obra: "Complexo Cultural", contratante: "MTPAR", orgao_sub: "Setor X", medicao_id: 41,
    titulo: "25ª Medição + Reajuste", valor_centavos: 308126381, marco: "2026-10-02", dias: 12 }),
  linha({ contrato_id: 7, obra: "Sem Marco", medicao_id: 42, titulo: "1ª Medição", valor_centavos: 1, marco: null, dias: null }),
  linha({ contrato_id: 8, obra: "Muito Parada", medicao_id: 43, titulo: "2ª Medição", marco: "2026-09-20", dias: 24 }),
];

describe("Aba Aguardando nota", () => {
  afterEach(() => { cleanup(); window.history.replaceState(null, "", "/"); });

  it("mostra cada linha com valor, data de envio e parada, sem contagem nem frase de apoio", () => {
    render(<AbaAguardandoNota linhas={LINHAS} podeIniciar aoIniciar={() => {}} />);
    const quadro = screen.getByRole("region", { name: "Aguardando nota" });
    expect(within(quadro).queryByText("4 medições")).toBeNull();
    expect(within(quadro).queryByText(/aparece aqui sozinha/)).toBeNull();
    for (const c of ["Obra", "Contratante", "Medição", "Valor", "Enviada ao faturamento em", "Parada há"])
      expect(within(quadro).getByRole("columnheader", { name: c })).toBeTruthy();
    const l1 = within(quadro).getByRole("row", { name: /Integra BRT/ });
    expect(within(l1).getByText("R$ 7.872.889,79")).toBeTruthy();
    expect(within(l1).getByText("10/10/2026")).toBeTruthy();
    expect(within(l1).getByText(/^4\s+dias$/).className).not.toContain("--");
    const l2 = within(quadro).getByRole("row", { name: /Complexo Cultural/ });
    expect(within(l2).getByText("Setor X")).toBeTruthy();
    expect(within(l2).getByText(/^12\s+dias/).className).toContain("medicoes__parada--atencao");
    expect(within(quadro).getByText(/^24\s+dias/).className).toContain("medicoes__parada--acao");
    // sem marco: traco, nunca data inventada
    const l3 = within(quadro).getByRole("row", { name: /Sem Marco/ });
    expect(within(l3).getAllByText("—")).toHaveLength(2);
  });

  it("a linha inteira abre a medição na etapa pendente, por clique e por teclado; a obra abre a obra", () => {
    render(<AbaAguardandoNota linhas={LINHAS} podeIniciar aoIniciar={() => {}} />);
    const linhaBRT = screen.getByRole("row", { name: /Integra BRT/ });
    fireEvent.click(within(linhaBRT).getByText("SINFRA"));
    expect(window.location.pathname + window.location.hash).toBe("/obras/5/medicoes/40#etapa-3");
    fireEvent.keyDown(screen.getByRole("row", { name: /Complexo Cultural/ }), { key: "Enter" });
    expect(window.location.pathname + window.location.hash).toBe("/obras/6/medicoes/41#etapa-3");
    // o nome da obra e' um link proprio: leva a' obra, e a linha nao o atropela
    fireEvent.click(within(screen.getByRole("row", { name: /Muito Parada/ })).getByRole("link", { name: "Muito Parada" }));
    expect(window.location.pathname + window.location.hash).toBe("/obras/8");
  });

  it("o título da medição é link de verdade na etapa pendente; Ctrl+clique na linha não navega", () => {
    render(<AbaAguardandoNota linhas={LINHAS} podeIniciar aoIniciar={() => {}} />);
    expect(screen.getByRole("link", { name: "16ª Medição" }).getAttribute("href")).toBe("/obras/5/medicoes/40#etapa-3");
    fireEvent.click(screen.getByRole("row", { name: /Integra BRT/ }), { ctrlKey: true });
    expect(window.location.pathname).toBe("/");
  });

  it("o botão Iniciar processo aparece só para quem pode iniciar, com ou sem linhas", () => {
    const aoIniciar = vi.fn();
    const { rerender } = render(<AbaAguardandoNota linhas={LINHAS} podeIniciar aoIniciar={aoIniciar} />);
    fireEvent.click(screen.getByRole("button", { name: /Iniciar processo de medição/ }));
    expect(aoIniciar).toHaveBeenCalledOnce();
    rerender(<AbaAguardandoNota linhas={[]} podeIniciar aoIniciar={aoIniciar} />);
    expect(screen.getByRole("button", { name: /Iniciar processo de medição/ })).toBeTruthy();
    rerender(<AbaAguardandoNota linhas={LINHAS} podeIniciar={false} aoIniciar={aoIniciar} />);
    expect(screen.queryByRole("button", { name: /Iniciar processo/ })).toBeNull();
  });

  it("sem medição esperando nota: estado vazio, sem tabela", () => {
    render(<AbaAguardandoNota linhas={[]} podeIniciar aoIniciar={() => {}} />);
    expect(screen.getByText("Nenhuma medição esperando nota.")).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });
});
