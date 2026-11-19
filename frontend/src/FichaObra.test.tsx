import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { SEM_LEITURA } from "./andamentoTeste";
import FichaObra, { MedicoesAgora, PrazoDaObra, mesAno, type Ficha } from "./FichaObra";

// O alto da pagina da obra (#646, redesenhado na #774) nao le nada: a pagina unica (`ContratoPagina`) le a ficha e
// passa para ca'.
const PRAZOS = { execucao_inicio: "2026-01-01", execucao_fim: "2026-11-18", vigencia_inicio: "2026-01-01", vigencia_fim: "2027-02-16",
  status: "ativo" as const };
const FICHA: Ficha = {
  // base de execucao e cota: 1.000.000,01 − 812.345,67 = 187.654,34
  topo: { vigente_centavos: 100000001, medido_centavos: 81234567, saldo_centavos: 18765434, reajuste_centavos: 0 },
  contrato: { original_centavos: 100000001, original_igual: true, tas: 2, data_base: "2025-01" },
  ultima_medicao: { id: 15, titulo: "15ª Medição", rotulo: "15ª", competencia: "2026-09", valor_centavos: 5000011,
    recebida_em: "2026-10-16", dias_apos_nota: 14 },
  em_andamento: { id: 16, titulo: "16ª Medição", rotulo: "16ª", competencia: "2026-10", valor_centavos: 6000022,
    etapa: "Pagamento", desde: "2026-11-05" },
  // ritmo 50.000,00/mes para 187.654,34 de saldo: conclusao depois do fim da execucao. #803: o fim da execucao cai no
  // mes de hoje, resta 1 competencia e o necessario e' o saldo inteiro
  ritmo: { ritmo_centavos: 5000000, necessario_centavos: 18765434, competencias_restantes: 1, conclusao: "2027-03-08",
    situacao: "atrasa", dias_alem: 110 },
  // #661: so' o que e' da obra; a certidao da empresa saiu daqui
  vencimentos: [
    { chave: "execucao", rotulo: "Fim da execução", data: "2026-11-18", dias: 12, nivel: "critico" }],
};

const regiao = (nome: string) => screen.getByRole("region", { name: nome });
const numero = (rotulo: string) => within(regiao("Resumo da obra")).getByText(rotulo).closest("div")!.querySelector("dd")!;

describe("Resumo da obra: a faixa de números", () => {
  afterEach(cleanup);

  it("valor vigente, medido e saldo vêm do topo da ficha, na mesma base, e o percentual usa os dois (#646)", () => {
    render(<FichaObra ficha={FICHA} />);
    expect(numero("Valor vigente").textContent).toMatch(/^R\$\s1\.000\.000,01$/);
    expect(numero("Medido").textContent).toMatch(/^R\$\s812\.345,67$/);
    expect(numero("Saldo a executar").textContent).toMatch(/^R\$\s187\.654,34$/);
    expect(within(regiao("Resumo da obra")).getByRole("progressbar").getAttribute("aria-valuenow")).toBe("81");
    // o percentual e' numero, nao situacao: sem glifo e sem a cor de "feito"
    const pct = within(regiao("Resumo da obra")).getByText("81% executado");
    expect(pct.className).not.toMatch(/feito|info--/);
    expect(regiao("Resumo da obra").querySelector(".glifo")).toBeNull();
    cleanup();
    // por piso, como na lista de Obras (#779): com 99,96% medido a página dizia "100% executado" ao lado de um saldo
    // a executar, e a lista, 99%
    render(<FichaObra ficha={{ ...FICHA, topo: { vigente_centavos: 1000000, medido_centavos: 999600, saldo_centavos: 400, reajuste_centavos: 0 } }} />);
    expect(within(regiao("Resumo da obra")).getByText("99% executado")).toBeTruthy();
    expect(within(regiao("Resumo da obra")).getByRole("progressbar").getAttribute("aria-valuenow")).toBe("99");
    cleanup();
    // medido acima do vigente: 100% (a barra não passa do fim) e o saldo negativo em crítico
    render(<FichaObra ficha={{ ...FICHA, topo: { vigente_centavos: 1000000, medido_centavos: 1002500, saldo_centavos: -2500, reajuste_centavos: 0 } }} />);
    expect(within(regiao("Resumo da obra")).getByText("100% executado")).toBeTruthy();
    expect(numero("Saldo a executar").className).toContain("obra-numero--critico");
    expect(within(regiao("Resumo da obra")).getByText("original igual · 2 TAs · data-base jan/2025")).toBeTruthy();
    expect(within(regiao("Resumo da obra")).queryByRole("link")).toBeNull();
  });

  it("o reajuste contratado aparece à parte, só quando existe (#646)", () => {
    render(<FichaObra ficha={FICHA} />);
    expect(within(regiao("Resumo da obra")).queryByText("Reajuste contratado")).toBeNull();
    cleanup();
    render(<FichaObra ficha={{ ...FICHA, topo: { ...FICHA.topo, reajuste_centavos: 5000003 } }} />);
    expect(numero("Reajuste contratado").textContent).toMatch(/50\.000,03/);
    // o valor vigente continua o de execucao, sem o reajuste
    expect(numero("Valor vigente").textContent).toMatch(/1\.000\.000,01/);
  });

  it("saldo negativo é crítico: a cor e o glifo", () => {
    render(<FichaObra ficha={{ ...FICHA, topo: { vigente_centavos: 100, medido_centavos: 151, saldo_centavos: -51, reajuste_centavos: 0 } }} />);
    const saldo = numero("Saldo a executar");
    expect(saldo.textContent).toMatch(/−R\$\s0,51/);
    expect(saldo.className).toContain("obra-numero--critico");
    expect(saldo.querySelector(".glifo--critico")).toBeTruthy();
  });

  it("carregando e falha da ficha: sem número inventado", () => {
    render(<FichaObra ficha={null} />);
    expect(within(regiao("Resumo da obra")).getByRole("alert").textContent).toBe("indisponível agora");
    expect(screen.queryByText(/R\$/)).toBeNull();
    cleanup();
    render(<FichaObra ficha={undefined} />);
    expect(within(regiao("Resumo da obra")).getByText("Carregando…")).toBeTruthy();
  });
});

