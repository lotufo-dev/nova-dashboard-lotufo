import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import CampoValor from "./CampoValor";
import { coladoParaBrl, digitosParaBrl } from "./formato";

// Campo de valor da issue #190: digitos pela direita, 2 casas, sem float.
function Campo({ inicial = "" }: { inicial?: string }) {
  const [v, setV] = useState(inicial);
  return <><label htmlFor="v">Valor</label><CampoValor id="v" name="v" value={v} onChange={setV} /></>;
}

const campo = () => screen.getByLabelText("Valor") as HTMLInputElement;
// O navegador manda um InputEvent com o tipo da edicao (inputType) e o texto que entrou (data); `depois` e' o
// texto que o campo teria sem o componente (o que o navegador montou).
const editar = (depois: string, inputType: string, data: string | null = null) =>
  fireEvent.input(campo(), { target: { value: depois }, inputType, data });
// teclar com o cursor no fim
const digitar = (texto: string) => { for (const c of texto) editar(campo().value + c, "insertText", c); };
const apagar = (depois = campo().value.slice(0, -1)) => editar(depois, "deleteContentBackward");
const colar = (texto: string) => fireEvent.paste(campo(), { clipboardData: { getData: () => texto } });

describe("CampoValor", () => {
  afterEach(cleanup);

  it("os dígitos entram pela direita: 1, 12, 1234, 5000000", () => {
    render(<Campo />);
    digitar("1"); expect(campo().value).toBe("0,01");
    digitar("2"); expect(campo().value).toBe("0,12");
    digitar("34"); expect(campo().value).toBe("12,34");
    apagar("");
    digitar("5000000"); expect(campo().value).toBe("50.000,00");
  });

  it("apagar tira o último dígito, até o campo ficar vazio", () => {
    render(<Campo />);
    digitar("12345");
    apagar(); expect(campo().value).toBe("12,34");
    apagar(); expect(campo().value).toBe("1,23");
    apagar(); expect(campo().value).toBe("0,12");
    apagar(); expect(campo().value).toBe("0,01");
    apagar(); expect(campo().value).toBe("");
  });

  it("colar 50.000,00, 50000,5 e 50000 lê em reais", () => {
    render(<Campo />);
    colar("50.000,00"); expect(campo().value).toBe("50.000,00");
    colar("50000,5"); expect(campo().value).toBe("50.000,50");
    colar("50000"); expect(campo().value).toBe("50.000,00");
    colar("R$ 1.234.567,89"); expect(campo().value).toBe("1.234.567,89");
  });

  it("colar formato que o servidor recusaria não muda o campo", () => {
    render(<Campo inicial="10,00" />);
    colar("1234.56"); expect(campo().value).toBe("10,00");
    colar("12,345"); expect(campo().value).toBe("10,00");
    colar("abc"); expect(campo().value).toBe("10,00");
  });

  it("vazio continua vazio (vale zero) e letras não entram", () => {
    render(<Campo />);
    expect(campo().value).toBe("");
    digitar("a");
    expect(campo().value).toBe("");
  });

  it("nenhum arredondamento: centavo ímpar e valor grande no teto do servidor", () => {
    render(<Campo />);
    digitar("9999999999999"); expect(campo().value).toBe("99.999.999.999,99");
    digitar("9"); expect(campo().value).toBe("99.999.999.999,99");   // acima do teto: o digito nao entra
    apagar("");
    digitar("123456789"); expect(campo().value).toBe("1.234.567,89");
  });
});

// rodada 1 de correcao da PR #193
describe("CampoValor: cursor, zero, colar inválido e ajuda", () => {
  afterEach(cleanup);

  it("S1: com o cursor no início, o dígito entra no fim e o cursor volta ao fim", () => {
    render(<Campo inicial="12,34" />);
    campo().focus();
    campo().setSelectionRange(0, 0);
    editar("512,34", "insertText", "5");     // o 5 digitado antes do 1
    expect(campo().value).toBe("123,45");
    expect(campo().selectionStart).toBe(6);
    apagar("12,45");                         // apagou o 3 do meio: sai o ultimo digito
    expect(campo().value).toBe("12,34");
    apagar("1234");                          // apagou a virgula: sai o ultimo digito
    expect(campo().value).toBe("1,23");
  });

  it("S1: tudo selecionado e um dígito digitado começa do zero", () => {
    render(<Campo inicial="12,34" />);
    editar("7", "insertText", "7");
    expect(campo().value).toBe("0,07");
  });

  it("S3: digitar 0 ou 00 mostra 0,00 (glosa total); apagar 0,00 volta a vazio", () => {
    render(<Campo />);
    digitar("0"); expect(campo().value).toBe("0,00");
    digitar("0"); expect(campo().value).toBe("0,00");
    digitar("5"); expect(campo().value).toBe("0,05");
    apagar("");
    digitar("00"); expect(campo().value).toBe("0,00");
    apagar(); expect(campo().value).toBe("");
  });

  it("R1: colar fora do formato avisa no campo; o próximo valor certo tira o aviso", () => {
    render(<Campo inicial="10,00" />);
    colar("8900000.00");
    expect(campo().value).toBe("10,00");
    expect(campo().getAttribute("aria-invalid")).toBe("true");
    const erro = screen.getByRole("alert");
    expect(erro.textContent).toContain("Valor colado em formato inválido: use vírgula nos centavos, ex.: 1.234,56");
    expect(campo().getAttribute("aria-describedby")).toContain(erro.id);
    colar("89.000,00");
    expect(campo().value).toBe("89.000,00");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(campo().getAttribute("aria-invalid")).toBeNull();
  });

  it("R3: texto inteiro sem evento de colar é lido em reais", () => {
    render(<Campo />);
    fireEvent.change(campo(), { target: { value: "50000" } });
    expect(campo().value).toBe("50.000,00");
    fireEvent.change(campo(), { target: { value: "8900000.00" } });
    expect(campo().value).toBe("50.000,00");
    expect(screen.getByRole("alert").textContent).toContain("formato inválido");
  });

  it("R2: sem frase de ajuda; o campo aponta para o erro só quando há erro (texto na tela, 26/10/2026)", () => {
    render(<Campo />);
    expect(campo().getAttribute("aria-describedby")).toBeNull();
    expect(screen.queryByText(/Digite só os números/)).toBeNull();
    fireEvent.change(campo(), { target: { value: "8900000.00" } });
    expect(campo().getAttribute("aria-describedby")).toBe("v-erro");
  });
});

