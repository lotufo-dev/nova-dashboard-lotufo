import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Caminho from "./Caminho";
import { ABAS_PRONTAS, type AReceberDoContratante, type MedicoesDoContratante, type SigaDoContratante } from "./abasDoContratante";
import { comLeitura, leituraDeTeste } from "./andamentoTeste";
import AReceber, { type ContratanteAReceber, type LinhaAReceber } from "./AReceber";
import ContratantePagina from "./ContratantePagina";
import type { LinhaFila } from "./filaMedicoes";
import type { ObraLista } from "./listaObras";
import type { Parada } from "./parada";
import { useRota } from "./rota";
import type { ProcessoSiga } from "./siga";

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
  obra(1, "Estações BRT", { andamento: { ritmo_centavos: 3_000_000_00, necessario_centavos: 7_500_000_00 }, medido_mes: doMes(80_00, 100_00),
    posicao: { vigente_centavos: 1000_00, medido_centavos: 650_00, saldo_centavos: 350_00, a_receber_centavos: 120_00 } }),
  obra(2, "Cavalaria", { andamento: { ritmo_centavos: 78_00, necessario_centavos: 100_00 }, medido_mes: doMes(60_00, 60_00) }),
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

// #818: o recorte da SINFRA que o servidor manda para cada aba (`app/contratante.py`). Obras, medições, notas,
// processos e valores inventados.
const parada = (dias: number | null, situacao: Parada["situacao"], extra: Partial<Parada> = {}): Parada => ({
  desde: dias === null ? null : "2026-11-02", dias_uteis: dias, hoje: dias === 0, situacao, prazo_orgao_dias: null, esperada: null,
  alem_do_prazo: false, ...extra });
const PASSOS = ["Planilha e carta", "Análise do órgão", "Espelhos", "Notas", "Envio da nota", "Pagamento"];
const naFila = (contrato_id: number, obra_: string, atual: number, com_quem: LinhaFila["com_quem"], extra: Partial<LinhaFila> = {}): LinhaFila => ({
  contrato_id, obra: obra_, contratante: "SINFRA", orgao_sub: "SUEF II", medicao_id: contrato_id * 100, medicao_ids: [contrato_id * 100],
  titulo: "8ª Medição", competencia: "2026-10", com_quem,
  passo: { numero: atual, nome: PASSOS[atual - 1], posicao: atual, total: 6 },
  passos: PASSOS.map((nome, i) => ({ numero: i + 1, nome, situacao: i + 1 < atual ? "feito" : i + 1 === atual ? "atual" : "futuro" })),
  parada: parada(3, "andamento"), pedido_centavos: 200_000_00, aprovado_centavos: null, aprovado_com_pedido_centavos: null,
  pedido_do_aprovado_centavos: null, abaixo_do_pedido_centavos: null, acima_do_pedido_centavos: null, acao: null, ...extra });
const MEDICOES: MedicoesDoContratante = {
  hoje: "2026-11-18", mes: "2026-10", limites: { dias_atencao: 5, dias_critico: 10, diferenca_critica_por_mil: 5 },
  grupos: [
    { com_quem: "lotufo", linhas: [naFila(1, "Estações BRT", 3, "lotufo", { parada: parada(12, "critico"), acao: "gerar_espelho",
      aprovado_centavos: 180_000_00, aprovado_com_pedido_centavos: 180_000_00, pedido_do_aprovado_centavos: 200_000_00,
      abaixo_do_pedido_centavos: 20_000_00, acima_do_pedido_centavos: 0 })] },
    { com_quem: "orgao", linhas: [naFila(2, "Cavalaria", 6, "orgao", { parada: parada(20, "critico", { prazo_orgao_dias: 47, esperada: "2026-11-10", alem_do_prazo: true }) }),
      naFila(3, "5 Bairros", 2, "orgao", { parada: parada(6, "breve") })] },
  ],
  concluidas: [{ contrato_id: 4, obra: "Trevo Antigo", medicao_id: 401, titulo: "9ª Medição", recebida_em: "2026-11-10" }],
  sem_medicao: [{ contrato_id: 6, obra: "Anel Viário", contratante: "SINFRA" }],
  quantidade: 4,                       // as três linhas da fila e a concluída
};
const emAberto = (medicao_id: number, obra_: string, valor_centavos: number, protocolo_em: string): LinhaAReceber => ({
  tipo_aberto: "nota", nota_id: medicao_id, numero: String(9000 + medicao_id), valor_centavos, paga_em_parte: false, contrato_id: 1, obra: obra_,
  medicao_id, medicao_numero: 7, tipo: "execucao", competencia: "2026-08", protocolo_em, emitida_em: null,
  parada: parada(30, "andamento", { prazo_orgao_dias: 47, esperada: "2026-12-01" }), orgao_pagou_em: null });
