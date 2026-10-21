import { cleanup, fireEvent, render, screen } from "@testing-library/react";
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
    // um cartao por data-base (com ancora), e a linha do ciclo com os dias do servidor
    expect(screen.getByRole("region", { name: /^Data-base 06\/2024 · INCC-DI/ }).closest("[id]")?.id).toBe("db-2024-06");
    expect(screen.getByText("Ciclo de 2026 · fez aniversário em 01/06/2026 (há 14 dias)")).toBeTruthy();
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
});
