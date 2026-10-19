import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { apiForm } from "./api";
import DocumentosEmpresa from "./DocumentosEmpresa";

vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()),
  api: vi.fn(async (caminho: string) => {
    if (caminho === "/api/documentos") return (await import("./documentosTeste")).PAINEL;
    return {};
  }),
  apiForm: vi.fn(),
}));

afterEach(cleanup);

const usuario = { id: 1, nome: "U", email: "u@lotufo.com", perfil: "engenharia" };
const diretoria = { ...usuario, perfil: "diretoria" };

const linhaDa = (nome: RegExp) => screen.getAllByRole("row").find(r => nome.test(r.querySelector("td")?.textContent ?? ""))!;

test("cabeçalho com caminho, nome, CNPJ, situação e as obras que exigem a empresa", async () => {
  render(<DocumentosEmpresa usuario={usuario} id={1} />);
  await screen.findByRole("heading", { level: 1, name: "Lotufo" });
  const caminho = screen.getByRole("navigation", { name: "Você está em" });
  expect(within(caminho).getByRole("link", { name: "Documentos" }).getAttribute("href")).toBe("/documentos");
  expect(within(caminho).getByText("Lotufo").getAttribute("title")).toBe("Lotufo");
  screen.getByText("31.200.101/0001-30");
  screen.getByText("1 vencida · 1 vence em 4 dias · regularidade atrasada · garantia vence em 12 dias · ART não anexada");
  expect(screen.getByRole("link", { name: "Obra Alfa" }).getAttribute("href")).toBe("/obras/5/documentos");
  screen.getByText(/também consorciada em/);
  expect(screen.getByRole("link", { name: "Consórcio Alfa" }).getAttribute("href")).toBe("/documentos/2");
  expect(screen.getByRole("link", { name: /Baixar o ZIP das certidões vigentes de Lotufo/ }).getAttribute("href"))
    .toBe("/api/documentos/zip?entidade_id=1&data=2026-09-23");
});

test("as abas têm endereço próprio e mostram a contagem de pendências", async () => {
  render(<DocumentosEmpresa usuario={usuario} id={1} />);
  await screen.findByRole("heading", { level: 1, name: "Lotufo" });
  const abas = screen.getByRole("navigation", { name: "Documentos da empresa" });
  const certidoes = within(abas).getByRole("link", { name: /^Certidões/ });
  expect(certidoes.getAttribute("href")).toBe("/documentos/1");
  expect(certidoes.getAttribute("aria-current")).toBe("page");
  expect(within(certidoes).getByLabelText("2 com pendência")).toBeTruthy();          // municipal vencida e FGTS vencendo
  const reg = within(abas).getByRole("link", { name: /^Regularidade do mês/ });
  expect(reg.getAttribute("href")).toBe("/documentos/1/regularidade");
  within(reg).getByLabelText("1 com pendência");
  const gar = within(abas).getByRole("link", { name: /^Garantia e ART por obra/ });
  expect(gar.getAttribute("href")).toBe("/documentos/1/garantia");
  within(gar).getByLabelText("2 com pendência");                                       // garantia vencendo e ART faltando
});

test("tabela de certidões: Emitir em toda exigida, o primário só na pendência mais urgente, Ver PDF", async () => {
  render(<DocumentosEmpresa usuario={usuario} id={1} />);
  await screen.findByRole("heading", { level: 1, name: "Lotufo" });
  const linhas = screen.getAllByRole("row").slice(1);
  expect(linhas.map(l => l.querySelector("td")!.textContent)).toEqual([
    "Federal (RFB/PGFN)", "Municipal (Cuiabá)", "FGTS (CRF)", "Falência (TJMT)",
  ]);
  // Emitir: toda certidao exigida com link do orgao (a federal, que esta em dia, tambem); a nao exigida, nao
  const emitir = (r: HTMLElement) => within(r).queryByRole("link", { name: /^Emitir/ });
  expect(emitir(linhaDa(/Federal/))!.getAttribute("href")).toBe("https://emissao.exemplo.com.br/federal");
  expect(emitir(linhaDa(/FGTS/))).not.toBeNull();
  expect(emitir(linhaDa(/Falência/))).toBeNull();
  // o unico botao principal: a municipal, vencida (mais urgente que o FGTS, que vence em 4 dias)
  const principais = screen.getAllByRole("link").filter(a => a.classList.contains("btn--primario"));
  expect(principais).toHaveLength(1);
  expect(emitir(linhaDa(/Municipal/))!.classList.contains("btn--primario")).toBe(true);
  // datas e situacao
  const municipal = linhaDa(/Municipal/);
  within(municipal).getByText("20/08/2026");
  within(municipal).getByText("20/09/2026");
  within(municipal).getByText("vencida");
  within(linhaDa(/FGTS/)).getByText("vence em 4 dias");
  within(linhaDa(/FGTS/)).getByText("digitada");
  within(linhaDa(/Falência/)).getByText("não exigida");
  // Ver PDF: o arquivo da certidao; sem certidao, desligado
  expect(within(municipal).getByRole("link", { name: /Ver PDF/ }).getAttribute("href")).toBe("/api/certidoes/8/arquivo");
  expect((within(linhaDa(/Falência/)).getByRole("button", { name: /Ver PDF/ }) as HTMLButtonElement).disabled).toBe(true);
});

