import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FormAssinadosPorFora, FormEnviarAssinados, type SituacaoAssinados } from "./AssinadosEnvio";

const { api, apiForm } = vi.hoisted(() => ({ api: vi.fn(), apiForm: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api, apiForm }));

const MB = 1024 * 1024;
const RECUSA = "PDF acima de 25 MB, o limite por documento do órgão: divida o arquivo";
const S: SituacaoAssinados = { disponivel: true, motivo: null, reajuste: { id: 6, numero: 23 }, limite: 25 * MB,
  limite_recusa: RECUSA, envios: [], reserva: null };
const PREVIA = { para: ["protocolo@orgao.exemplo.com.br"], copia: ["engenharia@lotufo.com"],
  assunto: "RE: CT-337-LT-2026 - 23ª Medição (09_2026) - IC 1/2026 - Obra Alfa",
  corpo: "Encaminho, em anexo, os documentos assinados e a justificativa de atraso do cronograma.",
  anexos: [{ nome: "Medicao.pdf", tamanho: 9, sha256: "a".repeat(64), origem: "medicao" },
    { nome: "Reajuste.pdf", tamanho: 9, sha256: "b".repeat(64), origem: "reajuste" },
    { nome: "Justificativa.pdf", tamanho: 9, sha256: "c".repeat(64), origem: "justificativa" }],
  total: 27, limite: 25 * MB, pendencias: [], reenvio: false };

const pdf = (nome: string, tamanho = 9) => {
  const f = new File(["%PDF-1.4"], nome, { type: "application/pdf" });
  Object.defineProperty(f, "size", { value: tamanho });
  return f;
};
const anexar = (rotulo: string, f: File) => fireEvent.change(screen.getByLabelText(rotulo), { target: { files: [f] } });

function montar(s = S, previa = PREVIA) {
  apiForm.mockImplementation(async (url: string) => (url.endsWith("/previa") ? previa : { envio_id: 1 }));
  api.mockResolvedValue({});
  const agir = vi.fn(async (fn: () => Promise<unknown>, _feito?: string) => { await fn(); return true; });
  const aoFechar = vi.fn();
  render(<FormEnviarAssinados medicaoId={5} s={s} salvando={false} agir={agir} aoFechar={aoFechar} aoLiberar={() => {}} />);
  return { agir, aoFechar };
}

