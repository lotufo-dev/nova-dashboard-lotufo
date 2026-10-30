import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