const GRUPO_SINFRA: ContratanteAReceber = {
  contratante: "SINFRA", chave: "sinfra", prazo_orgao_dias: 47, quantidade: 2, em_aberto_centavos: 350_000_01,
  por_ano: { 2025: 0, 2026: 350_000_01 }, alem_do_prazo: 0,
  linhas: [emAberto(71, "Estações BRT", 300_000_00, "2026-09-01"), emAberto(72, "Cavalaria", 50_000_01, "2026-10-01")],
  notas_sem_medicao: [], notas_sem_medicao_centavos: 0, anteriores: { quantidade: 0, valor_centavos: 0 },
};
const A_RECEBER: AReceberDoContratante = { anos: ["2025", "2026"], total_a_receber_liberado: true, contratante: GRUPO_SINFRA, quantidade: 2 };
const noSiga = (id: number, extra: Partial<ProcessoSiga>): ProcessoSiga => ({
  id, codigo: null, link: null, numero: `ORGAO-PRO-2026/0000${id}`, nome: null, categoria: "medicoes", complemento: null, o_que_e: "8ª Medição",
  categoria_a_conferir: null, contrato_id: 1, obra: "Estações BRT", medicao_id: null, medicao_titulo: null, contratante: "SINFRA", orgao_sub: "SUEF II",
  situacao_tempo: "andamento", protocolo_id: null, situacao: "1º Volume - Aguardando Andamento [COFIN, [X]]", setor: "COFIN", caixa_entrada: false,
  com_quem: "Fulano", encerrado: null, desde: "2026-11-10T09:00:00-04:00", dias_uteis: 3, dias_sem_movimentacao: 3, hoje: 0, ultima: null, protocolado_em: null,
  movimentacoes: [], ...extra });
const SIGA: SigaDoContratante = {
  lido_em: "2026-11-18T14:00:00+00:00", limites: { dias_atencao: 5, dias_critico: 10 },
  robo: { estado: "parado", rodada: null, pedidos: [], avisos: [] },
  // do mais parado para o menos, como o servidor manda
  processos: [noSiga(1, { dias_uteis: 12, situacao_tempo: "critico" }), noSiga(2, { dias_uteis: 3, contrato_id: 2, obra: "Cavalaria" }),
    noSiga(3, { categoria: "aditivos", o_que_e: "Aditivo de prazo", dias_uteis: 6, situacao_tempo: "breve" })],
  quantidade: 3,
};

// o caminho é da barra do topo (#814): aqui ele entra ao lado da página, como a casca o desenha
function Pagina({ perfil = "diretoria" }: { perfil?: string }) {
  const { rota, busca, ir } = useRota();
  return rota.tela === "contratante"
    ? <><Caminho rota={rota} perfil={perfil} ehH1={false} /><ContratantePagina chave={rota.chave} aba={rota.aba} perfil={perfil} busca={busca} ir={ir} /></>
    : <p>outra tela</p>;
}
function abrir(url: string, perfil?: string) {
  window.history.replaceState(null, "", url);
  return render(<Pagina perfil={perfil} />);
}
/** O servidor do teste: a lista, o painel e o recorte da SINFRA de cada aba; `troca` muda a resposta de um caminho
 *  (um Error vira falha). Outro contratante recebe o recorte vazio, como o servidor manda. */
