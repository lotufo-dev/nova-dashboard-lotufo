import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ApiErro } from "./api";
import LiberarEnvio, { envioReservado, type Reserva } from "./LiberarEnvio";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", () => ({
  api,
  ApiErro: class ApiErro extends Error {
    status: number;
    corpo?: unknown;
    constructor(status: number, mensagem: string, corpo?: unknown) { super(mensagem); this.status = status; this.corpo = corpo; }
  },
}));

const RESERVA: Reserva = {
  mensagem: "Este envio está em andamento ou foi interrompido (iniciado às 10:05 por Leo).", codigo: "ENVIO_RESERVADO",
  reservado_em: "2026-10-10T10:05:00-04:00", reservado_por_nome: "Leo", liberavel_a_partir_de: "2026-10-10T10:20:00-04:00",
};

describe("LiberarEnvio", () => {
  it("decide pelo codigo do erro, nao pelo texto", () => {
    expect(envioReservado(new ApiErro(409, RESERVA.mensagem, RESERVA))).toBe(true);
    expect(envioReservado(new ApiErro(409, RESERVA.mensagem, { ...RESERVA, codigo: "ENVIO_CONCLUIDO_NO_MEIO" }))).toBe(false);
    expect(envioReservado(new ApiErro(409, RESERVA.mensagem))).toBe(false);          // texto igual, sem codigo
    expect(envioReservado(new ApiErro(422, RESERVA.mensagem, RESERVA))).toBe(false);
    expect(envioReservado(new Error(RESERVA.mensagem))).toBe(false);
  });

  it("mostra quem iniciou, exige a declaracao e libera", async () => {
    api.mockResolvedValue({ ok: true });
    const aoLiberar = vi.fn();
    render(<LiberarEnvio tabela="espelhos" id={7} reserva={RESERVA} aoLiberar={aoLiberar} />);
    expect(screen.getByText(/Iniciado às 10:05 por Leo/)).toBeTruthy();
    expect(screen.getByText(/a partir das 10:20/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText(/Por que liberar/), { target: { value: "conferi os Enviados: não saiu" } });
    const botao = screen.getByRole("button", { name: "Liberar envio" }) as HTMLButtonElement;
    expect(botao.disabled).toBe(true);                                                // sem a declaracao, nao libera
    fireEvent.click(screen.getByLabelText(/Conferi a caixa de Enviados do Outlook e este e-mail NÃO consta/));
    expect(botao.disabled).toBe(false);
    fireEvent.click(botao);
    expect(await screen.findByText("Trava removida. Confira os dados e envie de novo.")).toBeTruthy();
    await waitFor(() => expect(aoLiberar).toHaveBeenCalled());
    expect(api).toHaveBeenCalledWith("/api/envios/liberar", expect.objectContaining({ method: "POST" }));
    expect(JSON.parse(api.mock.calls[0][1].body)).toEqual({
      tabela: "espelhos", id: 7, justificativa: "conferi os Enviados: não saiu", conferi_enviados: true });
  });

  it("sem a reserva (aberto pelo menu), nenhuma frase de apoio: só o campo, a declaração e o botão", () => {
    const { container } = render(<LiberarEnvio tabela="protocolos" id={3} aoLiberar={() => {}} />);
    expect(container.querySelector(".campo__nota")).toBeNull();
    expect(screen.queryByText(/15 minutos|não sabe se o e-mail saiu/)).toBeNull();
    expect(screen.getByRole("button", { name: "Liberar envio" })).toBeTruthy();
  });
});
