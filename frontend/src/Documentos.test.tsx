import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { apiForm } from "./api";
import Documentos from "./Documentos";
import { competenciaDoNome } from "./documentosDados";

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

const nomes = () => screen.getAllByRole("heading", { level: 2 }).map(h => h.textContent).filter(t => !/Anexar/.test(t ?? ""));

test("um cartão por empresa, com a pendência primeiro, a situação geral e a próxima a vencer", async () => {
  render(<Documentos usuario={usuario} />);
  await screen.findByRole("link", { name: "Lotufo" });
  // o servidor mandou a empresa em dia primeiro; a que tem pendência sobe
  expect(nomes()).toEqual(["Lotufo", "Consórcio Sem Certidão", "Beta Ltda", "Consórcio Alfa"]);
  const lotufo = screen.getByRole("link", { name: "Lotufo" }).closest("article")!;
  const c = within(lotufo);
  c.getByText("1 vencida · 1 vence em 4 dias · regularidade atrasada · garantia vence em 12 dias");
  c.getByText(/Próxima a vencer:/);
  expect(lotufo.textContent).toContain("FGTS em 27/09/2026");
  c.getByText("31.200.101/0001-30");
  c.getByText(/Regularidade do mês \(DP\): atrasada · esperada 07\/2026/);
  c.getByText("Exigida em 2 obras: Obra Alfa, Obra Beta");
  // garantia que pede algo da empresa entram no cartao
  c.getByText("Garantia de Obra Alfa: vence em 12 dias");
  expect(lotufo.textContent).not.toContain("ART");
  // um ponto por certidao, cada um com a situacao para o leitor de tela
  expect(within(c.getByRole("list", { name: "Certidões" })).getAllByRole("listitem")).toHaveLength(4);
  c.getByText(": vencida");
  // o cartao leva a pagina da empresa, que tem endereco proprio
  expect(screen.getByRole("link", { name: "Lotufo" }).getAttribute("href")).toBe("/documentos/1");
  // o consorcio diz quem o compoe
  within(screen.getByRole("link", { name: "Consórcio Alfa" }).closest("article")!).getByText("Consorciadas: Lotufo, Beta Ltda");
});

test("'Só as com pendência' filtra pela URL e diz o recorte", async () => {
  const { unmount } = render(<Documentos usuario={usuario} />);
  await screen.findByRole("link", { name: "Lotufo" });
  fireEvent.click(screen.getByRole("checkbox", { name: "Só as com pendência" }));
  expect(window.location.search).toBe("?pendentes=1");
  unmount();
  render(<Documentos usuario={usuario} busca={{ pendentes: "1" }} />);
  await screen.findByRole("link", { name: "Lotufo" });
  expect(screen.queryByRole("link", { name: "Beta Ltda" })).toBeNull();
  screen.getByRole("link", { name: "Consórcio Sem Certidão" });
  screen.getByText(/Mostrando as 2 com pendência, de 4 empresas/);
  expect((screen.getByRole("checkbox", { name: "Só as com pendência" }) as HTMLInputElement).checked).toBe(true);
});

test("o Copiar entrega o CNPJ e anuncia", async () => {
  const gravar = vi.fn(async () => {});
  vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText: gravar } });
  render(<Documentos usuario={usuario} />);
  await screen.findByRole("link", { name: "Lotufo" });
  fireEvent.click(screen.getByRole("button", { name: "Copiar o CNPJ de Lotufo" }));
  await waitFor(() => expect(gravar).toHaveBeenCalledWith("31200101000130"));
  await waitFor(() => expect(screen.getAllByText("CNPJ de Lotufo copiado.").length).toBeGreaterThan(0));
});

test("diretoria vê os cartões e o ZIP, mas não a área de anexar", async () => {
  render(<Documentos usuario={{ ...usuario, perfil: "diretoria" }} />);
  await screen.findByRole("link", { name: "Lotufo" });
  expect(screen.queryByText(/Arraste os PDFs das certidões/)).toBeNull();
  expect(screen.queryByLabelText(/Escolher PDFs/i)).toBeNull();
  screen.getByRole("button", { name: /ZIP das certidões vigentes/ });
});

