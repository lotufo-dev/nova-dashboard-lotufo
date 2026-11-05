import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Reajuste from "./Reajuste";
import { brl } from "./formato";

const { api, apiForm } = vi.hoisted(() => ({ api: vi.fn(), apiForm: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api, apiForm }));

describe("Reajuste", () => {
  afterEach(() => { cleanup(); api.mockReset(); });

  it("mostra o pleito não enviado e abre o fluxo com a data-base", async () => {
    api.mockImplementation(async (caminho: string) => caminho.endsWith("/reajuste")
      ? { ciclos: [{ data_base_mes: "2024-06", indice: "INCC-DI", ciclo: 2026, aniversario: "2026-06-01",
                     situacao: "pleito_pendente", dias: -14, pleito: null, apostilamento: null }], pleitos: [] }
      : { instrumentos: [] });
    render(<Reajuste contratoId={7} podeEditar />);
    expect(await screen.findByText("pleito não enviado")).toBeTruthy();
    // um cartao por data-base (com ancora), e a linha do ciclo so' com o ano e o aniversario
    expect(screen.getByRole("region", { name: /^Data-base 06\/2024 · INCC-DI/ }).closest("[id]")?.id).toBe("db-2024-06");
    expect(screen.getByText("Ciclo de 2026 · aniversário em 01/06/2026")).toBeTruthy();
    // texto na tela (26/10/2026): sem a regra do aniversario
    expect(screen.queryByText(/vale a partir do mês do aniversário/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Enviar pleito" }));
    expect(screen.getByRole("form", { name: "Novo ofício" }).textContent).toContain("06/2024");
    expect(screen.getByLabelText("Nº do ofício (CT)")).toBeTruthy();
  });

  it("mostra a previsão gravada do ciclo, competência × valor com a origem (issue #272)", async () => {
    const prev = (competencia: string, valor: number, origem: string, ciclo = 2026) => ({ data_base_mes: "2024-06",
      ciclo, competencia, valor_previsto_centavos: valor, origem, pleito_id: 3 });
    api.mockImplementation(async (caminho: string) => caminho.endsWith("/reajuste")
      ? { ciclos: [{ data_base_mes: "2024-06", indice: "INCC-DI", ciclo: 2026, aniversario: "2026-06-01",
                     situacao: "pleito_pendente", dias: -14, pleito: null, apostilamento: null }], pleitos: [],
          previsoes: [prev("2026-07", 123456, "pleito"), prev("2026-08", 700, "manual"), prev("2025-07", 1, "pleito", 2025)] }
      : { instrumentos: [] });
    render(<Reajuste contratoId={7} podeEditar />);
    const tabela = await screen.findByRole("table", { name: "Previsão de reajuste do ciclo de 2026" });
    const linhas = within(tabela).getAllByRole("row");
    expect(linhas).toHaveLength(1 + 2 + 1);                   // so' o ciclo corrente; cabeca e total
    expect(linhas[1].textContent).toContain("07/2026");
    expect(linhas[1].textContent).toContain("R$ 1.234,56");
    expect(linhas[1].textContent).toContain("planilha do pleito");
    expect(linhas[2].textContent).toContain("digitada");
    expect(linhas[3].textContent).toContain("R$ 1.241,56");
  });

  it("competência apostilada aparece só na tabela do apostilamento, não de novo na previsão (#271 com #272)", async () => {
    const prev = (competencia: string, valor: number, origem: string) => ({ data_base_mes: "2024-06", ciclo: 2026,
      competencia, valor_previsto_centavos: valor, origem, pleito_id: origem === "apostilamento" ? null : 3 });
    const apostilada = (competencia: string, valor: number) => ({ data_base_mes: "2024-06", ciclo: 2026, competencia,
      valor_centavos: valor, medicao: null, instrumento_chave: "ap-12", instrumento_numero: "019/2024/02/12",
      instrumento_data: "2026-10-01" });
    api.mockImplementation(async (caminho: string) => caminho.endsWith("/reajuste")
      ? { ciclos: [{ data_base_mes: "2024-06", indice: "INCC-DI", ciclo: 2026, aniversario: "2026-06-01",
                     situacao: "apostilado", dias: null, pleito: null, apostilamento: null }], pleitos: [],
          // a de 11/2026 e' de apostilamento mas nao esta' na tabela do apostilamento: continua na previsao
          previsoes: [prev("2026-07", 130003, "apostilamento"), prev("2026-08", 20005, "apostilamento"),
                      prev("2026-09", 700, "pleito"), prev("2026-10", 301, "manual"),
                      prev("2026-11", 2, "apostilamento")],
          competencias: [apostilada("2026-07", 130003), apostilada("2026-08", 20005)] }
      : { instrumentos: [] });
    render(<Reajuste contratoId={7} podeEditar={false} />);
    const apostiladas = await screen.findByRole("table", { name: "Competências apostiladas da data-base 06/2024" });
    const previsao = screen.getByRole("table", { name: "Previsão de reajuste do ciclo de 2026" });
    const competencias = (t: HTMLElement) => [...t.querySelectorAll("tbody tr")].map(tr => tr.firstElementChild?.textContent);
    expect(competencias(apostiladas)).toEqual(["07/2026", "08/2026"]);
    expect(competencias(previsao)).toEqual(["09/2026", "10/2026", "11/2026"]);   // uma linha por competência
    // o rodape diz o que soma: so' as linhas da previsao, nao o reajuste do ciclo inteiro
    expect(previsao.querySelector("tfoot")?.textContent).toBe(`Total previsto${brl(1003)}`);
  });

  it("mostra a parte do contrato de cada data-base ao lado do mês (issue #257)", async () => {
    const ciclo = { ciclo: 2026, situacao: "pleito_pendente", dias: 10, pleito: null, apostilamento: null };
    api.mockImplementation(async (caminho: string) => caminho.endsWith("/reajuste")
      ? { ciclos: [{ ...ciclo, data_base_mes: "2024-06", indice: "INCC-DI", aplica_a: "itens SINAPI", aniversario: "2026-06-01" },
                   { ...ciclo, data_base_mes: "2024-09", indice: "FGV/DNIT", aplica_a: "", aniversario: "2026-09-01" }],
          pleitos: [] }
      : { instrumentos: [] });
    render(<Reajuste contratoId={7} podeEditar={false} />);
    expect(await screen.findByRole("region", { name: "Data-base 06/2024 (itens SINAPI) · INCC-DI" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "Data-base 09/2024 · FGV/DNIT" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "06/2024 (itens SINAPI) · INCC-DI" })).toBeTruthy();
  });

  it("mostra as competências apostiladas e o pleito atendido pelo termo (issue #271)", async () => {
    const termo = { id: 5, chave: "ap-12", tipo: "apostilamento_reajuste", numero: "019/2024/02/12", data: "2026-10-01",
      dados: { data_base: "2024-06", ciclo: 2026 } };
    const pleito = { id: 3, tipo: "reajuste", rotulo: "Pleito de reajuste", origem: "cadastro", numero_oficio: "CT-122-LT-2026",
      data_base_mes: "2024-06", ciclo: 2026, dias: null, justificativa: null, situacao: "enviado", corpo_carta: null,
      montado_paginas: null, assinado_arquivo: null, nome_documento: null, conferencia: null, pendencias: [],
      enviado_em: "2026-04-23", envio_justificativa: null, anexos: [], exigidos: [], instrumento_chave: "ap-12" };
    api.mockImplementation(async (caminho: string) => caminho.endsWith("/reajuste")
      ? { ciclos: [{ data_base_mes: "2024-06", indice: "INCC-DI", ciclo: 2026, aniversario: "2026-06-01",
                     situacao: "apostilado", dias: null, pleito, apostilamento: termo }],
          pleitos: [pleito],
          competencias: [
            { data_base_mes: "2024-06", ciclo: 2026, competencia: "2026-07", valor_centavos: 130003, medicao: 30,
              instrumento_chave: "ap-12", instrumento_numero: "019/2024/02/12", instrumento_data: "2026-10-01" },
            { data_base_mes: "2024-06", ciclo: 2026, competencia: "2026-08", valor_centavos: -1001, medicao: null,
              instrumento_chave: "ap-11", instrumento_numero: "019/2024/02/11", instrumento_data: "2026-09-15" }] }
      : { instrumentos: [termo] });
    render(<Reajuste contratoId={7} podeEditar={false} />);
    const tabela = await screen.findByRole("table", { name: "Competências apostiladas da data-base 06/2024" });
    const linhas = [...tabela.querySelectorAll("tbody tr")].map(tr => [...tr.querySelectorAll("td,th")].map(c => c.textContent));
    expect(linhas).toEqual([
      ["07/2026", "2026", "30ª", brl(130003), "019/2024/02/12"],
      ["08/2026", "2026", "—", brl(-1001), "019/2024/02/11"]]);
    expect(brl(-1001).startsWith("−")).toBe(true);           // o reajuste negativo leva o sinal
    expect(screen.getByText("atendido pelo apostilamento 019/2024/02/12")).toBeTruthy();
  });

  it("pleito vigente sem termo ligado não aparece como atendido, mesmo com o ciclo apostilado (gate Sol, PR #317)", async () => {
    const termo = { id: 5, chave: "ap-12", tipo: "apostilamento_reajuste", numero: "019/2024/02/12", data: "2026-10-01",
      dados: { data_base: "2024-06", ciclo: 2026 } };
    const pleito = { id: 3, tipo: "reajuste", rotulo: "Pleito de reajuste", origem: "cadastro", numero_oficio: "CT-122-LT-2026",
      data_base_mes: "2024-06", ciclo: 2026, dias: null, justificativa: null, situacao: "enviado", corpo_carta: null,
      montado_paginas: null, assinado_arquivo: null, nome_documento: null, conferencia: null, pendencias: [],
      enviado_em: "2026-04-23", envio_justificativa: null, anexos: [], exigidos: [], instrumento_chave: null };
    api.mockImplementation(async (caminho: string) => caminho.endsWith("/reajuste")
      ? { ciclos: [{ data_base_mes: "2024-06", indice: "INCC-DI", ciclo: 2026, aniversario: "2026-06-01",
                     situacao: "apostilado", dias: null, pleito: { id: 3 }, apostilamento: termo }],
          pleitos: [pleito], competencias: [] }
      : { instrumentos: [termo] });
    render(<Reajuste contratoId={7} podeEditar={false} />);
    await screen.findByText(/CT-122-LT-2026/);
    expect(screen.queryByText(/atendido pelo apostilamento/)).toBeNull();
  });

  it.each([2025, 2024])("aditivo de valor de reajuste fecha o ciclo e atende o pleito; o apostilamento de mesmo id e ciclo %i continua (issue #390)", async (cicloOutro) => {
    const aditivo = { id: 5, chave: "ta-03", tipo: "aditivo_valor", numero: "3º TA", data: "2025-11-20", dados: {},
      origem: "aditivo" };
    // instrumento de outra tabela com o mesmo id do aditivo: segue na aba, no ciclo corrente ou nos anteriores
    const outro = { id: 5, chave: "ap-01", tipo: "apostilamento_reajuste", numero: "AP-1", data: `${cicloOutro}-12-01`,
      dados: { data_base: "2021-10", ciclo: cicloOutro } };
    const pleito = (id: number, ciclo: number, chave: string) => ({ id, tipo: "reajuste", rotulo: "Pleito de reajuste",
      origem: "cadastro", numero_oficio: `CT-${id}-LT-${ciclo}`, data_base_mes: "2021-10", ciclo, dias: null,
      justificativa: null, situacao: "enviado", corpo_carta: null, montado_paginas: null, assinado_arquivo: null,
      nome_documento: null, conferencia: null, pendencias: [], enviado_em: `${ciclo}-10-05`, envio_justificativa: null,
      anexos: [], exigidos: [], instrumento_chave: chave });
    api.mockImplementation(async (caminho: string) => caminho.endsWith("/reajuste")
      ? { ciclos: [{ data_base_mes: "2021-10", indice: "INCC-DI", ciclo: 2025, aniversario: "2025-10-01",
                     situacao: "apostilado", dias: null, pleito: { id: 3 }, apostilamento: aditivo }],
          pleitos: [pleito(3, 2025, "ta-03"), pleito(2, 2023, "ta-02")], competencias: [] }
      : { instrumentos: [outro], aditivos: [
          { id: 4, chave_cadastro: "ta-02", tipo: "valor", numero: "2º TA", data_assinatura: "2023-11-10" },
          { id: 5, chave_cadastro: "ta-03", tipo: "valor", numero: "3º TA", data_assinatura: "2025-11-20" }] });
    render(<Reajuste contratoId={7} podeEditar={false} />);
    expect(await screen.findByText("apostilado")).toBeTruthy();
    const corpo = screen.getByRole("region", { name: /^Data-base 10\/2021/ });
    expect(corpo.textContent).toContain("Termo aditivo 3º TA, de 20/11/2025");
    expect(corpo.textContent).toContain(`AP-1, de 01/12/${cicloOutro}`);
    expect(screen.getByText("atendido pelo termo aditivo 3º TA")).toBeTruthy();
    // pleito de ciclo anterior ligado ao aditivo dele tambem diz o termo
    expect(screen.getByText("atendido pelo termo aditivo 2º TA")).toBeTruthy();
  });

  it("termo do ciclo corrente sem ligação fica no cartão do ciclo; o corrigido não vira ciclo anterior (PR #317)", async () => {
    const termo = (id: number, chave: string, numero: string, ciclo: number, corrige?: string) => ({ id, chave,
      tipo: "apostilamento_reajuste", numero, data: `${ciclo}-09-01`, dados: { data_base: "2024-06", ciclo, ...(corrige ? { corrige } : {}) } });
    const instrumentos = [termo(1, "ap-26a", "AP-26A", 2026), termo(2, "ap-26b", "AP-26B", 2026, "ap-26a"),
                          termo(3, "ap-25", "AP-25", 2025)];
    api.mockImplementation(async (caminho: string) => caminho.endsWith("/reajuste")
      ? { ciclos: [{ data_base_mes: "2024-06", indice: "INCC-DI", ciclo: 2026, aniversario: "2026-06-01",
                     situacao: "apostilamento_pendente", dias: 40, pleito: null, apostilamento: null }],
          pleitos: [], competencias: [] }
      : { instrumentos });
    const { container } = render(<Reajuste contratoId={7} podeEditar={false} />);
    await screen.findByText("apostilamento pendente");
    const corpo = screen.getByText("Ciclo de 2026 · aniversário em 01/06/2026").parentElement!;
    expect(corpo.textContent).toContain("AP-26B, de 01/09/2026");
    expect(corpo.textContent).not.toContain("AP-26A");
    const anteriores = container.querySelector('[aria-label="Apostilamentos anteriores da data-base 06/2024"]');
    expect([...anteriores!.querySelectorAll("li")].map(li => li.textContent)).toEqual(["AP-25, de 01/09/2025"]);
    expect(container.textContent).not.toContain("AP-26A");
  });

  it("termo sem data-base vai para a base que a API resolveu, uma vez só, mesmo com duas bases (rodada 3, PR #317)", async () => {
    const termo = { id: 11, chave: "ap-11", tipo: "apostilamento_reajuste", numero: "AP-11", data: "2026-09-15",
      dados: { ciclo: 2026 } };
    const ciclo = { ciclo: 2026, dias: null, pleito: null };
    api.mockImplementation(async (caminho: string) => caminho.endsWith("/reajuste")
      ? { ciclos: [{ ...ciclo, data_base_mes: "2024-04", indice: "SICRO", aniversario: "2026-04-01",
                     situacao: "pleito_pendente", dias: -10, apostilamento: null },
                   { ...ciclo, data_base_mes: "2024-06", indice: "INCC-DI", aniversario: "2026-06-01",
                     situacao: "apostilado", apostilamento: termo }],
          pleitos: [], competencias: [], bases_dos_termos: [{ instrumento_id: 11, data_base_mes: "2024-06" }] }
      : { instrumentos: [termo] });
    const { container } = render(<Reajuste contratoId={7} podeEditar={false} />);
    const cartao = await screen.findByRole("region", { name: /^Data-base 06\/2024 · INCC-DI/ });
    expect(cartao.textContent).toContain("AP-11, de 15/09/2026");
    expect(screen.queryByRole("region", { name: "Apostilamentos sem data-base no cadastro" })).toBeNull();
    expect(container.textContent!.split("AP-11, de 15/09/2026").length - 1).toBe(1);
  });

  it("termo corrigido por outro de outra data-base sai da aba inteira (rodada 3, PR #317)", async () => {
    // T2 (base 2024-04) corrige T1 (base 2024-06); T0 nao tem base que se saiba e e' corrigido por T3
    const termo = (id: number, chave: string, numero: string, dados: Record<string, unknown>) => ({ id, chave,
      tipo: "apostilamento_reajuste", numero, data: "2026-09-01", dados: { ciclo: 2026, ...dados } });
    const instrumentos = [termo(1, "t1", "T-1", { data_base: "2024-06" }), termo(2, "t2", "T-2", { data_base: "2024-04", corrige: "t1" }),
                          termo(3, "t0", "T-0", {}), termo(4, "t3", "T-3", { data_base: "2024-04", corrige: "t0" })];
    const ciclo = { ciclo: 2026, situacao: "apostilamento_pendente", dias: 40, pleito: null, apostilamento: null };
    api.mockImplementation(async (caminho: string) => caminho.endsWith("/reajuste")
      ? { ciclos: [{ ...ciclo, data_base_mes: "2024-04", indice: "SICRO", aniversario: "2026-04-01" },
                   { ...ciclo, data_base_mes: "2024-06", indice: "INCC-DI", aniversario: "2026-06-01" }],
          pleitos: [], competencias: [] }
      : { instrumentos });
    const { container } = render(<Reajuste contratoId={7} podeEditar={false} />);
    await screen.findByRole("region", { name: /^Data-base 06\/2024 · INCC-DI/ });
    expect(container.textContent).toContain("T-2, de 01/09/2026");
    expect(container.textContent).not.toContain("T-1,");
    expect(container.textContent).not.toContain("T-0,");
    expect(screen.queryByRole("region", { name: "Apostilamentos sem data-base no cadastro" })).toBeNull();
  });

  it("pleito de ciclo anterior ligado a um termo também diz que foi atendido (issue #271)", async () => {
    const termo = { id: 4, chave: "ap-09", tipo: "apostilamento_reajuste", numero: "019/2024/02/09", data: "2025-08-01",
      dados: { data_base: "2024-06", ciclo: 2025 } };
    const pleito = { id: 2, tipo: "reajuste", rotulo: "Pleito de reajuste", origem: "cadastro", numero_oficio: "CT-90-LT-2025",
      data_base_mes: "2024-06", ciclo: 2025, dias: null, justificativa: null, situacao: "enviado", corpo_carta: null,
      montado_paginas: null, assinado_arquivo: null, nome_documento: null, conferencia: null, pendencias: [],
      enviado_em: "2025-06-10", envio_justificativa: null, anexos: [], exigidos: [], instrumento_chave: "ap-09" };
    api.mockImplementation(async (caminho: string) => caminho.endsWith("/reajuste")
      ? { ciclos: [{ data_base_mes: "2024-06", indice: "INCC-DI", ciclo: 2026, aniversario: "2026-06-01",
                     situacao: "pleito_pendente", dias: 10, pleito: null, apostilamento: null }],
          pleitos: [pleito], competencias: [] }
      : { instrumentos: [termo] });
    render(<Reajuste contratoId={7} podeEditar={false} />);
    await screen.findByText("pleito não enviado");
    expect(screen.getByText("atendido pelo apostilamento 019/2024/02/09")).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });

  // issue #277: reiteracao (familia B) e reemissao do cronograma ligadas ao pleito anterior
  const enviado = (extra: Record<string, unknown>) => ({
    tipo: "reajuste", rotulo: "Pleito de reajuste", origem: "sistema", data_base_mes: "2024-06", ciclo: 2026,
    dias: null, justificativa: null, situacao: "enviado", corpo_carta: "Texto", montado_paginas: 1,
    assinado_arquivo: "x.pdf", nome_documento: "x.pdf", conferencia: null, pendencias: [], envio_justificativa: null,
    anexos: [], exigidos: [], reemite_pleito_id: null, reemissao: null, anterior: null, reemissoes: [],
    reemissoes_possiveis: [], ...extra });
  const cicloPendente = (pleitoId: number) => ({ data_base_mes: "2024-06", indice: "INCC-DI", ciclo: 2026,
    aniversario: "2026-06-01", situacao: "apostilamento_pendente", dias: 137, pleito: { id: pleitoId }, apostilamento: null });

  it("aditivo depois do pleito mostra o ciclo com o cronograma de reajuste a reemitir (issue #273)", async () => {
    api.mockImplementation(async (caminho: string) => caminho.endsWith("/reajuste")
      ? { ciclos: [{ ...cicloPendente(10), situacao: "reemitir", dias: 92 }],
          pleitos: [enviado({ id: 10, numero_oficio: "CT-122-LT-2026", enviado_em: "2026-06-10",
            reemissoes_possiveis: ["cronograma"] })] }
      : { instrumentos: [] });
    render(<Reajuste contratoId={7} podeEditar />);
    expect((await screen.findAllByText("cronograma de reajuste a reemitir")).length).toBeGreaterThan(0);
    // continua sem apostilamento: o pleito vigente diz desde quando espera
    expect(screen.getByText(/^sem apostilamento há 92\sdias$/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Reemitir cronograma" })).toBeTruthy();
  });

  it("no pleito enviado, Reiterar abre o ofício ligado ao anterior", async () => {
    api.mockImplementation(async (caminho: string) => caminho.endsWith("/reajuste")
      ? { ciclos: [cicloPendente(10)], pleitos: [enviado({ id: 10, numero_oficio: "CT-122-LT-2026", enviado_em: "2026-06-15",
          reemissoes_possiveis: ["reiteracao", "cronograma"] })] }
      : caminho.endsWith("/reemitir") ? { id: 11 } : { instrumentos: [] });
    render(<Reajuste contratoId={7} podeEditar />);
    const reiterar = await screen.findByRole("button", { name: "Reiterar" });
    expect(screen.getByRole("button", { name: "Reemitir cronograma" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Reenviar pleito" })).toBeNull();
    fireEvent.click(reiterar);
    expect(screen.getByRole("heading", { name: "Reiteração do pleito CT-122-LT-2026" })).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Nº do ofício (CT)"), { target: { value: "245" } });
    fireEvent.click(screen.getByRole("button", { name: "Criar ofício" }));
    await waitFor(() => expect(api.mock.calls.some(c => c[0] === "/api/pleitos/10/reemitir")).toBe(true));
    const [, opcoes] = api.mock.calls.find(c => c[0] === "/api/pleitos/10/reemitir")!;
    expect(JSON.parse(opcoes.body)).toEqual({ reemissao: "reiteracao", numero_oficio: "245" });
  });

  it("mostra a cadeia: o original diz quem o reiterou e a reiteração diz o que reitera", async () => {
    const reit = { id: 11, numero_oficio: "CT-245-LT-2026", situacao: "enviado", enviado_em: "2026-10-30", reemissao: "reiteracao" };
    api.mockImplementation(async (caminho: string) => caminho.endsWith("/reajuste")
      ? { ciclos: [cicloPendente(11)], pleitos: [
          enviado({ ...reit, rotulo: "Reiteração do pleito de reajuste", reemite_pleito_id: 10,
            anterior: { id: 10, numero_oficio: "CT-122-LT-2026", situacao: "enviado", enviado_em: "2026-06-15", reemissao: null } }),
          enviado({ id: 10, numero_oficio: "CT-122-LT-2026", enviado_em: "2026-06-15", reemissoes: [reit] })] }
      : { instrumentos: [] });
    render(<Reajuste contratoId={7} podeEditar />);
    expect(await screen.findByText("Reitera o CT-122-LT-2026, enviado em 15/06/2026")).toBeTruthy();
    expect(screen.getByText("Reiterado pelo CT-245-LT-2026, enviado em 30/10/2026")).toBeTruthy();
    // a espera do ciclo aparece so' no pleito vigente (a reiteracao); o original fica com o selo neutro
    expect(screen.getAllByText(/^sem apostilamento há 137/)).toHaveLength(1);
    const original = document.getElementById("oficio-10")!;
    expect(original.textContent).not.toContain("sem apostilamento");
    // sem reemissao possivel no pleito vigente (servidor), nenhum botao de reiterar
    expect(screen.queryByRole("button", { name: "Reiterar" })).toBeNull();
  });
});
