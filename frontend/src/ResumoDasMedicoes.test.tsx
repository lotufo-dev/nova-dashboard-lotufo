import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ResumoDasMedicoes, { type RespostaResumo } from "./ResumoDasMedicoes";
import { ir, useRota } from "./rota";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

// Dados sinteticos, com os nomes do cadastro de exemplo. A etapa, as datas, os valores (na cota), as referencias das
// variacoes, a diferenca e o tempo parado (o `parada` da fila de trabalho) vem prontos do servidor; a tela so' mostra.
type Linha = RespostaResumo["grupos"][number]["linhas"][number];
type EtapaDaLinha = Linha["etapas"][number];
const e = (etapa: EtapaDaLinha["etapa"], situacao: EtapaDaLinha["situacao"], data: string | null = null): EtapaDaLinha => ({ etapa, situacao, data });
const linha = (x: Partial<Linha> & Pick<Linha, "contrato_id" | "obra" | "medicao_id" | "titulo" | "etapa" | "etapas">): Linha => ({
  contratante: "Secretaria de Exemplo", medicao_ids: [x.medicao_id], numero: 1, tipo: "execucao", competencia: "2026-10",
  valor_centavos: null, parada: null, recebida_em: null, dias_da_nota_ao_recebimento: null,
  pedido_do_aprovado_centavos: null, abaixo_do_pedido_centavos: null, acima_do_pedido_centavos: null, ...x,
});
type Parada = NonNullable<Linha["parada"]>;
const parada = (desde: string | null, dias_uteis: number | null, situacao: Parada["situacao"], extra: Partial<Parada> = {}): Parada => ({
  desde, dias_uteis, hoje: false, situacao, prazo_orgao_dias: null, esperada: null, alem_do_prazo: false, ...extra });
const FUTURAS = [e("boletim", "futuro"), e("nota", "futuro"), e("protocolado", "futuro"), e("recebido", "futuro")];

