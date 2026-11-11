import { cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EVENTO_LEITURA_FEITA, EVENTO_RESPOSTAS_LIDAS, useLeituraDasRespostas } from "./respostasOrgao";

const { api } = vi.hoisted(() => ({ api: vi.fn(async (): Promise<unknown> => ({ novas: [] })) }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

function Tela({ ativo }: { ativo: boolean }) {
  useLeituraDasRespostas(ativo);
  return null;
}

describe("Disparo da leitura das respostas do órgão (issue #644)", () => {
  beforeEach(() => { vi.useFakeTimers(); api.mockClear(); });
  afterEach(() => { cleanup(); vi.useRealTimers(); });

  it("quem envia: lê ao entrar e de novo a cada 5 minutos", async () => {
    render(<Tela ativo />);
    expect(api.mock.calls).toEqual([["/api/correio/respostas/ler", { method: "POST" }]]);
    await vi.advanceTimersByTimeAsync(5 * 60_000);
    expect(api).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(4 * 60_000);
    expect(api).toHaveBeenCalledTimes(2);
  });

  it("quem só consulta (diretoria) não dispara leitura", async () => {
    render(<Tela ativo={false} />);
    await vi.advanceTimersByTimeAsync(11 * 60_000);
    expect(api).not.toHaveBeenCalled();
  });

  it("resposta nova avisa as telas abertas; leitura vazia ou com falha, não", async () => {
    const ouvir = vi.fn();
    window.addEventListener(EVENTO_RESPOSTAS_LIDAS, ouvir);
    api.mockResolvedValueOnce({ novas: [{ id: 1 }] }).mockRejectedValueOnce(new Error("fora do ar"));
    render(<Tela ativo />);
    await vi.advanceTimersByTimeAsync(0);
    expect(ouvir).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(10 * 60_000);
    expect(api).toHaveBeenCalledTimes(3);
    expect(ouvir).toHaveBeenCalledTimes(1);
    window.removeEventListener(EVENTO_RESPOSTAS_LIDAS, ouvir);
  });

  it("toda leitura respondida avisa o aviso flutuante, com ou sem resposta nova; a que falhou, não (issue #654)", async () => {
    const ouvir = vi.fn();
    window.addEventListener(EVENTO_LEITURA_FEITA, ouvir);
    api.mockResolvedValueOnce({ novas: [] }).mockRejectedValueOnce(new Error("fora do ar")).mockResolvedValueOnce({ novas: [{ id: 1 }] });
    render(<Tela ativo />);
    await vi.advanceTimersByTimeAsync(0);
    expect(ouvir).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(5 * 60_000);
    expect(ouvir).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(5 * 60_000);
    expect(ouvir).toHaveBeenCalledTimes(2);
    window.removeEventListener(EVENTO_LEITURA_FEITA, ouvir);
  });
});
