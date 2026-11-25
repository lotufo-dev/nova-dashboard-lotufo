import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Janela from "./Janela";

describe("Janela", () => {
  afterEach(cleanup);

  function abrir() {
    const aoFechar = vi.fn();
    render(<Janela titulo="Analisar o edital" aoFechar={aoFechar}><input aria-label="Comando" readOnly value="/analisar-edital" /></Janela>);
    return { aoFechar, janela: screen.getByRole("dialog", { name: "Analisar o edital" }), campo: screen.getByLabelText("Comando") };
  }

  it("o clique no fundo fecha", async () => {
    const { aoFechar, janela } = abrir();
    fireEvent.mouseDown(janela);
    fireEvent.click(janela);
    await waitFor(() => expect(aoFechar).toHaveBeenCalledTimes(1));
  });

  it("o clique dentro da caixa não fecha", () => {
    const { aoFechar, campo } = abrir();
    fireEvent.mouseDown(campo);
    fireEvent.click(campo);
    expect(aoFechar).not.toHaveBeenCalled();
  });

  it("selecionar um texto arrastando e soltar o mouse no fundo não fecha", async () => {
    // o navegador manda o clique para o <dialog> (o ancestral comum de onde o mouse apertou e de onde soltou)
    const { aoFechar, janela, campo } = abrir();
    fireEvent.mouseDown(campo);
    fireEvent.click(janela);
    await new Promise(resolve => setTimeout(resolve, 0));
    expect(aoFechar).not.toHaveBeenCalled();
  });
});
