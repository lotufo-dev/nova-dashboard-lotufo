import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Inicio, { saudacao, type PainelInicio } from "./Inicio";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

const USUARIO = { id: 1, nome: "Leonardo Praeiro", email: "leonardo@lotufo.com", perfil: "admin" };

const painel = (extra: Partial<PainelInicio> = {}): PainelInicio => ({
  hoje: "2026-10-09",
  notas_a_enviar: 3,
  certidoes: { vencidas: 1, vencendo: 1, itens: [
    { tipo: "FGTS", entidade: "Encomind", validade: "2026-10-01", dias: null, vencida: true },
    { tipo: "Estadual", entidade: "Guaxe", validade: "2026-10-15", dias: 6, vencida: false }] },
  reajustes: [{ contrato_id: 7, obra: "Complexo Leblon", data_base_mes: "2025-11", aniversario: "2026-11-01", dias: 23 }],
  protocoladas: { obras_protocoladas: 2, obras_ativas: 18, ultima: "2026-09-30" },
  medido: { competencia: "2026-10", anterior_competencia: "2026-09",
            valor_centavos: 124_000_000, anterior_centavos: 100_000_000, quantidade: 2, ultimo_lancamento: "2026-10-08" },
  por_contratante: [{ contratante: "SINFRA", atual_centavos: 124_000_000, anterior_centavos: 100_000_000 }],
  recebido_ano: { valor_centavos: null, mes_centavos: 0, sem_data: 12 },
  a_receber: { liberado: true, valor_centavos: 1_720_000_000, mais_60_centavos: 210_000_000 },
  prazos: [
    { contrato_id: 3, obra: "MT-388 Sinop", contratante: "SINFRA", tipo: "vigencia", data: "2026-10-20", dias: 11 },
    { contrato_id: 7, obra: "Complexo Leblon", contratante: "Pref. Cuiabá", tipo: "data_base", data: "2026-11-01", dias: 23 }],
  ...extra,
});

describe("Início", () => {
  afterEach(() => { cleanup(); api.mockReset(); });

  it("cartões na ordem fixa, números sem frase de apoio e prazos levando à obra", async () => {
    api.mockResolvedValue(painel());
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    expect(api).toHaveBeenCalledWith("/api/inicio/painel");
    expect(screen.getByRole("heading", { level: 1 }).textContent).toMatch(/, Leonardo$/);
    const cartoes = within(await screen.findByRole("region", { name: "O que fazer agora" })).getAllByRole("link");
    expect(cartoes.map(a => a.getAttribute("href"))).toEqual(["/medicoes/enviar-nota", "/documentos", "/obras/7/reajuste"]);
    expect(cartoes[0].textContent).toContain("notas a enviar");
    expect(cartoes[1].textContent).toContain("certidões vencidas ou vencendo");
    expect(cartoes[1].textContent).not.toContain("FGTS Encomind");
    expect(cartoes[2].textContent).not.toContain("data-base");
    expect(cartoes[0].textContent).not.toContain("emitidas e ainda não enviadas");

    const numeros = { textContent: (screen.getByRole("region", { name: "Números do mês" }).textContent ?? "").replace(/ /g, " ") };
    expect(numeros.textContent).toContain("R$ 1.240.000,00");
    // B-01 (10/10/2026): competencia do mes contra o mes anterior inteiro, sem "ate' dia N"
    expect(numeros.textContent).toContain("Medido em outubro");
    expect(numeros.textContent).not.toContain("até dia");
    expect(numeros.textContent).not.toContain("sobre setembro");
    expect(numeros.textContent).not.toContain("valor cheio");
    expect(numeros.textContent).toContain("2 de 18 obras ativas");
    expect(numeros.textContent).not.toContain("Última protocolada");
    expect(numeros.textContent).not.toContain("sem data da baixa");
    expect(numeros.textContent).not.toContain("cota da Lotufo");
    // valor nulo do recebido vira "—"
    expect(numeros.textContent).toContain("Recebido em 2026—");
    // atraso que pede acao vira selo, com o valor no title
    const selo = screen.getByText("mais de 60 dias").closest(".selo");
    expect(selo?.className).toContain("selo--acao");
    expect(selo?.getAttribute("title")?.replace(/ /g, " ")).toBe("R$ 2.100.000,00");

    expect(screen.queryByText(/Nenhuma medição da competência/)).toBeNull();
    const prazos = within(screen.getByRole("region", { name: "Prazos chegando" }));
    expect(prazos.getByRole("link", { name: /MT-388 Sinop/ }).getAttribute("href")).toBe("/obras/3/prazos");
    expect(prazos.getByRole("link", { name: /Complexo Leblon/ }).getAttribute("href")).toBe("/obras/7/reajuste");
  });

  it("mês sem medição: aviso e botão para lançar", async () => {
    api.mockResolvedValue(painel({
      medido: { competencia: "2026-10", anterior_competencia: "2026-09",
                valor_centavos: 0, anterior_centavos: 0, quantidade: 0, ultimo_lancamento: "2026-09-30" },
      por_contratante: [], reajustes: [],
    }));
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    const aviso = await screen.findByRole("status");
    expect(aviso.textContent).toContain("Nenhuma medição da competência de outubro.");
    expect(aviso.textContent).not.toContain("Último lançamento");
    expect(within(aviso).getByRole("link", { name: /Lançar medição/ }).getAttribute("href")).toBe("/medicoes");
    const cartoes = within(screen.getByRole("region", { name: "O que fazer agora" })).getAllByRole("link");
    expect(cartoes[2].getAttribute("href")).toBe("/avisos");
  });

  it("a receber sem nada há mais de 60 dias, ou ainda não liberado, fica sem selo", async () => {
    api.mockResolvedValue(painel({ a_receber: { liberado: true, valor_centavos: 1_720_000_000, mais_60_centavos: 0 } }));
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    const numeros = await screen.findByRole("region", { name: "Números do mês" });
    expect(within(numeros).queryByText("mais de 60 dias")).toBeNull();
    expect(numeros.textContent).not.toContain("nada há mais de 60 dias");
    cleanup();
    api.mockResolvedValue(painel({ a_receber: { liberado: false, valor_centavos: null, mais_60_centavos: null } }));
    render(<Inicio usuario={USUARIO} ir={vi.fn()} />);
    const n2 = await screen.findByRole("region", { name: "Números do mês" });
    expect(within(n2).queryByText("mais de 60 dias")).toBeNull();
    expect(n2.textContent).not.toContain("aguardando a conciliação");
    expect(n2.textContent).toContain("A receber—");
  });

  it("saudação pela hora de Cuiabá", () => {
    expect(saudacao(new Date("2026-10-09T13:00:00Z"))).toBe("Bom dia");        // 09h em Cuiabá
    expect(saudacao(new Date("2026-10-09T17:00:00Z"))).toBe("Boa tarde");      // 13h
    expect(saudacao(new Date("2026-10-10T01:00:00Z"))).toBe("Boa noite");      // 21h
  });
});