// protocolada ha' 4 dias uteis, dentro do prazo do orgao, com o aprovado 1,9% abaixo do pedido (acima do limite de
// 0,5%: critico)
const PROPRIA = linha({
  contrato_id: 7, obra: "Obra Própria", medicao_id: 71, titulo: "12ª Medição + Reajuste", medicao_ids: [71, 72], etapa: "protocolado",
  valor_centavos: 10_100_001, parada: parada("2026-11-10", 4, "andamento", { prazo_orgao_dias: 30, esperada: "2026-12-10" }),
  pedido_do_aprovado_centavos: 10_300_000, abaixo_do_pedido_centavos: 199_999, acima_do_pedido_centavos: 0,
  etapas: [e("em_analise", "feito", "2026-11-03"), e("boletim", "feito"), e("nota", "feito", "2026-11-09"),
    e("protocolado", "atual", "2026-11-10"), e("recebido", "futuro")],
});
// protocolada hoje, com o aprovado acima do pedido
const SEXTA = linha({
  contrato_id: 13, obra: "Obra Sexta", medicao_id: 131, titulo: "2ª Medição", etapa: "protocolado", valor_centavos: 5_000_000,
  parada: parada("2026-11-16", 0, "feito", { hoje: true }),
  pedido_do_aprovado_centavos: 4_990_000, abaixo_do_pedido_centavos: 0, acima_do_pedido_centavos: 10_000,
  etapas: [e("em_analise", "feito", "2026-11-03"), e("boletim", "feito", "2026-11-06"), e("nota", "feito", "2026-11-09"),
    e("protocolado", "atual", "2026-11-16"), e("recebido", "futuro")],
});
// em analise ha' 11 dias uteis: critico
const QUARTA = linha({
  contrato_id: 11, obra: "Obra Quarta", medicao_id: 111, titulo: "4ª Medição", etapa: "em_analise", valor_centavos: 900_000,
  parada: parada("2026-10-30", 11, "critico"), etapas: [e("em_analise", "atual", "2026-10-30"), ...FUTURAS],
});
// familia sem planilha/carta: a obra nao tem a etapa "em analise"; no boletim, sem a data do evento
const CONSORCIO = linha({
  contrato_id: 8, obra: "Obra Consórcio", contratante: "Companhia de Exemplo", medicao_id: 81, titulo: "3ª Medição", etapa: "boletim",
  valor_centavos: 333_300, parada: parada(null, null, null),
  etapas: [e("boletim", "atual"), e("nota", "futuro"), e("protocolado", "futuro"), e("recebido", "futuro")],
});
const REAJUSTE = linha({
  contrato_id: 8, obra: "Obra Consórcio", contratante: "Companhia de Exemplo", medicao_id: 82, titulo: "Reajuste da 3ª Medição", tipo: "reajuste",
  etapa: "recebido", valor_centavos: 50_000, recebida_em: "2026-11-12", dias_da_nota_ao_recebimento: 8,
  pedido_do_aprovado_centavos: 50_000, abaixo_do_pedido_centavos: 0, acima_do_pedido_centavos: 0,
  etapas: [e("boletim", "feito", "2026-11-02"), e("nota", "feito", "2026-11-04"), e("protocolado", "feito", "2026-11-05"), e("recebido", "feito", "2026-11-12")],
});
const ANTIGA = linha({
  contrato_id: 7, obra: "Obra Própria", medicao_id: 61, titulo: "11ª Medição", competencia: "2025-12", etapa: "em_analise", valor_centavos: 0,
  parada: parada("2026-01-08", 214, "critico"), etapas: [e("em_analise", "atual", "2026-01-08"), ...FUTURAS],
});
const RESUMO: RespostaResumo = {
  hoje: "2026-11-16", mes: "2026-10", em_trabalho: "2026-10",
  atualizacao: { ultimo_lancamento: "2026-11-14 18:40:00", rm_lido_em: "2026-11-16 11:00:00" },
  contratante: null,
  contratantes: [{ contratante: "Companhia de Exemplo", medicoes: 2, anteriores: 0 }, { contratante: "Secretaria de Exemplo", medicoes: 4, anteriores: 1 }],
  etapas: [
    { etapa: "antes", medicoes: 0, valor_centavos: 0 }, { etapa: "em_analise", medicoes: 1, valor_centavos: 900_000 },
    { etapa: "boletim", medicoes: 1, valor_centavos: 333_300 }, { etapa: "nota", medicoes: 0, valor_centavos: 0 },
    { etapa: "protocolado", medicoes: 3, valor_centavos: 15_100_001 }, { etapa: "recebido", medicoes: 1, valor_centavos: 50_000 },
  ],
  medido: { valor_centavos: 16_383_301, mes_anterior: { competencia: "2026-09", valor_centavos: 15_000_000 },
    ano_anterior: { competencia: "2025-10", valor_centavos: 16_383_301 } },
  // o protocolado acumulado: o que esta' na etapa (151.000,01) e o que ja' foi recebido (500,00)
  protocolado_acumulado_centavos: 15_150_001,
  mesma_altura: { competencia: "2026-09", ate: "2026-10-16", protocolado_acumulado_centavos: 12_500_000, recebido_centavos: null },
  diferenca_critica_por_mil: 5,
  grupos: [{ contratante: "Companhia de Exemplo", medicoes: 2, valor_centavos: 383_300, linhas: [CONSORCIO, REAJUSTE] },
    { contratante: "Secretaria de Exemplo", medicoes: 4, valor_centavos: 16_000_001, linhas: [PROPRIA, QUARTA, SEXTA] }],
  sem_medicao: [
    { contrato_id: 9, obra: "Obra Terceira", contratante: "Secretaria de Exemplo",
      ultima: { medicao_id: 91, titulo: "5ª Medição", competencia: "2026-09", etapa: "protocolado" } },
    { contrato_id: 14, obra: "Obra Sétima", contratante: "Secretaria de Exemplo",
      ultima: { medicao_id: 141, titulo: "1ª Medição", competencia: "2025-12", etapa: "recebido" } },
    { contrato_id: 10, obra: "Obra Nova", contratante: null, ultima: null },
  ],
  anteriores_etapas: [
    { etapa: "antes", medicoes: 0, valor_centavos: 0 }, { etapa: "em_analise", medicoes: 1, valor_centavos: 0 },
    { etapa: "boletim", medicoes: 0, valor_centavos: 0 }, { etapa: "nota", medicoes: 0, valor_centavos: 0 },
    { etapa: "protocolado", medicoes: 0, valor_centavos: 0 }, { etapa: "recebido", medicoes: 0, valor_centavos: 0 },
  ],
  anteriores: [{ competencia: "2025-12", medicoes: 1, valor_centavos: 0, linhas: [ANTIGA] }],
};
const ZERADAS = RESUMO.etapas.map(x => ({ ...x, medicoes: 0, valor_centavos: 0 }));
const VAZIO: RespostaResumo = {
  ...RESUMO, mes: "2026-09", atualizacao: { ultimo_lancamento: null, rm_lido_em: null }, contratantes: [],
  etapas: ZERADAS, medido: { valor_centavos: 0, mes_anterior: null, ano_anterior: null }, mesma_altura: null,
  grupos: [], sem_medicao: [], anteriores_etapas: ZERADAS, anteriores: [],
};

const texto = (el: Element | null) => (el?.textContent ?? "").replace(/\s+/g, " ").trim();
const celulas = (l: HTMLElement) => within(l).getAllByRole("cell").map(texto);

// a pagina le a competencia, a aba, a vista e o contratante da URL, como no App
function Pagina() {
  const { busca } = useRota();
  return <ResumoDasMedicoes ir={ir} busca={busca} />;
}
const abrir = (endereco = "/resumo-medicoes") => {
  window.history.replaceState(null, "", endereco);
  return render(<Pagina />);
};

