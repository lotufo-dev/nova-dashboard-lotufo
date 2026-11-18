/// <reference types="node" />
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import CaixaAviso from "./CaixaAviso";
import ConfirmarFaltas from "./ConfirmarFaltas";
import JustificativaEnvio from "./JustificativaEnvio";

// #720: trava, confirmacao e justificativa tem formas distintas. Trava: bloco cheio no critico, com o botao da acao
// desligado. Confirmacao: faixa amarela com o triangulo e o botao ativo. Justificativa: caixa de moldura grossa com
// o campo obrigatorio. O jsdom nao aplica CSS: aqui a marcacao de cada forma e a regra dela em tokens.css.
const tokensCss = readFileSync(join(process.cwd(), "src", "tokens.css"), "utf8");
const regra = (seletor: string) => new RegExp(`(?:^|\\n)${seletor.replace(/[.[\]()"=*+-]/g, "\\$&")}\\s*\\{([^}]*)\\}`).exec(tokensCss)?.[1] ?? "";

describe("os três casos de aviso", () => {
  afterEach(cleanup);

  it("trava: bloco cheio no crítico com o sinal de proibido; o botão da ação fica desligado", () => {
    render(<>
      <CaixaAviso nivel="trava" role="alert">Envio bloqueado: certidão vencida</CaixaAviso>
      <button type="button" className="btn btn--primario" disabled>Enviar a nota</button>
    </>);
    const caixa = screen.getByRole("alert");
    expect(caixa.className).toBe("aviso aviso--trava");
    expect(caixa.querySelector("svg.icone")).not.toBeNull();       // o sinal de proibido, e nao o glifo de situacao
    expect(caixa.querySelector(".glifo")).toBeNull();
    expect(caixa.textContent).toBe("Crítico: Envio bloqueado: certidão vencida");
    expect((screen.getByRole("button", { name: "Enviar a nota" }) as HTMLButtonElement).disabled).toBe(true);
    // bloco cheio: fundo no tom forte do critico e texto claro por cima
    expect(regra(".aviso--trava")).toMatch(/background:\s*var\(--situacao-critico-ponto\)/);
    expect(regra(".aviso--trava")).toMatch(/color:\s*var\(--cor-sobre-ponto\)/);
  });

  it("confirmação: faixa amarela com o triângulo, e o botão segue ativo", () => {
    const continuar = vi.fn();
    render(<ConfirmarFaltas itens={["Regularidade mensal: não anexada"]} aoCancelar={vi.fn()} aoContinuar={continuar} />);
    const titulo = screen.getByRole("heading", { name: "ATENÇÃO" });
    expect(titulo.className).toContain("aviso");
    expect(titulo.className).not.toMatch(/aviso--/);
    expect(titulo.querySelector(".glifo--breve")).not.toBeNull();
    const botao = screen.getByRole("button", { name: "Continuar com o envio" }) as HTMLButtonElement;
    expect(botao.disabled).toBe(false);
    fireEvent.click(botao);
    expect(continuar).toHaveBeenCalledTimes(1);
    // a mesma faixa na caixa de aviso que nao trava
    cleanup();
    render(<CaixaAviso nivel="atencao" role="status">Envio da planilha/carta não registrado.</CaixaAviso>);
    const faixa = screen.getByRole("status");
    expect(faixa.className).toBe("aviso");
    expect(faixa.querySelector(".glifo--breve")).not.toBeNull();
    expect(faixa.textContent).toBe("Atenção: Envio da planilha/carta não registrado.");
    expect(regra(".aviso")).toMatch(/background:\s*var\(--situacao-breve-fundo\)/);
    expect(regra(".aviso")).toMatch(/border:\s*var\(--borda-situacao-breve\)/);
  });

  it("crítico que não trava (divergência): faixa clara do crítico com o octógono", () => {
    render(<CaixaAviso nivel="critico" como="span">NF 1187 diverge do espelho</CaixaAviso>);
    const faixa = screen.getByText("NF 1187 diverge do espelho").closest(".aviso")!;
    expect(faixa.tagName).toBe("SPAN");
    expect(faixa.className).toBe("aviso aviso--critico");
    expect(faixa.querySelector(".glifo--critico")).not.toBeNull();
    expect(regra(".aviso--critico")).toMatch(/background:\s*var\(--situacao-critico-fundo\)/);
  });

  it("justificativa: caixa de moldura grossa com o campo obrigatório dentro", () => {
    const aoMudar = vi.fn();
    render(<JustificativaEnvio id="just" valor="" aoMudar={aoMudar} notaDivergente />);
    const campo = screen.getByLabelText("Motivo do envio com a nota divergente (obrigatório)");
    const caixa = campo.closest(".justificativa")!;
    expect(caixa).not.toBeNull();
    expect(caixa.querySelector(".aviso, .glifo")).toBeNull();      // nao e' faixa de aviso: e' a caixa do campo
    expect(campo.getAttribute("aria-invalid")).toBeNull();
    fireEvent.change(campo, { target: { value: "ISS retido a maior pela prefeitura" } });
    expect(aoMudar).toHaveBeenCalledWith("ISS retido a maior pela prefeitura");
    expect(regra(".justificativa")).toMatch(/border:\s*var\(--borda-justificativa\)/);
    expect(tokensCss).toMatch(/--borda-justificativa:\s*var\(--borda-grossa\) solid var\(--cor-tinta\)/);
  });

  it("as três formas não se confundem: cada uma tem o próprio fundo e a própria moldura", () => {
    const fundo = (s: string) => /background:\s*([^;]+);/.exec(regra(s))?.[1];
    const moldura = (s: string) => /border:\s*([^;]+);/.exec(regra(s))?.[1];
    expect(new Set([fundo(".aviso--trava"), fundo(".aviso"), fundo(".justificativa")]).size).toBe(3);
    expect(new Set([moldura(".aviso--trava"), moldura(".aviso"), moldura(".justificativa")]).size).toBe(3);
  });
});

describe("campo com erro", () => {
  afterEach(cleanup);

  it("o campo marca aria-invalid, aponta para a mensagem e ganha a moldura do erro", () => {
    render(<JustificativaEnvio id="just" valor="curta" aoMudar={vi.fn()} erro="Escreva a justificativa, com pelo menos 10 caracteres." />);
    const campo = screen.getByLabelText("Justificativa (obrigatória para enviar sem apostilamento)");
    expect(campo.getAttribute("aria-invalid")).toBe("true");
    const erro = screen.getByRole("alert");
    expect(erro.textContent).toBe("Escreva a justificativa, com pelo menos 10 caracteres.");
    expect(campo.getAttribute("aria-describedby")).toBe(erro.id);
    expect(tokensCss).toMatch(/input\[aria-invalid="true"\], select\[aria-invalid="true"\], textarea\[aria-invalid="true"\]\s*\{\s*border:\s*var\(--borda-erro\)/);
    expect(tokensCss).toMatch(/--borda-erro:\s*var\(--borda-grossa\) solid var\(--situacao-critico-texto\)/);
  });
});
