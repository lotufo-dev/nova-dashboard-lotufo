import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import AReceber, { type ContratanteAReceber, type LinhaAReceber, type RespostaAReceber } from "./AReceber";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

// Dados ficticios, valores inventados. Os numeros vem prontos do servidor (subtotal, total, o de cada ano, o tempo
// parado e a data prevista); a tela so' mostra.
const parada = (desde: string, dias: number, situacao: "andamento" | "critico", esperada: string | null, prazo: number | null) => ({
  desde, dias_uteis: dias, hoje: false, situacao, prazo_orgao_dias: prazo, esperada, alem_do_prazo: situacao === "critico",
});
const linha = (x: Partial<LinhaAReceber> & Pick<LinhaAReceber, "medicao_id" | "obra" | "valor_centavos">): LinhaAReceber => ({
  tipo_aberto: "nota", nota_id: x.medicao_id + 1000, numero: String(x.medicao_id + 1000), paga_em_parte: false, contrato_id: 7,
  medicao_numero: 3, tipo: "execucao", competencia: "2026-08", protocolo_em: "2026-09-01", emitida_em: null, parada: null,
  orgao_pagou_em: null, ...x,
});
const grupo = (x: Partial<ContratanteAReceber> & Pick<ContratanteAReceber, "contratante" | "chave">): ContratanteAReceber => ({
  prazo_orgao_dias: null, quantidade: 0, em_aberto_centavos: 0, por_ano: { 2025: 0, 2026: 0 }, alem_do_prazo: 0, linhas: [],
  notas_sem_medicao: [], notas_sem_medicao_centavos: 0, anteriores: { quantidade: 0, valor_centavos: 0 }, ...x,
});

const SINFRA = grupo({
  contratante: "SINFRA", chave: "sinfra", prazo_orgao_dias: 45, quantidade: 3, em_aberto_centavos: 125_033_333,
  por_ano: { 2025: 0, 2026: 125_033_333 }, alem_do_prazo: 1,
  linhas: [
    linha({ medicao_id: 71, obra: "Obra Alfa", valor_centavos: 100_000_000, parada: parada("2026-09-01", 55, "critico", "2026-10-16", 45) }),
    linha({ medicao_id: 72, contrato_id: 8, obra: "Obra Beta", medicao_numero: 5, competencia: "2026-09", protocolo_em: "2026-10-05",
      tipo_aberto: "repasse", valor_centavos: 25_000_000, orgao_pagou_em: "2026-11-04" }),
    linha({ medicao_id: 73, obra: "Obra Alfa", medicao_numero: 4, tipo: "reajuste", competencia: "2026-09", protocolo_em: "2026-11-10",
      tipo_aberto: "sem_nota", nota_id: null, numero: null, valor_centavos: 33_333, parada: parada("2026-11-10", 6, "andamento", "2026-12-25", 45) }),
  ],
});
const PREFEITURA = grupo({
  contratante: "Pref. Exemplo", chave: "pref-exemplo", quantidade: 2, em_aberto_centavos: 6_000_000,
  por_ano: { 2025: 5_000_000, 2026: 1_000_000 },
  linhas: [
    linha({ medicao_id: 81, contrato_id: 9, obra: "Escola Gama", medicao_numero: 2, competencia: "2025-11", protocolo_em: "2025-12-01",
      paga_em_parte: true, valor_centavos: 5_000_000, parada: parada("2025-12-01", 230, "andamento", null, null) }),
    linha({ medicao_id: 82, contrato_id: 9, obra: "Escola Gama", competencia: "2026-09", protocolo_em: null, emitida_em: "2026-10-20",
      valor_centavos: 1_000_000, parada: parada("2026-10-20", 20, "andamento", null, null) }),
  ],
  notas_sem_medicao: [{ nota_id: 3003, numero: "3003", contrato_id: 9, obra: "Escola Gama", emissao: "2026-07-01", valor_centavos: 777_777,
    paga_em_parte: false }],
  notas_sem_medicao_centavos: 777_777, anteriores: { quantidade: 1, valor_centavos: 400_000 },
});
const SES = grupo({ contratante: "SES-MT", chave: "ses-mt" });
const RESPOSTA: RespostaAReceber = {
  anos: ["2025", "2026"], total_a_receber_liberado: true, em_aberto_centavos: 131_033_333,
  por_ano: { 2025: 5_000_000, 2026: 126_033_333 }, quantidade: 5, alem_do_prazo: 1,
  notas_sem_medicao: PREFEITURA.notas_sem_medicao, notas_sem_medicao_centavos: 777_777,
  anteriores: { quantidade: 1, valor_centavos: 400_000 }, contratantes: [SINFRA, PREFEITURA, SES],
};