describe("Enviar documentos assinados", () => {
  afterEach(() => { cleanup(); api.mockReset(); apiForm.mockReset(); });

  it("a prévia mostra para, cópia, assunto e os três anexos; Enviar manda os arquivos e confirma a hora", async () => {
    const { agir, aoFechar } = montar();
    anexar("PDF assinado da medição", pdf("Medicao.pdf"));
    anexar("PDF assinado do reajuste (opcional)", pdf("Reajuste.pdf"));
    anexar("Justificativa de atraso (opcional)", pdf("Justificativa.pdf"));
    fireEvent.click(screen.getByRole("button", { name: "Prévia do e-mail" }));
    expect(((await screen.findByLabelText("Assunto")) as HTMLInputElement).value).toBe(PREVIA.assunto);
    const anexos = screen.getByRole("list", { name: "Anexos" });
    for (const a of PREVIA.anexos) expect(within(anexos).getByText(a.nome)).toBeTruthy();
    expect(screen.getByText("protocolo@orgao.exemplo.com.br")).toBeTruthy();
    expect(screen.getByText("engenharia@lotufo.com")).toBeTruthy();
    const fdPrevia = apiForm.mock.calls[0][1] as FormData;
    expect(apiForm.mock.calls[0][0]).toBe("/api/medicoes/5/assinados/previa");
    expect([...fdPrevia.keys()]).toEqual(["arquivo", "arquivo_reajuste", "justificativa"]);
    expect(screen.queryByLabelText("Motivo do reenvio")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Enviar" }));
    await vi.waitFor(() => expect(agir).toHaveBeenCalled());
    expect(agir.mock.calls[0][1]).toMatch(/^Documentos assinados enviados às \d{2}:\d{2}\.$/);
    const [url, fd] = apiForm.mock.calls[1] as [string, FormData];
    expect(url).toBe("/api/medicoes/5/assinados/enviar");
    const dados = JSON.parse(fd.get("dados") as string);
    expect(dados.para).toEqual(PREVIA.para);
    expect(dados.assunto).toBe(PREVIA.assunto);
    expect(dados.anexos_previa).toEqual(PREVIA.anexos.map(({ nome, tamanho, sha256 }) => ({ nome, tamanho, sha256 })));
    expect(fd.get("arquivo")).toBeTruthy();
    await vi.waitFor(() => expect(aoFechar).toHaveBeenCalled());
  });

  it("PDF acima do limite do órgão é recusado antes da prévia", () => {
    montar();
    anexar("PDF assinado da medição", pdf("Grande.pdf", 26 * MB));
    fireEvent.click(screen.getByRole("button", { name: "Prévia do e-mail" }));
    expect(screen.getByText(RECUSA)).toBeTruthy();
    expect(apiForm).not.toHaveBeenCalled();
  });

  it("sem o PDF da medição a prévia não abre", () => {
    montar();
    fireEvent.click(screen.getByRole("button", { name: "Prévia do e-mail" }));
    expect(screen.getByText("Anexe o PDF assinado da medição.")).toBeTruthy();
    expect(apiForm).not.toHaveBeenCalled();
  });

  it("o reenvio exige o motivo", async () => {
    const { agir } = montar(S, { ...PREVIA, reenvio: true });
    anexar("PDF assinado da medição", pdf("Medicao.pdf"));
    fireEvent.click(screen.getByRole("button", { name: "Prévia do e-mail" }));
    await screen.findByLabelText("Motivo do reenvio");
    fireEvent.click(screen.getByRole("button", { name: "Enviar" }));
    expect(screen.getByText("Escreva o motivo do reenvio, com pelo menos 10 caracteres.")).toBeTruthy();
    expect(agir).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Motivo do reenvio"), { target: { value: "faltou o cronograma do pacote" } });
    fireEvent.click(screen.getByRole("button", { name: "Enviar" }));
    await vi.waitFor(() => expect(agir).toHaveBeenCalled());
    expect(JSON.parse((apiForm.mock.calls[1][1] as FormData).get("dados") as string).motivo).toBe("faltou o cronograma do pacote");
  });

  it("sem reajuste com boletim, o campo do PDF do reajuste não aparece", () => {
    montar({ ...S, reajuste: null });
    expect(screen.queryByLabelText("PDF assinado do reajuste (opcional)")).toBeNull();
  });
});

describe("Registrar envio dos assinados por fora", () => {
  afterEach(() => { cleanup(); apiForm.mockReset(); });

  it("manda a data, o PDF e o .eml, e confirma", async () => {
    apiForm.mockResolvedValue({ id: 1 });
    const agir = vi.fn(async (fn: () => Promise<unknown>, _feito?: string) => { await fn(); return true; });
    render(<FormAssinadosPorFora medicaoId={5} s={S} salvando={false} agir={agir} aoFechar={() => {}} aoLiberar={() => {}} />);
    fireEvent.change(screen.getByLabelText("Data do envio"), { target: { value: "2026-11-09" } });
    anexar("PDF assinado da medição", pdf("Medicao.pdf"));
    fireEvent.click(screen.getByRole("button", { name: "Registrar envio" }));
    await vi.waitFor(() => expect(agir).toHaveBeenCalled());
    expect(agir.mock.calls[0][1]).toBe("Envio dos documentos assinados registrado.");
    const [url, fd] = apiForm.mock.calls[0] as [string, FormData];
    expect(url).toBe("/api/medicoes/5/assinados/envio-externo");
    expect(fd.get("enviado_em")).toBe("2026-11-09");
    expect(fd.get("arquivo")).toBeTruthy();
  });

  it("sem o PDF assinado não registra", () => {
    const agir = vi.fn();
    render(<FormAssinadosPorFora medicaoId={5} s={S} salvando={false} agir={agir} aoFechar={() => {}} aoLiberar={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Registrar envio" }));
    expect(screen.getByText("Anexe o PDF assinado da medição.")).toBeTruthy();
    expect(agir).not.toHaveBeenCalled();
  });
});
