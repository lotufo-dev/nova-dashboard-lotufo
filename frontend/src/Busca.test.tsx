import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Busca from "./Busca";
import { ESPERA_MS, type RespostaBusca } from "./buscaDados";
import { ApiErro } from "./api";

// Busca unica do topo (#819). Obras e orgaos ficticios ou publicos; o servidor aplica o recorte do perfil, a tela
// desenha o que vier.
const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

const CHEIA: RespostaBusca = {
  obras: { itens: [{ id: 7, nome: "Obra Exemplo", instrumento: "001/2026", contratante: "SINFRA", orgao_sub: "SUEF II" }], total: 1 },
  medicoes: { itens: [
    { id: 70, contrato_id: 7, titulo: "15ª Medição", competencia: "2026-10", obra: "Obra Exemplo", contratante: "SINFRA" },
    { id: 71, contrato_id: 8, titulo: "15ª Medição", competencia: "2026-09", obra: "Obra Beta", contratante: "MTPAR" },
  ], total: 12 },
  processos: { itens: [{ id: 3, numero: "ORGAO-PRO-2026/00001", assunto: "Obra Exemplo · 15ª Medição" }], total: 1 },
};
const VAZIA: RespostaBusca = { obras: { itens: [], total: 0 }, medicoes: { itens: [], total: 0 }, processos: { itens: [], total: 0 } };

const campo = () => screen.getByRole("combobox", { name: "Buscar obra, medição ou processo" });
const lista = () => screen.getByRole("listbox", { name: "Resultados da busca" });

function montar(perfil = "engenharia") {
  const ir = vi.fn();
  render(<><button>antes</button><Busca perfil={perfil} ir={ir} /></>);
  return ir;
}

async function digitar(texto: string) {
  fireEvent.focus(campo());
  fireEvent.change(campo(), { target: { value: texto } });
  await waitFor(() => expect(api).toHaveBeenCalled());
}

