import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { apiForm } from "./api";
import Documentos from "./Documentos";
import { competenciaDoNome } from "./documentosDados";
import { chipCertidao, competenciasRegularidade } from "./matriz";

vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()),
  api: vi.fn(async (caminho: string) => {
    if (caminho === "/api/documentos") return (await import("./documentosTeste")).PAINEL;
    return {};
  }),
  apiForm: vi.fn(),
}));

afterEach(() => { cleanup(); vi.unstubAllGlobals(); window.history.replaceState(null, "", "/"); });

const usuario = { id: 1, nome: "U", email: "u@lotufo.com", perfil: "engenharia" };

const linhaDe = (nome: string) => screen.getByRole("link", { name: nome }).closest("li")!;

test("três abas com contador: certidões vencendo, regularidade faltando e garantias vencidas", async () => {
  render(<Documentos usuario={usuario} />);
  await screen.findByRole("link", { name: "Lotufo" });
  const abas = screen.getAllByRole("tab").map(t => t.textContent);
  expect(abas).toEqual(["Certidões · 2 vencendo", "Regularidade mensal · 5 faltando", "Garantias · 1 vencida"]);
  expect(screen.getByRole("button", { name: /Anexar PDF/ })).toBeTruthy();
});

test("aba Certidões: uma linha por empresa, chips com os dias e a cor pela situação", async () => {
  render(<Documentos usuario={usuario} />);
  await screen.findByRole("link", { name: "Lotufo" });
  const l = within(linhaDe("Lotufo"));
  l.getByText("própria");
  // cinco chips (Federal, FGTS, CNDT, Estadual, Municipal); falência nao exigida fica fora
  const chip = (rotulo: string) => l.getByText(rotulo, { selector: ".doc-chip__rotulo" }).closest(".doc-chip")!;
  expect(chip("FGTS").textContent).toContain("4 d");
  expect(chip("FGTS").textContent).toContain("27/09/2026");
  expect(chip("FGTS").className).toContain("doc-chip--breve");
  expect(chip("Federal").textContent).toContain("120 d");
  expect(chip("Federal").className).toContain("doc-chip--feito");
  expect(chip("Municipal").textContent).toContain("vencida");
  expect(chip("Municipal").className).toContain("doc-chip--critico");
  expect(chip("CNDT").className).toContain("doc-chip--neutro");     // nao cadastrada nesta empresa
  expect(l.queryByText("Falência")).toBeNull();
  // o chip abre o PDF; a empresa abre a pagina dela
  expect(chip("FGTS").getAttribute("href")).toBe("/api/certidoes/7/arquivo");
  expect(screen.getByRole("link", { name: "Lotufo" }).getAttribute("href")).toBe("/documentos/1");
});

test("vence hoje e vence em até 7 dias são âmbar ou vermelho pelas regras da legenda", () => {
  const l = (dias: number | null, situacao: "ok" | "vencida" | "faltando" = "ok") => ({
    tipo_id: 1, chave: "fgts", tipo: "FGTS", link_emissao: null, exigida: true, situacao, dias,
    certidao: { id: 1, emissao: "2026-08-01", validade: "2026-09-27", natureza: "negativa" } });
  expect(chipCertidao(l(0), "x")).toMatchObject({ cor: "critico", valor: "hoje" });
  expect(chipCertidao(l(7), "x")).toMatchObject({ cor: "breve", valor: "7 d" });
  expect(chipCertidao(l(8), "x")).toMatchObject({ cor: "feito", valor: "8 d" });
  expect(chipCertidao(l(null, "faltando"), "x")).toMatchObject({ cor: "critico", valor: "sem registro" });
});

test("aba Regularidade: só quem tem folha, seis meses com o estado de cada um", async () => {
  render(<Documentos usuario={usuario} busca={{ aba: "regularidade" }} />);
  await screen.findByRole("link", { name: "Lotufo" });
  expect(screen.queryByRole("link", { name: "Beta Ltda" })).toBeNull();
  const l = within(linhaDe("Lotufo"));
  expect(l.getAllByRole("img").map(i => i.textContent)).toEqual([
    "03/2026: faltando", "04/2026: faltando", "05/2026: faltando", "06/2026: anexada", "07/2026: faltando", "08/2026: faltando",
  ]);
  l.getByText("última: junho, 08/07");
  screen.getByText(/Não exigida: .*Beta Ltda/);
  screen.getByText("Agosto esperada a partir de 10/09.");
  expect(l.getAllByRole("img")[3].closest("a")!.getAttribute("href")).toBe("/api/documentos/regularidades/9/arquivo");
});