function servidor(troca: Record<string, unknown> = {}) {
  return async (caminho: string) => {
    const r = caminho in troca ? troca[caminho] : ({
      "/api/contratos": OBRAS, "/api/diretoria": PAINEL, "/api/contratantes/sinfra/medicoes": MEDICOES,
      "/api/contratantes/sinfra/a-receber": A_RECEBER, "/api/contratantes/sinfra/siga": SIGA,
    } as Record<string, unknown>)[caminho];
    if (r instanceof Error) throw r;
    if (r !== undefined) return r;
    // outro contratante da lista (a MTPAR, com a obra Granito): sem nada em cada aba
    if (/^\/api\/contratantes\/mtpar\/medicoes$/.test(caminho)) return { ...MEDICOES, grupos: [], concluidas: [], sem_medicao: [], quantidade: 0 };
    if (/^\/api\/contratantes\/mtpar\/a-receber$/.test(caminho)) return { ...A_RECEBER, contratante: null, quantidade: 0 };
    if (/^\/api\/contratantes\/mtpar\/siga$/.test(caminho)) return { ...SIGA, processos: [], quantidade: 0 };
    throw new Error(`chamada inesperada: ${caminho}`);
  };
}
/** A faixa de abas: o nome, a quantidade desenhada e o endereço de cada uma. */
const abas = () => [...within(screen.getByRole("navigation", { name: "Seções de SINFRA" })).getAllByRole("link")].map(a => [
  a.firstChild?.textContent, a.querySelector(".contador [aria-hidden]")?.textContent ?? null, a.getAttribute("href")]);
const abaAtual = () => within(screen.getByRole("navigation", { name: "Seções de SINFRA" })).getAllByRole("link")
  .filter(a => a.getAttribute("aria-current") === "page").map(a => a.firstChild?.textContent);
const limpo = (s: string | null | undefined) => (s ?? "").replace(/[ \s]+/g, " ").trim();