describe("Resumo das medições em quadro por etapa (#749, #805)", () => {
  afterEach(() => { cleanup(); api.mockReset(); window.history.replaceState(null, "", "/"); });

  it("abre na competência em trabalho, no quadro, e diz de quando é o dado", async () => {
    api.mockResolvedValue(RESUMO);
    abrir();
    expect(await screen.findByRole("heading", { name: "Outubro de 2026" })).toBeTruthy();
    expect(api).toHaveBeenCalledWith("/api/resumo-medicoes");
    expect(screen.getByText("Competência em trabalho")).toBeTruthy();
    // os carimbos do banco (UTC) saem no horario de Cuiaba
    expect(screen.getByText(/Medido das medições de cada etapa, na cota da Lotufo\. Último lançamento em 14\/11\/2026 às 14:40; recebimentos lidos do RM em 16\/11\/2026 às 07:00\./)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Voltar à competência em trabalho/ })).toBeNull();
    expect(screen.getByRole("link", { name: /Exportar CSV/ }).getAttribute("href")).toBe("/api/resumo-medicoes.csv?mes=2026-10");
    expect(screen.getByRole("link", { name: "Mês a mês no Fechamento" }).getAttribute("href")).toBe("/fechamento");
    // as abas: o mes em trabalho e os meses anteriores, com a quantidade em aberto
    const abas = within(screen.getByRole("navigation", { name: "Resumo das medições" })).getAllByRole("link");
    expect(abas.map(texto)).toEqual(["Outubro em trabalho", "Meses anteriores 11 medição em aberto"]);
    expect(abas[0].getAttribute("aria-current")).toBe("page");
    expect(abas[1].getAttribute("href")).toBe("/resumo-medicoes?aba=anteriores");
    // a vista padrao e' o quadro
    expect(screen.getByRole("group", { name: "Medições de outubro de 2026, uma coluna por etapa" })).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("a faixa diz o valor e a quantidade de cada etapa, com a marca dela, e o medido do mês com as variações", async () => {
    api.mockResolvedValue(RESUMO);
    const { container } = abrir();
    await screen.findByRole("heading", { name: "Outubro de 2026" });
    const itens = [...container.querySelectorAll(".rdm-faixa__item")];
    expect(itens.map(i => texto(i.querySelector("dt")))).toEqual(["Em análise", "Boletim", "Nota", "Protocolado", "Recebido", "Medido em outubro"]);
    expect(itens.map(i => texto(i.querySelector(".rdm-faixa__valor")))).toEqual([
      "R$ 9.000,00", "R$ 3.333,00", "—", "R$ 151.000,01", "R$ 500,00", "R$ 163.833,01"]);
    expect(itens.slice(0, 5).map(i => texto(i.querySelector(".rdm-faixa__qtd")))).toEqual(["1 medição", "1 medição", "", "3 medições", "1 medição"]);
    expect(itens.slice(0, 5).map(i => i.querySelector(".marca-etapa__cor")?.className)).toEqual(
      ["em_analise", "boletim", "nota", "protocolado", "recebido"].map(x => `marca-etapa__cor marca-etapa__cor--${x}`));
    // o protocolado: o ACUMULADO da competencia (151.500,01, com os 500,00 ja' recebidos) contra o da anterior na
    // mesma altura (125.000,00). A linha da variacao mostra o numero de que a seta fala e a referencia escrita; o
    // recebido veio sem lastro: nada
    const [, , , protocolado, recebido, medido] = itens;
    expect(protocolado.querySelector(".variacao")?.className).toBe("variacao variacao--bom");
    expect(texto(protocolado.querySelector(".rdm-faixa__base"))).toBe("acumulado R$ 151.500,01");
    expect(texto(protocolado.querySelector(".rdm-faixa__variacao"))).toBe(
      "acumulado R$ 151.500,01 ▲ +21,2%× set até 16/10subiu 21,2% em relação a setembro até 16 de outubro");
    expect(recebido.querySelector(".variacao")).toBeNull();
    expect(itens[0].querySelector(".variacao")).toBeNull();
    // o medido: contra o mes anterior e contra o mesmo mes do ano anterior
    expect([...medido.querySelectorAll(".variacao")].map(v => [v.className, texto(v.querySelector(".sr-only"))])).toEqual([
      ["variacao variacao--bom", "subiu 9,2% em relação a setembro"],
      ["variacao variacao--estavel", "estável em relação a outubro de 2025"]]);
  });

  it("o órgão pagou cedo: o valor do protocolado cai, e a variação, que compara o acumulado, não fica vermelha", async () => {
    // decisao do dono de 18/11/2026. Das 150.000,00 protocoladas, 110.000,00 ja' foram recebidas: na etapa restam
    // 40.000,00, menos que as 125.000,00 da referencia; o acumulado (150.000,00) esta' 20% acima dela
    const etapas = RESUMO.etapas.map(x => x.etapa === "protocolado" ? { ...x, medicoes: 1, valor_centavos: 4_000_000 }
      : x.etapa === "recebido" ? { ...x, medicoes: 2, valor_centavos: 11_000_000 } : x);
    api.mockResolvedValue({ ...RESUMO, etapas, protocolado_acumulado_centavos: 15_000_000,
      mesma_altura: { ...RESUMO.mesma_altura!, recebido_centavos: 10_000_000 } });
    const { container } = abrir();
    await screen.findByRole("heading", { name: "Outubro de 2026" });
    const [, , , protocolado, recebido] = [...container.querySelectorAll(".rdm-faixa__item")];
    expect(texto(protocolado.querySelector(".rdm-faixa__valor"))).toBe("R$ 40.000,00");          // o valor continua o da etapa
    expect(protocolado.querySelector(".variacao")?.className).toBe("variacao variacao--bom");
    // o acumulado, que e' outro numero, vai escrito ao lado da variacao dele
    expect(texto(protocolado.querySelector(".rdm-faixa__variacao"))).toBe(
      "acumulado R$ 150.000,00 ▲ +20,0%× set até 16/10subiu 20,0% em relação a setembro até 16 de outubro");
    // no recebido o valor da etapa ja' e' o acumulado: a variacao compara o proprio valor, sem a base escrita
    expect(texto(recebido.querySelector(".rdm-faixa__variacao"))).toBe("▲ +10,0%× set até 16/10subiu 10,0% em relação a setembro até 16 de outubro");
    expect(recebido.querySelector(".rdm-faixa__base")).toBeNull();
  });

  it("tudo o que foi protocolado já foi recebido: a etapa fica no traço e a linha do acumulado continua", async () => {
    const etapas = RESUMO.etapas.map(x => x.etapa === "protocolado" ? { ...x, medicoes: 0, valor_centavos: 0 }
      : x.etapa === "recebido" ? { ...x, medicoes: 3, valor_centavos: 15_000_000 } : x);
    api.mockResolvedValue({ ...RESUMO, etapas, protocolado_acumulado_centavos: 15_000_000 });
    const { container } = abrir();
    await screen.findByRole("heading", { name: "Outubro de 2026" });
    const protocolado = [...container.querySelectorAll(".rdm-faixa__item")][3];
    expect(texto(protocolado.querySelector(".rdm-faixa__valor"))).toBe("—");
    expect(protocolado.querySelector(".rdm-faixa__qtd")).toBeNull();
    expect(texto(protocolado.querySelector(".rdm-faixa__variacao"))).toContain("acumulado R$ 150.000,00 ▲ +20,0%");
  });

  it("sem lastro num dos lados do protocolado acumulado, somem o número e a variação", async () => {
    api.mockResolvedValue({ ...RESUMO, protocolado_acumulado_centavos: null });
    const { container, unmount } = abrir();
    await screen.findByRole("heading", { name: "Outubro de 2026" });
    const protocolado = () => [...container.querySelectorAll(".rdm-faixa__item")][3];
    expect(texto(protocolado().querySelector(".rdm-faixa__valor"))).toBe("R$ 151.000,01");
    expect(protocolado().querySelector(".rdm-faixa__variacao, .rdm-faixa__base, .variacao")).toBeNull();
    unmount();
    api.mockResolvedValue({ ...RESUMO, mesma_altura: { ...RESUMO.mesma_altura!, protocolado_acumulado_centavos: null } });
    const outra = abrir();
    await screen.findByRole("heading", { name: "Outubro de 2026" });
    // o lado de hoje existe, mas sem a referencia nao ha' variacao: o numero solto nao aparece
    expect([...outra.container.querySelectorAll(".rdm-faixa__item")][3].querySelector(".rdm-faixa__variacao, .rdm-faixa__base, .variacao")).toBeNull();
  });

  it("o quadro tem uma coluna por etapa, com a quantidade e o valor, e um cartão por medição, o de maior valor primeiro", async () => {
    api.mockResolvedValue(RESUMO);
    abrir();
    const quadro = await screen.findByRole("group", { name: "Medições de outubro de 2026, uma coluna por etapa" });
    const colunas = within(quadro).getAllByRole("region");
    expect(colunas.map(c => texto(c.querySelector(".rdm-coluna__cab")))).toEqual([
      "Em análise1 mediçãoR$ 9.000,00", "Boletim1 mediçãoR$ 3.333,00", "Nota", "Protocolado3 mediçõesR$ 151.000,01", "Recebido1 mediçãoR$ 500,00"]);
    expect(colunas.map(c => within(c).queryAllByRole("listitem").map(li => texto(li.querySelector(".rdm-cartao__obra"))))).toEqual([
      ["Obra Quarta"], ["Obra Consórcio"], [], ["Obra Própria", "Obra Sexta"], ["Obra Consórcio"]]);
    // a coluna vazia diz que esta' vazia
    expect(texto(colunas[2])).toBe("Notanenhuma medição");
  });

  it("o cartão diz a obra, o contratante, a medição, o valor, há quanto tempo está parada e a diferença para o pedido", async () => {
    api.mockResolvedValue(RESUMO);
    abrir();
    const quadro = await screen.findByRole("group", { name: /uma coluna por etapa/ });
    const cartao = (obra: string, coluna: number) => within(within(quadro).getAllByRole("region")[coluna]).getAllByRole("listitem")
      .find(li => texto(li.querySelector(".rdm-cartao__obra")) === obra) as HTMLElement;
    const propria = cartao("Obra Própria", 3);
    expect(within(propria).getByRole("link", { name: "Obra Própria" }).getAttribute("href")).toBe("/obras/7/medicoes");
    expect(within(propria).getByRole("link", { name: "12ª Medição + Reajuste" }).getAttribute("href")).toBe("/obras/7/medicoes/71");
    expect(texto(propria.querySelector(".rdm-cartao__sub"))).toBe("Secretaria de Exemplo · 12ª Medição + Reajuste");
    expect(texto(propria.querySelector(".rdm-cartao__valor"))).toBe("R$ 101.000,01");
    // o tempo parado e' o da fila de trabalho: a situacao que o servidor leu, o prazo do orgao e a data do evento
    expect(propria.querySelector(".selo")?.className).toBe("selo selo--andamento");
    expect(texto(propria.querySelector(".rdm-cartao__tempo"))).toBe("há 4 dias úteisprazo do órgão: 10/12desde 10/11/26");
    // aprovado 1,9% abaixo do pedido: acima do limite de 0,5% que o servidor manda, critico
    expect(propria.querySelector(".diferenca")?.className).toBe("diferenca diferenca--ruim");
    expect(texto(propria.querySelector(".diferenca .sr-only"))).toBe("R$ 1.999,99 abaixo do pedido, 1,9%");
    // 11 dias uteis em analise: critico; em analise nao ha' diferenca
    const quarta = cartao("Obra Quarta", 0);
    expect(quarta.querySelector(".selo")?.className).toBe("selo selo--critico");
    expect(texto(quarta.querySelector(".selo"))).toBe("há 11 dias úteis");
    expect(quarta.querySelector(".diferenca")).toBeNull();
    // chegou hoje: so' o selo, sem repetir a data; o aprovado acima do pedido sai escrito, no tom da atencao
    const sexta = cartao("Obra Sexta", 3);
    expect(texto(sexta.querySelector(".rdm-cartao__tempo"))).toBe("desde hoje");
    expect(sexta.querySelector(".selo")?.className).toBe("selo selo--feito");
    expect(sexta.querySelector(".diferenca")?.className).toBe("diferenca diferenca--leve");
    expect(texto(sexta.querySelector(".diferenca"))).toBe("+ R$ 100,00acima do pedido");
    // sem a data do evento, nada e' contado; igual ao pedido nao vira etiqueta
    const consorcio = cartao("Obra Consórcio", 1);
    expect(consorcio.querySelector(".selo")).toBeNull();
    expect(consorcio.querySelector(".rdm-cartao__tempo")).toBeNull();
    // a recebida: a data e os dias da nota ao recebimento
    const recebida = cartao("Obra Consórcio", 4);
    expect(recebida.querySelector(".selo")?.className).toBe("selo selo--feito");
    expect(texto(recebida.querySelector(".rdm-cartao__tempo"))).toBe("recebida em 12/11/268 dias após a nota");
    expect(recebida.querySelector(".diferenca")).toBeNull();
  });

  it("as obras sem medição no mês saem num bloco curto, com o mês da última medição de cada uma", async () => {
    api.mockResolvedValue(RESUMO);
    abrir();
    const bloco = await screen.findByRole("region", { name: "Sem medição em outubro" });
    expect(texto(within(bloco).getByRole("heading").parentElement)).toBe("Sem medição em outubro33 obras");
    // do mesmo ano, so' o mes; de outro, com o ano; a obra que nunca mediu diz isso
    expect(within(bloco).getAllByRole("listitem").map(texto)).toEqual(["Obra Terceiraúltima em set", "Obra Sétimaúltima em dez/25", "Obra Novanunca mediu"]);
    expect(within(bloco).getByRole("link", { name: "5ª Medição, de setembro de 2026" }).getAttribute("href")).toBe("/obras/9/medicoes/91");
    expect(within(bloco).getByRole("link", { name: "Obra Terceira" }).getAttribute("href")).toBe("/obras/9/medicoes");
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("a planilha/carta ainda não enviada não tem coluna: fica num bloco próprio, e na tabela com o selo", async () => {
    // a medicao ainda nao enviada nao conta no medido: o servidor manda a linha sem valor e a etapa com zero
    const antes = linha({ contrato_id: 15, obra: "Obra Oitava", medicao_id: 151, titulo: "1ª Medição", etapa: "antes",
      parada: parada("2026-11-11", 3, "andamento"), etapas: [e("em_analise", "futuro"), ...FUTURAS] });
    api.mockResolvedValue({ ...RESUMO, etapas: RESUMO.etapas.map(x => (x.etapa === "antes" ? { ...x, medicoes: 1 } : x)),
      grupos: [{ contratante: "Secretaria de Exemplo", medicoes: 1, valor_centavos: 0, linhas: [antes] }] });
    abrir();
    const bloco = await screen.findByRole("region", { name: "Planilha/carta a enviar" });
    // com ha' quanto tempo a planilha/carta espera o envio
    expect(within(bloco).getAllByRole("listitem").map(texto)).toEqual(["Obra Oitava1ª Mediçãohá 3 dias úteis"]);
    expect(within(screen.getByRole("group", { name: /uma coluna por etapa/ })).queryAllByRole("listitem")).toEqual([]);
    cleanup();
    abrir("/resumo-medicoes?vista=tabela");
    const tabela = await screen.findByRole("table", { name: /Etapa da medição de cada obra/ });
    expect(texto(within(tabela).getAllByRole("rowheader")[1])).toBe("Obra Oitava1ª MediçãoPlanilha/carta a enviar");
    expect(celulas(within(tabela).getAllByRole("row")[2])).toEqual(["ainda não", "ainda não", "ainda não", "ainda não", "ainda não", "—"]);
    expect(screen.queryByRole("region", { name: "Planilha/carta a enviar" })).toBeNull();
  });

  it("a vista Tabela fica na URL: uma linha por medição, por contratante, com a data de cada etapa e a diferença", async () => {
    api.mockResolvedValue(RESUMO);
    abrir();
    const vistas = within(await screen.findByRole("navigation", { name: "Vista do mês" })).getAllByRole("link");
    expect(vistas.map(v => [texto(v), v.getAttribute("aria-current")])).toEqual([["Quadro", "true"], ["Tabela", null]]);
    fireEvent.click(vistas[1]);
    const tabela = await screen.findByRole("table", { name: /Etapa da medição de cada obra em outubro de 2026/ });
    expect(window.location.search).toBe("?vista=tabela");
    expect(api).toHaveBeenCalledTimes(1);     // a vista nao pede nada ao servidor
    expect(screen.queryByRole("group", { name: /uma coluna por etapa/ })).toBeNull();
    expect(within(tabela).getAllByRole("columnheader").map(texto)).toEqual(["Obra", "Em análise", "Boletim", "Nota", "Protocolado", "Recebido", "Medido"]);
    // o contratante abre o grupo com a quantidade e o medido dele (o cabecalho de grupo forte)
    expect(within(tabela).getAllByRole("rowheader").map(texto)).toEqual([
      "Companhia de Exemplo2 medições", "Obra Consórcio3ª Medição", "Obra ConsórcioReajuste da 3ª Medição",
      "Secretaria de Exemplo4 medições", "Obra Própria12ª Medição + Reajuste", "Obra Quarta4ª Medição", "Obra Sexta2ª Medição"]);
    const [, grupo, consorcio, reajuste, , propria] = within(tabela).getAllByRole("row");
    expect(celulas(grupo)).toEqual(["R$ 3.833,00"]);
    // sem "em analise" no fluxo; no boletim, sem data registrada: o traço, nunca uma data estimada
    expect(celulas(consorcio)).toEqual(["a obra não tem esta etapa", "BoletimEtapa atual, desde —sem data registrada", "ainda não", "ainda não", "ainda não", "R$ 3.333,00"]);
    expect(celulas(propria).slice(0, 5)).toEqual(["Em análiseFeito em 03/11/26", "BoletimFeito em —sem data registrada", "NotaFeito em 09/11/26",
      "ProtocoladoEtapa atual, desde 10/11/26", "ainda não"]);
    // a diferenca para o pedido sob o valor da linha
    const valor = within(propria).getAllByRole("cell").at(-1) as HTMLElement;
    expect(texto(valor.querySelector(".rdm-valor__cel > span"))).toBe("R$ 101.000,01");
    expect(valor.querySelector(".diferenca")?.className).toBe("diferenca diferenca--ruim");
    // a situacao tem forma alem da cor: o visto no que passou, o meio circulo na etapa atual
    const [, boletim, , protocolado] = within(propria).getAllByRole("cell");
    expect(boletim.querySelector(".glifo--feito")).not.toBeNull();
    expect(protocolado.querySelector(".glifo--andamento")).not.toBeNull();
    expect(protocolado.getAttribute("aria-current")).toBe("step");
    // a obra e a medicao abrem; a obra repetida na linha de baixo nao e' link de novo
    expect(within(propria).getByRole("link", { name: "Obra Própria" }).getAttribute("href")).toBe("/obras/7/medicoes");
    expect(within(reajuste).queryByRole("link", { name: "Obra Consórcio" })).toBeNull();
    // e volta ao quadro, que e' o padrao e sai da URL
    fireEvent.click(screen.getByRole("link", { name: "Quadro" }));
    expect(await screen.findByRole("group", { name: /uma coluna por etapa/ })).toBeTruthy();
    expect(window.location.search).toBe("");
  });

  it("etapa que ficou para trás sem registro não leva visto nem data", async () => {
    // protocolada direto: a planilha nao foi enviada, nao houve boletim e a nota nao tem emissao registrada
    api.mockResolvedValue({ ...RESUMO, grupos: [{ contratante: "Secretaria de Exemplo", medicoes: 1, valor_centavos: 45_001, linhas: [
      linha({ contrato_id: 12, obra: "Obra Quinta", medicao_id: 121, titulo: "8ª Medição", etapa: "protocolado", valor_centavos: 45_001,
        etapas: [e("em_analise", "sem_registro"), e("boletim", "sem_registro"), e("nota", "feito", "2026-11-10"),
          e("protocolado", "atual", "2026-11-12"), e("recebido", "futuro")] })] }] });
    abrir("/resumo-medicoes?vista=tabela");
    const tabela = await screen.findByRole("table", { name: /Etapa da medição de cada obra/ });
    const quinta = within(tabela).getAllByRole("row")[2];
    expect(celulas(quinta)).toEqual(["sem registro", "sem registro", "NotaFeito em 10/11/26", "ProtocoladoEtapa atual, desde 12/11/26", "ainda não", "R$ 450,01"]);
    const [analise, boletim, nota, , recebido] = within(quinta).getAllByRole("cell");
    for (const c of [analise, boletim]) {
      expect(c.className).toBe("rdm-etapa rdm-etapa--sem-registro");
      expect(c.querySelector(".glifo")).toBeNull();
    }
    // nem a cor da etapa (feita) nem a da que falta
    expect(nota.className).toContain("rdm-cor--nota");
    expect(recebido.className).toContain("rdm-cor--vazia");
  });

  it("a aba Meses anteriores fica na URL e mostra as medições em aberto por competência, com a faixa das etapas", async () => {
    api.mockResolvedValue(RESUMO);
    const { container } = abrir();
    fireEvent.click(await screen.findByRole("link", { name: /Meses anteriores/ }));
    const tabela = await screen.findByRole("table", { name: /competências anteriores a outubro de 2026 ainda não recebidas/ });
    expect(window.location.search).toBe("?aba=anteriores");
    expect(screen.getByRole("link", { name: /Meses anteriores/ }).getAttribute("aria-current")).toBe("page");
    expect(within(tabela).getAllByRole("rowheader").map(texto)).toEqual(["Dezembro de 20251 medição", "Obra Própria11ª Medição"]);
    // a data curta leva o ano (a lista atravessa o ano); o valor zero vira traço
    expect(celulas(within(tabela).getAllByRole("row")[2])).toEqual(["Em análiseEtapa atual, desde 08/01/26", "ainda não", "ainda não", "ainda não", "ainda não", "—"]);
    // a faixa e' a dos meses anteriores: so' as etapas, sem o medido do mes nem variacao
    expect([...container.querySelectorAll(".rdm-faixa__item dt")].map(texto)).toEqual(["Em análise", "Boletim", "Nota", "Protocolado", "Recebido"]);
    expect(container.querySelector(".rdm-faixa .variacao")).toBeNull();
    // o quadro, a vista e os blocos do mes nao aparecem aqui
    expect(screen.queryByRole("navigation", { name: "Vista do mês" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Sem medição em outubro" })).toBeNull();
    // abre direto pela URL
    cleanup();
    abrir("/resumo-medicoes?aba=anteriores");
    expect(await screen.findByRole("table", { name: /competências anteriores/ })).toBeTruthy();
  });

  it("o filtro por contratante fica na URL, lista quem tem medição na aba e recorta no servidor", async () => {
    const daCompanhia: RespostaResumo = { ...RESUMO, contratante: "Companhia de Exemplo", grupos: [RESUMO.grupos[0]], sem_medicao: [], anteriores: [],
      etapas: RESUMO.etapas.map(x => (x.etapa === "boletim" || x.etapa === "recebido" ? x : { ...x, medicoes: 0, valor_centavos: 0 })),
      medido: { valor_centavos: 383_300, mes_anterior: null, ano_anterior: null }, mesma_altura: null };
    api.mockImplementation(async (caminho: string) => (caminho.includes("contratante=") ? daCompanhia : RESUMO));
    const { container } = abrir();
    const filtro = within(await screen.findByRole("navigation", { name: "Contratante" })).getAllByRole("link");
    expect(filtro.map(f => [texto(f), f.getAttribute("aria-current")])).toEqual([
      ["Todos 6", "true"], ["Companhia de Exemplo 2", null], ["Secretaria de Exemplo 4", null]]);
    fireEvent.click(filtro[1]);
    await waitFor(() => expect(api).toHaveBeenLastCalledWith("/api/resumo-medicoes?contratante=Companhia+de+Exemplo"));
    expect(window.location.search).toBe("?contratante=Companhia+de+Exemplo");
    await waitFor(() => expect(texto(container.querySelector(".rdm-faixa__item--medido .rdm-faixa__valor"))).toBe("R$ 3.833,00"));
    expect(screen.getByRole("link", { name: /Companhia de Exemplo 2/ }).getAttribute("aria-current")).toBe("true");
    expect(within(screen.getByRole("group", { name: /uma coluna por etapa/ })).getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByRole("link", { name: /Exportar CSV/ }).getAttribute("href")).toBe("/api/resumo-medicoes.csv?mes=2026-10&contratante=Companhia+de+Exemplo");
    // as outras escolhas levam o filtro junto
    expect(screen.getByRole("link", { name: "Tabela" }).getAttribute("href")).toBe("/resumo-medicoes?contratante=Companhia+de+Exemplo&vista=tabela");
    // nos meses anteriores, so' quem tem medicao em aberto la'; o contratante da URL aparece mesmo sem nenhuma
    fireEvent.click(screen.getByRole("link", { name: /Meses anteriores/ }));
    expect(await screen.findByText(/Nenhuma medição aberta de meses anteriores de Companhia de Exemplo\./)).toBeTruthy();
    expect(within(screen.getByRole("navigation", { name: "Contratante" })).getAllByRole("link").map(texto)).toEqual([
      "Todos", "Companhia de Exemplo 0", "Secretaria de Exemplo 1"]);
    fireEvent.click(screen.getByRole("link", { name: "Ver todos os contratantes" }));
    await waitFor(() => expect(api).toHaveBeenLastCalledWith("/api/resumo-medicoes"));
    expect(window.location.search).toBe("?aba=anteriores");
  });

  it("troca a competência, guarda o mês na URL e volta à competência em trabalho", async () => {
    api.mockImplementation(async (caminho: string) => (caminho.endsWith("mes=2026-09") ? VAZIO : RESUMO));
    abrir();
    fireEvent.click(await screen.findByRole("button", { name: "Mês anterior" }));
    expect(await screen.findByRole("heading", { name: "Setembro de 2026" })).toBeTruthy();
    expect(api).toHaveBeenLastCalledWith("/api/resumo-medicoes?mes=2026-09");
    expect(window.location.search).toBe("?mes=2026-09");
    expect(screen.getByText("Competência")).toBeTruthy();
    // fora da competencia em trabalho, a aba leva o nome do mes
    expect(texto(within(screen.getByRole("navigation", { name: "Resumo das medições" })).getAllByRole("link")[0])).toBe("Setembro de 2026");
    // sem lancamento e sem leitura do RM, a frase diz so' o que o sistema tem; o mes vazio vira uma linha curta
    expect(screen.getByText("Medido das medições de cada etapa, na cota da Lotufo. Nenhum lançamento registrado.")).toBeTruthy();
    expect(screen.getByText("Nenhuma medição em setembro de 2026.")).toBeTruthy();
    expect(screen.queryByRole("group", { name: /uma coluna por etapa/ })).toBeNull();
    expect(screen.queryByRole("region", { name: /Sem medição/ })).toBeNull();
    expect(screen.queryByRole("navigation", { name: "Contratante" })).toBeNull();
    expect(screen.getByRole("link", { name: /Exportar CSV/ }).getAttribute("href")).toBe("/api/resumo-medicoes.csv?mes=2026-09");
    fireEvent.click(screen.getByRole("button", { name: "Voltar à competência em trabalho" }));
    expect(await screen.findByRole("heading", { name: "Outubro de 2026" })).toBeTruthy();
    expect(api).toHaveBeenLastCalledWith("/api/resumo-medicoes");
    expect(window.location.search).toBe("");
  });

  it("abre no mês que veio na URL; mês inválido cai na competência em trabalho", async () => {
    api.mockResolvedValue(VAZIO);
    abrir("/resumo-medicoes?mes=2026-09");
    await screen.findByRole("heading", { name: "Setembro de 2026" });
    expect(api).toHaveBeenCalledWith("/api/resumo-medicoes?mes=2026-09");
    cleanup(); api.mockClear(); api.mockResolvedValue(RESUMO);
    abrir("/resumo-medicoes?mes=2026-13");
    await screen.findByRole("heading", { name: "Outubro de 2026" });
    expect(api).toHaveBeenCalledWith("/api/resumo-medicoes");
  });

  it("erro ao carregar vira aviso com o que fazer", async () => {
    api.mockRejectedValue(new Error("sem resposta do servidor"));
    abrir();
    await waitFor(() => expect(screen.getByRole("alert").textContent).toMatch(/Não foi possível carregar o resumo das medições/));
  });
});
