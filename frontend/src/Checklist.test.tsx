import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import Checklist from "./Checklist";

afterEach(() => cleanup());

const itens = [{ chave: "planilha", rotulo: "Planilha", situacao: "anexada" as const,
  arquivos: [{ id: 9, nome: "planilha.pdf", tamanho: 2048 }] }];

// issue #28: remover peça ou anexo pede confirmação antes do pedido (protocolo e ofício usam este checklist)
test("Remover a peça pede confirmação; Cancelar não remove nada", () => {
  const aoRemover = vi.fn();
  render(<Checklist itens={itens} legenda="Peças" editavel ocupado={false} aoAnexar={() => {}} aoRemover={aoRemover} />);
  fireEvent.click(screen.getByRole("button", { name: "Remover planilha.pdf" }));
  expect(aoRemover).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));
  expect(aoRemover).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Remover planilha.pdf" }));
  fireEvent.click(screen.getByRole("button", { name: /Confirmar a remoção:\s*planilha\.pdf/ }));
  expect(aoRemover).toHaveBeenCalledWith(9);
});

// texto na tela (26/10/2026): a peca mostra o nome e o arquivo, sem o tamanho
test("a peça não mostra o tamanho do arquivo", () => {
  render(<Checklist itens={itens} legenda="Peças" editavel={false} ocupado={false}
    aoAnexar={() => {}} aoRemover={() => {}} />);
  expect(screen.getByText("planilha.pdf")).toBeTruthy();
  expect(screen.queryByText(/KB/)).toBeNull();
});
