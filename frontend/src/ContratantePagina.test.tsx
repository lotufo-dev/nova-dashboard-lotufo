import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { comLeitura, leituraDeTeste } from "./andamentoTeste";
import ContratantePagina from "./ContratantePagina";
import type { ObraLista } from "./listaObras";
import { useRota } from "./rota";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

// Dados sintéticos, na cota: a SINFRA com três obras em andamento (devagar, em atenção e com a execução vencida) e uma
// encerrada; a MTPAR com uma. O medido é o de agosto (a competência fechada) contra julho.
const doMes = (valor: number, referencia: number) =>
  ({ competencia: "2026-08", valor_centavos: valor, referencia_competencia: "2026-07", referencia_centavos: referencia });
// #822: a leitura do andamento vem do servidor; `comLeitura` põe em cada obra a que ele mandaria para o ritmo e o necessário dela
const obra = (id: number, nome: string, extra: Partial<ObraLista> = {}): ObraLista => comLeitura({
  id, orgao: "SINFRA - SUEF II", contratante: "SINFRA", contratante_chave: "sinfra", numero_instrumento: `IC ${id}/2026`, nome_curto: nome,
  estado: "ativo", percentual_direito_bp: 10000, execucao_fim_vigente: "2027-03-31", dias_execucao: 190,
  posicao: { vigente_centavos: 1000_00, medido_centavos: 250_00, saldo_centavos: 750_00, a_receber_centavos: 0 },
  andamento: { ritmo_centavos: null, necessario_centavos: null }, medido_mes: doMes(0, 0), ...extra });

const OBRAS: ObraLista[] = [
  obra(1, "Estações BRT", { andamento: { ritmo_centavos: 2_400_000_00, necessario_centavos: 8_800_000_00 }, medido_mes: doMes(80_00, 100_00),
    posicao: { vigente_centavos: 1000_00, medido_centavos: 370_00, saldo_centavos: 630_00, a_receber_centavos: 120_00 } }),
  obra(2, "Cavalaria", { andamento: { ritmo_centavos: 81_00, necessario_centavos: 100_00 }, medido_mes: doMes(60_00, 60_00) }),
  obra(3, "5 Bairros", { execucao_fim_vigente: "2026-08-31", dias_execucao: -24, andamento: { ritmo_centavos: 10_00, necessario_centavos: null } }),
  obra(4, "Trevo Antigo", { estado: "encerrado", execucao_fim_vigente: "2025-12-31" }),
  obra(5, "Granito", { orgao: "MTPAR", contratante: "MTPAR", contratante_chave: "mtpar",
    posicao: { vigente_centavos: 1000_00, medido_centavos: 500_00, saldo_centavos: 500_00, a_receber_centavos: 70_00 } }),
];

const noPainel = (contrato_id: number, nome: string, farol: "verde" | "atencao" | "acao" | "vermelho", motivos: string[] = []) => ({
  contrato_id, seq: contrato_id, obra: nome, contratante: "SINFRA", empreita: "PRÓPRIA", direito: 1, pi_va: 0, faturados: 0, saldo: 0,
  status: "EM ANDAMENTO", termino: null, farol, motivo: motivos.join("; "),
  motivos: motivos.map(texto => ({ tipo: "t", nivel: farol === "vermelho" ? "critico" : "atencao", dias: null, valor_centavos: null, texto })) });
const aviso = (contrato_id: number, nivel: string) => ({ tipo: "execucao_vencendo", nivel, publico: ["diretoria"], contrato_id, obra: "x",
  dias: 1, valor_centavos: null, mensagem: "x", destino: null });
const PAINEL = {
  hoje: "2026-09-24", medido_ano: { ano: "2026", valor_centavos: 0 }, prazo_pagamento: { SINFRA: 47 },
  obras: [noPainel(1, "Estações BRT", "vermelho", ["garantia não cobre o fim da execução", "aprovado abaixo do pedido"]),
    noPainel(2, "Cavalaria", "verde"), noPainel(3, "5 Bairros", "atencao", ["execução venceu há 24 dias"]), noPainel(5, "Granito", "verde")],
  avisos: [aviso(1, "critico"), aviso(1, "atencao"), aviso(5, "critico")],
};

