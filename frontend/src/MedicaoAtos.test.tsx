import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FormProtocoloManual, FormRecebimento, FormValor, notaDoEspelho, valorEditavel } from "./MedicaoAtos";
import type { Medicao } from "./Medicoes";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", () => ({ api }));

const base: Medicao = {
  id: 631, numero: 7, tipo: "execucao", competencia: "2026-09", estado: "nota_emitida",
  valor_protocolado_centavos: 938483418, valor_protocolado_origem: "espelho",
  valor_atestado_centavos: null, valor_atestado_origem: null, atestado_em: null, nf_emitida_em: null,
  recebida_em: null, congelada: 0, protocolos: [],
};

describe("valorEditavel", () => {
  it("valor que veio do espelho não se edita à mão (testes de quebra 10/10, A-16)", () => {
    expect(valorEditavel(base, "protocolado", true)).toBe(false);
    expect(valorEditavel(base, "atestado", true)).toBe(true);
  });

  it("valor aceito ou manual segue editável depois da nota", () => {
    expect(valorEditavel({ ...base, valor_protocolado_origem: "aceito" }, "protocolado", true)).toBe(true);
    expect(valorEditavel({ ...base, valor_protocolado_origem: null, valor_protocolado_centavos: null }, "protocolado", true)).toBe(true);
  });

  it("da planilha/carta ao boletim o pedido só muda por revisão; o atestado segue editável (#281)", () => {
    for (const estado of ["planilha_gerada", "planilha_enviada", "boletim_recebido"]) {
      const m = { ...base, estado, valor_protocolado_origem: "manual" };
      expect(valorEditavel(m, "protocolado", true)).toBe(false);
      expect(valorEditavel(m, "atestado", true)).toBe(true);
    }
  });
});

describe("notaDoEspelho (gate Sol S7)", () => {
  it("diz como mudar o valor que veio do espelho, antes e depois de protocolada", () => {
    expect(notaDoEspelho(base)).toBe("vem do espelho · para mudar, gere o espelho de novo");
    expect(notaDoEspelho({ ...base, congelada: 1 })).toBe("vem do espelho · protocolada: corrija por reapresentação");
    expect(notaDoEspelho({ ...base, valor_protocolado_origem: "aceito" })).toBeNull();
  });
});

// issue #190: o valor se digita como em caixa registradora e vai ao servidor no mesmo formato de antes
// gate Sol S6 (10/10/2026): o servidor exige 10 caracteres para protocolar com pendencia; a tela acompanha
describe("FormProtocoloManual", () => {
  afterEach(() => { cleanup(); api.mockReset(); });

  const PENDENTE = { entidade: "Lotufo", pronto: false,
    itens: [{ entidade_id: 1, entidade: "Lotufo", tipo: "CND Federal", situacao: "pendente" }] };

  // issue #11: o botão não fica apagado; o clique diz o que falta, junto do campo
  it("clicar sem a data mostra o erro no campo da data e não grava", async () => {
    api.mockResolvedValueOnce({ entidade: "Lotufo", pronto: true, itens: [] });
    const agir = vi.fn(async () => true);
    render(<FormProtocoloManual contratoId={1} m={base} salvando={false} agir={agir} aoFechar={() => {}} />);
    await screen.findByText(/em dia para protocolar/);
    const botao = screen.getByRole("button", { name: "Registrar protocolo" }) as HTMLButtonElement;
    expect(botao.disabled).toBe(false);
    fireEvent.click(botao);
    const data = screen.getByLabelText("Data do protocolo");
    expect(data.getAttribute("aria-invalid")).toBe("true");
    expect(document.getElementById(data.getAttribute("aria-describedby") ?? "")?.textContent).toContain("Informe a data do protocolo.");
    expect(agir).not.toHaveBeenCalled();
    fireEvent.change(data, { target: { value: "2026-10-13" } });
    expect(screen.queryByText("Informe a data do protocolo.")).toBeNull();
    fireEvent.click(botao);
    expect(agir).toHaveBeenCalledTimes(1);
  });

  it("com certidão pendente, o clique pede para assumir e justificar com 10 caracteres", async () => {
    api.mockResolvedValueOnce(PENDENTE);
    const agir = vi.fn(async () => true);
    render(<FormProtocoloManual contratoId={1} m={base} salvando={false} agir={agir} aoFechar={() => {}} />);
    const apesar = await screen.findByLabelText(/Protocolar apesar das pendências/);
    fireEvent.change(screen.getByLabelText("Data do protocolo"), { target: { value: "2026-10-13" } });
    const botao = screen.getByRole("button", { name: "Registrar protocolo" }) as HTMLButtonElement;
    expect(botao.disabled).toBe(false);
    fireEvent.click(botao);
    expect(document.getElementById(apesar.getAttribute("aria-describedby") ?? "")?.textContent)
      .toContain("Marque “Protocolar apesar das pendências” e justifique");
    fireEvent.click(apesar);
    expect(screen.queryByText(/Marque “Protocolar apesar/)).toBeNull();
    const just = screen.getByLabelText("Justificativa");
    fireEvent.change(just, { target: { value: "  curta   " } });
    fireEvent.click(botao);
    expect(just.getAttribute("aria-invalid")).toBe("true");
    expect(document.getElementById(just.getAttribute("aria-describedby") ?? "")?.textContent).toContain("pelo menos 10 caracteres");
    expect(agir).not.toHaveBeenCalled();
    fireEvent.change(just, { target: { value: "órgão aceita a CND em 5 dias" } });
    fireEvent.click(botao);
    expect(agir).toHaveBeenCalledTimes(1);
  });
});