describe("Página do contratante (#805)", () => {
  beforeEach(() => { api.mockImplementation(servidor()); });
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
    // a página não desenha trilha própria (#814): a única é a da barra do topo
    expect(screen.getAllByRole("navigation", { name: "Você está em" })).toHaveLength(1);
    expect(document.querySelector(".topbar .caminho, .topbar__trilha")).toBeNull();
  });

  it("#818: a página desenha Obras, Medições, A receber e Processos no SIGA; Avisos ainda leva à página dos Avisos", async () => {
    expect(ABAS_PRONTAS).toEqual(["obras", "medicoes", "a-receber", "siga"]);
  });

  it("o cabeçalho traz os números do bloco: contratado e participação, medido, medido no mês, a receber, prazo e andamento", async () => {
    abrir("/obras/contratante/sinfra");
    const faixa = await screen.findByLabelText("Números de SINFRA");
    await waitFor(() => expect(limpo(faixa.textContent)).toContain("47 dias"));
    expect([...faixa.querySelectorAll(".obras-numero")].map(n => limpo(n.textContent))).toEqual([
      "ContratadoR$ 3.000,0075% da carteira",              // 3 de 4 obras em andamento de 1.000,00
      "Medido (38%)R$ 1.150,00",
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
      "Estações BRTexecução até 31/03/2027", "65%", "Devagar · 40% do necessárioR$ 3 mi/mês de R$ 7,5 mi",
      "R$ 80,00▼ −20,0%× julcaiu 20,0% em relação a julho", "R$ 120,00", "Críticogarantia não cobre o fim da execuçãomais 1 motivo de Estações BRT"]);
    expect(linha("Estações BRT").querySelector(".obras-em-aberto")).toBeTruthy();
    expect(celulas("Cavalaria")).toEqual([
      "Cavalariaexecução até 31/03/2027", "25%", "Atenção · 78% do necessárioR$ 78/mês de R$ 100",
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

  it("o atalho leva aos Avisos do contratante; o a receber e o SIGA, que levavam ao Fechamento e à tela SIGA, são abas", async () => {
    for (const perfil of ["diretoria", "engenharia"]) {
      abrir("/obras/contratante/sinfra", perfil);
      const atalhos = await screen.findByRole("navigation", { name: "SINFRA em outras páginas" });
      expect(within(atalhos).getAllByRole("link").map(a => [a.textContent, a.getAttribute("href")])).toEqual([["Avisos", "/avisos?c=SINFRA"]]);
      expect(document.querySelector('a[href="/fechamento"], a[href="/siga"]')).toBeNull();
      cleanup();
    }
    // quem só consulta não vê botão de escrita: a página não tem nenhum, em aba nenhuma
    for (const aba of ["", "/medicoes", "/a-receber"]) {
      abrir(`/obras/contratante/sinfra${aba}`, "diretoria");
      await screen.findByRole("navigation", { name: "Seções de SINFRA" });
      await act(async () => {});
      expect(screen.queryAllByRole("button")).toHaveLength(0);
      cleanup();
    }
  });

  it("chave que a lista não conhece: diz que não achou e oferece os contratantes", async () => {
    abrir("/obras/contratante/nao-existe");
    expect(await screen.findByText("Contratante não encontrado.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Ver os contratantes" }).getAttribute("href")).toBe("/obras");
    expect(screen.queryByRole("table")).toBeNull();
    // #818: nem pede as abas (o servidor responde 404 à chave que nenhuma obra tem)
    expect(api.mock.calls.map(c => String(c[0])).filter(c => c.startsWith("/api/contratantes/"))).toEqual([]);
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
      obra(4, "Leblon", { andamento: { ritmo_centavos: 40_00, necessario_centavos: 100_00 } }),
    ];
    api.mockImplementation(async (caminho: string) => caminho === "/api/contratos" ? obras : PAINEL);
    abrir("/obras/contratante/sinfra");
    const tabela = await screen.findByRole("table", { name: /Obras de SINFRA/ });
    const andamento = (nome: string) => within(tabela).getByRole("link", { name: nome }).closest("tr")!.querySelector('td[data-rotulo="Andamento"]')!;
    expect(limpo(andamento("Estações BRT").textContent)).toBe("Prazo no fim · prorrogação pedida");
    expect(limpo(andamento("Cavalaria").textContent)).toBe("Sem medição desde 05/2026");
    expect(limpo(andamento("5 Bairros").textContent)).toBe("Prorrogação pedida");
    expect(limpo(andamento("Leblon").textContent)).toBe("Devagar · 40% do necessárioR$ 40/mês de R$ 100");
    expect(tabela.querySelectorAll(".andamento__trilho").length).toBe(1);
    expect(andamento("Estações BRT").querySelector(".andamento--fora")).toBeTruthy();
    // a contagem só olha quem tem leitura: uma obra, e ela está devagar; a do prazo no fim vai ao lado, em tinta
    const faixa = screen.getByLabelText("Números de SINFRA");
    expect([...faixa.querySelectorAll(".obras-numero")].map(n => limpo(n.textContent))).toContain("Andamento1 de 1obra devagar1 com prazo no fim");
    expect([...document.querySelectorAll(".pagina > .obras-etiquetas .obras-etiqueta")].map(e => limpo(e.textContent))).toEqual(["1 devagar"]);
  });
});

