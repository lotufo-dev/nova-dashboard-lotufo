import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AvisoRespostas from "./AvisoRespostas";
import { EVENTO_LEITURA_FEITA } from "./respostasOrgao";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

const aviso = (n: number, extra: object = {}) => ({ medicao_id: 30 + n, contrato_id: 7, orgao: "SINFRA", obra: `Obra ${n}`,
  numero: n, tipo: "execucao", respostas: 1, ate: 100 + n, recebida_em: "2026-11-10T14:00:00Z", ...extra });

/** `naoVistas` e' o que o servidor guarda: marcar como vista tira de la', como no banco. */
function servidor(naoVistas: ReturnType<typeof aviso>[]) {
  api.mockImplementation(async (caminho: string, opcoes?: { method?: string }) => {
    if (caminho === "/api/correio/respostas/nao-vistas") return [...naoVistas];
    const m = /^\/api\/correio\/respostas\/vistas\/(\d+)$/.exec(caminho);
    if (m && opcoes?.method === "POST") {
      const i = naoVistas.findIndex(a => a.medicao_id === Number(m[1]));
      if (i >= 0) naoVistas.splice(i, 1);
      return { marcadas: 1 };
    }
    return [];
  });
}
const marcacoes = () => api.mock.calls.filter(c => String(c[0]).includes("/vistas/"));

describe("Aviso flutuante de resposta do órgão (issue #654)", () => {
  const ir = vi.fn();
  beforeEach(() => { api.mockReset(); ir.mockReset(); });
  afterEach(cleanup);

  it("ao entrar, mostra a resposta ainda não vista, anunciada por aria-live e sem roubar o foco", async () => {
    servidor([aviso(1)]);
    render(<AvisoRespostas ir={ir} />);
    const regiao = screen.getByRole("status");
    expect(regiao.getAttribute("aria-live")).toBe("polite");       // a regiao existe antes de o aviso chegar
    expect(await within(regiao).findByText("SINFRA respondeu:")).toBeTruthy();
    expect(regiao.textContent).toContain("SINFRA respondeu: Obra 1, 1ª Medição");
    expect(within(regiao).getByRole("link", { name: "Ver resposta" }).getAttribute("href")).toBe("/obras/7/medicoes/31#passo-2");
    expect(document.activeElement).toBe(document.body);
  });

  it("sem resposta não vista, nada aparece", async () => {
    servidor([]);
    render(<AvisoRespostas ir={ir} />);
    await act(async () => {});
    expect(screen.getByRole("status").textContent).toBe("");
  });

  it("depois de uma leitura, a resposta nova aparece sem recarregar", async () => {
    const guardadas: ReturnType<typeof aviso>[] = [];
    servidor(guardadas);
    render(<AvisoRespostas ir={ir} />);
    await act(async () => {});
    guardadas.push(aviso(2, { tipo: "reajuste" }));
    await act(async () => { window.dispatchEvent(new Event(EVENTO_LEITURA_FEITA)); });
    expect(await screen.findByText("SINFRA respondeu:")).toBeTruthy();
    expect(screen.getByRole("status").textContent).toContain("Obra 2, Reajuste da 2ª Medição");
  });

  it("\"Ver resposta\" abre a medição no passo de análise, marca como vista e o aviso some", async () => {
    servidor([aviso(1)]);
    render(<AvisoRespostas ir={ir} />);
    fireEvent.click(await screen.findByRole("link", { name: "Ver resposta" }));
    expect(ir).toHaveBeenCalledWith({ tela: "medicao", obra: 7, id: 31 }, { secao: "passo-2" });
    expect(marcacoes()).toEqual([["/api/correio/respostas/vistas/31", { method: "POST", body: JSON.stringify({ ate: 101 }) }]]);
    expect(screen.queryByText("SINFRA respondeu:")).toBeNull();
  });

  it("fechar marca como vista e o aviso não volta na leitura seguinte nem ao recarregar", async () => {
    const guardadas = [aviso(1)];
    servidor(guardadas);
    const { unmount } = render(<AvisoRespostas ir={ir} />);
    fireEvent.click(await screen.findByRole("button", { name: "Fechar o aviso de Obra 1, 1ª Medição" }));
    expect(screen.queryByText("SINFRA respondeu:")).toBeNull();
    expect(marcacoes()).toEqual([["/api/correio/respostas/vistas/31", { method: "POST", body: JSON.stringify({ ate: 101 }) }]]);
    expect(ir).not.toHaveBeenCalled();
    await act(async () => { window.dispatchEvent(new Event(EVENTO_LEITURA_FEITA)); });
    expect(screen.queryByText("SINFRA respondeu:")).toBeNull();
    unmount();
    render(<AvisoRespostas ir={ir} />);       // recarregou: o servidor ja' nao devolve a resposta
    await act(async () => {});
    expect(screen.queryByText("SINFRA respondeu:")).toBeNull();
  });

  it("aviso fechado não volta se a lista pedida antes de fechar chegar depois; resposta mais nova da mesma medição avisa", async () => {
    let soltar: (v: unknown) => void = () => {};
    const guardadas = [aviso(1)];
    servidor(guardadas);
    render(<AvisoRespostas ir={ir} />);
    const fechar = await screen.findByRole("button", { name: /Fechar o aviso/ });
    api.mockImplementationOnce(() => new Promise(r => { soltar = r; }));
    await act(async () => { window.dispatchEvent(new Event(EVENTO_LEITURA_FEITA)); });
    fireEvent.click(fechar);
    await act(async () => { soltar([aviso(1)]); });                // lista velha: ainda trazia o aviso fechado
    expect(screen.queryByText("SINFRA respondeu:")).toBeNull();
    guardadas.splice(0, guardadas.length, aviso(1, { ate: 150 }));  // chegou outra resposta na mesma medicao
    await act(async () => { window.dispatchEvent(new Event(EVENTO_LEITURA_FEITA)); });
    expect(await screen.findByText("SINFRA respondeu:")).toBeTruthy();
  });

  it("empilha até três avisos e resume o resto em \"e mais N\"", async () => {
    servidor([1, 2, 3, 4, 5].map(n => aviso(n)));
    render(<AvisoRespostas ir={ir} />);
    expect(await screen.findAllByRole("link", { name: "Ver resposta" })).toHaveLength(3);
    expect(screen.getByText("e mais 2")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Fechar o aviso de Obra 1, 1ª Medição" }));
    expect(screen.getAllByRole("link", { name: "Ver resposta" })).toHaveLength(3);     // o quarto sobe
    expect(screen.getByText("e mais 1")).toBeTruthy();
  });

  it("falha ao ler a lista não aparece na tela", async () => {
    api.mockRejectedValue(new Error("fora do ar"));
    render(<AvisoRespostas ir={ir} />);
    await act(async () => {});
    expect(screen.getByRole("status").textContent).toBe("");
  });
});
