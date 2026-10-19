import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiErro } from "./api";
import { FrcConsorcio } from "./Frc";
import { ItensEnvio } from "./NotasAEnviar";

const { api, baixarArquivo } = vi.hoisted(() => ({ api: vi.fn(), baixarArquivo: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api, apiForm: vi.fn(),
  baixarArquivo }));
const DESATUALIZADA = "As notas mudaram depois desta FRC: gere de novo na etapa 3 (Nota fiscal) antes de baixar";

const item = (empresa: string, municipio: string, extra: Record<string, unknown> = {}) => ({
  chave: `${empresa}-${municipio}`, empresa, municipio, esperado_centavos: 81887199, situacao: "falta", documento_id: null,
  nome: null, numero: null, problema: null, valores: null, ...extra });
const anexada = (empresa: string, municipio: string, numero: string) => item(empresa, municipio, {
  situacao: "anexada", documento_id: 1, nome: "x.pdf", numero,
  valores: { bruto: 81887199, inss: 3603036, irrf: 982646, iss: 1637744, retencoes: 6223426, liquido: 75663773 } });

describe("FRC do consórcio (etapa 3)", () => {
  afterEach(() => { cleanup(); api.mockReset(); });

  it("checklist incompleto: anexada com o nº lido, falta em âmbar, número sugerido e geração travada", async () => {
    api.mockResolvedValue({
      disponivel: true, consorcio: "Consórcio Integra BRT", motivo: null, completa: false, ultima: 21, sugerido: 22,
      itens: [anexada("Guaxe", "Várzea Grande", "2026204"), item("Encomind", "Várzea Grande")],
      nao_lidas: [{ documento_id: 9, nome: "NFSE 2026205 - GRUPO GUAXE.pdf", motivo: "sem-numero" }], sobras: [],
      bloqueio: "Falta 1 nota: Encomind · Várzea Grande", frc: null, assinada: false });
    render(<FrcConsorcio medicaoId={7} podeEditar versao={0} aoMudar={() => {}} />);
    const lista = await screen.findByRole("list", { name: "Notas esperadas da medição" });
    const [guaxe, encomind] = within(lista).getAllByRole("listitem");
    expect(within(guaxe).getByText("Anexada")).toBeTruthy();
    expect(guaxe.textContent).toContain("anexada · NF nº 2026204");
    expect(within(encomind).getByText("Falta")).toBeTruthy();
    expect(screen.getByText(/rascunho/).textContent).toContain("não conta");
    expect((screen.getByLabelText("Número da FRC") as HTMLInputElement).value).toBe("22");
    expect(screen.getByText(/Última registrada/).textContent).toContain("21");
    expect((screen.getByRole("button", { name: "Gerar a FRC" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.queryByRole("link", { name: "Baixar PDF" })).toBeNull();
    expect(screen.getByText(/Assine no DocuSign/)).toBeTruthy();
  });

  const gerada = (desatualizada: boolean) => ({
    disponivel: true, consorcio: "Consórcio Integra BRT", motivo: null, completa: true, ultima: 22, sugerido: 22,
    itens: [anexada("Lotufo", "Cuiabá", "2284")], nao_lidas: [], sobras: [], bloqueio: null, assinada: false,
    frc: { numero: 22, data_geracao: "2026-10-09", gerada_em: "", gerada_por: "Leo", bruto_centavos: 1210048928,
           liquido_centavos: 1118085213, desatualizada } });

  it("FRC gerada: gerar de novo e os dois downloads", async () => {
    api.mockResolvedValue(gerada(false));
    baixarArquivo.mockResolvedValue(undefined);
    render(<FrcConsorcio medicaoId={7} podeEditar versao={0} aoMudar={() => {}} />);
    expect((await screen.findByRole("button", { name: "Gerar de novo" }) as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Baixar PDF" }));
    fireEvent.click(screen.getByRole("button", { name: "Baixar planilha" }));
    expect(baixarArquivo.mock.calls.map(c => c[0])).toEqual(["/api/medicoes/7/frc/pdf", "/api/medicoes/7/frc/xlsx"]);
    expect(screen.getByText(/00022/)).toBeTruthy();
    baixarArquivo.mockReset();
  });

  it("issue #169: FRC desatualizada não oferece download", async () => {
    api.mockResolvedValue(gerada(true));
    render(<FrcConsorcio medicaoId={7} podeEditar versao={0} aoMudar={() => {}} />);
    expect(await screen.findByText(/As notas mudaram depois desta FRC/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Baixar PDF" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Baixar planilha" })).toBeNull();
  });

  it("issue #169: download recusado (ficou desatualizada depois de a tela carregar) mostra o motivo e recarrega", async () => {
    api.mockResolvedValueOnce(gerada(false)).mockResolvedValueOnce(gerada(true));
    baixarArquivo.mockRejectedValue(new ApiErro(409, DESATUALIZADA));
    const aoMudar = vi.fn();
    render(<FrcConsorcio medicaoId={7} podeEditar versao={0} aoMudar={aoMudar} />);
    fireEvent.click(await screen.findByRole("button", { name: "Baixar PDF" }));
    expect((await screen.findByRole("alert")).textContent).toContain(DESATUALIZADA);
    await waitFor(() => expect(screen.queryByRole("button", { name: "Baixar PDF" })).toBeNull());
    expect(api).toHaveBeenCalledTimes(2);
    expect(aoMudar).toHaveBeenCalled();
    baixarArquivo.mockReset();
  });

  it("consórcio sem formulário: avisa que a geração não está disponível", async () => {
    api.mockResolvedValue({ disponivel: false, consorcio: "Consórcio Oriundi",
                            motivo: "Geração da FRC ainda não disponível para este consórcio" });
    render(<FrcConsorcio medicaoId={7} podeEditar versao={0} aoMudar={() => {}} />);
    expect((await screen.findByText(/ainda não disponível/)).textContent).toContain("Consórcio Oriundi");
  });
});

describe("FRC assinada no envio (etapa 4)", () => {
  it("o item que falta tem onde anexar", () => {
    render(<ItensEnvio aoMudar={() => {}} itens={[{ chave: "frc:7", rotulo: "FRC assinada", estado: "falta",
      detalhe: "Falta a FRC assinada", acao: "anexar_frc", medicao_id: 7 }]} />);
    expect(screen.getByLabelText("Anexar FRC assinada")).toBeTruthy();
    expect(screen.getByText(/Arraste a FRC assinada/)).toBeTruthy();
    cleanup();
  });

  it("issue #169: baixar a FRC gerada que ficou desatualizada mostra o motivo e recarrega", async () => {
    baixarArquivo.mockRejectedValue(new ApiErro(409, DESATUALIZADA));
    const aoMudar = vi.fn();
    render(<ItensEnvio aoMudar={aoMudar} itens={[{ chave: "frc:7", rotulo: "FRC assinada", estado: "falta",
      detalhe: "Falta a assinada", acao: "anexar_frc", medicao_id: 7, frc_gerada: 22 }]} />);
    const link = screen.getByRole("link", { name: "Baixar a FRC gerada (nº 22)" });
    expect(link.getAttribute("href")).toBe("/api/medicoes/7/frc/pdf");
    fireEvent.click(link);
    expect((await screen.findByRole("alert")).textContent).toContain(DESATUALIZADA);
    expect(baixarArquivo).toHaveBeenCalledWith("/api/medicoes/7/frc/pdf", "FRC.pdf");
    expect(aoMudar).toHaveBeenCalled();
    baixarArquivo.mockReset();
    cleanup();
  });
});
