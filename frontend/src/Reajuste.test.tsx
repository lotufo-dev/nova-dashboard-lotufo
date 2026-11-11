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

  // issue #275: uma linha de `competencias_por_ciclo` (reajuste.competencias_por_ciclo), so' prevista por padrao
  const comp = (competencia: string, extra: Record<string, unknown> = {}) => ({ competencia, estado: "prevista",
    previsto_centavos: null, previsto_origem: null, medicao_id: null, medicao_numero: null, medicao_estado: null,
    medicoes: [], medicoes_pedido: [], medicoes_aprovado: [], medicoes_nota: [], pedido_centavos: null,
    aprovado_centavos: null, apostilada: false, apostilado_centavos: null, apostilado_percentual: null,
    apostilamento_chave: null, medicao_orgao: null, faturado_centavos: null, recebida_em: null, recebidas: [],
    data_base_incerta: false, avisos: [], ...extra });
  const cicloAberto = { data_base_mes: "2024-06", indice: "INCC-DI", ciclo: 2026, aniversario: "2026-06-01",
    situacao: "apostilamento_pendente", dias: 40, pleito: null, apostilamento: null, aditivos: [] };
  const celulas = (tr: Element) => [...tr.querySelectorAll("td,th")];
  // o texto a' vista da celula, sem a origem que vai so' para o leitor de tela
  const visivel = (el: Element) => {
    const c = el.cloneNode(true) as Element;
    c.querySelectorAll(".sr-only").forEach(s => s.remove());
    return c.textContent;
  };

  it("mostra a tabela do ciclo, competência × previsto × pedido × aprovado × apostilado × nota × recebido, com a origem no título (issue #275)", async () => {
    const termo = { id: 5, chave: "ap-12", tipo: "apostilamento_reajuste", numero: "019/2024/02/12", data: "2026-10-01",
      dados: { data_base: "2024-06", ciclo: 2026 } };
    api.mockImplementation(async (caminho: string) => caminho.endsWith("/reajuste")
      ? { ciclos: [cicloAberto], pleitos: [],
          competencias_por_ciclo: [
            { data_base_mes: "2024-06", ciclo: 2025, competencias: [comp("2025-07", { previsto_centavos: 5, previsto_origem: "manual" })] },
            { data_base_mes: "2024-06", ciclo: 2026, competencias: [
              // a 3ª recebida e a 8ª (complemento) so' pedida: aprovado, nota e recebido sao so' da 3ª
              comp("2026-07", { estado: "recebida", previsto_centavos: 100_01, previsto_origem: "pleito", medicao_numero: 3,
                medicoes: [3, 8], medicoes_pedido: [3, 8], medicoes_aprovado: [3], medicoes_nota: [3],
                pedido_centavos: 100_01, aprovado_centavos: 99_99, apostilada: true,
                apostilado_centavos: 100_01, apostilamento_chave: "ap-12", medicao_orgao: 30, faturado_centavos: 99_99,
                recebida_em: "2026-10-15", recebidas: [{ numero: 3, recebida_em: "2026-10-15" }] }),
              comp("2026-08", { previsto_centavos: 200_03, previsto_origem: "manual" }),
              comp("2026-09", { estado: "pedida", medicao_numero: 7, medicoes: [4, 7], medicoes_pedido: [4, 7],
                pedido_centavos: 301_01 })] },
            { data_base_mes: "2024-06", ciclo: 2027, competencias: [comp("2027-06", { previsto_centavos: 9, previsto_origem: "manual" })] }] }
      : { instrumentos: [termo] });
    render(<Reajuste contratoId={7} podeEditar={false} />);
    const tabela = await screen.findByRole("table", { name: "Reajuste por competência da data-base 06/2024, ciclo de 2026" });
    expect(within(tabela).getAllByRole("columnheader").map(c => c.textContent)).toEqual(
      ["Competência", "Previsto", "Pedido", "Aprovado", "Previsto no apostilamento", "Nota", "Recebido", "Situação"]);
    const [jul, ago, set] = [...tabela.querySelectorAll("tbody tr")];
    // o nº da medicao que o termo cita fica a' vista ao lado do apostilado
    expect(celulas(jul).map(visivel)).toEqual(
      ["07/2026", brl(100_01), brl(100_01), brl(99_99), `${brl(100_01)} (30ª med.)`, brl(99_99), "15/10/2026", "recebida"]);
    // a origem de cada celula ao passar o mouse; cada soma cita so' as medicoes que entraram nela
    const origens = ["Origem: planilha do pleito", "Origem: 3ª e 8ª medições de reajuste",
      "Origem: boletim da 3ª medição de reajuste", "Origem: apostilamento 019/2024/02/12, de 01/10/2026 (30ª medição)",
      "Origem: notas fiscais da 3ª medição de reajuste", "Origem: baixa no RM da 3ª medição de reajuste"];
    expect(celulas(jul).slice(1, 7).map(c => c.getAttribute("title"))).toEqual(origens);
    // e para o leitor de tela, que nao abre o titulo
    expect(celulas(jul).slice(1, 7).map(c => c.querySelector(".sr-only")?.textContent)).toEqual(origens.map(o => `, ${o}`));
    // celula vazia: traco e sem titulo
    expect(celulas(ago).map(visivel)).toEqual(["08/2026", brl(200_03), "—", "—", "—", "—", "—", "prevista"]);
    expect(celulas(ago)[1].getAttribute("title")).toBe("Origem: digitada");
    expect(celulas(ago).slice(2, 7).every(c => !c.hasAttribute("title") && !c.querySelector(".sr-only"))).toBe(true);
    // complemento: o pedido soma as medicoes da competencia
    expect(celulas(set)[2].getAttribute("title")).toBe("Origem: 4ª e 7ª medições de reajuste");
    // o rodape soma cada coluna de dinheiro com o centavo impar
    expect(celulas(tabela.querySelector("tfoot tr")!).map(c => c.textContent)).toEqual(
      ["Total", brl(300_04), brl(401_02), brl(99_99), brl(100_01), brl(99_99), "", ""]);
    // as tabelas antigas (previsao e apostiladas) nao voltam: a da competencia traz as duas colunas
    expect(screen.queryByRole("table", { name: /^Previsão de reajuste/ })).toBeNull();
    expect(screen.queryByRole("table", { name: /^Competências apostiladas/ })).toBeNull();
    // o ciclo anterior fica recolhido em "Ciclos anteriores"
    const anterior = screen.getByRole("table", { name: "Reajuste por competência da data-base 06/2024, ciclo de 2025" });
    expect(anterior.closest("details")?.querySelector("summary")?.textContent).toBe("Ciclos anteriores");
    // previsao de ciclo seguinte (lancada antes da janela abrir) fica a' vista, no cartao da data-base
    const seguinte = screen.getByRole("table", { name: "Reajuste por competência da data-base 06/2024, ciclo de 2027" });
    expect(seguinte.closest("details")).toBeNull();
    expect(seguinte.closest("section")?.id).toBe("db-2024-06");
  });

  it("a tabela por competência não acusa diferença: sem os três selos e sem cor de alerta (issue #648)", async () => {
    api.mockImplementation(async (caminho: string) => caminho.endsWith("/reajuste")
      ? { ciclos: [cicloAberto], pleitos: [],
          // a marca de diferenca vinha do servidor em `avisos`: mesmo que venha, a aba nao a desenha
          competencias_por_ciclo: [{ data_base_mes: "2024-06", ciclo: 2026, competencias: [
            comp("2026-07", { estado: "pedida", previsto_centavos: 100_01, previsto_origem: "manual", medicoes: [1],
              pedido_centavos: 101_02, avisos: ["fora_da_previsao"] }),
            comp("2026-08", { estado: "aprovada", medicoes: [2], pedido_centavos: 200_03, aprovado_centavos: 200_03,
              avisos: ["sem_apostilamento"] }),
            comp("2026-09", { estado: "faturada", medicoes: [3], pedido_centavos: 300_05, aprovado_centavos: 300_05,
              faturado_centavos: 300_05, avisos: ["sem_apostilamento", "nota_antes_do_apostilamento"] }),
            comp("2026-10", { estado: "apostilada", apostilada: true, apostilado_percentual: "6,76",
              apostilamento_chave: "ap-mtpar" }),
            // o cadastro com o sinal e tres casas: a tela nao dobra o % nem arredonda o indice (/code-review)
            comp("2026-11", { estado: "apostilada", apostilada: true, apostilado_percentual: "4,125%",
              apostilamento_chave: "ap-mtpar" })] }] }
      : { instrumentos: [] });
    render(<Reajuste contratoId={7} podeEditar />);
    const tabela = await screen.findByRole("table", { name: "Reajuste por competência da data-base 06/2024, ciclo de 2026" });
    const linhas = [...tabela.querySelectorAll("tbody tr")];
    const selos = (tr: Element) => [...celulas(tr)[7].querySelectorAll(".selo")].map(s => [s.textContent, s.className]);
    expect(linhas.map(selos)).toEqual([[["pedida", "selo"]], [["aprovada", "selo"]], [["faturada", "selo"]],
      [["apostilada", "selo"]], [["apostilada", "selo"]]]);
    for (const texto of ["fora da previsão", "sem apostilamento", "nota antes do apostilamento"])
      expect(within(tabela).queryByText(texto)).toBeNull();
    expect(tabela.querySelector(".selo--atencao, .selo--acao")).toBeNull();
    // sem a marca, nada a justificar na linha
    expect(within(tabela).queryByRole("button", { name: /^Justificar/ })).toBeNull();
    // nenhum valor some: previsto, pedido, aprovado e nota continuam na linha
    expect(celulas(linhas[0]).slice(0, 4).map(visivel)).toEqual(["07/2026", brl(100_01), brl(101_02), "—"]);
    expect(celulas(linhas[2]).slice(0, 6).map(visivel)).toEqual(
      ["09/2026", "—", brl(300_05), brl(300_05), "—", brl(300_05)]);
    // o percentual da MT-PAR no lugar do valor previsto no apostilamento
    expect(visivel(celulas(linhas[3])[4])).toBe("6,76%");
    expect(visivel(celulas(linhas[4])[4])).toBe("4,125%");
  });

  it("a justificativa já registrada continua na linha da competência (issue #274)", async () => {
    api.mockImplementation(async (caminho: string) => caminho.endsWith("/reajuste")
      ? { ciclos: [cicloAberto], pleitos: [], competencias_por_ciclo: [{ data_base_mes: "2024-06", ciclo: 2026,
          competencias: [comp("2026-07", { estado: "pedida", previsto_centavos: 100_01, previsto_origem: "manual",
            medicoes: [1], pedido_centavos: 150_03, justificativa: { texto: "Índice definitivo saiu maior",
              usuario: "Engenharia", criado_em: "2026-10-01 12:00:00", pedido_centavos: 150_03,
              previsto_centavos: 100_01 } })] }] }
      : { instrumentos: [] });
    render(<Reajuste contratoId={7} podeEditar />);
    const selo = await screen.findByText("justificado");
    expect(selo.closest(".selo")?.getAttribute("title")).toBe("Índice definitivo saiu maior (Engenharia)");
    expect(screen.queryByRole("button", { name: /^Justificar/ })).toBeNull();
  });

  it("o total apostilado diz que é parcial quando há competência apostilada só por percentual (gate Sol, PR #438)", async () => {
    // spec 2026-10-20 §2.2: o sistema nao calcula valor do percentual da MT-PAR, entao a soma em reais e' so' das
    // competencias com valor; o rodape nao pode mostra-la como se fosse o total apostilado do ciclo
    api.mockImplementation(async (caminho: string) => caminho.endsWith("/reajuste")
      ? { ciclos: [cicloAberto], pleitos: [],
          competencias_por_ciclo: [{ data_base_mes: "2024-06", ciclo: 2026, competencias: [
            comp("2026-07", { estado: "apostilada", apostilada: true, apostilado_centavos: 100_01,
              apostilamento_chave: "ap-12" }),
            comp("2026-08", { estado: "apostilada", apostilada: true, apostilado_percentual: "6,76",
              apostilamento_chave: "ap-mtpar" }),
            comp("2026-09", { estado: "apostilada", apostilada: true, apostilado_percentual: "6,76",
              apostilamento_chave: "ap-mtpar" })] },
          { data_base_mes: "2024-06", ciclo: 2027, competencias: [
            comp("2027-07", { estado: "apostilada", apostilada: true, apostilado_percentual: "3,1",
              apostilamento_chave: "ap-mtpar-2" })] }] }
      : { instrumentos: [] });
    render(<Reajuste contratoId={7} podeEditar={false} />);
    const tabela = await screen.findByRole("table", { name: "Reajuste por competência da data-base 06/2024, ciclo de 2026" });
    const total = celulas(tabela.querySelector("tfoot tr")!)[4];
    expect(visivel(total)).toBe(`${brl(100_01)} (parcial)`);
    const motivo = "Parcial: 2 competências apostiladas por percentual, sem valor em reais, ficam fora da soma";
    expect(total.getAttribute("title")).toBe(motivo);
    expect(total.querySelector(".sr-only")?.textContent).toBe(`, ${motivo}`);
    // so' por percentual: nada somado, e o rodape diz por que
    const so = screen.getByRole("table", { name: "Reajuste por competência da data-base 06/2024, ciclo de 2027" });
    const total2 = celulas(so.querySelector("tfoot tr")!)[4];
    expect(visivel(total2)).toBe("— (parcial)");
    expect(total2.getAttribute("title")).toBe(
      "Parcial: 1 competência apostilada por percentual, sem valor em reais, fica fora da soma");
  });

  it("o percentual do termo no cabeçalho do ciclo lê a vírgula do cadastro (issue #275)", async () => {
    const termo = { id: 6, chave: "ap-mtpar", tipo: "apostilamento_reajuste", numero: "AP-2", data: "2026-05-11",
      dados: { data_base: "2024-06", ciclo: 2026, percentual: "3,80" } };
    api.mockImplementation(async (caminho: string) => caminho.endsWith("/reajuste")
      ? { ciclos: [{ ...cicloAberto, situacao: "apostilado", dias: null, apostilamento: termo }], pleitos: [] }
      : { instrumentos: [termo] });
    render(<Reajuste contratoId={7} podeEditar={false} />);
    const corpo = (await screen.findByText("Ciclo de 2026 · aniversário em 01/06/2026")).parentElement!;
    expect(corpo.textContent).toContain("AP-2, de 11/05/2026 · 3,8%");
    expect(corpo.textContent).not.toContain("NaN");
  });

  it("mostra a linha do tempo do ciclo: pleito, aditivo, reemissão, reiteração e termo, em ordem (issue #275)", async () => {
    const termo = { id: 5, chave: "ap-12", tipo: "apostilamento_reajuste", numero: "019/2024/02/12", data: "2026-11-03",
      dados: { data_base: "2024-06", ciclo: 2026 } };
    const pleito = (id: number, numero: string, enviado_em: string, extra: Record<string, unknown> = {}) => ({ id,
      tipo: "reajuste", rotulo: "Pleito de reajuste", origem: "cadastro", numero_oficio: numero, data_base_mes: "2024-06",
      ciclo: 2026, dias: null, justificativa: null, situacao: "enviado", corpo_carta: null, montado_paginas: null,
      assinado_arquivo: null, nome_documento: null, conferencia: null, pendencias: [], enviado_em,
      envio_justificativa: null, anexos: [], exigidos: [], instrumento_chave: null, ...extra });
    api.mockImplementation(async (caminho: string) => caminho.endsWith("/reajuste")
      ? { ciclos: [{ ...cicloAberto, situacao: "apostilado", dias: null, pleito: { id: 12 }, apostilamento: termo,
                     aditivos: [{ id: 2, numero: "2º TA", tipo: "prazo", data_assinatura: "2026-08-01" },
                                // no mesmo dia da reemissao: o aditivo vem antes, a reemissao responde a ele
                                { id: 3, numero: "3º TA", tipo: "misto", data_assinatura: "2026-09-20" }] }],
          pleitos: [
            pleito(12, "CT-245-LT-2026", "2026-10-30 09:00:00", { rotulo: "Reiteração do pleito de reajuste",
              reemissao: "reiteracao", reemite_pleito_id: 11, instrumento_chave: "ap-12" }),
            pleito(11, "CT-200-LT-2026", "2026-09-20", { rotulo: "Reemissão do pleito de reajuste",
              reemissao: "cronograma", reemite_pleito_id: 10 }),
            pleito(10, "CT-122-LT-2026", "2026-06-10"),
            pleito(9, "CT-90-LT-2025", "2025-06-10", { ciclo: 2025 })] }
      : { instrumentos: [termo] });
    render(<Reajuste contratoId={7} podeEditar={false} />);
    const tempo = await screen.findByRole("list", { name: "Linha do tempo do ciclo de 2026" });
    expect([...tempo.querySelectorAll("li")].map(li => li.textContent)).toEqual([
      "10/06/2026Pleito de reajuste CT-122-LT-2026 enviado",
      "01/08/2026Aditivo de prazo 2º TA assinado",
      "20/09/2026Aditivo de prazo e valor 3º TA assinado",
      "20/09/2026Reemissão do pleito de reajuste CT-200-LT-2026 enviada",
      "30/10/2026Reiteração do pleito de reajuste CT-245-LT-2026 enviada",
      "03/11/2026Apostilamento 019/2024/02/12"]);
  });

  it("dois complementos recebidos: a célula mostra a última baixa e a origem cita os dois (issue #445)", async () => {
    api.mockImplementation(async (caminho: string) => caminho.endsWith("/reajuste")
      ? { ciclos: [cicloAberto], pleitos: [],
          competencias_por_ciclo: [{ data_base_mes: "2024-06", ciclo: 2026, competencias: [
            comp("2026-07", { estado: "recebida", medicoes: [3, 8], medicao_numero: 8,
              recebida_em: "2026-11-02", recebidas: [{ numero: 3, recebida_em: "2026-10-15" },
                { numero: 8, recebida_em: "2026-11-02" }] })] }] }
      : { instrumentos: [] });
    render(<Reajuste contratoId={7} podeEditar={false} />);
    const tabela = await screen.findByRole("table", { name: "Reajuste por competência da data-base 06/2024, ciclo de 2026" });
    const recebido = celulas(tabela.querySelector("tbody tr")!)[6];
    expect(visivel(recebido)).toBe("02/11/2026");
    expect(recebido.getAttribute("title")).toBe("Origem: baixa no RM da 3ª e 8ª medições de reajuste");
  });

  it("dois envios no mesmo dia aparecem na ordem do horário (issue #445)", async () => {
    const pleito = (id: number, numero: string, enviado_em: string) => ({ id,
      tipo: "reajuste", rotulo: "Pleito de reajuste", origem: "cadastro", numero_oficio: numero, data_base_mes: "2024-06",
      ciclo: 2026, dias: null, justificativa: null, situacao: "enviado", corpo_carta: null, montado_paginas: null,
      assinado_arquivo: null, nome_documento: null, conferencia: null, pendencias: [], enviado_em,
      envio_justificativa: null, anexos: [], exigidos: [], instrumento_chave: null });
    api.mockImplementation(async (caminho: string) => caminho.endsWith("/reajuste")
      // a API manda do mais novo para o mais antigo
      ? { ciclos: [{ ...cicloAberto, situacao: "apostilado", dias: null, pleito: { id: 2 } }],
          pleitos: [pleito(2, "CT-2", "2026-06-10 16:00:00"), pleito(1, "CT-1", "2026-06-10 09:00:00")] }
      : { instrumentos: [] });
    render(<Reajuste contratoId={7} podeEditar={false} />);
    const tempo = await screen.findByRole("list", { name: "Linha do tempo do ciclo de 2026" });
    expect([...tempo.querySelectorAll("li")].map(li => li.textContent)).toEqual([
      "10/06/2026Pleito de reajuste CT-1 enviado", "10/06/2026Pleito de reajuste CT-2 enviado"]);
  });

  it("termo não ligado ao pleito não entra na linha do tempo do ciclo corrente (issue #445)", async () => {
    const solto = { id: 6, chave: "ap-99", tipo: "apostilamento_reajuste", numero: "SOLTO-1", data: "2026-10-01",
      dados: { data_base: "2024-06", ciclo: 2026 } };
    api.mockImplementation(async (caminho: string) => caminho.endsWith("/reajuste")
      ? { ciclos: [{ ...cicloAberto, apostilamento: null }], pleitos: [] }
      : { instrumentos: [solto] });
    render(<Reajuste contratoId={7} podeEditar={false} />);
    await screen.findByText("apostilamento pendente");
    expect(screen.queryByRole("list", { name: /^Linha do tempo/ })).toBeNull();
  });

  it("ciclo sem pleito enviado nem termo não tem linha do tempo (issue #275)", async () => {
    api.mockImplementation(async (caminho: string) => caminho.endsWith("/reajuste")
      ? { ciclos: [{ ...cicloAberto, situacao: "pleito_pendente", dias: 10 }], pleitos: [] }
      : { instrumentos: [] });
    render(<Reajuste contratoId={7} podeEditar={false} />);
    await screen.findByText("pleito não enviado");
    expect(screen.queryByRole("list", { name: /^Linha do tempo/ })).toBeNull();
  });

  it("para a diretoria, nenhum botão de ação aparece na aba (issue #275)", async () => {
    const vigente = { id: 10, tipo: "reajuste", rotulo: "Pleito de reajuste", origem: "sistema", numero_oficio: "CT-122-LT-2026",
      data_base_mes: "2024-09", ciclo: 2026, dias: null, justificativa: null, situacao: "enviado", corpo_carta: "Texto",
      montado_paginas: 1, assinado_arquivo: "x.pdf", nome_documento: "x.pdf", conferencia: null, pendencias: [],
      enviado_em: "2026-06-15", envio_justificativa: null, anexos: [], exigidos: [], reemite_pleito_id: null,
      reemissao: null, anterior: null, reemissoes: [], reemissoes_possiveis: ["reiteracao", "cronograma"] };
    api.mockImplementation(async (caminho: string) => caminho.endsWith("/reajuste")
      ? { ciclos: [{ ...cicloAberto, situacao: "pleito_pendente", dias: 10 },
                   { ...cicloAberto, data_base_mes: "2024-09", aniversario: "2026-09-01", pleito: { id: 10 } }],
          pleitos: [vigente],
          competencias_por_ciclo: [{ data_base_mes: "2024-09", ciclo: 2026, competencias: [
            comp("2026-09", { estado: "aprovada", medicoes: [2], pedido_centavos: 1, aprovado_centavos: 1,
              avisos: ["sem_apostilamento"] })] }] }
      : { instrumentos: [] });
    const { unmount } = render(<Reajuste contratoId={7} podeEditar />);
    // quem edita ve as acoes do ciclo (a prova de que a diretoria as perderia)
    expect(await screen.findByRole("button", { name: "Enviar pleito" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Reiterar" })).toBeTruthy();
    unmount();
    render(<Reajuste contratoId={7} podeEditar={false} />);
    await screen.findByRole("table", { name: "Reajuste por competência da data-base 09/2024, ciclo de 2026" });
    expect(screen.queryAllByRole("button")).toEqual([]);
    expect(screen.queryByText("sem apostilamento")).toBeNull();       // issue #648: a aba nao acusa a diferenca
  });

  it("competência fora das datas-base do cadastro não some (issue #275)", async () => {
    api.mockImplementation(async (caminho: string) => caminho.endsWith("/reajuste")
      ? { ciclos: [cicloAberto], pleitos: [],
          competencias_por_ciclo: [
            { data_base_mes: "2023-03", ciclo: 2025, competencias: [comp("2025-04", { previsto_centavos: 7, previsto_origem: "manual" })] },
            { data_base_mes: null, ciclo: null, competencias: [comp("2026-09", { estado: "pedida", medicoes: [2],
              pedido_centavos: 300_04, data_base_incerta: true })] }] }
      : { instrumentos: [] });
    render(<Reajuste contratoId={7} podeEditar={false} />);
    const cartao = await screen.findByRole("region", { name: "Reajuste sem data-base definida ou fora do cadastro" });
    expect(within(cartao).getByRole("table", { name: "Reajuste por competência da data-base 03/2023, ciclo de 2025" })).toBeTruthy();
    const semBase = within(cartao).getByRole("table", { name: "Reajuste por competência sem data-base definida" });
    expect(semBase.querySelector("tbody tr")?.textContent).toContain(brl(300_04));
    // a data-base e o ciclo de cada tabela a' vista (rodada 1 da PR #438), nao so' no nome para o leitor de tela
    expect([...cartao.querySelectorAll(".resumo__rotulo")].map(p => p.textContent)).toEqual(
      ["Data-base 03/2023, ciclo de 2025", "Data-base não definida"]);
  });

  it("cada ciclo anterior tem a linha do tempo dele em Ciclos anteriores (rodada 1 da PR #438)", async () => {
    const termo25 = { id: 4, chave: "ap-09", tipo: "apostilamento_reajuste", numero: "AP-9", data: "2025-09-01",
      dados: { data_base: "2024-06", ciclo: 2025 } };
    const pleito = (id: number, numero: string, enviado_em: string, ciclo: number) => ({ id, tipo: "reajuste",
      rotulo: "Pleito de reajuste", origem: "cadastro", numero_oficio: numero, data_base_mes: "2024-06", ciclo, dias: null,
      justificativa: null, situacao: "enviado", corpo_carta: null, montado_paginas: null, assinado_arquivo: null,
      nome_documento: null, conferencia: null, pendencias: [], enviado_em, envio_justificativa: null, anexos: [],
      exigidos: [], instrumento_chave: null });
    api.mockImplementation(async (caminho: string) => caminho.endsWith("/reajuste")
      ? { ciclos: [{ ...cicloAberto, pleito: { id: 10 } }],
          pleitos: [pleito(10, "CT-122-LT-2026", "2026-06-10", 2026), pleito(9, "CT-90-LT-2025", "2025-06-10", 2025)],
          linhas_do_tempo: [
            { data_base_mes: "2024-06", ciclo: 2025, termo: termo25,
              aditivos: [{ id: 2, numero: "2º TA", tipo: "prazo", data_assinatura: "2025-08-01" }] },
            { data_base_mes: "2024-06", ciclo: 2026, termo: null, aditivos: [] }] }
      : { instrumentos: [termo25] });
    render(<Reajuste contratoId={7} podeEditar={false} />);
    const tempo25 = await screen.findByRole("list", { name: "Linha do tempo do ciclo de 2025" });
    expect(tempo25.closest("details")?.querySelector("summary")?.textContent).toBe("Ciclos anteriores");
    expect([...tempo25.querySelectorAll("li")].map(li => li.textContent)).toEqual([
      "10/06/2025Pleito de reajuste CT-90-LT-2025 enviado",
      "01/08/2025Aditivo de prazo 2º TA assinado",
      "01/09/2025Apostilamento AP-9"]);
    // o corrente segue no cartao, so' com o que e' dele
    const tempo26 = screen.getByRole("list", { name: "Linha do tempo do ciclo de 2026" });
    expect(tempo26.closest("details")).toBeNull();
    expect([...tempo26.querySelectorAll("li")].map(li => li.textContent)).toEqual(
      ["10/06/2026Pleito de reajuste CT-122-LT-2026 enviado"]);
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
          // o termo que o cadastro nao manda mais (ap-11) ainda se nomeia pela lista das competencias apostiladas
          competencias: [
            { data_base_mes: "2024-06", ciclo: 2026, competencia: "2026-07", valor_centavos: 130003, medicao: 30,
              instrumento_chave: "ap-12", instrumento_numero: "019/2024/02/12", instrumento_data: "2026-10-01" },
            { data_base_mes: "2024-06", ciclo: 2026, competencia: "2026-08", valor_centavos: -1001, medicao: null,
              instrumento_chave: "ap-11", instrumento_numero: "019/2024/02/11", instrumento_data: "2026-09-15" }],
          competencias_por_ciclo: [{ data_base_mes: "2024-06", ciclo: 2026, competencias: [
            comp("2026-07", { estado: "apostilada", apostilada: true, apostilado_centavos: 130003,
              apostilamento_chave: "ap-12", medicao_orgao: 30 }),
            comp("2026-08", { estado: "apostilada", apostilada: true, apostilado_centavos: -1001,
              apostilamento_chave: "ap-11" })] }] }
      : { instrumentos: [termo] });
    render(<Reajuste contratoId={7} podeEditar={false} />);
    const tabela = await screen.findByRole("table", { name: "Reajuste por competência da data-base 06/2024, ciclo de 2026" });
    const apostilado = [...tabela.querySelectorAll("tbody tr")].map(tr => celulas(tr)[4]);
    expect(apostilado.map(c => [visivel(c), c.getAttribute("title")])).toEqual([
      [`${brl(130003)} (30ª med.)`, "Origem: apostilamento 019/2024/02/12, de 01/10/2026 (30ª medição)"],
      [brl(-1001), "Origem: apostilamento 019/2024/02/11, de 15/09/2026"]]);
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
    // o ofício aparece na seção dele e na linha do tempo do ciclo (issue #275)
    await screen.findByRole("heading", { name: /CT-122-LT-2026/ });
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
          pleitos: [pleito(3, 2025, "ta-03"), pleito(2, 2023, "ta-02"), pleito(1, 2022, "ta-01")], competencias: [],
          // so' os aditivos que valem como termo (gate Sol, PR #407): o ta-01 (cancelado, ou de execucao) nao vem
          aditivos_de_reajuste: [
            { id: 4, chave: "ta-02", tipo: "aditivo_valor", numero: "2º TA", data: "2023-11-10", dados: {} },
            { ...aditivo }] }
      : { instrumentos: [outro], aditivos: [
          { id: 3, chave_cadastro: "ta-01", tipo: "valor", numero: "1º TA", data_assinatura: "2022-11-10" }] });
    render(<Reajuste contratoId={7} podeEditar={false} />);
    expect(await screen.findByText("apostilado")).toBeTruthy();
    const corpo = screen.getByRole("region", { name: /^Data-base 10\/2021/ });
    expect(corpo.textContent).toContain("Termo aditivo 3º TA, de 20/11/2025");
    expect(corpo.textContent).toContain(`AP-1, de 01/12/${cicloOutro}`);
    expect(screen.getByText("atendido pelo termo aditivo 3º TA")).toBeTruthy();
    // pleito de ciclo anterior ligado ao aditivo dele tambem diz o termo
    expect(screen.getByText("atendido pelo termo aditivo 2º TA")).toBeTruthy();
    expect(screen.queryByText(/atendido pelo termo aditivo 1º TA/)).toBeNull();
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

  // issue #586: a resposta do orgao ao pleito (indeferimento fecha o ciclo; deferimento parcial espera o termo)
  const indeferimento = { id: 3, pleito_id: 10, resultado: "indeferido", data: "2026-10-20",
    documento: "Ofício 77/2026 do órgão", texto: "Índice não previsto", corrige_resposta_id: null, criado_em: "2026-10-21 10:00:00" };

  it("ciclo indeferido mostra o indeferimento com data e documento no cartão, no pleito e na linha do tempo (issue #586)", async () => {
    api.mockImplementation(async (caminho: string) => caminho.endsWith("/reajuste")
      ? { ciclos: [{ ...cicloPendente(10), situacao: "indeferido", dias: null, resposta: indeferimento }],
          pleitos: [enviado({ id: 10, numero_oficio: "CT-122-LT-2026", enviado_em: "2026-06-15" })],
          linhas_do_tempo: [{ data_base_mes: "2024-06", ciclo: 2026, termo: null, aditivos: [], respostas: [indeferimento] }] }
      : { instrumentos: [] });
    render(<Reajuste contratoId={7} podeEditar={false} />);
    const cartao = await screen.findByRole("region", { name: /^Data-base 06\/2024/ });
    expect(within(cartao).getAllByText("indeferido").length).toBeGreaterThan(0);
    expect(cartao.textContent).toContain("Indeferido em 20/10/2026 · Ofício 77/2026 do órgão");
    // o pleito vigente diz o desfecho, e nao a espera do apostilamento
    expect(screen.getByText("indeferido em 20/10/2026")).toBeTruthy();
    expect(screen.queryByText(/sem apostilamento/)).toBeNull();
    const linha = screen.getByRole("list", { name: "Linha do tempo do ciclo de 2026" });
    expect([...linha.querySelectorAll("li")].map(li => li.textContent)).toEqual(
      ["15/06/2026Pleito de reajuste CT-122-LT-2026 enviado", "20/10/2026Indeferido · Ofício 77/2026 do órgão"]);
    // quem so' consulta nao registra resposta
    expect(screen.queryByRole("button", { name: "Registrar resposta do órgão" })).toBeNull();
  });

  it("no pleito enviado sem apostilamento, registra a resposta do órgão (issue #586)", async () => {
    // o foco volta ao cartao depois de gravar; o jsdom nao tem scrollIntoView
    Element.prototype.scrollIntoView = vi.fn();
    api.mockImplementation(async (caminho: string) => caminho.endsWith("/reajuste")
      ? { ciclos: [cicloPendente(10)], pleitos: [enviado({ id: 10, numero_oficio: "CT-122-LT-2026", enviado_em: "2026-06-15" })] }
      : caminho.endsWith("/respostas") ? { id: 3 } : { instrumentos: [] });
    render(<Reajuste contratoId={7} podeEditar />);
    fireEvent.click(await screen.findByRole("button", { name: "Registrar resposta do órgão" }));
    const form = screen.getByRole("form", { name: "Resposta do órgão ao pleito CT-122-LT-2026" });
    // /code-review (#586): sem escolha previa (o indeferimento fecha o ciclo), e sem "sem efeito" sem resposta anterior
    const select = within(form).getByLabelText("Resposta") as HTMLSelectElement;
    expect(select.value).toBe("");
    expect(select.required).toBe(true);
    expect([...select.options].map(o => o.value)).toEqual(["", "indeferido", "deferido_parcial"]);
    fireEvent.change(select, { target: { value: "indeferido" } });
    fireEvent.change(within(form).getByLabelText("Data"), { target: { value: "2026-10-20" } });
    fireEvent.change(within(form).getByLabelText("Documento"), { target: { value: "Ofício 77/2026 do órgão" } });
    fireEvent.change(within(form).getByLabelText("Texto"), { target: { value: "Índice não previsto" } });
    fireEvent.click(within(form).getByRole("button", { name: "Registrar resposta" }));
    await waitFor(() => expect(api.mock.calls.some(c => c[0] === "/api/pleitos/10/respostas")).toBe(true));
    const [, opcoes] = api.mock.calls.find(c => c[0] === "/api/pleitos/10/respostas")!;
    expect(opcoes.method).toBe("POST");
    expect(JSON.parse(opcoes.body)).toEqual({ resultado: "indeferido", data: "2026-10-20",
      documento: "Ofício 77/2026 do órgão", texto: "Índice não previsto" });
    await waitFor(() => expect(screen.queryByRole("form", { name: /^Resposta do órgão/ })).toBeNull());
  });

  it("com resposta registrada, a resposta errada fica sem efeito pelo formulário (rodada 1 da PR #599)", async () => {
    Element.prototype.scrollIntoView = vi.fn();
    api.mockImplementation(async (caminho: string) => caminho.endsWith("/reajuste")
      ? { ciclos: [{ ...cicloPendente(10), situacao: "indeferido", dias: null, resposta: indeferimento }],
          pleitos: [enviado({ id: 10, numero_oficio: "CT-122-LT-2026", enviado_em: "2026-06-15" })] }
      : caminho.endsWith("/respostas") ? { id: 4 } : { instrumentos: [] });
    render(<Reajuste contratoId={7} podeEditar />);
    fireEvent.click(await screen.findByRole("button", { name: "Registrar resposta do órgão" }));
    const form = screen.getByRole("form", { name: "Resposta do órgão ao pleito CT-122-LT-2026" });
    const select = within(form).getByLabelText("Resposta") as HTMLSelectElement;
    expect([...select.options].map(o => o.value)).toEqual(["", "indeferido", "deferido_parcial", "sem_efeito"]);
    fireEvent.change(select, { target: { value: "sem_efeito" } });
    fireEvent.change(within(form).getByLabelText("Data"), { target: { value: "2026-10-21" } });
    fireEvent.change(within(form).getByLabelText("Documento"), { target: { value: "Registro errado" } });
    fireEvent.change(within(form).getByLabelText("Texto"), { target: { value: "Lançado no pleito errado" } });
    fireEvent.click(within(form).getByRole("button", { name: "Registrar resposta" }));
    await waitFor(() => expect(api.mock.calls.some(c => c[0] === "/api/pleitos/10/respostas")).toBe(true));
    const [, opcoes] = api.mock.calls.find(c => c[0] === "/api/pleitos/10/respostas")!;
    expect(JSON.parse(opcoes.body)).toEqual({ resultado: "sem_efeito", data: "2026-10-21",
      documento: "Registro errado", texto: "Lançado no pleito errado" });
  });
});
