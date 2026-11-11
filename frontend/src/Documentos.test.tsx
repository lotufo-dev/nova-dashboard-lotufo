import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { api, apiForm } from "./api";
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

test("três abas com contador: certidões a renovar, regularidade faltando e garantias a conferir", async () => {
  render(<Documentos usuario={usuario} />);
  await screen.findByRole("link", { name: "Lotufo" });
  const abas = screen.getAllByRole("tab").map(t => t.textContent);
  expect(abas).toEqual(["Certidões · 2 a renovar", "Regularidade mensal · 1 faltando", "Garantias · 1 a conferir"]);
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

test("empresa sem certidão exigida sai da aba Certidões e continua no Anexar PDF e na aba Regularidade (#651)", async () => {
  vi.mocked(apiForm).mockResolvedValueOnce({
    ok: false, motivo: "datas-implausiveis", digitavel: true, mensagem: "Confira as datas no documento e digite",
    lidos: { entidade_id: 1, tipo: "trabalhista", emissao: "2026-06-24", validade: "2028-12-21", natureza: "negativa" },
  });
  const { rerender } = render(<Documentos usuario={usuario} />);
  await screen.findByRole("link", { name: "Lotufo" });
  expect([...screen.getByRole("list", { name: "Certidões por empresa" }).querySelectorAll(".doc-linha__nome a")].map(a => a.textContent))
    .toEqual(["Beta Ltda", "Consórcio Alfa", "Lotufo"]);
  fireEvent.change(screen.getByLabelText("Escolher PDFs para anexar"), { target: { files: [new File(["%PDF"], "cndt.pdf", { type: "application/pdf" })] } });
  await screen.findByText(/Confira as datas/);
  within(screen.getByLabelText("Empresa")).getByRole("option", { name: /Consórcio Sem Certidão/ });
  rerender(<Documentos usuario={usuario} busca={{ aba: "regularidade" }} />);
  screen.getByText(/Não exigida: .*Consórcio Sem Certidão/);
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
  // #651: antes do primeiro PDF da empresa (06/2026) o mes nao e' cobrado: "—", sem cor
  const chips = l.getAllByRole("img");
  expect(chips.map(i => i.getAttribute("aria-label") ?? i.textContent)).toEqual([
    "03/2026: sem registro", "04/2026: sem registro", "05/2026: sem registro", "06/2026: anexada", "07/2026: faltando", "08/2026: sem registro",
  ]);
  // #699: so' a competencia esperada (07/2026) aparece "faltando"; a outra sem PDF fica "—"
  expect(chips[5].textContent).toBe("—");
  expect(chips[0].textContent).toBe("—");
  expect(chips[0].closest(".doc-chip")!.className).toContain("doc-chip--neutro");
  expect(chips[4].closest(".doc-chip")!.className).toContain("doc-chip--breve");
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

test("aba Garantias: por órgão, com a contagem, e os quatro chips por obra (sem ART)", async () => {
  render(<Documentos usuario={usuario} busca={{ aba: "garantias" }} />);
  await screen.findByText("Obra Alfa");
  expect(screen.getAllByRole("heading", { level: 2 }).map(h => h.textContent)).toEqual([
    "SINFRA · 2 obras", "MTPAR · 1 obra", "Prefeituras · 1 obra",
  ]);
  const alfa = within(screen.getByText("Obra Alfa").closest("li")!);
  alfa.getByText("AP-9"); alfa.getByText("05/10/2026"); alfa.getByText("sim"); alfa.getByText("registrado");
  expect(alfa.queryByText("registrada")).toBeNull();
  expect(screen.queryByText("ART")).toBeNull();
  expect(screen.getAllByText("CNO", { selector: ".doc-linha--cabeca span" }).length).toBeGreaterThan(0);
  const delta = within(screen.getByText("Obra Delta").closest("li")!);
  expect(delta.getAllByText("sem registro")).toHaveLength(1);     // apólice
  expect(delta.getByText("não, até 31/03/2027").closest(".doc-chip")!.className).toContain("doc-chip--breve");
  // #651: o ultimo documento venceu: diz o que se sabe, sem vermelho
  expect(delta.getByText("Último registro: 01/09/2026").closest(".doc-chip")!.className).toContain("doc-chip--neutro");
  expect(within(screen.getByText("Obra Beta").closest("li")!).getAllByText("sem registro").length).toBe(4);   // sem garantia: tudo sem registro
});

test("contrato de contratante privado aparece no grupo Privados (#651)", async () => {
  const { api } = await import("./api");
  const base = (await import("./documentosTeste")).PAINEL;
  vi.mocked(api).mockImplementationOnce(async () => ({ ...base,
    contratos: base.contratos.map(o => ({ ...o, tipo_contratante: o.contrato_id === 7 ? "PRIVADO" : "PÚBLICO" })) }));
  render(<Documentos usuario={usuario} busca={{ aba: "garantias" }} />);
  await screen.findByText("Obra Gama");
  expect(screen.getAllByRole("heading", { level: 2 }).map(h => h.textContent)).toEqual([
    "SINFRA · 2 obras", "MTPAR · 1 obra", "Privados · 1 obra",
  ]);
  within(screen.getByRole("region", { name: "Garantias de Privados" })).getByText("Obra Gama");
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
  const legenda = within(screen.getByRole("list", { name: "Legenda das cores" }));
  legenda.getByText("sem registro");
  expect(legenda.queryByText(/vencida/)).toBeNull();
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

/* ---------------------------------------------------------------- Renovar agora (#658) */

const bloco = () => within(screen.getByRole("region", { name: "Renovar agora" }));

test("Renovar agora: uma linha por certidão, com a validade, Emitir e Anexar", async () => {
  render(<Documentos usuario={usuario} />);
  await screen.findByRole("link", { name: "Lotufo" });
  const linhas = bloco().getAllByRole("listitem");
  expect(linhas.map(x => x.querySelector(".doc-renovar__certidao")!.textContent)).toEqual(["Municipal", "FGTS"]);
  // a vencida em vermelho, a que vence antes do proximo protocolo em ambar
  expect(linhas[0].querySelector(".doc-chip")!.className).toContain("doc-chip--critico");
  expect(linhas[0].textContent).toContain("20/09/2026");
  expect(linhas[1].querySelector(".doc-chip")!.className).toContain("doc-chip--breve");
  expect(linhas[1].textContent).toContain("27/09/2026");
  expect(linhas[1].querySelector(".doc-linha__nome")!.textContent).toBe("Lotufo");
  expect(within(linhas[1]).getByRole("link", { name: /Emitir FGTS de Lotufo/ }).getAttribute("href")).toBe("https://emissao.exemplo.com.br/fgts");
  within(linhas[1]).getByRole("button", { name: "Anexar FGTS de Lotufo" });
  // o bloco e' da aba Certidoes
  cleanup();
  render(<Documentos usuario={usuario} busca={{ aba: "garantias" }} />);
  await screen.findByText("Obra Alfa");
  expect(screen.queryByRole("region", { name: "Renovar agora" })).toBeNull();
});

test("Renovar agora: diretoria vê as linhas, sem Emitir nem Anexar", async () => {
  render(<Documentos usuario={{ ...usuario, perfil: "diretoria" }} />);
  await screen.findByRole("link", { name: "Lotufo" });
  expect(bloco().getAllByRole("listitem")).toHaveLength(2);
  expect(bloco().queryByRole("link", { name: /Emitir/ })).toBeNull();
  expect(bloco().queryByRole("button", { name: /Anexar/ })).toBeNull();
});

test("sem nada a renovar o bloco não aparece, o contador some e o chip que vence depois do protocolo não fica âmbar", async () => {
  const { PAINEL } = await import("./documentosTeste");
  const lotufo = PAINEL.empresas.find(x => x.entidade_id === 1)!;
  vi.mocked(api).mockResolvedValueOnce({
    ...PAINEL, renovar_agora: [],
    empresas: [{ ...lotufo, certidoes: lotufo.certidoes.filter(x => x.chave === "fgts").map(x => ({ ...x, renovar: false, proximo_protocolo: null })) }],
  });
  render(<Documentos usuario={usuario} />);
  await screen.findByRole("link", { name: "Lotufo" });
  expect(screen.queryByRole("region", { name: "Renovar agora" })).toBeNull();
  expect(screen.getByRole("tab", { name: /Certidões/ }).textContent).toBe("Certidões");
  const chip = within(linhaDe("Lotufo")).getByText("FGTS", { selector: ".doc-chip__rotulo" }).closest(".doc-chip")!;
  expect(chip.textContent).toContain("4 d");
  expect(chip.className).toContain("doc-chip--feito");
});

test("a legenda das certidões fala do próximo protocolo, não dos 7 dias", async () => {
  render(<Documentos usuario={usuario} />);
  await screen.findByRole("link", { name: "Lotufo" });
  const legenda = within(screen.getByRole("list", { name: "Legenda das cores" }));
  legenda.getByText("vence antes do próximo protocolo");
  expect(legenda.queryByText(/7 dias/)).toBeNull();
});

test("aba Garantias: os quatro chips em quatro colunas, no cabeçalho e nas linhas", async () => {
  render(<Documentos usuario={usuario} busca={{ aba: "garantias" }} />);
  await screen.findByText("Obra Alfa");
  const grupo = screen.getByRole("region", { name: "Garantias de SINFRA" });
  const grades = [...grupo.querySelectorAll(".doc-chips")];
  expect(grades).toHaveLength(3);                                   // o cabecalho e as duas obras
  for (const g of grades) { expect(g.className).toContain("doc-chips--4"); expect(g.children).toHaveLength(4); }
  const css = readFileSync(join(process.cwd(), "src", "documentos.css"), "utf8");
  expect(css).toContain(".doc-chips--4 { grid-template-columns: repeat(4, minmax(0, 1fr)); }");
});