describe("Prazo da obra: os dias da execução, as linhas do tempo e o ritmo (#655, #774)", () => {
  afterEach(cleanup);
  const montar = (ficha: Ficha | null | undefined = FICHA) => render(<PrazoDaObra ficha={ficha} prazos={PRAZOS} />);
  const comRitmo = (ritmo: Partial<Ficha["ritmo"]>) => montar({ ...FICHA, ritmo: { ...FICHA.ritmo, ...ritmo } });
  const valor = (rotulo: string) => within(regiao("Prazo")).getByText(rotulo).closest("div")!.querySelector("dd")!;
  const dias = () => regiao("Prazo").querySelector(".obra-prazo__numero")!;

  it("os dias da execução levam o nível do servidor, com o glifo além da cor", () => {
    montar();
    expect(dias().textContent).toMatch(/^em 12.dias$/);
    expect(dias().className).toContain("obra-prazo__numero--critico");
    expect(dias().querySelector(".glifo--critico")).toBeTruthy();
    cleanup();
    montar({ ...FICHA, vencimentos: FICHA.vencimentos.map(v => ({ ...v, dias: 45, nivel: "atencao" })) });
    expect(dias().className).toContain("obra-prazo__numero--breve");
    expect(dias().querySelector(".glifo--breve")).toBeTruthy();
    cleanup();
    montar({ ...FICHA, vencimentos: FICHA.vencimentos.map(v => ({ ...v, dias: 200, nivel: "normal" })) });
    expect(dias().textContent).toMatch(/^em 200.dias$/);
    expect(dias().className).not.toMatch(/critico|breve/);
    expect(dias().querySelector(".glifo")).toBeNull();
  });

  it("prazo vencido diz há quantos dias; sem os dias, o traço", () => {
    montar({ ...FICHA, vencimentos: FICHA.vencimentos.map(v => ({ ...v, dias: -48, nivel: "critico" })) });
    expect(dias().textContent).toMatch(/^vencido há 48.dias$/);
    cleanup();
    montar({ ...FICHA, vencimentos: FICHA.vencimentos.map(v => ({ ...v, dias: null, nivel: "normal" })) });
    expect(dias().textContent).toBe("—");
  });

  it("as linhas do tempo da execução e da vigência moram no painel, com as datas", () => {
    montar();
    expect(within(regiao("Prazo")).getByText("Execução")).toBeTruthy();
    expect(within(regiao("Prazo")).getByText("Vigência")).toBeTruthy();
    expect(within(regiao("Prazo")).getByText("18/11/2026")).toBeTruthy();
    expect(within(regiao("Prazo")).getByText("16/02/2027")).toBeTruthy();
  });

  it("mostra o ritmo mensal, o necessário por mês e a conclusão estimada; o saldo e o fim da execução não se repetem", () => {
    montar();
    const conta = within(regiao("Prazo")).getByLabelText("Ritmo e prazo");
    expect([...conta.querySelectorAll("dt")].map(dt => dt.textContent)).toEqual(
      ["Ritmo mensal", "Necessário para terminar no prazo", "Andamento", "Conclusão estimada"]);
    expect(valor("Ritmo mensal").textContent).toMatch(/^R\$\s50\.000,00$/);
    // #803: o valor por mês e as competências que restam; o saldo do topo dividido por elas é o necessário
    const [porMes, restam] = [...valor("Necessário para terminar no prazo").querySelectorAll("span")].map(x => x.textContent);
    expect(porMes).toMatch(/^R\$\s187\.654,34$/);
    expect(restam).toBe("por mês, em 1 competência");
    expect(valor("Conclusão estimada").querySelector("span")!.textContent).toBe("08/03/2027");
    expect(within(regiao("Prazo")).queryByText("Saldo")).toBeNull();
    expect(within(regiao("Prazo")).getAllByText("18/11/2026")).toHaveLength(1);
  });

  it("conclusão depois do fim da execução: selo crítico com os dias, na linha da conclusão estimada", () => {
    // no alto do painel, ao lado de "vencido há N dias", o selo lia-se como a mesma conta: são duas medidas
    montar({ ...FICHA, vencimentos: FICHA.vencimentos.map(v => ({ ...v, dias: -82, nivel: "critico" })) });
    expect(dias().textContent).toMatch(/^vencido há 82.dias$/);
    expect(regiao("Prazo").querySelector(".cartao__cabeca .selo")).toBeNull();
    const selo = valor("Conclusão estimada").querySelector(".selo")!;
    expect(selo.className).toContain("selo--critico");
    expect(selo.textContent).toBe("110 dias depois do fim da execução");
  });

  it("ritmo igual ou acima do necessário: selo de feito 'No ritmo do prazo' (#803)", () => {
    comRitmo({ ritmo_centavos: 7000000, necessario_centavos: 6255145, competencias_restantes: 3, conclusao: "2027-01-26",
      situacao: "no_prazo", dias_alem: null });
    expect(valor("Necessário para terminar no prazo").textContent).toMatch(/^R\$\s62\.551,45por mês, em 3 competências$/);
    const selos = regiao("Prazo").querySelectorAll(".obra-ritmo .selo");
    expect(selos).toHaveLength(1);
    const selo = valor("Conclusão estimada").querySelector(".selo")!;
    expect(selo.className).toContain("selo--feito");
    expect(selo.querySelector(".glifo--feito")).toBeTruthy();
    expect(selo.textContent).toBe("No ritmo do prazo");
  });

  it("execução vencida: '—' no necessário, e o selo crítico dos dias além do fim continua (#803)", () => {
    comRitmo({ necessario_centavos: null, competencias_restantes: null });
    expect(valor("Necessário para terminar no prazo").textContent).toBe("—");
    expect(valor("Ritmo mensal").textContent).toMatch(/^R\$\s50\.000,00$/);
    expect(valor("Conclusão estimada").querySelector(".selo--critico")!.textContent).toMatch(/^110.dias depois do fim da execução$/);
  });

  it("sem medição nas 6 últimas competências: '—' no ritmo e na conclusão e nenhum selo; o necessário continua", () => {
    comRitmo({ ritmo_centavos: null, conclusao: null, situacao: null, dias_alem: null });
    expect(valor("Ritmo mensal").textContent).toBe("—");
    expect(valor("Conclusão estimada").textContent).toBe("—");
    expect(valor("Necessário para terminar no prazo").textContent).toMatch(/^R\$\s187\.654,34por mês, em 1 competência$/);
    expect(regiao("Prazo").querySelector(".selo")).toBeNull();
  });

  it("sem prazo a cumprir e sem ritmo: '—' nos quatro e nenhum selo", () => {
    comRitmo({ ritmo_centavos: null, necessario_centavos: null, competencias_restantes: null, conclusao: null, situacao: null, dias_alem: null,
      leitura: SEM_LEITURA });
    expect(["Ritmo mensal", "Necessário para terminar no prazo", "Andamento", "Conclusão estimada"].map(r => valor(r).textContent)).toEqual(["—", "—", "—", "—"]);
    expect(regiao("Prazo").querySelector(".selo")).toBeNull();
  });

  it("#822: o andamento é a leitura do servidor, com a peça da lista de Obras: a palavra, o percentual e a barra", () => {
    comRitmo({ ritmo_centavos: 5000000, necessario_centavos: 6255145, competencias_restantes: 3, conclusao: "2027-03-08", situacao: "atrasa", dias_alem: 37,
      leitura: { ...SEM_LEITURA, situacao: "atencao", pct: 79 } });
    const andamento = valor("Andamento");
    expect(andamento.textContent!.replace(/\s/g, " ")).toBe("Atenção · mede 79% do necessário");
    expect(andamento.querySelector(".andamento--atencao .andamento__barra")).toBeTruthy();
    // o selo da conclusão estimada continua ao lado da data
    expect(valor("Conclusão estimada").querySelector(".selo--critico")!.textContent).toMatch(/^37.dias depois do fim da execução$/);
  });

  it("#822: a obra cuja conclusão estimada não fecha continua com a leitura da lista (a página calava a situação)", () => {
    comRitmo({ ritmo_centavos: 100, necessario_centavos: 6255145, competencias_restantes: 3, conclusao: null, situacao: null, dias_alem: null,
      leitura: { ...SEM_LEITURA, situacao: "devagar", pct: 0 } });
    expect(valor("Andamento").textContent!.replace(/\s/g, " ")).toBe("Devagar · mede 0% do necessário");
    expect(valor("Conclusão estimada").textContent).toBe("—");
  });

  it("#822: fora da régua, o motivo em tinta no andamento; a data e o selo da conclusão continuam (19/11)", () => {
    const fora: [Partial<typeof SEM_LEITURA>, string][] = [
      [{ motivo: "prazo_no_fim" }, "Prazo no fim"],
      [{ motivo: "prazo_no_fim", prorrogacao_pedida: true }, "Prazo no fim · prorrogação pedida"],
      [{ motivo: "prorrogacao_pedida", prorrogacao_pedida: true }, "Prorrogação pedida"],
      [{ motivo: "sem_medicao", sem_medicao_desde: "2026-07" }, "Sem medição desde 07/2026"],
    ];
    for (const [extra, frase] of fora) {
      // o servidor manda `situacao` e `dias_alem` também fora da régua (decisão do dono de 19/11/2026)
      comRitmo({ situacao: "atrasa", dias_alem: 110, leitura: { ...SEM_LEITURA, ...extra } });
      expect(valor("Andamento").textContent!.replace(/\s/g, " ")).toBe(frase);
      expect(valor("Andamento").querySelector(".andamento--fora")).toBeTruthy();
      expect(valor("Andamento").querySelector(".andamento__trilho")).toBeNull();
      const conclusao = valor("Conclusão estimada");
      expect(conclusao.querySelector("span")!.textContent).toBe("08/03/2027");
      expect(conclusao.querySelector(".selo--critico")!.textContent).toMatch(/^110.dias depois do fim da execução$/);
      cleanup();
    }
  });

  it("carregando e falha da ficha: sem número inventado e sem selo", () => {
    montar(null);
    expect(within(regiao("Prazo")).getByRole("alert").textContent).toBe("indisponível agora");
    expect(regiao("Prazo").querySelector(".cartao__cabeca .selo")).toBeNull();
    expect(screen.queryByText("Ritmo mensal")).toBeNull();
    cleanup();
    render(<PrazoDaObra ficha={undefined} prazos={PRAZOS} />);
    expect(within(regiao("Prazo")).getByText("Carregando…")).toBeTruthy();
  });
});

