import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Usuario } from "./Login";
import MedicoesPagina from "./MedicoesPagina";
import type { LinhaResumo, ResumoMedicoes } from "./resumoMedicoes";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api, apiForm: vi.fn() }));

const usuario = { id: 1, nome: "Leonardo Praeiro", email: "l@l.com", perfil: "admin" } as Usuario;

const linha = (extra: Partial<LinhaResumo>): LinhaResumo => ({
  situacao: "enviar-nota", contrato_id: 12, obra: "Estações BRT", contratante: "SINFRA", orgao_sub: "SAGPM / SUOESP",
  medicao_id: 70, medicao_ids: [70, 71], numero: 7, competencia: "2026-09", titulo: "7ª Medição + Reajuste", proximo_passo: "protocolar",
  valor_centavos: 997926492, marco: "2026-10-07", dias: 2, ...extra });

const RESUMO: ResumoMedicoes = {
  hoje: "2026-10-09",
  contagens: { "sem-medicao": 3, "planilha-gerada": 0, "planilha-enviada": 0, "boletim-recebido": 0, faturamento: 0, "aguardando-nota": 0, "enviar-nota": 2, "aguardando-pagamento": 0 },
  linhas: [
    linha({}),
    linha({ medicao_id: 72, medicao_ids: [72], numero: 1, titulo: "1ª Medição de Projeto", valor_centavos: 14811701, dias: 24 }),
  ],
  obras: [
    { contrato_id: 12, obra: "Estações BRT", contratante: "SINFRA", orgao_sub: "SAGPM / SUOESP", aberta: true, prevista_id: null, encerramento: false,
      ultima: { numero: 6, tipo: "execucao", competencia: "2026-08" }, ha_dias: null, prevista: null, proxima: 7, proxima_tipo: "execucao" },
    { contrato_id: 17, obra: "MT-388", contratante: "SINFRA", orgao_sub: "SUEF II", aberta: false, prevista_id: 900, encerramento: false,
      ultima: { numero: 23, tipo: "execucao", competencia: "2026-01" }, ha_dias: 251,
      prevista: { numero: 24, tipo: "execucao", competencia: "2026-09" }, proxima: 24, proxima_tipo: "execucao" },
    { contrato_id: 4, obra: "Cavalaria", contratante: "SINFRA", orgao_sub: "SACID", aberta: false, prevista_id: null, encerramento: false,
      ultima: null, ha_dias: null, prevista: null, proxima: 1, proxima_tipo: "execucao" },
    { contrato_id: 13, obra: "Granito", contratante: "MTPAR", orgao_sub: null, aberta: false, prevista_id: null, encerramento: true,
      ultima: { numero: 1, tipo: "projeto", competencia: "2026-09" }, ha_dias: 9, prevista: null, proxima: 2, proxima_tipo: "projeto" },
  ],
};