test("área de arrastar no fim: datas lidas implausíveis abrem a digitação já preenchida (gate Sol S6)", async () => {
  vi.mocked(apiForm).mockResolvedValueOnce({
    ok: false, motivo: "datas-implausiveis", digitavel: true,
    mensagem: "As datas lidas (emissão 24/06/2026, validade 21/12/2028) não batem com o prazo normal desta certidão: confira no documento e digite",
    lidos: { entidade_id: 1, tipo: "trabalhista", emissao: "2026-06-24", validade: "2028-12-21", natureza: "negativa" },
  });
  render(<Documentos usuario={usuario} />);
  await screen.findByText(/Arraste os PDFs das certidões aqui/);
  fireEvent.change(screen.getByLabelText(/Escolher PDFs/i), { target: { files: [new File(["%PDF"], "cndt.pdf", { type: "application/pdf" })] } });
  await screen.findByText(/não batem com o prazo normal/);
  expect((screen.getByLabelText("Empresa") as HTMLSelectElement).value).toBe("1");
  expect((screen.getByLabelText("Tipo") as HTMLSelectElement).value).toBe("trabalhista");
  expect((screen.getByLabelText("Emissão") as HTMLInputElement).value).toBe("2026-06-24");
  expect((screen.getByLabelText(/^Validade/) as HTMLInputElement).value).toBe("2028-12-21");
});

test("a fila mostra a leitura para conferir e descarta", async () => {
  vi.mocked(apiForm).mockResolvedValueOnce({
    ok: true, leitura: { tipo: "fgts", tipo_nome: "FGTS", natureza: "negativa", entidade_id: 1, entidade: "Lotufo",
      emissao: "2026-09-20", validade: "2026-10-19", numero: "123", validade_calculada: false },
  });
  render(<Documentos usuario={usuario} />);
  await screen.findByText(/Arraste os PDFs das certidões aqui/);
  fireEvent.change(screen.getByLabelText(/Escolher PDFs/i), { target: { files: [new File(["%PDF"], "crf.pdf", { type: "application/pdf" })] } });
  await screen.findByText(/válida até 19\/10\/2026/);
  fireEvent.click(screen.getByRole("button", { name: "Descartar" }));
  expect(screen.queryByText("crf.pdf")).toBeNull();
});

test("o ZIP abre uma janela com a data e uma caixa por empresa, e diz o que a empresa sem certidão respondeu", async () => {
  const buscar = vi.fn(async () => new Response(JSON.stringify({ detail: "nenhuma certidão vigente em 2026-09-23" }), { status: 422 }));
  vi.stubGlobal("fetch", buscar);
  render(<Documentos usuario={usuario} />);
  await screen.findByRole("link", { name: "Lotufo" });
  fireEvent.click(screen.getByRole("button", { name: /ZIP das certidões vigentes/ }));
  expect((screen.getByLabelText("Certidões vigentes em") as HTMLInputElement).value).toBe("2026-09-23");
  fireEvent.click(screen.getByRole("checkbox", { name: "Beta Ltda" }));
  fireEvent.click(screen.getByRole("checkbox", { name: "Consórcio Alfa" }));
  fireEvent.click(screen.getByRole("checkbox", { name: "Consórcio Sem Certidão" }));
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

test("a garantia vencida de uma obra conta como pendência do cartão e a empresa sem certidão continua na lista", async () => {
  render(<Documentos usuario={usuario} />);
  const c = (await screen.findByRole("link", { name: "Consórcio Sem Certidão" })).closest("article")!;
  within(c).getByText("Garantia de Obra Delta: vencida");
  within(c).getByText("Garantia vencida");
  within(c).getByText("Nenhuma certidão vigente");
});
