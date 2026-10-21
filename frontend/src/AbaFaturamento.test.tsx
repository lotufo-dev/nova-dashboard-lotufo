import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Usuario } from "./Login";
import MedicoesPagina from "./MedicoesPagina";
import type { LinhaResumo, ResumoMedicoes } from "./resumoMedicoes";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api, apiForm: vi.fn() }));

const usuario = { id: 1, nome: "Leonardo Praeiro", email: "l@l.com", perfil: "admin" } as Usuario;

const linha = (extra: Partial<LinhaResumo>): LinhaResumo => ({
  situacao: "faturamento", contrato_id: 17, obra: "MT-388", contratante: "SINFRA", orgao_sub: "SUEF II",
  medicao_id: 900, medicao_ids: [900], numero: 15, competencia: "2026-09", titulo: "15ª Medição + Reajuste",
  proximo_passo: "enviar ao faturamento", valor_centavos: 124890317, marco: "2026-10-08", dias: 6, ...extra });

const resumo = (linhas: LinhaResumo[]): ResumoMedicoes => ({
  hoje: "2026-10-14",
  contagens: { "planilha-gerada": 0, "planilha-enviada": 0, "boletim-recebido": 0, "sem-medicao": 0, faturamento: linhas.length, "aguardando-nota": 0, "enviar-nota": 0, "aguardando-pagamento": 0 },
  linhas, obras: [],
});

const LINHAS = [
  linha({}),
  linha({ medicao_id: 901, contrato_id: 18, obra: "Terminais BRT", numero: 1, titulo: "1ª Medição de Projeto",
    valor_centavos: 47237645, dias: 2 }),
  linha({ medicao_id: 902, contrato_id: 19, obra: "Complexo Orla", contratante: "MTPAR", orgao_sub: null, numero: 8,
    competencia: "2026-08", titulo: "8ª Medição", valor_centavos: 31822015, marco: null, dias: null }),
  linha({ medicao_id: 903, contrato_id: 20, obra: "Obra de outra etapa", situacao: "enviar-nota" }),
];