// #818: as abas Medições, A receber e Processos no SIGA, cada uma o recorte que o servidor manda de uma tela que já
// existe, desenhado com as peças dela. A quantidade ao lado do nome é o número de linhas da aba.
describe("Página do contratante: as abas (#818)", () => {
  beforeEach(() => { api.mockImplementation(servidor()); });
  afterEach(() => { cleanup(); api.mockReset(); window.history.replaceState(null, "", "/"); });

  const linhasDaFila = () => [...document.querySelectorAll<HTMLElement>(".fila__tabela tbody tr")];
  const concluidas = () => [...document.querySelectorAll("#concluidas-titulo ~ .fila-lista .fila-lista__item, .fila-bloco:has(#concluidas-titulo) .fila-lista__item")];
  const linhasEmAberto = () => [...document.querySelectorAll(".arc-tabela:not(.arc-tabela--soltas) tbody tr:not(.arc-grupo)")];
  const linhasDoSiga = () => [...document.querySelectorAll("tr.sg__linha")];

  it("cada aba com endereço e a quantidade de linhas; a diretoria não tem a do SIGA e a página nem pede o dado dela", async () => {
    abrir("/obras/contratante/sinfra", "engenharia");
    await waitFor(() => expect(abas().map(a => a[1])).toEqual(["3", "4", "2", "3"]));
    expect(abas()).toEqual([
      ["Obras", "3", "/obras/contratante/sinfra"], ["Medições", "4", "/obras/contratante/sinfra/medicoes"],
      ["A receber", "2", "/obras/contratante/sinfra/a-receber"], ["Processos no SIGA", "3", "/obras/contratante/sinfra/siga"]]);
    expect(abaAtual()).toEqual(["Obras"]);
    // o leitor de tela ouve a quantidade com o que ela conta
    expect([...document.querySelectorAll(".ct-abas .contador .sr-only")].map(s => s.textContent))
      .toEqual([", 3 obras", ", 4 medições", ", 2 em aberto", ", 3 processos"]);
    // a quantidade de Obras e' a da tabela, e muda com ela
    expect(document.querySelectorAll("tr.linha--obra")).toHaveLength(3);
    cleanup();

    api.mockClear();
    abrir("/obras/contratante/sinfra", "diretoria");
    await waitFor(() => expect(abas().map(a => a[1])).toEqual(["3", "4", "2"]));
    expect(abas().map(a => a[0])).toEqual(["Obras", "Medições", "A receber"]);
    expect(api.mock.calls.map(c => String(c[0])).filter(c => c.endsWith("/siga"))).toEqual([]);
  });

  it("Medições: a fila do contratante no mês em trabalho, por quem tem de agir, com a etapa, o tempo parado e a diferença", async () => {
    abrir("/obras/contratante/sinfra/medicoes", "engenharia");
    await screen.findByRole("heading", { level: 2, name: "outubro de 2026" });
    expect(abaAtual()).toEqual(["Medições"]);
    await waitFor(() => expect(document.title).toBe("SINFRA · Medições · grupolotufo"));
    expect(screen.getByText("competência em trabalho · valor cheio")).toBeTruthy();
    // a faixa de números é da aba Obras (os números das obras do contratante)
    expect(screen.queryByLabelText("Números de SINFRA")).toBeNull();
    // os grupos da fila, cada um com as linhas na ordem do servidor; a tabela de Obras não aparece nesta aba
    expect(screen.getAllByRole("heading", { level: 2 }).map(h => h.textContent)).toEqual(
      ["outubro de 2026", "Com a Lotufo", "Com o órgão", "Concluídas no mês", "Sem medição em outubro"]);
    expect(linhasDaFila().map(l => l.querySelector("th a")!.textContent)).toEqual(["Estações BRT", "Cavalaria", "5 Bairros"]);
    expect(screen.queryByRole("table", { name: /Obras de SINFRA/ })).toBeNull();
    const alfa = linhasDaFila()[0];
    expect(limpo(alfa.querySelector('td[data-rotulo="Passo"]')!.textContent)).toContain("Espelhos");
    expect(alfa.querySelector('td[data-rotulo="Parada há"] .selo--critico')).toBeTruthy();
    expect(limpo(alfa.querySelector('td[data-rotulo="Aprovado"]')!.textContent)).toContain("R$ 180.000,00");
    expect(alfa.querySelector('td[data-rotulo="Aprovado"] .diferenca')).toBeTruthy();
    // quem opera vê o próximo passo, que leva à página da medição
    expect(within(alfa).getByRole("link", { name: /Gerar espelho/ }).getAttribute("href")).toBe("/obras/1/medicoes/100#passo-3");
    // a quantidade da aba é o número de linhas: as três da fila e a concluída
    expect(concluidas().map(li => limpo(li.textContent))).toEqual(["Trevo Antigo · 9ª Mediçãorecebida em 10/11"]);
    expect(linhasDaFila().length + concluidas().length).toBe(Number(abas()[1][1]));
    cleanup();

    // quem só consulta vê "Abrir" no lugar do próximo passo
    abrir("/obras/contratante/sinfra/medicoes", "diretoria");
    await screen.findByRole("heading", { level: 2, name: "outubro de 2026" });
    expect(within(linhasDaFila()[0]).getByRole("link", { name: /^Abrir/ })).toBeTruthy();
    expect(screen.queryByRole("link", { name: /Gerar espelho/ })).toBeNull();
  });

  it("Medições sem nada no mês: a linha curta no lugar da fila e a aba com zero", async () => {
    api.mockImplementation(servidor({ "/api/contratantes/sinfra/medicoes": { ...MEDICOES, grupos: [], concluidas: [], sem_medicao: [], quantidade: 0 } }));
    abrir("/obras/contratante/sinfra/medicoes");
    expect(await screen.findByText("Nenhuma medição de SINFRA em andamento em outubro.")).toBeTruthy();
    expect(linhasDaFila()).toHaveLength(0);
    expect(abas()[1]).toEqual(["Medições", "0", "/obras/contratante/sinfra/medicoes"]);
  });

  it("A receber: o subtotal e o prazo do órgão, e o total igual ao da página A receber filtrada pelo mesmo contratante", async () => {
    abrir("/obras/contratante/sinfra/a-receber");
    const painel = await screen.findByRole("region", { name: "Em aberto de SINFRA" });
    expect(abaAtual()).toEqual(["A receber"]);
    const total = document.querySelector(".arc-numero__valor")!.textContent;
    const cabeca = painel.querySelector("tr.arc-grupo")!;
    const subtotal = cabeca.querySelector("td.dinheiro")!.textContent;
    expect(limpo(total)).toBe("R$ 350.000,01");
    expect(subtotal).toBe(total);
    expect(limpo(cabeca.textContent)).toContain("2 em aberto · prazo do órgão: 47 dias");
    // o grupo nasce aberto (um contratante só), com as linhas pela data do protocolo; a quantidade da aba bate com elas
    expect(linhasEmAberto().map(l => l.querySelector(".arc-obra")!.textContent)).toEqual(["Estações BRT", "Cavalaria"]);
    expect(linhasEmAberto()).toHaveLength(Number(abas()[2][1]));
    expect(painel.querySelector("button")).toBeNull();
    // a frase que diz o que o total soma (o a receber da faixa de cima é outra conta, docs/adr/0006)
    expect(document.querySelector(".arc-base")!.textContent).toContain("O em aberto do Fechamento");
    const daAba = { total, subtotal, linhas: linhasEmAberto().map(l => limpo(l.textContent)) };
    cleanup();

    // a página A receber com o mesmo grupo, filtrada pela mesma chave: os mesmos números e as mesmas linhas
    api.mockImplementation(async (caminho: string) => {
      if (caminho !== "/api/a-receber") throw new Error(`chamada inesperada: ${caminho}`);
      return { anos: ["2025", "2026"], total_a_receber_liberado: true, em_aberto_centavos: 350_000_01, por_ano: { 2025: 0, 2026: 350_000_01 },
        quantidade: 2, alem_do_prazo: 0, notas_sem_medicao: [], notas_sem_medicao_centavos: 0, anteriores: { quantidade: 0, valor_centavos: 0 },
        contratantes: [GRUPO_SINFRA, { ...GRUPO_SINFRA, contratante: "MTPAR", chave: "mtpar", em_aberto_centavos: 0, quantidade: 0, linhas: [] }] };
    });
    render(<AReceber busca={{ contratante: "sinfra" }} ir={vi.fn()} />);
    const daPagina = await screen.findByRole("region", { name: "Em aberto de SINFRA" });
    expect(document.querySelector(".arc-numero__valor")!.textContent).toBe(daAba.total);
    expect(daPagina.querySelector("tr.arc-grupo td.dinheiro")!.textContent).toBe(daAba.subtotal);
    expect(linhasEmAberto().map(l => limpo(l.textContent))).toEqual(daAba.linhas);
  });

  it("A receber com a trava do total: a aba diz a trava, sem valor e sem quantidade", async () => {
    api.mockImplementation(servidor({ "/api/contratantes/sinfra/a-receber": { anos: ["2025", "2026"], total_a_receber_liberado: false } }));
    abrir("/obras/contratante/sinfra/a-receber");
    expect(await screen.findByText("O total a receber ainda não está liberado: o em aberto fica sem valor.")).toBeTruthy();
    expect(document.querySelector(".arc-numero__valor, .arc-tabela")).toBeNull();
    await waitFor(() => expect(abas()[1][1]).toBe("4"));
    expect(abas()[2]).toEqual(["A receber", null, "/obras/contratante/sinfra/a-receber"]);
  });

  it("A receber de contratante sem nota em aberto: a linha curta", async () => {
    api.mockImplementation(servidor({ "/api/contratantes/sinfra/a-receber": { ...A_RECEBER, contratante: null, quantidade: 0 } }));
    abrir("/obras/contratante/sinfra/a-receber");
    expect(await screen.findByText("Nenhuma nota em aberto de SINFRA.")).toBeTruthy();
    expect(abas()[2][1]).toBe("0");
  });

  it("Processos no SIGA: um painel por categoria, do mais parado para o menos, com a borda do tempo parado", async () => {
    abrir("/obras/contratante/sinfra/siga", "engenharia");
    await waitFor(() => expect(linhasDoSiga()).toHaveLength(3));
    expect(abaAtual()).toEqual(["Processos no SIGA"]);
    const paineis = [...document.querySelectorAll(".sg-grupo")];
    expect(paineis.map(p => p.querySelector("h2")!.textContent)).toEqual(["Medições", "Aditivos"]);
    expect([...paineis[0].querySelectorAll("tr.sg__linha")].map(l => l.getAttribute("aria-label"))).toEqual(
      ["Estações BRT · 8ª Medição", "Cavalaria · 8ª Medição"]);
    expect(paineis[0].querySelector("tr.sg__linha")!.classList.contains("sg__linha--critico")).toBe(true);
    expect(linhasDoSiga()).toHaveLength(Number(abas()[3][1]));
    // a linha abre o histórico do processo na tela SIGA
    fireEvent.click(paineis[1].querySelector("tr.sg__linha td.sg__proc")!);
    expect(window.location.pathname + window.location.search).toBe("/siga?processo=3");
  });

  it("Processos no SIGA para a diretoria: a aba não existe e o endereço dela mostra Obras", async () => {
    abrir("/obras/contratante/sinfra/siga", "diretoria");
    await screen.findByRole("table", { name: /Obras de SINFRA/ });
    expect(abaAtual()).toEqual(["Obras"]);
    expect(abas().map(a => a[0])).not.toContain("Processos no SIGA");
    expect(document.querySelector(".sg-grupo, tr.sg__linha")).toBeNull();
    expect(api.mock.calls.map(c => String(c[0])).filter(c => c.endsWith("/siga"))).toEqual([]);
  });

  it("a aba que falhou diz a falha só nela; as outras e a quantidade delas continuam", async () => {
    api.mockImplementation(servidor({ "/api/contratantes/sinfra/medicoes": new Error("falhou") }));
    abrir("/obras/contratante/sinfra/medicoes", "engenharia");
    expect((await screen.findByRole("alert")).textContent).toContain("Não foi possível carregar as medições");
    await waitFor(() => expect(abas().map(a => a[1])).toEqual(["3", null, "2", "3"]));
    fireEvent.click(screen.getByRole("link", { name: /^A receber/ }));
    expect(window.location.pathname).toBe("/obras/contratante/sinfra/a-receber");
    await screen.findByRole("region", { name: "Em aberto de SINFRA" });
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