// o texto de cada pedaco separado por espaco (o selo e a data prevista ficam em elementos vizinhos, sem espaco entre eles)
function texto(el: Element | null): string {
  if (!el) return "";
  const partes: string[] = [];
  const andar = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  while (andar.nextNode()) partes.push(andar.currentNode.textContent ?? "");
  return partes.join(" ").replace(/\s+/g, " ").replace(/ ([.,:])/g, "$1").trim();
}
const linhas = () => [...document.querySelectorAll(".arc-tabela:not(.arc-tabela--soltas) tbody tr:not(.arc-grupo)")];

async function abrir(resposta: RespostaAReceber | Error, busca: Record<string, string> = {}) {
  api.mockImplementation(async (caminho: string) => {
    if (caminho !== "/api/a-receber") throw new Error(`caminho inesperado: ${caminho}`);
    if (resposta instanceof Error) throw resposta;
    return resposta;
  });
  render(<AReceber busca={busca} ir={vi.fn()} />);
  await act(async () => {});
}

describe("A receber: o em aberto nota a nota (#816)", () => {
  afterEach(() => { cleanup(); api.mockReset(); });

  it("no alto, o total em aberto com o de cada ano, as linhas além do prazo e o que ele soma", async () => {
    await abrir(RESPOSTA);
    const numeros = document.querySelector(".arc-numeros")!;
    expect(texto(numeros.querySelector(".arc-numero__valor"))).toBe("R$ 1.310.333,33");
    expect(texto(numeros.querySelector(".arc-numero__rotulo"))).toBe("Em aberto");
    expect(numeros.querySelector(".marca-etapa__cor--em_aberto")).toBeTruthy();
    expect(texto(numeros.querySelector(".arc-numero__apoio"))).toBe("2026: R$ 1.260.333,33 · 2025: R$ 50.000,00");
    expect(texto(within(numeros as HTMLElement).getByText(/além do prazo do órgão/))).toBe("1 além do prazo do órgão");
    expect(texto(document.querySelector(".arc-base"))).toMatch(/^O em aberto do Fechamento, na cota da Lotufo e pelo valor bruto da nota; o a receber da Início e de Obras também soma/);
  });

  it("a fileira de contratantes: Todos e cada um com a quantidade, o sem nada em aberto com zero; o endereço leva a chave", async () => {
    await abrir(RESPOSTA);
    const fileira = screen.getByRole("navigation", { name: "Contratante" });
    const opcoes = within(fileira).getAllByRole("link");
    expect(opcoes.map(texto)).toEqual(["Todos 5", "SINFRA 3", "Pref. Exemplo 2", "SES-MT 0"]);
    expect(opcoes.map(o => o.getAttribute("href"))).toEqual(["/a-receber", "/a-receber?contratante=sinfra",
      "/a-receber?contratante=pref-exemplo", "/a-receber?contratante=ses-mt"]);
    expect(opcoes.map(o => o.getAttribute("aria-current"))).toEqual(["true", null, null, null]);
  });

  it("sem filtro, cada contratante é um cabeçalho de grupo forte recolhido, com o subtotal e o prazo do órgão; o nome abre o grupo", async () => {
    await abrir(RESPOSTA);
    const grupos = [...document.querySelectorAll("tr.arc-grupo")];
    expect(grupos.map(texto)).toEqual([
      "▸ SINFRA 3 em aberto · prazo do órgão: 45 dias 1 além do prazo do órgão R$ 1.250.333,33",
      "▸ Pref. Exemplo 2 em aberto · sem previsão de pagamento R$ 60.000,00"]);
    expect(linhas()).toHaveLength(0);                                    // recolhidos: só o cabeçalho
    const sinfra = screen.getByRole("button", { name: /SINFRA/ });
    expect(sinfra.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(sinfra);
    expect(sinfra.getAttribute("aria-expanded")).toBe("true");
    expect(linhas().map(l => texto(l.querySelector("th")))).toEqual([
      "Obra Alfa 3ª Medição · 08/2026", "Obra Beta 5ª Medição · 09/2026", "Obra Alfa Reajuste da 4ª Medição · 09/2026"]);
    fireEvent.click(sinfra);
    expect(linhas()).toHaveLength(0);
  });

  it("?contratante= mostra só o contratante, aberto, com cada linha: medição, nota, protocolo, tempo parado, data prevista e valor", async () => {
    await abrir(RESPOSTA, { contratante: "sinfra" });
    expect(within(screen.getByRole("navigation", { name: "Contratante" })).getAllByRole("link").map(o => o.getAttribute("aria-current")))
      .toEqual([null, "true", null, null]);
    expect(texto(document.querySelector(".arc-numero__valor"))).toBe("R$ 1.250.333,33");
    expect(document.querySelector(".arc-numero__apoio")).toBeNull();     // um ano só: o de cada ano repetiria o total
    expect(screen.queryByRole("button")).toBeNull();                       // um grupo só, aberto
    const [alfa, beta, reajuste] = linhas();
    expect(within(alfa as HTMLElement).getByRole("link", { name: "Obra Alfa" }).getAttribute("href")).toBe("/obras/7/medicoes");
    expect(within(alfa as HTMLElement).getByRole("link", { name: "3ª Medição" }).getAttribute("href")).toBe("/obras/7/medicoes/71");
    expect(texto(alfa.querySelector(".arc-a-nota"))).toBe("1071");
    expect(texto(alfa.querySelector(".arc-a-data"))).toBe("01/09/2026");
    expect(texto(alfa.querySelector(".arc-a-parada"))).toBe("55 dias úteis prazo do órgão venceu em 16/10");
    expect(alfa.querySelector(".arc-a-parada .selo--critico")).toBeTruthy();
    expect(texto(alfa.querySelector(".arc-a-valor"))).toBe("R$ 1.000.000,00");
    // o repasse sem baixa: o órgão já pagou o consórcio, sem tempo parado com o órgão
    expect(texto(beta.querySelector(".arc-a-nota"))).toBe("1072 repasse sem baixa");
    expect(texto(beta.querySelector(".arc-a-parada"))).toBe("órgão pagou em 04/11");
    expect(beta.querySelector(".arc-a-parada .selo--feito")).toBeTruthy();
    // a medição protocolada sem nota ligada, dentro do prazo do órgão: a data prevista embaixo
    expect(texto(reajuste.querySelector(".arc-a-nota"))).toBe("sem nota ligada");
    expect(texto(reajuste.querySelector(".arc-a-parada"))).toBe("6 dias úteis prazo do órgão: 25/12");
    expect(reajuste.querySelector(".arc-a-parada .selo--andamento")).toBeTruthy();
    expect(texto(reajuste.querySelector(".arc-a-valor"))).toBe("R$ 333,33");
    expect(screen.queryByRole("region", { name: /À parte/ })).toBeNull();     // a SINFRA não tem nada à parte
  });

  it("paga em parte, a nota sem protocolo conta da emissão e o órgão sem prazo não tem data prevista; à parte, a nota sem medição e o antigo", async () => {
    await abrir(RESPOSTA, { contratante: "pref-exemplo" });
    const [parte, semProtocolo] = linhas();
    expect(texto(parte.querySelector(".arc-a-nota"))).toBe("1081 paga em parte");
    expect(texto(parte.querySelector(".arc-a-parada"))).toBe("230 dias úteis");
    expect(texto(semProtocolo.querySelector(".arc-a-data"))).toBe("nota emitida em 20/10/2026");
    expect(texto(document.querySelector(".arc-numero__apoio"))).toBe("2026: R$ 10.000,00 · 2025: R$ 50.000,00");
    const aparte = screen.getByRole("region", { name: "À parte, fora do total" });
    expect(texto(within(aparte).getByRole("table").querySelector("tbody tr"))).toBe("Escola Gama 3003 01/07/2026 R$ 7.777,77");
    expect(texto(within(aparte).getByRole("table").querySelector("tfoot"))).toBe("Subtotal à parte R$ 7.777,77");
    expect(texto(aparte.querySelector(".arc-antigo"))).toBe("Em aberto de competências anteriores a 2025 R$ 4.000,00");
    // sem medição sem nota na vista, o aviso de que as duas podem ser a mesma cobrança não aparece
    expect(aparte.querySelector(".aviso")).toBeNull();
  });

  it("sem filtro, com medição sem nota e nota sem medição na página, o aviso de que podem ser a mesma cobrança", async () => {
    await abrir(RESPOSTA);
    const aparte = screen.getByRole("region", { name: "À parte, fora do total" });
    expect(texto(aparte.querySelector(".aviso"))).toBe("Atenção: Medição sem nota ligada e nota sem medição ligada podem ser a mesma cobrança enquanto o vínculo não for feito.");
    expect(texto(within(aparte).getByRole("table").querySelector("tfoot"))).toBe("Subtotal à parte R$ 7.777,77");
  });

  it("contratante sem nada em aberto: a opção fica na fileira com zero e a página diz o vazio em uma linha", async () => {
    await abrir(RESPOSTA, { contratante: "ses-mt" });
    expect(texto(screen.getByRole("link", { name: /SES-MT/ }))).toBe("SES-MT 0");
    expect(screen.getByRole("link", { name: /SES-MT/ }).getAttribute("aria-current")).toBe("true");
    expect(texto(document.querySelector(".vazio__titulo"))).toBe("Nenhuma nota em aberto de SES-MT.");
    expect(screen.getByRole("link", { name: "Ver todos os contratantes" }).getAttribute("href")).toBe("/a-receber");
    expect(screen.queryByRole("table")).toBeNull();
    expect(document.querySelector(".arc-numeros")).toBeNull();
  });

  it("a chave que nenhum contratante tem: nenhuma opção acesa, o vazio com a chave e o caminho de volta", async () => {
    await abrir(RESPOSTA, { contratante: "orgao-que-nao-existe" });
    expect(within(screen.getByRole("navigation", { name: "Contratante" })).getAllByRole("link").map(o => o.getAttribute("aria-current")))
      .toEqual([null, null, null, null]);
    expect(texto(document.querySelector(".vazio__titulo"))).toBe("Nenhuma nota em aberto de orgao-que-nao-existe.");
    expect(screen.queryByRole("region", { name: /À parte/ })).toBeNull();
  });

  it("um contratante só com linhas: o grupo nasce aberto, sem botão", async () => {
    await abrir({ ...RESPOSTA, em_aberto_centavos: 125_033_333, por_ano: { 2025: 0, 2026: 125_033_333 }, quantidade: 3,
      notas_sem_medicao: [], notas_sem_medicao_centavos: 0, anteriores: { quantidade: 0, valor_centavos: 0 }, contratantes: [SINFRA, SES] });
    expect(screen.queryByRole("button")).toBeNull();
    expect(linhas()).toHaveLength(3);
  });

  it("sem nota em aberto nenhuma, diz isso em uma linha", async () => {
    await abrir({ ...RESPOSTA, em_aberto_centavos: 0, por_ano: { 2025: 0, 2026: 0 }, quantidade: 0, alem_do_prazo: 0,
      notas_sem_medicao: [], notas_sem_medicao_centavos: 0, anteriores: { quantidade: 0, valor_centavos: 0 }, contratantes: [] });
    expect(texto(screen.getByRole("region", { name: "Em aberto" }))).toBe("Nenhuma nota em aberto.");
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByRole("navigation", { name: "Contratante" })).toBeNull();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("com o total a receber não liberado, nenhum valor: a frase da trava", async () => {
    await abrir({ anos: ["2025", "2026"], total_a_receber_liberado: false });
    expect(texto(document.querySelector(".aviso"))).toBe("Atenção: O total a receber ainda não está liberado: o em aberto fica sem valor.");
    expect(document.body.textContent).not.toMatch(/R\$/);
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByRole("navigation", { name: "Contratante" })).toBeNull();
  });

  it("a falha de leitura em palavras da pessoa", async () => {
    await abrir(new Error("o servidor não respondeu."));
    expect(screen.getByRole("alert").textContent).toMatch(/^Não foi possível carregar o a receber: .*Recarregue a página para tentar de novo\.$/);
  });
});
