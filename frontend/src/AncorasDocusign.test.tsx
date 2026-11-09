import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import AncorasDocusign from "./AncorasDocusign";

const { apiForm, baixarArquivoForm } = vi.hoisted(() => ({ apiForm: vi.fn(), baixarArquivoForm: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), apiForm, baixarArquivoForm }));

const PAGINAS = [
  { pagina: 1, motivo: "nome", papeis: ["fiscal", "supervisor"] },
  { pagina: 2, motivo: "diario", papeis: ["fiscal", "supervisor", "executora"] },
  { pagina: 3, motivo: null, papeis: [] },
];
const pdf = (nome: string) => new File(["%PDF-1.4"], nome, { type: "application/pdf" });

async function analisado() {
  apiForm.mockResolvedValue({ paginas: PAGINAS });
  render(<AncorasDocusign />);
  fireEvent.change(screen.getByLabelText("Escolher PDFs", { selector: "input" }), { target: { files: [pdf("a.pdf"), pdf("b.pdf")] } });
  fireEvent.change(screen.getByLabelText("Fiscal do órgão"), { target: { value: "Ana Souza" } });
  fireEvent.click(screen.getByRole("button", { name: "Ver as páginas com âncora" }));
  await screen.findByText("Páginas com âncora (2)");
}

describe("AncorasDocusign", () => {
  afterEach(() => { cleanup(); apiForm.mockReset(); baixarArquivoForm.mockReset(); });

  it("formulário com os quatro papéis, a opção de conferência e o botão de baixar", () => {
    render(<AncorasDocusign />);
    for (const r of ["Fiscal do órgão", "Supervisor (supervisora)", "Responsável técnico da executora", "Superior imediato do fiscal"]) {
      expect(screen.getByLabelText(r)).toBeTruthy();
    }
    expect(screen.getByLabelText(/Mostrar âncoras/)).toBeTruthy();
    expect((screen.getByRole("button", { name: /Baixar PDF com âncoras/ }) as HTMLButtonElement).disabled).toBe(true);
    expect(document.body.textContent).not.toMatch(/anchor/i);
  });

  it("lista as páginas com e sem âncora, com o motivo e os papéis", async () => {
    await analisado();
    const form = apiForm.mock.calls[0][1] as FormData;
    expect(apiForm.mock.calls[0][0]).toBe("/api/ancoras-docusign/paginas");
    expect(form.getAll("arquivos")).toHaveLength(2);
    expect(JSON.parse(form.get("papeis") as string)).toEqual({ fiscal: "Ana Souza" });
    const linhas = screen.getAllByRole("row");
    expect(within(linhas[1]).getByText("Nome impresso")).toBeTruthy();
    expect(within(linhas[1]).getByText("Fiscal, Supervisor")).toBeTruthy();
    expect(within(linhas[2]).getByText("Diário de Obra (rodapé)")).toBeTruthy();
    expect(screen.getByText("Páginas sem âncora (1)")).toBeTruthy();
    expect(screen.getByLabelText("Pôr âncoras no rodapé da página 3")).toBeTruthy();
  });

  it("marcar e desmarcar páginas vão no download, e a tela acompanha", async () => {
    await analisado();
    fireEvent.click(screen.getByLabelText("Manter a âncora da página 1"));
    fireEvent.click(screen.getByLabelText("Pôr âncoras no rodapé da página 3"));
    expect(screen.getByText("Páginas com âncora (2)")).toBeTruthy();       // sai a 1, entra a 3
    expect(screen.getByText("Rodapé (marcada por você)")).toBeTruthy();
    expect(screen.getByLabelText("Restaurar a âncora da página 1")).toBeTruthy();
    fireEvent.click(screen.getByLabelText(/Mostrar âncoras/));
    fireEvent.click(screen.getByRole("button", { name: /Baixar PDF com âncoras/ }));
    await waitFor(() => expect(baixarArquivoForm).toHaveBeenCalled());
    const [caminho, dados] = baixarArquivoForm.mock.calls[0] as [string, FormData];
    expect(caminho).toBe("/api/ancoras-docusign/pdf");
    expect(JSON.parse(dados.get("marcar") as string)).toEqual([3]);
    expect(JSON.parse(dados.get("desmarcar") as string)).toEqual([1]);
    expect(dados.get("mostrar")).toBe("true");
  });

  it("mostra a recusa do servidor em português", async () => {
    const { ApiErro } = await import("./api");
    apiForm.mockRejectedValue(new ApiErro(413, "Arquivo acima do limite de 40 MB"));
    render(<AncorasDocusign />);
    fireEvent.change(screen.getByLabelText("Escolher PDFs", { selector: "input" }), { target: { files: [pdf("a.pdf")] } });
    fireEvent.click(screen.getByRole("button", { name: "Ver as páginas com âncora" }));
    expect((await screen.findByRole("alert")).textContent).toContain("Arquivo acima do limite de 40 MB");
  });
});