test("área tracejada embaixo da tabela; Anexar abre a escolha de arquivos e a leitura de outro tipo vem com aviso", async () => {
  const clique = vi.spyOn(HTMLInputElement.prototype, "click").mockImplementation(() => {});
  vi.mocked(apiForm).mockResolvedValueOnce({
    ok: true, leitura: { tipo: "federal", tipo_nome: "Federal", natureza: "negativa", entidade_id: 3, entidade: "Beta Ltda",
      emissao: "2026-09-20", validade: "2027-03-19", numero: null, validade_calculada: false },
  });
  render(<DocumentosEmpresa usuario={usuario} id={1} />);
  await screen.findByText(/Arraste os PDFs das certidões aqui/);
  fireEvent.click(within(linhaDa(/FGTS/)).getByRole("button", { name: /Anexar certidão FGTS/ }));
  expect(clique).toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText(/Escolher PDFs/i), { target: { files: [new File(["%PDF"], "x.pdf", { type: "application/pdf" })] } });
  await screen.findByText(/Beta Ltda · Federal/);
  screen.getByText(/Este PDF é de Beta Ltda, não de Lotufo/);
  screen.getByText(/Você clicou em Anexar na certidão FGTS, mas o PDF é Federal/);
  screen.getByRole("button", { name: /Gravar certidão/ });
  clique.mockRestore();
});

test("a digitação abre com a empresa da página escolhida", async () => {
  vi.mocked(apiForm).mockResolvedValueOnce({ ok: false, motivo: "sem-texto", digitavel: true, mensagem: "PDF sem texto: digite os dados" });
  render(<DocumentosEmpresa usuario={usuario} id={1} />);
  await screen.findByText(/Arraste os PDFs das certidões aqui/);
  fireEvent.change(screen.getByLabelText(/Escolher PDFs/i), { target: { files: [new File(["%PDF"], "x.pdf", { type: "application/pdf" })] } });
  await screen.findByText("PDF sem texto: digite os dados");
  expect((screen.getByLabelText("Empresa") as HTMLSelectElement).value).toBe("1");
});

test("diretoria só consulta: sem Anexar, sem área de arrastar e sem gravar a regularidade", async () => {
  render(<DocumentosEmpresa usuario={diretoria} id={1} />);
  await screen.findByRole("heading", { level: 1, name: "Lotufo" });
  expect(screen.queryByRole("button", { name: /^Anexar/ })).toBeNull();
  expect(screen.queryByText(/Arraste os PDFs das certidões/)).toBeNull();
  expect(screen.queryByLabelText(/Escolher PDFs/i)).toBeNull();
  screen.getAllByRole("link", { name: /^Emitir/ });
  cleanup();
  render(<DocumentosEmpresa usuario={diretoria} id={1} aba="regularidade" />);
  await screen.findByText("Competência esperada");
  expect(screen.queryByRole("button", { name: /Gravar regularidade/ })).toBeNull();
  expect(screen.queryByLabelText(/da regularidade de Lotufo/)).toBeNull();
  screen.getByRole("link", { name: "Ver PDF da regularidade de 06/2026" });
});

test("regularidade: situação, competência esperada, anexadas e gravar com a competência como AAAA-MM", async () => {
  vi.mocked(apiForm).mockResolvedValueOnce({});
  render(<DocumentosEmpresa usuario={usuario} id={1} aba="regularidade" />);
  await screen.findByText("Competência esperada");
  screen.getByText("atrasada");
  expect(screen.getByRole("link", { name: "Ver PDF da regularidade de 06/2026" }).getAttribute("href")).toBe("/api/documentos/regularidades/9/arquivo");
  const campo = screen.getByLabelText("Competência") as HTMLInputElement;
  expect(campo.value).toBe("07/2026");              // a esperada vem da API como 2026-07
  const gravar = screen.getByRole("button", { name: /Gravar regularidade/ }) as HTMLButtonElement;
  expect(gravar.disabled).toBe(true);
  fireEvent.change(screen.getByLabelText(/da regularidade de Lotufo/), { target: { files: [new File(["%PDF"], "x.pdf", { type: "application/pdf" })] } });
  fireEvent.change(campo, { target: { value: "062026" } });
  expect(campo.value).toBe("06/2026");
  fireEvent.click(gravar);
  await waitFor(() => expect(apiForm).toHaveBeenCalled());
  const fd = vi.mocked(apiForm).mock.calls.at(-1)![1] as FormData;
  expect(fd.get("competencia")).toBe("2026-06");
  expect(fd.get("entidade_id")).toBe("1");
  await screen.findByText("Regularidade de 06/2026 gravada para Lotufo.");
});