test("a competência esperada só vale a partir do dia 10 do mês seguinte (antes, aguardando o DP)", () => {
  const meses = competenciasRegularidade("2026-11-07");
  expect(meses.map(m => m.competencia)).toEqual(["2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]);
  expect(meses.map(m => m.aguardando)).toEqual([false, false, false, false, false, true]);
  expect(competenciasRegularidade("2026-11-10")[5].aguardando).toBe(false);
  expect(competenciasRegularidade("2027-01-05")[5]).toEqual({ competencia: "2026-12", aguardando: true });
});

test("aba Garantias: por órgão, com a contagem, e os cinco chips por obra", async () => {
  render(<Documentos usuario={usuario} busca={{ aba: "garantias" }} />);
  await screen.findByText("Obra Alfa");
  expect(screen.getAllByRole("heading", { level: 2 }).map(h => h.textContent)).toEqual([
    "SINFRA · 2 obras", "MTPAR · 1 obra", "Prefeituras · 1 obra",
  ]);
  const alfa = within(screen.getByText("Obra Alfa").closest("li")!);
  alfa.getByText("AP-9"); alfa.getByText("05/10/2026"); alfa.getByText("sim"); alfa.getByText("registrada"); alfa.getByText("registrado");
  const delta = within(screen.getByText("Obra Delta").closest("li")!);
  expect(delta.getAllByText("sem registro")).toHaveLength(2);     // apólice e ART
  expect(delta.getByText("não, até 31/03/2027").closest(".doc-chip")!.className).toContain("doc-chip--breve");
  expect(delta.getByText("01/09/2026").closest(".doc-chip")!.className).toContain("doc-chip--critico");
  expect(within(screen.getByText("Obra Beta").closest("li")!).getAllByText("sem registro").length).toBe(5);   // sem garantia: tudo sem registro
});

test("grupo grande mostra as primeiras obras e '+N obras'", async () => {
  const mais = Array.from({ length: 11 }, (_, i) => ({ contrato_id: 100 + i, obra: `Obra X${i}`, entidade_id: 1, garantia: null,
    orgao: "SES", art: null, cno: null, cobre_execucao: { cobre: null, ate: null } }));
  const { api } = await import("./api");
  vi.mocked(api).mockImplementationOnce(async () => ({ ...(await import("./documentosTeste")).PAINEL, contratos: mais }));
  render(<Documentos usuario={usuario} busca={{ aba: "garantias" }} />);
  await screen.findByText("Obra X0");
  expect(screen.queryByText("Obra X8")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "+3 obras" }));
  screen.getByText("Obra X10");
});

test("garantia sem fim de execução cadastrado: 'Cobre a execução' fica neutro, não vermelho", async () => {
  const { api } = await import("./api");
  const obra = { contrato_id: 200, obra: "Obra Sem Fim", entidade_id: 1, orgao: "SES", art: "A", cno: "1",
    garantia: { apolice: "AP-1", vigencia_fim: "2027-12-31", dias: 400, origem: "contrato" as const, situacao: "ok" as const },
    cobre_execucao: { cobre: null, ate: null } };
  vi.mocked(api).mockImplementationOnce(async () => ({ ...(await import("./documentosTeste")).PAINEL, contratos: [obra] }));
  render(<Documentos usuario={usuario} busca={{ aba: "garantias" }} />);
  await screen.findByText("Obra Sem Fim");
  const chip = within(screen.getByText("Obra Sem Fim").closest("li")!).getByText("—").closest(".doc-chip")!;
  expect(chip.className).toContain("doc-chip--neutro");
});

test("a legenda muda com a aba", async () => {
  render(<Documentos usuario={usuario} busca={{ aba: "garantias" }} />);
  await screen.findByText("Obra Alfa");
  screen.getByText("não cobre");
  screen.getByText("vencida ou sem registro");
  expect(screen.queryByText("aguardando o DP")).toBeNull();
});

test("a aba escolhida vai para a URL", async () => {
  render(<Documentos usuario={usuario} />);
  await screen.findByRole("link", { name: "Lotufo" });
  fireEvent.click(screen.getByRole("tab", { name: /Garantias/ }));
  expect(window.location.search).toBe("?aba=garantias");
});

test("diretoria vê as abas e o ZIP, mas não o Anexar PDF", async () => {
  render(<Documentos usuario={{ ...usuario, perfil: "diretoria" }} />);
  await screen.findByRole("link", { name: "Lotufo" });
  expect(screen.queryByRole("button", { name: /Anexar PDF/ })).toBeNull();
  expect(screen.queryByLabelText(/Escolher PDFs/i)).toBeNull();
  screen.getByRole("button", { name: "ZIP das certidões vigentes de Lotufo" });
});

const pdf = (nome: string) => new File(["%PDF"], nome, { type: "application/pdf" });

test("Anexar PDF: datas lidas implausíveis abrem a digitação já preenchida (gate Sol S6)", async () => {
  vi.mocked(apiForm).mockResolvedValueOnce({
    ok: false, motivo: "datas-implausiveis", digitavel: true,
    mensagem: "As datas lidas (emissão 24/06/2026, validade 21/12/2028) não batem com o prazo normal desta certidão: confira no documento e digite",
    lidos: { entidade_id: 1, tipo: "trabalhista", emissao: "2026-06-24", validade: "2028-12-21", natureza: "negativa" },
  });
  render(<Documentos usuario={usuario} />);
  await screen.findByRole("link", { name: "Lotufo" });
  fireEvent.change(screen.getByLabelText("Escolher PDFs para anexar"), { target: { files: [pdf("cndt.pdf")] } });
  await screen.findByText(/não batem com o prazo normal/);
  expect(vi.mocked(apiForm).mock.calls.at(-1)![0]).toBe("/api/documentos/anexar/ler");
  expect((screen.getByLabelText("Empresa") as HTMLSelectElement).value).toBe("1");
  expect((screen.getByLabelText("Tipo") as HTMLSelectElement).value).toBe("trabalhista");
  expect((screen.getByLabelText("Emissão") as HTMLInputElement).value).toBe("2026-06-24");
  expect((screen.getByLabelText(/^Validade/) as HTMLInputElement).value).toBe("2028-12-21");
});