// rodada 2 de correcao da PR #193: a edicao se le pelo tipo (inputType), nao pela diferenca dos textos
describe("CampoValor: edição pelo tipo do evento", () => {
  afterEach(cleanup);

  it("C1: tudo selecionado e um dígito igual ao último caractere começa do zero", () => {
    render(<Campo inicial="50.000,00" />);
    editar("0", "insertText", "0");
    expect(campo().value).toBe("0,00");
    cleanup();
    render(<Campo inicial="1.234,56" />);
    editar("6", "insertText", "6");
    expect(campo().value).toBe("0,06");
  });

  it("C2: preenchimento automático troca o valor inteiro (10,00 → 12,00)", () => {
    render(<Campo inicial="10,00" />);
    editar("12,00", "insertReplacementText");
    expect(campo().value).toBe("12,00");
    fireEvent.change(campo(), { target: { value: "15,00" } });   // sem tipo (autofill de alguns navegadores)
    expect(campo().value).toBe("15,00");
  });

  it("C2: desfazer e refazer do navegador não mudam o valor", () => {
    render(<Campo inicial="1,23" />);
    editar("12,34", "historyUndo");
    expect(campo().value).toBe("1,23");
    editar("0,12", "historyRedo");
    expect(campo().value).toBe("1,23");
  });

  it("A1: vários caracteres de uma vez substituem o valor, mesmo com começo e fim iguais ao anterior", () => {
    render(<Campo inicial="9.384.834,18" />);
    editar("9.500.000,00", "insertText", "9.500.000,00");   // tudo selecionado; comeca com "9." como o anterior
    expect(campo().value).toBe("9.500.000,00");
    apagar("");
    digitar("938483418");
    editar("9.384.834,189.500.000,00", "insertText", "9.500.000,00");
    expect(campo().value).toBe("9.500.000,00");
    editar("9.500.000,009.384.834,18", "insertFromDrop", "9.384.834,18");
    expect(campo().value).toBe("9.384.834,18");
    editar("9.384.834,189.500.000,00", "insertFromPaste", "9.500.000,00");
    expect(campo().value).toBe("9.500.000,00");
  });

  it("A2: apagar uma seleção parcial tira um dígito só", () => {
    render(<Campo inicial="12,34" />);
    apagar(",34");   // "12" selecionado e apagado
    expect(campo().value).toBe("1,23");
    editar("1,2", "deleteContentForward");
    expect(campo().value).toBe("0,12");
  });

  it("composição (IME): só o fim dela entra", () => {
    render(<Campo inicial="1,23" />);
    fireEvent.input(campo(), { target: { value: "1,235" }, inputType: "insertCompositionText", data: "5", isComposing: true });
    expect(campo().value).toBe("1,23");
    fireEvent.compositionEnd(campo(), { data: "5" });
    expect(campo().value).toBe("12,35");
  });

  // gate Sol (rodada extra): teclado que manda numeros por composicao (Firefox Android + SwiftKey)
  it("composição sobre o campo inteiro selecionado começa do zero; sem seleção total, acrescenta", () => {
    render(<Campo inicial="12,34" />);
    campo().setSelectionRange(0, 5);
    fireEvent.compositionStart(campo(), { data: "" });
    fireEvent.compositionEnd(campo(), { data: "7" });
    expect(campo().value).toBe("0,07");
    cleanup();
    render(<Campo inicial="12,34" />);
    campo().setSelectionRange(5, 5);
    fireEvent.compositionStart(campo(), { data: "" });
    fireEvent.compositionEnd(campo(), { data: "7" });
    expect(campo().value).toBe("123,47");
  });

  it("C3: com o aviso de colar inválido, o formulário não envia; a próxima edição válida libera", () => {
    const enviar = vi.fn((ev: React.FormEvent) => ev.preventDefault());
    render(<form onSubmit={enviar}><Campo inicial="10,00" /><button type="submit">Salvar</button></form>);
    colar("8900000.00");
    expect(campo().validity.valid).toBe(false);
    expect(campo().validationMessage).toContain("formato inválido");
    fireEvent.click(screen.getByRole("button", { name: "Salvar" }));
    expect(enviar).not.toHaveBeenCalled();
    digitar("1");
    expect(campo().validity.valid).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Salvar" }));
    expect(enviar).toHaveBeenCalledTimes(1);
  });
});

describe("digitosParaBrl e coladoParaBrl", () => {
  it("convertem em texto, sem float", () => {
    expect(digitosParaBrl("")).toBe("");
    expect(digitosParaBrl("007")).toBe("0,07");
    expect(digitosParaBrl("100")).toBe("1,00");
    expect(digitosParaBrl("123456789012")).toBe("1.234.567.890,12");
    expect(coladoParaBrl("0,01")).toBe("0,01");
    expect(coladoParaBrl("0")).toBe("0,00");
    expect(coladoParaBrl("100000000000")).toBeNull();   // R$ 100 bilhoes: acima do teto
  });
});