test("o nome do arquivo do DP preenche a competência", async () => {
  render(<DocumentosEmpresa usuario={usuario} id={1} aba="regularidade" />);
  await screen.findByText("Competência esperada");
  fireEvent.change(screen.getByLabelText(/da regularidade de Lotufo/), { target: { files: [new File(["%PDF"], "052026 - LOTUFO.pdf", { type: "application/pdf" })] } });
  expect((screen.getByLabelText("Competência") as HTMLInputElement).value).toBe("05/2026");
});

test("o consórcio não entrega regularidade: manda para as consorciadas", async () => {
  render(<DocumentosEmpresa usuario={usuario} id={2} aba="regularidade" />);
  await screen.findByText("O consórcio não entrega regularidade mensal");
  const painel = within(document.querySelector<HTMLElement>(".doc-painel")!);
  expect(painel.getByRole("link", { name: "Lotufo" }).getAttribute("href")).toBe("/documentos/1/regularidade");
  expect(painel.getByRole("link", { name: "Beta Ltda" }).getAttribute("href")).toBe("/documentos/3/regularidade");
});

test("garantia e ART só das obras contratadas pela empresa, com a situação de cada uma (issue #65)", async () => {
  render(<DocumentosEmpresa usuario={usuario} id={1} aba="garantia" />);
  const alfa = (await screen.findByRole("rowheader", { name: "Obra Alfa" })).closest("tr")!;
  expect(alfa.textContent).toContain("vence em 12 dias");
  expect(alfa.textContent).toContain("até 05/10/2026 (endosso) · apólice AP-9");
  expect(alfa.textContent).toContain("Anexada");
  expect(alfa.textContent).toContain("nº 1234567");
  expect(within(alfa).getByRole("link", { name: "Obra Alfa" }).getAttribute("href")).toBe("/obras/5/documentos");
  const beta = screen.getByRole("rowheader", { name: "Obra Beta" }).closest("tr")!;
  expect(beta.textContent).toContain("sem vigência no cadastro");
  expect(beta.textContent).toContain("não anexada");
  expect(screen.queryByRole("rowheader", { name: "Obra Gama" })).toBeNull();      // e' do consorcio
});

test("empresa sem obra própria aponta o consórcio, onde ficam a garantia e a ART", async () => {
  render(<DocumentosEmpresa usuario={usuario} id={3} aba="garantia" />);
  await screen.findByText("Nenhuma obra contratada direto por esta empresa");
  expect(within(document.querySelector<HTMLElement>(".doc-painel")!).getByRole("link", { name: "Consórcio Alfa" })
    .getAttribute("href")).toBe("/documentos/2/garantia");
});

test("consórcio: as consorciadas com a situação de cada uma; a página diz quem compõe o consórcio", async () => {
  render(<DocumentosEmpresa usuario={usuario} id={2} />);
  await screen.findByRole("heading", { level: 1, name: "Consórcio Alfa" });
  screen.getByText(/Consórcio · consorciadas:/);
  const lista = screen.getByRole("heading", { name: "Consorciadas" }).parentElement!;
  expect(within(lista).getByRole("link", { name: "Lotufo" }).getAttribute("href")).toBe("/documentos/1");
  within(lista).getByText("1 vencida · 1 vence em 4 dias · regularidade atrasada · garantia vence em 12 dias · ART não anexada");
  within(lista).getByText("Em dia");
});

test("empresa que não existe no painel diz isso e volta para a lista", async () => {
  render(<DocumentosEmpresa usuario={usuario} id={99} />);
  await screen.findByText("Essa empresa não tem documento exigido.");
  expect(screen.getByRole("link", { name: "Ver todas as empresas" }).getAttribute("href")).toBe("/documentos");
});

test("obra de empresa sem certidão exigida continua visível na aba Garantia e ART (revisor, rodada 1)", async () => {
  render(<DocumentosEmpresa usuario={usuario} id={4} aba="garantia" />);
  const delta = (await screen.findByRole("rowheader", { name: "Obra Delta" })).closest("tr")!;
  expect(delta.textContent).toContain("vencida");
  expect(delta.textContent).toContain("venceu em 01/09/2026");
});