test("Anexar PDF: certidão lida vai para conferir e descarta", async () => {
  vi.mocked(apiForm).mockResolvedValueOnce({
    ok: true, leitura: { tipo: "fgts", tipo_nome: "FGTS", natureza: "negativa", entidade_id: 1, entidade: "Lotufo",
      emissao: "2026-09-20", validade: "2026-10-19", numero: "123", validade_calculada: false },
  });
  render(<Documentos usuario={usuario} />);
  await screen.findByRole("link", { name: "Lotufo" });
  fireEvent.change(screen.getByLabelText("Escolher PDFs para anexar"), { target: { files: [pdf("crf.pdf")] } });
  await screen.findByText(/válida até 19\/10\/2026/);
  fireEvent.click(screen.getByRole("button", { name: "Descartar" }));
  expect(screen.queryByText("crf.pdf")).toBeNull();
});

test("Anexar PDF: a folha do DP aparece como regularidade e grava pelo endpoint único", async () => {
  vi.mocked(apiForm)
    .mockResolvedValueOnce({ ok: true, documento: "regularidade",
      leitura: { documento: "regularidade", competencia: "2026-08", entidade_id: 1, entidade: "Lotufo" } } as never)
    .mockResolvedValueOnce({ documento: "regularidade", entidade: "Lotufo", competencia: "2026-08" } as never);
  render(<Documentos usuario={usuario} />);
  await screen.findByRole("link", { name: "Lotufo" });
  fireEvent.change(screen.getByLabelText("Escolher PDFs para anexar"), { target: { files: [pdf("folha.pdf")] } });
  await screen.findByText(/regularidade mensal de 08\/2026/);
  fireEvent.click(screen.getByRole("button", { name: /Gravar regularidade/ }));
  await screen.findByText(/gravada: Lotufo · regularidade de 08\/2026/);
  expect(vi.mocked(apiForm).mock.calls.at(-1)![0]).toBe("/api/documentos/anexar");
});

test("Anexar PDF: folha de empresa desconhecida cai na fila humana como recusada", async () => {
  vi.mocked(apiForm).mockResolvedValueOnce({ ok: false, motivo: "regularidade-sem-empresa", digitavel: false,
    mensagem: "Folha do DP de 08/2026: empresa não identificada no cadastro." });
  render(<Documentos usuario={usuario} />);
  await screen.findByRole("link", { name: "Lotufo" });
  fireEvent.change(screen.getByLabelText("Escolher PDFs para anexar"), { target: { files: [pdf("folha.pdf")] } });
  expect((await screen.findAllByText(/empresa não identificada/)).length).toBeGreaterThan(0);
  screen.getByRole("button", { name: "Descartar" });
});

test("o ZIP das vigentes fica na linha da empresa e diz o que ela respondeu", async () => {
  const buscar = vi.fn(async () => new Response(JSON.stringify({ detail: "nenhuma certidão vigente em 2026-09-23" }), { status: 422 }));
  vi.stubGlobal("fetch", buscar);
  render(<Documentos usuario={usuario} />);
  await screen.findByRole("link", { name: "Lotufo" });
  fireEvent.click(screen.getByRole("button", { name: "ZIP das certidões vigentes de Lotufo" }));
  expect((screen.getByLabelText("Certidões vigentes em") as HTMLInputElement).value).toBe("2026-09-23");
  fireEvent.click(screen.getByRole("button", { name: "Baixar ZIP" }));
  await screen.findByText(/Lotufo: nenhuma certidão vigente em 2026-09-23/);
  expect(buscar).toHaveBeenCalledTimes(1);
  expect(buscar.mock.calls[0]).toEqual(["/api/documentos/zip?entidade_id=1&data=2026-09-23", { credentials: "same-origin" }]);
});

test("competência pelo nome do arquivo do DP", () => {
  expect(competenciaDoNome("042026 - LOTUFO ENGENHARIA.pdf")).toBe("2026-04");
  expect(competenciaDoNome("Documentos Lotufo.pdf")).toBe("");
});

test("link salvo da tela antiga (?empresa=N) abre a página da empresa, trocando o endereço", async () => {
  window.history.replaceState(null, "", "/documentos?empresa=3#emp-3");
  render(<Documentos usuario={usuario} busca={{ empresa: "3" }} />);
  await waitFor(() => expect(window.location.pathname).toBe("/documentos/3"));
  expect(window.location.search).toBe("");
  expect(window.location.hash).toBe("");
});