function Pagina({ perfil = "diretoria" }: { perfil?: string }) {
  const { rota, busca, ir } = useRota();
  return rota.tela === "contratante" ? <ContratantePagina chave={rota.chave} perfil={perfil} busca={busca} ir={ir} /> : <p>outra tela</p>;
}
function abrir(url: string, perfil?: string) {
  window.history.replaceState(null, "", url);
  return render(<Pagina perfil={perfil} />);
}
const limpo = (s: string | null | undefined) => (s ?? "").replace(/[ \s]+/g, " ").trim();

describe("Página do contratante (#805)", () => {
  beforeEach(() => {
    api.mockImplementation(async (caminho: string) => {
      if (caminho === "/api/contratos") return OBRAS;
      if (caminho === "/api/diretoria") return PAINEL;
      throw new Error(`chamada inesperada: ${caminho}`);
    });
  });
  afterEach(() => { cleanup(); api.mockReset(); window.history.replaceState(null, "", "/"); });

  it("o caminho no alto é Obras › SINFRA, e o título diz o contratante e a cota uma vez", async () => {
    abrir("/obras/contratante/sinfra");
    await screen.findByRole("heading", { level: 1, name: /SINFRA/ });
    const caminho = screen.getByRole("navigation", { name: "Você está em" });
    expect([...caminho.querySelectorAll("li")].map(li => li.textContent)).toEqual(["Obras", "SINFRA"]);
    expect(within(caminho).getByRole("link", { name: "Obras" }).getAttribute("href")).toBe("/obras");
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("SINFRA cota da Lotufo");
    expect(document.querySelector(".topbar__meta")!.textContent).toBe("3 obras em andamento");
    await waitFor(() => expect(document.title).toBe("SINFRA · Obras · grupolotufo"));
  });

  it("o cabeçalho traz os números do bloco: contratado e participação, medido, medido no mês, a receber, prazo e andamento", async () => {
    abrir("/obras/contratante/sinfra");
    const faixa = await screen.findByLabelText("Números de SINFRA");
    await waitFor(() => expect(limpo(faixa.textContent)).toContain("47 dias"));
    expect([...faixa.querySelectorAll(".obras-numero")].map(n => limpo(n.textContent))).toEqual([
      "ContratadoR$ 3.000,0075% da carteira",              // 3 de 4 obras em andamento de 1.000,00
      "Medido (29%)R$ 870,00",
      "Medido em agostoR$ 140,00▼ −12,5%× julcaiu 12,5% em relação a julho",      // 140,00 contra 160,00
      "A receberR$ 120,00",
      "Prazo de pagamento47 dias",
      "Andamento1 de 2obra devagar",
    ]);
    expect(faixa.querySelector(".variacao--ruim")).toBeTruthy();
    // o que pede atenção, com a régua do andamento e os avisos da diretoria
    expect([...document.querySelectorAll(".pagina > .obras-etiquetas li")].map(li => limpo(li.textContent)))
      .toEqual(["1 devagar", "1 em atenção", "1 com execução vencida", "1 aviso crítico"]);
  });

  it("a tabela das obras: executado, andamento com os valores, medido no mês com a variação, a receber e a situação com o motivo", async () => {
    abrir("/obras/contratante/sinfra");
    const tabela = await screen.findByRole("table", { name: /Obras de SINFRA/ });
    expect(within(tabela).getAllByRole("columnheader").map(c => c.textContent)).toEqual(
      ["Obra", "Executado", "Andamento", "Medido em ago", "A receber", "Situação"]);
    const linha = (nome: string) => within(tabela).getByRole("link", { name: nome }).closest("tr")!;
    const celulas = (nome: string) => [...linha(nome).querySelectorAll("td")].map(td => limpo(td.textContent));
    await waitFor(() => expect(linha("Estações BRT").querySelector(".obras-situacao")).toBeTruthy());
    expect(celulas("Estações BRT")).toEqual([
      "Estações BRTexecução até 31/03/2027", "37%", "Devagar · 27% do necessárioR$ 2,4 mi/mês de R$ 8,8 mi",
      "R$ 80,00▼ −20,0%× julcaiu 20,0% em relação a julho", "R$ 120,00", "Críticogarantia não cobre o fim da execuçãomais 1 motivo de Estações BRT"]);
    expect(linha("Estações BRT").querySelector(".obras-em-aberto")).toBeTruthy();
    expect(celulas("Cavalaria")).toEqual([
      "Cavalariaexecução até 31/03/2027", "25%", "Atenção · 81% do necessárioR$ 81/mês de R$ 100",
      "R$ 60,00● estável× julestável em relação a julho", "R$ 0,00", "Em dia"]);
    expect(linha("Cavalaria").querySelector(".obras-em-aberto")).toBeNull();
    // execução vencida: sem necessário, sem leitura do andamento; o motivo diz o que há
    expect(celulas("5 Bairros")).toEqual(["5 Bairrosexecução até 31/08/2026", "25%", "—", "—", "R$ 0,00", "Atençãoexecução venceu há 24 dias"]);
    expect(linha("5 Bairros").querySelector(".selo--breve .glifo--breve")).toBeTruthy();
    // a linha leva à página da obra
    expect(within(tabela).getByRole("link", { name: "Cavalaria" }).getAttribute("href")).toBe("/obras/2");
    fireEvent.click(linha("Cavalaria"));
    expect(window.location.pathname).toBe("/obras/2");
    expect((window.history.state as { origem?: { tela: string; href: string } }).origem).toEqual({ tela: "contratante", href: "/obras/contratante/sinfra" });
  });

  it("devagar é motivo da situação: a obra devagar sem aviso não diz 'Em dia'; o aviso do farol continua ganhando", async () => {
    // decisao do dono de 18/11/2026: "Devagar" numa coluna e "Em dia" na outra se contradiziam
    const ritmo = (centavos: number) => ({ andamento: { ritmo_centavos: centavos, necessario_centavos: 100_00 } });
    const obras = [
      obra(1, "Anel Viário", ritmo(69_99)),        // devagar (69,99% e' 69%, pela regua da coluna), sem aviso
      obra(2, "Estações BRT", ritmo(40_00)),       // devagar, com aviso critico
      obra(3, "5 Bairros", ritmo(40_00)),          // devagar, com aviso de atencao
      obra(4, "Cavalaria", ritmo(70_00)),          // em atencao (70%), sem aviso
      obra(5, "Granito", ritmo(120_00)),           // adiantada, sem aviso
      obra(6, "Trevo Novo"),                       // sem leitura do andamento, sem aviso
    ];
    const painel = { ...PAINEL, avisos: [aviso(2, "critico")], obras: [
      noPainel(1, "Anel Viário", "verde"), noPainel(2, "Estações BRT", "vermelho", ["garantia não cobre o fim da execução"]),
      noPainel(3, "5 Bairros", "atencao", ["prorrogação pedida há 9 dias"]), noPainel(4, "Cavalaria", "verde"),
      noPainel(5, "Granito", "verde"), noPainel(6, "Trevo Novo", "verde")] };
    api.mockImplementation(async (caminho: string) => (caminho === "/api/contratos" ? obras : painel));
    abrir("/obras/contratante/sinfra");
    const tabela = await screen.findByRole("table", { name: /Obras de SINFRA/ });
    const celula = (nome: string, rotulo: string) =>
      within(tabela).getByRole("link", { name: nome }).closest("tr")!.querySelector<HTMLElement>(`td[data-rotulo="${rotulo}"]`)!;
    const situacao = (nome: string) => celula(nome, "Situação");
    await waitFor(() => expect(situacao("Estações BRT").querySelector(".selo")).toBeTruthy());

    // devagar sem aviso: a Situacao diz o motivo do andamento, com o mesmo percentual da coluna Andamento
    expect(limpo(celula("Anel Viário", "Andamento").textContent)).toBe("Devagar · 69% do necessárioR$ 70/mês de R$ 100");
    expect(limpo(situacao("Anel Viário").textContent)).toBe("Devagarmede 69% do necessário");
    expect(situacao("Anel Viário").querySelector(".obras-situacao__emdia")).toBeNull();
    // andamento e' valor, nao situacao: a palavra vai na etiqueta do tom da leitura, sem selo e sem glifo
    expect(situacao("Anel Viário").querySelector(".obras-etiqueta--devagar")!.textContent)
      .toBe(celula("Anel Viário", "Andamento").querySelector(".andamento__palavra")!.textContent);        // a mesma palavra
    expect(situacao("Anel Viário").querySelector(".selo, .glifo")).toBeNull();

    // devagar com aviso critico, ou com aviso de atencao: o aviso ganha, e o andamento fica so' na coluna dele
    expect(limpo(situacao("Estações BRT").textContent)).toBe("Críticogarantia não cobre o fim da execução");
    expect(limpo(situacao("5 Bairros").textContent)).toBe("Atençãoprorrogação pedida há 9 dias");
    for (const nome of ["Estações BRT", "5 Bairros"]) expect(situacao(nome).querySelector(".obras-etiqueta--devagar")).toBeNull();

    // em dia: em atencao no andamento (so' o devagar vira motivo), adiantada e sem leitura
    expect(limpo(celula("Cavalaria", "Andamento").textContent)).toContain("Atenção · 70% do necessário");
    for (const nome of ["Cavalaria", "Granito", "Trevo Novo"]) expect(limpo(situacao(nome).textContent)).toBe("Em dia");
  });

  it("só as obras do contratante, em andamento; 'Ver todas' traz a encerrada sem mudar os números do alto", async () => {
    abrir("/obras/contratante/sinfra");
    await screen.findByRole("table", { name: /Obras de SINFRA/ });
    const nomes = () => [...document.querySelectorAll("tr.linha--obra")].map(l => l.querySelector("a")!.textContent);
    expect(nomes()).toEqual(["5 Bairros", "Cavalaria", "Estações BRT"]);
    expect(document.querySelector(".obras-rodape span")!.textContent).toBe("Mostrando 3 de 4 obras");
    fireEvent.click(screen.getByRole("link", { name: "Ver todas" }));
    expect(window.location.pathname + window.location.search).toBe("/obras/contratante/sinfra?situacao=todas");
    await screen.findByRole("link", { name: "Só em andamento" });
    expect(nomes()).toEqual(["5 Bairros", "Cavalaria", "Estações BRT", "Trevo Antigo"]);
    expect(limpo(screen.getByRole("link", { name: "Trevo Antigo" }).closest("tr")!.querySelector('td[data-rotulo="Situação"]')!.textContent)).toBe("Encerrada");
    expect(limpo(screen.getByLabelText("Números de SINFRA").textContent)).toContain("ContratadoR$ 3.000,00");
  });

  it("contratante sem prazo de pagamento no sistema mostra o traço; sem nada pendente, 'Em dia'", async () => {
    abrir("/obras/contratante/mtpar");
    const faixa = await screen.findByLabelText("Números de MTPAR");
    await screen.findByText("Em dia", { selector: ".obras-situacao__emdia" });
    const numeros = [...faixa.querySelectorAll(".obras-numero")].map(n => limpo(n.textContent));
    expect(numeros).toContain("Prazo de pagamento—");
    expect(numeros).toContain("Andamento—");
    expect(numeros).toContain("Medido em agosto—");
    expect(numeros[0]).toBe("ContratadoR$ 1.000,0025% da carteira");
    // o aviso crítico da obra dele conta
    expect([...document.querySelectorAll(".pagina > .obras-etiquetas li")].map(li => limpo(li.textContent))).toEqual(["1 aviso crítico"]);
  });

  it("os atalhos levam ao que é do contratante nas outras páginas; o SIGA só para quem o vê", async () => {
    abrir("/obras/contratante/sinfra", "diretoria");
    const atalhos = await screen.findByRole("navigation", { name: "SINFRA em outras páginas" });
    expect(within(atalhos).getAllByRole("link").map(a => [a.textContent, a.getAttribute("href")])).toEqual(
      [["Avisos", "/avisos?c=SINFRA"], ["Fechamento", "/fechamento"]]);
    // quem só consulta não vê botão de escrita: a página não tem nenhum
    expect(screen.queryAllByRole("button")).toHaveLength(0);
    cleanup();
    abrir("/obras/contratante/sinfra", "engenharia");
    const daEngenharia = await screen.findByRole("navigation", { name: "SINFRA em outras páginas" });
    expect(within(daEngenharia).getAllByRole("link").map(a => [a.textContent, a.getAttribute("href")])).toEqual(
      [["Avisos", "/avisos?c=SINFRA"], ["Fechamento", "/fechamento"], ["SIGA", "/siga"]]);
    // as abas Medições, A receber e Processos no SIGA ficam para a PR seguinte: nada de aba vazia
    expect(screen.queryByRole("tab")).toBeNull();
    expect(document.querySelector(".abas")).toBeNull();
  });

  it("chave que a lista não conhece: diz que não achou e oferece os contratantes", async () => {
    abrir("/obras/contratante/nao-existe");
    expect(await screen.findByText("Contratante não encontrado.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Ver os contratantes" }).getAttribute("href")).toBe("/obras");
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("falha ao ler as obras vira o aviso; sem o painel da diretoria a tabela continua e diz o que faltou", async () => {
    api.mockImplementation(async () => { throw new Error("falhou"); });
    abrir("/obras/contratante/sinfra");
    expect((await screen.findByRole("alert")).textContent).toContain("Recarregue a página");
    cleanup();
    api.mockImplementation(async (caminho: string) => {
      if (caminho === "/api/contratos") return OBRAS;
      throw new Error("falhou");
    });
    abrir("/obras/contratante/sinfra");
    await screen.findByRole("table", { name: /Obras de SINFRA/ });
    expect((await screen.findByRole("alert")).textContent).toContain("Não foi possível carregar a situação das obras e o prazo de pagamento.");
    expect(limpo(screen.getByLabelText("Números de SINFRA").textContent)).toContain("Prazo de pagamento—");
  });

  it("#822: a obra fora da régua leva o motivo no andamento, sem barra, e não conta em 'N devagar'", async () => {
    // as três mediriam 10% do necessário; o servidor as tirou da régua
    const fora = (motivo: Parameters<typeof leituraDeTeste>[2]) => ({ ritmo_centavos: 10_00, necessario_centavos: 100_00, leitura: leituraDeTeste(10_00, 100_00, motivo) });
    const obras = [
      obra(1, "Estações BRT", { andamento: fora({ motivo: "prazo_no_fim", prorrogacao_pedida: true }) }),
      obra(2, "Cavalaria", { andamento: fora({ motivo: "sem_medicao", sem_medicao_desde: "2026-05" }) }),
      obra(3, "5 Bairros", { andamento: fora({ motivo: "prorrogacao_pedida", prorrogacao_pedida: true }) }),
      obra(4, "Leblon", { andamento: { ritmo_centavos: 27_00, necessario_centavos: 100_00 } }),
    ];
    api.mockImplementation(async (caminho: string) => caminho === "/api/contratos" ? obras : PAINEL);
    abrir("/obras/contratante/sinfra");
    const tabela = await screen.findByRole("table", { name: /Obras de SINFRA/ });
    const andamento = (nome: string) => within(tabela).getByRole("link", { name: nome }).closest("tr")!.querySelector('td[data-rotulo="Andamento"]')!;
    expect(limpo(andamento("Estações BRT").textContent)).toBe("Prazo no fim · prorrogação pedida");
    expect(limpo(andamento("Cavalaria").textContent)).toBe("Sem medição desde 05/2026");
    expect(limpo(andamento("5 Bairros").textContent)).toBe("Prorrogação pedida");
    expect(limpo(andamento("Leblon").textContent)).toBe("Devagar · 27% do necessárioR$ 27/mês de R$ 100");
    expect(tabela.querySelectorAll(".andamento__trilho").length).toBe(1);
    expect(andamento("Estações BRT").querySelector(".andamento--fora")).toBeTruthy();
    // a contagem só olha quem tem leitura: uma obra, e ela está devagar; a do prazo no fim vai ao lado, em tinta
    const faixa = screen.getByLabelText("Números de SINFRA");
    expect([...faixa.querySelectorAll(".obras-numero")].map(n => limpo(n.textContent))).toContain("Andamento1 de 1obra devagar1 com prazo no fim");
    expect([...document.querySelectorAll(".pagina > .obras-etiquetas .obras-etiqueta")].map(e => limpo(e.textContent))).toEqual(["1 devagar"]);
  });
});
