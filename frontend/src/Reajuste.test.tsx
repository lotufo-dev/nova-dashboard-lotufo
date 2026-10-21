import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Reajuste from "./Reajuste";

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
    // sem reemissao possivel no pleito vigente (servidor), nenhum botao de reiterar
    expect(screen.queryByRole("button", { name: "Reiterar" })).toBeNull();
  });
});