describe("Medições com abas", () => {
  afterEach(() => { cleanup(); api.mockReset(); });

  it("Resumo: cartões por situação, a tabela em andamento e as obras sem medição por contratante", async () => {
    api.mockResolvedValue(RESUMO);
    render(<MedicoesPagina aba="resumo" busca={{}} usuario={usuario} />);
    const quadro = await screen.findByRole("region", { name: "Todas as obras" });
    // sem legenda de contagem ao lado do titulo (texto-na-tela, 26/10/2026)
    expect(quadro.querySelector(".medicoes__legenda")).toBeNull();
    expect(within(quadro).queryByText(/obras ativas|em andamento/)).toBeNull();
    // a medição abre na etapa pendente (enviar a nota = etapa 4)
    expect(within(quadro).getByRole("link", { name: "7ª Medição + Reajuste" }).getAttribute("href")).toBe("/obras/12/medicoes/70#etapa-4");
    // a segunda medição aberta da mesma obra não repete o nome como link
    expect(within(quadro).getAllByRole("link", { name: "Estações BRT" })).toHaveLength(1);
    expect(within(quadro).getByText(/^24\s+dias$/).className).toContain("medicoes__parada--acao");
    // sem medição: grupos por contratante, o maior primeiro, fechados
    const grupos = quadro.querySelectorAll("details");
    expect([...grupos].map(d => d.querySelector("summary")?.textContent)).toEqual(
      ["SINFRA", "MTPAR"]);
    expect(quadro.querySelector(".medicoes__faixa")?.textContent).toBe("Sem medição aberta");
    expect([...grupos].every(d => !d.open)).toBe(true);
    // cartão leva à aba; a aba diz a contagem
    const cartoes = screen.getByRole("navigation", { name: "Medições por situação" });
    expect(within(cartoes).getByRole("link", { name: /Enviar nota/ }).getAttribute("href")).toBe("/medicoes/enviar-nota");
    const abas = screen.getByRole("navigation", { name: "Seções de Medições" });
    expect(within(abas).getByRole("link", { name: "Resumo" }).getAttribute("aria-current")).toBe("page");
    expect(within(abas).getByRole("link", { name: /Sem medição aberta/ }).textContent).toBe("Sem medição aberta3");
  });

  it("aba Sem medição aberta (#154): grupos por contratante, última medição, há quanto tempo, prevista e iniciar", async () => {
    api.mockResolvedValue(RESUMO);
    render(<MedicoesPagina aba="sem-medicao" busca={{}} usuario={usuario} />);
    const quadro = await screen.findByRole("region", { name: "Sem medição aberta" });
    // sem contagem ao lado do titulo nem no grupo (texto-na-tela, 26/10/2026)
    expect(quadro.querySelector(".medicoes__legenda")).toBeNull();
    // o maior grupo primeiro; os dois primeiros abertos
    expect([...quadro.querySelectorAll("details")].map(d => d.querySelector("summary")?.textContent)).toEqual(
      ["SINFRA", "MTPAR"]);
    const mt = within(quadro).getByRole("row", { name: /MT-388/ });
    expect(within(mt).getByText("SUEF II")).toBeTruthy();
    expect(within(mt).getByText("23ª · 01/2026")).toBeTruthy();
    expect(within(mt).getByText(/^251\s+dias$/).className).not.toContain("parada");   // sem cor
    expect(within(mt).getByText("Prevista: 24ª · 09/2026")).toBeTruthy();
    // a prevista abre a medição dela; a obra sem prevista abre a nova, com o número seguinte
    expect(within(mt).getByRole("link", { name: "Iniciar a 24ª medição" }).getAttribute("href")).toBe("/obras/17/medicoes/900");
    const cav = within(quadro).getByRole("row", { name: /Cavalaria/ });
    expect(within(cav).getByRole("link", { name: "Iniciar a 1ª medição" }).getAttribute("href")).toBe("/obras/4/medicoes/nova");
    expect(within(cav).getAllByText("—")).toHaveLength(3);   // sem última medição, sem tempo, sem prevista
    expect(within(quadro).getByRole("link", { name: "Granito" }).getAttribute("href")).toBe("/obras/13");
    // obra que só mede projeto: o tipo aparece na última e no link (série própria)
    const gr = within(quadro).getByRole("row", { name: /Granito/ });
    expect(within(gr).getByText("1ª de Projeto · 09/2026")).toBeTruthy();
    expect(within(gr).getByRole("link", { name: "Iniciar a 2ª medição de Projeto" })).toBeTruthy();
    // o botão de iniciar continua na aba; a diretoria não o vê
    fireEvent.click(screen.getByRole("button", { name: /Iniciar processo de medição/ }));
    expect(screen.getByRole("dialog", { name: "Iniciar processo de medição" })).toBeTruthy();
  });

  it("aba Sem medição aberta sem obras: estado vazio e sem botão para a diretoria", async () => {
    api.mockResolvedValue({ ...RESUMO, obras: RESUMO.obras.map(o => ({ ...o, aberta: true })) });
    render(<MedicoesPagina aba="sem-medicao" busca={{}} usuario={{ ...usuario, perfil: "diretoria" }} />);
    expect(await screen.findByText("Todas as obras ativas têm medição aberta.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Iniciar processo/ })).toBeNull();
  });

  it("estados novos do motor: abas e cartões na ordem do ciclo, antes do espelho, com o texto em português", async () => {
    api.mockResolvedValue({ ...RESUMO, contagens: { ...RESUMO.contagens, "planilha-enviada": 1 },
      linhas: [linha({ situacao: "planilha-enviada", proximo_passo: "registrar o boletim" })] });
    render(<MedicoesPagina aba="planilha-enviada" busca={{}} usuario={usuario} />);
    const abas = await screen.findByRole("navigation", { name: "Seções de Medições" });
    expect(within(abas).getAllByRole("link").map(a => a.textContent)).toEqual([
      "Resumo", "Sem medição aberta3", "Planilha/carta gerada0", "Planilha/carta enviada1", "Boletim recebido0",
      "Enviar ao faturamento0", "Aguardando nota0", "Enviar nota2", "Aguardando pagamento0"]);
    const quadro = await screen.findByRole("region", { name: "Planilha/carta enviada" });
    expect(within(quadro).getByText("7ª Medição + Reajuste")).toBeTruthy();
    expect(quadro.querySelector(".sit-pilula--planilha-enviada")?.textContent).toBe("Planilha/carta enviada");
  });

  it("aba Boletim recebido vazia diz o que falta", async () => {
    api.mockResolvedValue(RESUMO);
    render(<MedicoesPagina aba="boletim-recebido" busca={{}} usuario={usuario} />);
    expect(await screen.findByText("Nenhum boletim recebido à espera do espelho.")).toBeTruthy();
  });

  it("aba Aguardando nota: estado vazio sem medição, e a linha da medição que espera a nota", async () => {
    api.mockResolvedValue(RESUMO);
    const { unmount } = render(<MedicoesPagina aba="aguardando-nota" busca={{}} usuario={usuario} />);
    expect(await screen.findByText("Nenhuma medição esperando nota.")).toBeTruthy();
    expect(screen.queryByRole("navigation", { name: "Medições por situação" })).toBeNull();
    unmount();
    api.mockResolvedValue({ ...RESUMO, linhas: [linha({ situacao: "aguardando-nota", proximo_passo: "anexar as notas" })] });
    render(<MedicoesPagina aba="aguardando-nota" busca={{}} usuario={usuario} />);
    const quadro = await screen.findByRole("region", { name: "Aguardando nota" });
    expect(within(quadro).getByText("R$ 9.979.264,92")).toBeTruthy();
  });

  it("Iniciar processo: a obra com medição prevista abre essa medição; as outras, a nova medição", async () => {
    api.mockResolvedValue(RESUMO);
    render(<MedicoesPagina aba="resumo" busca={{}} usuario={usuario} />);
    fireEvent.click(await screen.findByRole("button", { name: /Iniciar processo de medição/ }));
    const janela = screen.getByRole("dialog", { name: "Iniciar processo de medição" });
    expect(within(janela).getByRole("link", { name: /MT-388/ }).getAttribute("href")).toBe("/obras/17/medicoes/900");
    expect(within(janela).getByRole("link", { name: /Granito/ }).getAttribute("href")).toBe("/obras/13/medicoes/nova");
    fireEvent.change(within(janela).getByRole("searchbox"), { target: { value: "granito" } });
    expect(within(janela).getAllByRole("link")).toHaveLength(1);
  });

  it("a diretoria não vê o botão de iniciar", async () => {
    api.mockResolvedValue(RESUMO);
    render(<MedicoesPagina aba="resumo" busca={{}} usuario={{ ...usuario, perfil: "diretoria" }} />);
    await screen.findByRole("region", { name: "Todas as obras" });
    expect(screen.queryByRole("button", { name: /Iniciar processo/ })).toBeNull();
  });

  it("abas Enviar nota e Aguardando pagamento sem parágrafo de descrição", async () => {
    api.mockImplementation(async (c: string) => c.includes("a-enviar") ? { envios: [], contadores: {} }
      : c.includes("aguardando") ? [] : RESUMO);
    const { container, unmount } = render(<MedicoesPagina aba="enviar-nota" busca={{}} usuario={usuario} />);
    await screen.findByText("Nenhuma nota a enviar.");
    expect(container.querySelector(".pagina__descricao")).toBeNull();
    expect(screen.queryByText(/juntos na SINFRA/)).toBeNull();
    unmount();
    const r = render(<MedicoesPagina aba="aguardando-pagamento" busca={{}} usuario={usuario} />);
    expect(r.container.querySelector(".pagina__descricao")).toBeNull();
    expect(screen.queryByText(/se registra na etapa 4/)).toBeNull();
  });

  it("os filtros da aba Enviar nota vêm da URL e vão para a URL (sobrevivem ao recarregar)", async () => {
    const env = (chave: string, obra: string) => ({
      chave, contrato_id: 12, obra, orgao: "SINFRA", orgao_sub: null, familia: "sinfra", grupo: "SINFRA", a_pedido: false,
      medicao_ids: [637], descricao: "14ª medição", notas: [{ numero: "2340", natureza: "execucao", valor_centavos: 100 }],
      valor_centavos: 100, emitida_em: "2026-10-08", dias: 1, situacao: "pronto", aviso: null, protocolo_id: null, itens: [] });
    api.mockImplementation(async (c: string) => c.includes("a-enviar")
      ? { envios: [env("a", "MT-388"), env("b", "Granito")], contadores: { Todas: 2, SINFRA: 2 } } : RESUMO);
    window.history.replaceState(null, "", "/medicoes/enviar-nota");
    const { unmount } = render(<MedicoesPagina aba="enviar-nota" busca={{}} usuario={usuario} />);
    const caixa = await screen.findByRole("searchbox", { name: "Buscar nota ou obra" });
    fireEvent.change(caixa, { target: { value: "granito" } });
    expect(window.location.search).toBe("?q=granito");
    unmount();
    // recarregar: a busca da URL reabre a lista ja' filtrada
    render(<MedicoesPagina aba="enviar-nota" busca={Object.fromEntries(new URLSearchParams(window.location.search))} usuario={usuario} />);
    const de = await screen.findByRole("searchbox", { name: "Buscar nota ou obra" }) as HTMLInputElement;
    expect(de.value).toBe("granito");
    expect(screen.queryByText("MT-388")).toBeNull();
  });
});