describe("Medições de agora (#774)", () => {
  afterEach(cleanup);

  it("a em andamento leva o passo da vez no selo de andamento; a última recebida, o selo de feito", () => {
    render(<MedicoesAgora contratoId={3} ficha={FICHA} />);
    const r = regiao("Medições");
    const links = within(r).getAllByRole("link");
    expect(links.map(l => l.textContent)).toEqual(["16ª · out/2026", "15ª · set/2026"]);
    expect(links.map(l => l.getAttribute("href"))).toEqual(["/obras/3/medicoes/16", "/obras/3/medicoes/15"]);
    expect(within(r).getByText(/60\.000,22/)).toBeTruthy();
    expect(within(r).getByText(/50\.000,11/)).toBeTruthy();
    expect(r.querySelector(".selo--andamento")!.textContent).toBe("Pagamento desde 05/11");
    expect(r.querySelector(".selo--feito")!.textContent).toBe("recebida em 16/10/2026");
    expect(within(r).getByText(/^14.dias após a nota$/)).toBeTruthy();
  });

  it("sem medição em andamento nem recebida: o traço; na falha, indisponível", () => {
    render(<MedicoesAgora contratoId={3} ficha={{ ...FICHA, em_andamento: null, ultima_medicao: null }} />);
    expect(within(regiao("Medições")).getAllByText("—")).toHaveLength(2);
    expect(regiao("Medições").querySelector(".selo")).toBeNull();
    cleanup();
    render(<MedicoesAgora contratoId={3} ficha={null} />);
    expect(within(regiao("Medições")).getByRole("alert").textContent).toBe("indisponível agora");
  });
});

describe("regras puras da ficha", () => {
  it("mês e ano", () => expect(mesAno("2026-09")).toBe("set/2026"));
});