// issue #190: o valor se digita como em caixa registradora e vai ao servidor no mesmo formato de antes
describe("FormValor (CampoValor)", () => {
  afterEach(() => { cleanup(); api.mockReset(); });

  it("digitar 5000000 manda \"50.000,00\" ao servidor", async () => {
    api.mockResolvedValue({});
    const agir = vi.fn(async (fn: () => Promise<unknown>) => { await fn(); return true; });
    const m = { ...base, valor_protocolado_origem: null, valor_protocolado_centavos: null };
    render(<FormValor m={m} campo="protocolado" salvando={false} agir={agir} aoFechar={() => {}} />);
    const valor = screen.getByLabelText("Valor (R$)") as HTMLInputElement;
    expect(valor.value).toBe("");
    for (const c of "5000000") fireEvent.input(valor, { target: { value: valor.value + c }, inputType: "insertText", data: c });
    expect(valor.value).toBe("50.000,00");
    fireEvent.click(screen.getByRole("button", { name: "Salvar valor" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/medicoes/631/valor",
      { method: "PUT", body: JSON.stringify({ campo: "protocolado", valor: "50.000,00" }) }));
  });

  // gate Sol S2: com o painel aberto, trocar de campo nao pode levar o valor do outro
  it("trocar de protocolado para atestado com o formulário aberto mostra o valor do atestado", async () => {
    api.mockResolvedValue({});
    const agir = vi.fn(async (fn: () => Promise<unknown>) => { await fn(); return true; });
    const m = { ...base, valor_protocolado_origem: null, valor_atestado_centavos: 12345 };
    const { rerender } = render(<FormValor m={m} campo="protocolado" salvando={false} agir={agir} aoFechar={() => {}} />);
    expect((screen.getByLabelText("Valor (R$)") as HTMLInputElement).value).toBe("9.384.834,18");
    rerender(<FormValor m={m} campo="atestado" salvando={false} agir={agir} aoFechar={() => {}} />);
    expect((screen.getByLabelText("Valor (R$)") as HTMLInputElement).value).toBe("123,45");
    fireEvent.click(screen.getByRole("button", { name: "Salvar valor" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/medicoes/631/valor",
      { method: "PUT", body: JSON.stringify({ campo: "atestado", valor: "123,45" }) }));
  });

  it("o valor gravado abre formatado e apagar tira o último dígito", () => {
    render(<FormValor m={base} campo="protocolado" salvando={false} agir={vi.fn()} aoFechar={() => {}} />);
    const valor = screen.getByLabelText("Valor (R$)") as HTMLInputElement;
    expect(valor.value).toBe("9.384.834,18");
    fireEvent.input(valor, { target: { value: valor.value.slice(0, -1) }, inputType: "deleteContentBackward" });
    expect(valor.value).toBe("938.483,41");
  });

  // rodada 2 da PR #193 (C3): o aviso de colar invalido segura o envio; nada de gravar o valor antigo calado
  it("colar em formato inválido e clicar em Salvar valor não chama o servidor", () => {
    const agir = vi.fn(async () => true);
    render(<FormValor m={{ ...base, valor_atestado_centavos: 890000000 }} campo="atestado" salvando={false} agir={agir} aoFechar={() => {}} />);
    const valor = screen.getByLabelText("Valor (R$)") as HTMLInputElement;
    expect(valor.value).toBe("8.900.000,00");   // valor ja' gravado: o required nao segura
    fireEvent.paste(valor, { clipboardData: { getData: () => "8900000.00" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar valor" }));
    expect(agir).not.toHaveBeenCalled();
    expect(api).not.toHaveBeenCalled();
    expect(screen.getByRole("alert").textContent).toContain("formato inválido");
  });
});

// issue #53: o recebimento a mao exige o motivo (o servidor recusa com menos de 10 caracteres)
describe("FormRecebimento", () => {
  afterEach(() => { cleanup(); api.mockReset(); });
  const protocolada: Medicao = { ...base, estado: "protocolada", congelada: 1 };

  it("sem o motivo mostra o erro no campo e não grava", () => {
    const agir = vi.fn(async () => true);
    render(<FormRecebimento m={protocolada} salvando={false} agir={agir} aoFechar={() => {}} />);
    const motivo = screen.getByLabelText("Motivo");
    fireEvent.change(motivo, { target: { value: "  curto  " } });
    fireEvent.click(screen.getByRole("button", { name: "Registrar recebimento" }));
    expect(agir).not.toHaveBeenCalled();
    expect(motivo.getAttribute("aria-invalid")).toBe("true");
    expect(document.getElementById(motivo.getAttribute("aria-describedby") ?? "")?.textContent)
      .toContain("pelo menos 10 caracteres");
    // conta caractere como o servidor: 5 emojis sao 10 unidades UTF-16, mas 5 caracteres
    fireEvent.change(motivo, { target: { value: "😀😀😀😀😀" } });
    fireEvent.click(screen.getByRole("button", { name: "Registrar recebimento" }));
    expect(agir).not.toHaveBeenCalled();
  });

  it("com o motivo manda o motivo e a data ao servidor", async () => {
    api.mockResolvedValue({ ok: true });
    const agir = vi.fn(async (fn: () => Promise<unknown>) => { await fn(); return true; });
    render(<FormRecebimento m={protocolada} salvando={false} agir={agir} aoFechar={() => {}} />);
    fireEvent.change(screen.getByLabelText("Data da baixa (opcional)"), { target: { value: "2026-09-30" } });
    fireEvent.change(screen.getByLabelText("Motivo"), { target: { value: " a baixa não entrou no RM " } });
    fireEvent.click(screen.getByRole("button", { name: "Registrar recebimento" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/medicoes/631/estado", {
      method: "POST", body: JSON.stringify({ estado: "recebida", motivo: "a baixa não entrou no RM", data: "2026-09-30" }) }));
  });
});
