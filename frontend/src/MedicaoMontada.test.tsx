import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Medicao } from "./Medicoes";
import { FaixaPasso, PassoCartao, Passos } from "./Passos";
import { LinhaDoTempo, ResumoMedicao, ValorDaPagina } from "./ResumoLateral";

// #722: a pagina da medicao como o dono montou (16/11/2026). As pecas do alto e da barra, sem a pagina em volta:
// as abas dos passos, o valor grande com o rotulo dele, o Resumo em faixa e a Linha do tempo.

const MEDICAO = { id: 5, numero: 5, tipo: "execucao", competencia: "2026-09", estado: "nota_emitida",
  valor_protocolado_centavos: 128450001, valor_protocolado_origem: null, valor_atestado_centavos: 125132047,
  valor_atestado_origem: null, atestado_em: "2026-11-09", nf_emitida_em: null, recebida_em: null, congelada: 0, final: 0,
  protocolos: [], notas: [], documentos: [] } as unknown as Medicao;
const com = (extra: Record<string, unknown>) => ({ ...MEDICAO, ...extra }) as unknown as Medicao;
const aqui = { tela: "medicao" as const, obra: 12, id: 5 };

afterEach(cleanup);

describe("abas dos passos (#722)", () => {
  const barra = (extra: Partial<Parameters<typeof Passos>[0]> = {}) => {
    const aoIr = vi.fn();
    render(<Passos passos={[1, 2, 3, 4, 5, 6]} atual={3} vendo={3} datas={{ 1: "19/10", 2: "09/11" }} aoIr={aoIr} {...extra} />);
    return aoIr;
  };
  const aba = (nome: RegExp) => screen.getByRole("button", { name: nome }).closest("li")!;

  it("cada aba traz o número do passo, o nome e a situação: feito com a data, o da vez em andamento, o futuro sem sinal", () => {
    barra();
    const feito = aba(/^Passo 1: Planilha e carta, feito em 19\/10$/);
    expect(feito.className).toBe("passo passo--feito");
    expect(feito.querySelector(".passo__num")!.textContent).toBe("1");
    expect(feito.querySelector(".glifo--feito")).not.toBeNull();
    expect(feito.querySelector(".passo__data")!.textContent).toBe("19/10");
    const atual = aba(/^Passo 3: Espelhos$/);
    expect(atual.className).toBe("passo passo--atual passo--aberto");
    expect(atual.getAttribute("aria-current")).toBe("step");
    expect(atual.querySelector(".glifo--andamento")).not.toBeNull();
    expect(atual.querySelector(".passo__data")).toBeNull();
    const futuro = aba(/^Passo 6: Pagamento$/);
    expect(futuro.className).toBe("passo passo--futuro");
    expect(futuro.querySelector(".glifo")).toBeNull();
    expect(futuro.querySelector(".passo__num")!.textContent).toBe("6");
  });

  it("o clique na aba pede o passo dela; a aba aberta pode ser outra que não a da vez", () => {
    const aoIr = barra({ vendo: 1 });
    expect(aba(/^Passo 1: /).className).toContain("passo--aberto");
    expect(aba(/^Passo 3: /).className).not.toContain("passo--aberto");
    fireEvent.click(screen.getByRole("button", { name: /^Passo 2: Análise do órgão/ }));
    expect(aoIr).toHaveBeenCalledWith(2);
  });

  it("na obra sem planilha/carta as quatro abas levam os números 1 a 4; a metade em espera leva o sinal de atenção", () => {
    barra({ passos: [3, 4, 5, 6], atual: 5, vendo: 5, datas: {}, espera: true });
    expect(screen.getAllByRole("listitem").map(li => li.querySelector(".passo__num")!.textContent)).toEqual(["1", "2", "3", "4"]);
    const espera = aba(/^Passo 3: Envio da nota · em espera$/);
    expect(espera.className).toBe("passo passo--espera passo--aberto");
    expect(espera.querySelector(".glifo--breve")).not.toBeNull();
  });

  it("medição cancelada no passo 3: só os passos com data levam o visto; os que não aconteceram ficam sem sinal", () => {
    // `atual` 0 = encerrada por excecao; a planilha foi enviada e o boletim chegou, e nada mais aconteceu
    barra({ atual: 0, vendo: 1, datas: { 1: "19/10", 2: "09/11", 3: null, 4: null, 5: null, 6: null } });
    for (const n of [1, 2]) {
      const feito = aba(new RegExp(`^Passo ${n}: .*, feito em`));
      expect(feito.className).toContain("passo--feito");
      expect(feito.querySelector(".glifo--feito")).not.toBeNull();
    }
    for (const nome of ["Espelhos", "Notas", "Envio da nota", "Pagamento"]) {
      const li = screen.getByRole("button", { name: new RegExp(`^Passo \\d: ${nome}$`) }).closest("li")!;
      expect(li.className).toBe("passo passo--encerrado");
      expect(li.querySelector(".glifo")).toBeNull();
      expect(li.getAttribute("aria-current")).toBeNull();
    }
    // nenhum passo e' "o da vez" numa medicao encerrada
    expect(document.querySelectorAll(".glifo--andamento")).toHaveLength(0);
    cleanup();
    // fora da excecao, o passo feito sem data conhecida continua com o visto
    barra({ atual: 4, vendo: 4, datas: { 1: "19/10" } });
    expect(aba(/^Passo 2: Análise do órgão$/).className).toBe("passo passo--feito");
    expect(aba(/^Passo 2: Análise do órgão$/).querySelector(".glifo--feito")).not.toBeNull();
  });

  it("o passo futuro abre dentro do painel com o nome e “Libera depois do passo N”; a faixa oferece voltar ao passo da vez", () => {
    const aoVoltar = vi.fn();
    render(<>
      <FaixaPasso vendo={5} atual={3} passos={[1, 2, 3, 4, 5, 6]} aoVoltar={aoVoltar} />
      <PassoCartao n={5} atual={3} passos={[1, 2, 3, 4, 5, 6]} />
    </>);
    const passo = screen.getByRole("region", { name: "Envio da nota" });
    expect(within(passo).getByRole("heading", { name: "Envio da nota", level: 2 })).toBeTruthy();
    expect(within(passo).getByText("Passo 5")).toBeTruthy();
    expect(within(passo).getByText("Libera depois do passo 4")).toBeTruthy();
    expect(screen.getByText("Você está vendo o passo 5")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Voltar ao passo atual" }));
    expect(aoVoltar).toHaveBeenCalled();
  });
});

describe("o valor grande do alto (#722)", () => {
  const valor = (m: Medicao, extra: Partial<Parameters<typeof ValorDaPagina>[0]> = {}) => {
    const aoEditarValor = vi.fn();
    render(<ValorDaPagina m={m} doPar={false} valor={m.valor_protocolado_centavos} podeEditar salvando={false} aoEditarValor={aoEditarValor} {...extra} />);
    return aoEditarValor;
  };

  it("leva o rótulo “Valor da medição” até o protocolo, “Protocolado” depois e “Total” no par; o centavo ímpar aparece inteiro", () => {
    valor(MEDICAO);
    expect(screen.getByText("Valor da medição")).toBeTruthy();
    expect(screen.getByLabelText(/^Valor: R\$\s1\.284\.500,01$/).textContent).toMatch(/^R\$\s1\.284\.500,01$/);
    cleanup();
    valor(com({ estado: "protocolada" }));
    expect(screen.getByText("Protocolado")).toBeTruthy();
    cleanup();
    valor(MEDICAO, { doPar: true, valor: 128450001 + 50000 });
    expect(screen.getByText("Total")).toBeTruthy();
    expect(screen.getByLabelText(/^Valor: R\$\s1\.285\.000,01$/)).toBeTruthy();
  });

  it("“Editar o valor” fica ao lado do rótulo só quando o valor se edita à mão; sem valor é “Definir o valor”", () => {
    const aoEditarValor = valor(MEDICAO);
    fireEvent.click(screen.getByRole("button", { name: "Editar o valor" }));
    expect(aoEditarValor).toHaveBeenCalled();
    cleanup();
    valor(com({ valor_protocolado_centavos: null }));
    expect(screen.getByRole("button", { name: "Definir o valor" })).toBeTruthy();
    expect(screen.getByLabelText("Valor: —")).toBeTruthy();
    cleanup();
    // quem so' consulta e a medicao congelada nao editam
    valor(MEDICAO, { podeEditar: false });
    expect(screen.queryByRole("button")).toBeNull();
    cleanup();
    valor(com({ congelada: 1 }));
    expect(screen.queryByRole("button")).toBeNull();
    cleanup();
    valor(MEDICAO, { salvando: true });
    expect((screen.getByRole("button", { name: "Editar o valor" }) as HTMLButtonElement).disabled).toBe(true);
  });
});

describe("Resumo em faixa e Linha do tempo (#722)", () => {
  const resumo = (m: Medicao, extra: Partial<Parameters<typeof ResumoMedicao>[0]> = {}) => {
    render(<ResumoMedicao m={m} execucao={null} reajuste={null} outras={[]} passo={{ rotulo: "Envio da nota", secao: "passo-5" }}
      aqui={aqui} contratoId={12} podeEditar salvando={false} aoEditarValor={() => {}} {...extra} />);
    return screen.getByRole("region", { name: "Resumo da medição" });
  };
  const celula = (r: HTMLElement, rotulo: string) => within(r).getByText(rotulo).closest("div")!;

  it("mostra situação, próximo passo, competência, atestado, medição final e da mesma competência; o valor fica no alto", () => {
    const r = resumo(MEDICAO);
    expect(within(r).getAllByRole("term").map(x => x.textContent)).toEqual(
      ["Situação", "Próximo passo", "Competência", "Atestado", "Medição final", "Da mesma competência"]);
    expect(celula(r, "Situação").textContent).toBe("SituaçãoNota emitida");
    expect(celula(r, "Situação").querySelector(".glifo--andamento")).not.toBeNull();
    expect(within(r).getByRole("link", { name: "Envio da nota" }).getAttribute("href")).toBe("/obras/12/medicoes/5#passo-5");
    expect(celula(r, "Competência").textContent).toBe("Competência09/2026");
    expect(celula(r, "Atestado").textContent).toMatch(/^AtestadoR\$\s1\.251\.320,47atestada em 09\/11\/2026$/);
    expect(celula(r, "Medição final").textContent).toBe("Medição finalNão");
    expect(celula(r, "Da mesma competência").textContent).toBe("Da mesma competência—");
    expect(within(r).queryByText("Valor da medição")).toBeNull();
  });

  it("a situação diz a verdade: recebida leva o visto de feito, a medição em curso o sinal de andamento, a cancelada fica riscada e sem sinal", () => {
    let r = resumo(com({ estado: "recebida", final: 1, congelada: 1 }));
    expect(celula(r, "Situação").querySelector(".glifo--feito")).not.toBeNull();
    expect(celula(r, "Situação").querySelector(".glifo--andamento")).toBeNull();
    expect(within(celula(r, "Situação")).getByText("Recebida")).toBeTruthy();
    expect(within(celula(r, "Situação")).getByText("final")).toBeTruthy();
    expect(within(celula(r, "Situação")).getByRole("img", { name: "Congelada" })).toBeTruthy();
    expect(celula(r, "Medição final").textContent).toBe("Medição finalSim");
    cleanup();
    r = resumo(com({ estado: "prevista" }));
    expect(celula(r, "Situação").querySelector(".glifo--andamento")).not.toBeNull();
    cleanup();
    r = resumo(com({ estado: "cancelada" }));
    expect(celula(r, "Situação").querySelector(".glifo")).toBeNull();
    expect(celula(r, "Situação").querySelector(".estado--excecao")).not.toBeNull();
  });

  it("no par, o valor de cada metade fica no resumo (o total é o valor grande); o passo que abre janela vira botão", () => {
    const aoAcao = vi.fn();
    const reajuste = com({ id: 6, tipo: "reajuste", valor_protocolado_centavos: 50001 });
    const r = resumo(MEDICAO, { execucao: MEDICAO, reajuste, passo: { rotulo: "Registrar o boletim", secao: "", acao: "boletim" }, aoAcao,
      outras: [com({ id: 9, tipo: "projeto", estado: "prevista" })] });
    // a pagina aberta e' a da execucao, com o valor editavel: o link de editar fica junto do valor dela
    expect(celula(r, "Valor da medição").textContent).toMatch(/^Valor da mediçãoR\$\s1\.284\.500,01Editar o valor$/);
    expect(celula(r, "Reajuste").textContent).toMatch(/^ReajusteR\$\s500,01$/);
    expect(within(r).queryByText("Total")).toBeNull();
    fireEvent.click(within(r).getByRole("button", { name: "Registrar o boletim" }));
    expect(aoAcao).toHaveBeenCalledWith("boletim");
    expect(within(celula(r, "Da mesma competência")).getByRole("link").getAttribute("href")).toBe("/obras/12/medicoes/9");
  });

  it("no par, “Editar o valor” fica junto do valor da metade que ele edita, nunca ao lado do Total", () => {
    const reajuste = com({ id: 6, tipo: "reajuste", valor_protocolado_centavos: 50001 });
    // a pagina aberta e' a do reajuste: o link fica na celula do reajuste
    const aoEditarValor = vi.fn();
    let r = resumo(reajuste, { execucao: MEDICAO, reajuste, aoEditarValor });
    expect(within(celula(r, "Valor da medição")).queryByRole("button")).toBeNull();
    fireEvent.click(within(celula(r, "Reajuste")).getByRole("button", { name: "Editar o valor" }));
    expect(aoEditarValor).toHaveBeenCalledTimes(1);
    expect(within(r).getAllByRole("button")).toHaveLength(1);
    cleanup();
    // a pagina aberta e' a da execucao: o link fica na celula dela
    r = resumo(MEDICAO, { execucao: MEDICAO, reajuste });
    expect(within(celula(r, "Valor da medição")).getByRole("button", { name: "Editar o valor" })).toBeTruthy();
    expect(within(celula(r, "Reajuste")).queryByRole("button")).toBeNull();
    cleanup();
    // o valor grande do par (o Total) nao leva o link
    render(<ValorDaPagina m={MEDICAO} doPar valor={128450001 + 50001} podeEditar salvando={false} aoEditarValor={() => {}} />);
    expect(screen.getByText("Total")).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
    cleanup();
    // fora do par o resumo nao repete o link (ele fica ao lado do rotulo do valor grande); quem so' consulta nao ve
    r = resumo(MEDICAO);
    expect(within(r).queryByRole("button")).toBeNull();
    cleanup();
    r = resumo(MEDICAO, { execucao: MEDICAO, reajuste, podeEditar: false });
    expect(within(r).queryByRole("button")).toBeNull();
  });

  it("o sinal da situação fica preso ao nome dela; só o selo “final” e o cadeado ficam fora", () => {
    const r = resumo(com({ estado: "planilha_enviada", final: 1, congelada: 1 }));
    const nome = within(r).getByText("Planilha/carta enviada").parentElement!;
    expect(nome.className).toBe("med-situacao__nome");
    expect(nome.firstElementChild!.className).toBe("glifo glifo--andamento");
    expect(nome.children).toHaveLength(2);
    expect(within(nome).queryByText("final")).toBeNull();
    expect(within(nome.parentElement!).getByText("final")).toBeTruthy();
    expect(within(nome.parentElement!).getByRole("img", { name: "Congelada" })).toBeTruthy();
  });

  it("a linha do tempo lista do mais novo ao mais antigo, com a data sobre o texto e o link do boletim", () => {
    render(<LinhaDoTempo eventos={[
      { data: "2026-10-20", texto: "Nº do SIGA da planilha/carta: 2026.10.004512" },
      { data: "2026-11-09 18:42:00", texto: "Boletim nº 05/2026 (SMO)", href: "/api/medicoes/5/boletins/1/arquivo" }]} />);
    const tempo = screen.getByRole("region", { name: "Linha do tempo" });
    const itens = within(tempo).getAllByRole("listitem");
    expect(itens).toHaveLength(2);
    expect(itens[0].querySelector("time")!.textContent).toMatch(/^09\/11\/2026 às \d{2}:42$/);
    expect(itens[0].querySelector("p")!.textContent).toBe("Boletim nº 05/2026 (SMO) Ver o boletim");
    expect(within(itens[0]).getByRole("link", { name: "Ver o boletim" }).getAttribute("href")).toBe("/api/medicoes/5/boletins/1/arquivo");
    expect(itens[1].querySelector("time")!.textContent).toBe("20/10/2026");
    cleanup();
    render(<LinhaDoTempo eventos={[]} />);
    expect(screen.getByText("Nada registrado ainda.")).toBeTruthy();
  });
});