describe("Busca", () => {
  afterEach(() => { cleanup(); api.mockReset(); });

  it("pergunta ao servidor depois de a pessoa parar de digitar, uma vez so'", async () => {
    api.mockResolvedValue(CHEIA);
    montar();
    fireEvent.focus(campo());
    fireEvent.change(campo(), { target: { value: "1" } });
    fireEvent.change(campo(), { target: { value: "15" } });
    fireEvent.change(campo(), { target: { value: "15ª" } });
    expect(api).not.toHaveBeenCalled();
    await waitFor(() => expect(api).toHaveBeenCalledTimes(1), { timeout: ESPERA_MS * 4 });
    expect(api.mock.calls[0][0]).toBe(`/api/busca?q=${encodeURIComponent("15ª")}`);
    expect(api.mock.calls[0][1].signal).toBeInstanceOf(AbortSignal);
  });

  it("cancela a pergunta anterior quando o texto muda", async () => {
    let primeiro: AbortSignal | undefined;
    api.mockImplementation((_u: string, o: { signal: AbortSignal }) => { primeiro ??= o.signal; return new Promise(() => {}); });
    montar();
    await digitar("obra");
    fireEvent.change(campo(), { target: { value: "obra e" } });
    expect(primeiro?.aborted).toBe(true);
  });

  it("agrupa em Obras, Medições e Processos, cada item com o que o identifica e o endereço dele", async () => {
    api.mockResolvedValue(CHEIA);
    montar();
    await digitar("15");
    const grupos = await within(lista()).findAllByRole("group");
    expect(grupos.map(g => g.getAttribute("aria-labelledby") && document.getElementById(g.getAttribute("aria-labelledby")!)!.firstChild!.textContent))
      .toEqual(["Obras", "Medições", "Processos"]);
    const opcoes = within(lista()).getAllByRole("option");
    expect(opcoes.map(o => o.textContent)).toEqual([
      "Obra ExemploSINFRA · SUEF II",
      "15ª Medição · Obra ExemploSINFRA · 10/2026",
      "15ª Medição · Obra BetaMTPAR · 09/2026",
      "Obra Exemplo · 15ª MediçãoORGAO-PRO-2026/00001",
    ]);
    expect(opcoes.map(o => o.getAttribute("href"))).toEqual(["/obras/7", "/obras/7/medicoes/70", "/obras/8/medicoes/71", "/siga?processo=3"]);
    // a contagem do grupo cortado diz quantos ha' ao todo
    expect(within(grupos[1]).getByText("2 de 12 medições")).toBeTruthy();
    expect(screen.getByText("4 resultados.")).toBeTruthy();
  });

  it("sem processo na resposta (perfil sem SIGA), o grupo nao aparece", async () => {
    const { processos: _p, ...semSiga } = CHEIA;
    api.mockResolvedValue(semSiga);
    montar("diretoria");
    await digitar("15");
    await within(lista()).findAllByRole("option");
    expect(within(lista()).getAllByRole("group")).toHaveLength(2);
    expect(screen.queryByText(/Processos/)).toBeNull();
  });

  it("sem resultado, uma linha diz isso", async () => {
    api.mockResolvedValue(VAZIA);
    montar();
    await digitar("xyzw");
    expect(await screen.findByText("Nada encontrado para “xyzw”.")).toBeTruthy();
    expect(within(lista()).queryAllByRole("option")).toHaveLength(0);
    expect(screen.getByText("Nada encontrado.")).toBeTruthy();       // o aviso do leitor de tela
  });

  it("falha do servidor vira uma linha em portugues", async () => {
    api.mockRejectedValue(new ApiErro(0, "Sem conexão com o servidor."));
    montar();
    await digitar("obra");
    expect((await screen.findByRole("alert")).textContent).toBe("Não deu para buscar agora. Tente de novo em instantes.");
  });

  it("setas andam pelos resultados, Enter abre o item escolhido", async () => {
    api.mockResolvedValue(CHEIA);
    const ir = montar();
    await digitar("15");
    await within(lista()).findAllByRole("option");
    fireEvent.keyDown(campo(), { key: "ArrowDown" });
    fireEvent.keyDown(campo(), { key: "ArrowDown" });
    const opcoes = within(lista()).getAllByRole("option");
    expect(opcoes[1].getAttribute("aria-selected")).toBe("true");
    expect(campo().getAttribute("aria-activedescendant")).toBe(opcoes[1].id);
    fireEvent.keyDown(campo(), { key: "ArrowUp" });
    fireEvent.keyDown(campo(), { key: "ArrowUp" });          // do primeiro volta ao ultimo
    expect(opcoes[3].getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(campo(), { key: "Enter" });
    expect(ir).toHaveBeenCalledWith({ tela: "siga" }, { busca: { processo: "3" } });
    expect((campo() as HTMLInputElement).value).toBe("");
    expect(campo().getAttribute("aria-expanded")).toBe("false");
  });

  it("clique no item abre a pagina dele", async () => {
    api.mockResolvedValue(CHEIA);
    const ir = montar();
    await digitar("15");
    fireEvent.click((await within(lista()).findAllByRole("option"))[1], { button: 0 });
    expect(ir).toHaveBeenCalledWith({ tela: "medicao", obra: 7, id: 70 }, undefined);
  });

  it("o atalho / (fora de campo) e Ctrl+K poem o foco no campo; Esc fecha e devolve o foco", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    try {
      montar();
      const antes = screen.getByRole("button", { name: "antes" });
      antes.focus();
      fireEvent.keyDown(antes, { key: "/" });
      act(() => { vi.advanceTimersByTime(1); });
      expect(document.activeElement).toBe(campo());
      fireEvent.keyDown(campo(), { key: "Escape" });
      expect(document.activeElement).toBe(antes);
      fireEvent.keyDown(antes, { key: "k", ctrlKey: true });
      act(() => { vi.advanceTimersByTime(1); });
      expect(document.activeElement).toBe(campo());
      // "/" digitado dentro do campo e' texto, nao atalho
      const ev = new KeyboardEvent("keydown", { key: "/", bubbles: true, cancelable: true });
      campo().dispatchEvent(ev);
      expect(ev.defaultPrevented).toBe(false);
    } finally {
      vi.useRealTimers();
    }
  });

  it("no celular, o botao da lupa abre o campo e o Fechar o fecha", () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    try {
      montar();
      const lupa = screen.getByRole("button", { name: "Buscar obra, medição ou processo" });
      expect(lupa.getAttribute("aria-expanded")).toBe("false");
      fireEvent.click(lupa);
      act(() => { vi.advanceTimersByTime(1); });
      expect(lupa.getAttribute("aria-expanded")).toBe("true");
      expect(document.querySelector(".busca--aberta")).not.toBeNull();
      fireEvent.click(screen.getByRole("button", { name: "Fechar" }));
      expect(document.querySelector(".busca--aberta")).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });
});