describe("Aba Enviar ao faturamento", () => {
  afterEach(() => { cleanup(); api.mockReset(); });

  it("um quadro por contratante com a quantidade e a soma; o mais parado primeiro", async () => {
    api.mockResolvedValue(resumo(LINHAS));
    render(<MedicoesPagina aba="faturamento" busca={{}} usuario={usuario} />);
    const sinfra = await screen.findByRole("region", { name: /^SINFRA/ });
    // 124.890.317 + 47.237.645 = 172.127.962 centavos
    expect(sinfra.querySelector("h2")?.textContent?.replace(/ /g, " ")).toBe("SINFRA · 2 medições · R$ 1.721.279,62");
    const titulos = screen.getAllByRole("heading", { level: 2 }).map(h => h.textContent?.replace(/ /g, " "));
    expect(titulos[0]).toMatch(/^SINFRA/);
    expect(titulos[1]).toBe("MTPAR · 1 medição · R$ 318.220,15");
    // so' a situacao faturamento entra
    expect(screen.queryByText("Obra de outra etapa")).toBeNull();
  });

  it("a linha traz a competência, o valor e a parada com a cor do limiar; sem marco, traço", async () => {
    api.mockResolvedValue(resumo([linha({ dias: 16 }), LINHAS[2]]));
    render(<MedicoesPagina aba="faturamento" busca={{}} usuario={usuario} />);
    const sinfra = await screen.findByRole("region", { name: /^SINFRA/ });
    expect(within(sinfra).getByText("09/2026")).toBeTruthy();
    expect(within(sinfra).getAllByText("R$ 1.248.903,17").length).toBeGreaterThan(0);
    expect(within(sinfra).getByText(/^16\s+dias$/).className).toContain("medicoes__parada--acao");
    const mtpar = screen.getByRole("region", { name: /^MTPAR/ });
    const par = within(mtpar).getByTitle("Sem a data do marco desta etapa");
    expect(par.textContent).toBe("—");
    expect(within(mtpar).queryByText(/Parada há/)).toBeNull();
  });

  it("o botão abre a medição na etapa 2, sem enviar nada", async () => {
    api.mockResolvedValue(resumo([linha({})]));
    render(<MedicoesPagina aba="faturamento" busca={{}} usuario={usuario} />);
    const botao = await screen.findByRole("link", { name: /Enviar ao faturamento: MT-388/ });
    expect(botao.getAttribute("href")).toBe("/obras/17/medicoes/900#etapa-2");
    expect(api).toHaveBeenCalledTimes(1);   // so' a leitura do resumo
  });

  it("estado vazio: a frase da aba, sem lista", async () => {
    api.mockResolvedValue(resumo([]));
    render(<MedicoesPagina aba="faturamento" busca={{}} usuario={usuario} />);
    expect(await screen.findByText("Nenhum espelho esperando o envio ao faturamento.")).toBeTruthy();
    expect(screen.queryByRole("list")).toBeNull();
  });

  it("Iniciar processo de medição aparece e abre a janela; a diretoria não o vê", async () => {
    api.mockResolvedValue(resumo(LINHAS));
    const { unmount } = render(<MedicoesPagina aba="faturamento" busca={{}} usuario={usuario} />);
    fireEvent.click(await screen.findByRole("button", { name: /Iniciar processo de medição/ }));
    expect(screen.getByRole("dialog", { name: "Iniciar processo de medição" })).toBeTruthy();
    unmount();
    render(<MedicoesPagina aba="faturamento" busca={{}} usuario={{ ...usuario, perfil: "diretoria" }} />);
    await screen.findByRole("region", { name: /^SINFRA/ });
    expect(screen.queryByRole("button", { name: /Iniciar processo/ })).toBeNull();
    // a diretoria so' consulta: sem o botao de enviar, e o titulo da medicao continua levando a' etapa 2
    expect(screen.queryByRole("link", { name: /Enviar ao faturamento:/ })).toBeNull();
    expect(screen.getByRole("link", { name: "15ª Medição + Reajuste" }).getAttribute("href")).toBe("/obras/17/medicoes/900#etapa-2");
  });

  it("limiar da parada: 7 dias sem cor, 8 dias âmbar", async () => {
    api.mockResolvedValue(resumo([linha({ medicao_id: 1, dias: 7 }), linha({ medicao_id: 2, obra: "Outra", dias: 8 })]));
    render(<MedicoesPagina aba="faturamento" busca={{}} usuario={usuario} />);
    const sete = await screen.findByText(/^7\s+dias$/);
    expect(sete.className).toBe("medicoes__parada");
    expect(screen.getByText(/^8\s+dias$/).className).toContain("medicoes__parada--atencao");
  });

  it("contratante nulo (obra fora do cadastro ativo) não derruba a aba", async () => {
    api.mockResolvedValue(resumo([linha({ contratante: null as unknown as string })]));
    render(<MedicoesPagina aba="faturamento" busca={{}} usuario={usuario} />);
    expect(await screen.findByRole("region", { name: /^Órgão sem cadastro · 1 medição/ })).toBeTruthy();
  });

  it("empate de parada desempata pelo nome; sem marco conta como o menos parado", async () => {
    api.mockResolvedValue(resumo([
      linha({ medicao_id: 1, contratante: "Zeta", dias: 3 }), linha({ medicao_id: 2, contratante: "Alfa", dias: 3 }),
      linha({ medicao_id: 3, contratante: "Sem marco", dias: null })]));
    render(<MedicoesPagina aba="faturamento" busca={{}} usuario={usuario} />);
    await screen.findByRole("region", { name: /^Alfa/ });
    expect(screen.getAllByRole("heading", { level: 2 }).map(h => h.textContent?.split(" · ")[0])).toEqual(["Alfa", "Zeta", "Sem marco"]);
  });
});
