import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import MinhaConta from "./MinhaConta";
import { ApiErro } from "./api";

// vi.mock e' icado para o topo do arquivo: a funcao falsa precisa nascer em vi.hoisted para
// existir quando a fabrica do mock rodar.
const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

const NENHUM = { estado: "nenhum", user_code: null, verification_uri: null };
const ENG = { id: 2, nome: "Maria", email: "maria@lotufo.com", perfil: "engenharia" };

describe("MinhaConta", () => {
  afterEach(() => { cleanup(); api.mockReset(); });

  it("mostra que a conta não está conectada e, ao conectar, o código para digitar", async () => {
    api.mockResolvedValueOnce({ configurado: true, conectado: false, login: NENHUM });
    api.mockResolvedValueOnce({ configurado: true, conectado: false, login: {
      estado: "aguardando", user_code: "ABCD-1234", verification_uri: "https://microsoft.com/devicelogin" } });
    render(<MinhaConta usuario={ENG} />);
    expect(await screen.findByText("Não conectada")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Conectar minha conta Microsoft" }));
    expect(await screen.findByText("ABCD-1234")).toBeTruthy();
  });

  it("conectada, permite mandar o e-mail de teste e mostra para onde foi", async () => {
    api.mockResolvedValueOnce({ configurado: true, conectado: true, login: NENHUM });
    api.mockResolvedValueOnce({ envio_id: 7, remetente: "engenheira.obra@exemplo.com.br" });
    render(<MinhaConta usuario={ENG} />);
    fireEvent.click(await screen.findByRole("button", { name: "Enviar e-mail de teste" }));
    await waitFor(() => expect(screen.getByText(/engenheira\.obra@exemplo\.com\.br/)).toBeTruthy());
  });

  // issue #28: remover a assinatura pede confirmação antes do DELETE
  it("Remover a assinatura pede confirmação; Cancelar não apaga", async () => {
    api.mockResolvedValue({ configurado: true, conectado: true, login: NENHUM, assinatura: true });
    render(<MinhaConta usuario={ENG} />);
    fireEvent.click(await screen.findByRole("button", { name: "Remover a assinatura" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));
    expect(api).not.toHaveBeenCalledWith("/api/correio/assinatura", expect.objectContaining({ method: "DELETE" }));
    fireEvent.click(screen.getByRole("button", { name: "Remover a assinatura" }));
    fireEvent.click(screen.getByRole("button", { name: /Confirmar a remoção:\s*a assinatura/ }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/correio/assinatura", { method: "DELETE" }));
  });
});

// A-05/B-10 (10/10/2026): cada um troca a própria senha
describe("MinhaConta › Trocar senha", () => {
  afterEach(() => { cleanup(); api.mockReset(); });

  function preencher(atual: string, nova: string, confirmar: string) {
    fireEvent.change(screen.getByLabelText("Senha atual"), { target: { value: atual } });
    fireEvent.change(screen.getByLabelText(/^Senha nova/), { target: { value: nova } });
    fireEvent.change(screen.getByLabelText("Confirmar a senha nova"), { target: { value: confirmar } });
    fireEvent.click(screen.getByRole("button", { name: "Trocar senha" }));
  }

  it("enquanto a troca roda, o botão diz que está trocando e fica desabilitado", async () => {
    api.mockImplementation((url: string) =>
      url === "/api/correio/status" ? Promise.resolve({ configurado: true, conectado: false, login: NENHUM }) : new Promise(() => {}));
    render(<MinhaConta usuario={ENG} />);
    await screen.findByText("Não conectada");
    preencher("senha-velha-123", "senha-nova-456", "senha-nova-456");
    const botao = await screen.findByRole("button", { name: "Trocando…" }) as HTMLButtonElement;
    expect(botao.disabled).toBe(true);
  });

  it("outra ação em curso (conectar) desabilita 'Trocar senha' sem mudar o rótulo dele", async () => {
    api.mockImplementation((url: string) =>
      url === "/api/correio/status" ? Promise.resolve({ configurado: true, conectado: false, login: NENHUM }) : new Promise(() => {}));
    render(<MinhaConta usuario={ENG} />);
    await screen.findByText("Não conectada");
    fireEvent.click(screen.getByRole("button", { name: /Conectar/ }));
    await waitFor(() => expect((screen.getByRole("button", { name: "Trocar senha" }) as HTMLButtonElement).disabled).toBe(true));
  });

  it("manda a atual e a nova para /api/auth/senha", async () => {
    api.mockImplementation(async (url: string) =>
      url === "/api/correio/status" ? { configurado: true, conectado: false, login: NENHUM } : { ok: true });
    render(<MinhaConta usuario={ENG} />);
    await screen.findByText("Não conectada");
    preencher("senha-velha-123", "senha-nova-456", "senha-nova-456");
    expect(api).toHaveBeenCalledWith("/api/auth/senha", { method: "POST",
      body: JSON.stringify({ senha_atual: "senha-velha-123", senha_nova: "senha-nova-456" }) });
    expect(await screen.findByText(/Senha trocada/)).toBeTruthy();
  });

  it("confirmação diferente não manda nada; erro do servidor aparece na tela", async () => {
    api.mockImplementation(async (url: string) => {
      if (url === "/api/correio/status") return { configurado: true, conectado: false, login: NENHUM };
      throw new ApiErro(400, "Senha atual não confere");
    });
    render(<MinhaConta usuario={ENG} />);
    await screen.findByText("Não conectada");
    preencher("senha-velha-123", "senha-nova-456", "outra-coisa-789");
    expect(api).not.toHaveBeenCalledWith("/api/auth/senha", expect.anything());
    expect(screen.getByText(/não bate/)).toBeTruthy();
    preencher("senha-errada-00", "senha-nova-456", "senha-nova-456");
    expect(await screen.findByText("Senha atual não confere")).toBeTruthy();
  });
});

// B-09 (10/10/2026): a diretoria nao manda e-mail pela dashboard; ve o e-mail de login e troca a senha
// gate Sol S6: o usuario no formato da resposta de /api/auth/eu, que e' o que o App guarda e passa adiante
const EU_DIRETORIA = { id: 3, nome: "Diretor", email: "dir@lotufo.com", perfil: "diretoria", csrf: "token" };

describe("MinhaConta › diretoria", () => {
  afterEach(() => { cleanup(); api.mockReset(); });

  it("sem e-mail, a linha do e-mail de login não aparece (gate Sol S6)", () => {
    render(<MinhaConta usuario={{ ...EU_DIRETORIA, email: "" }} />);
    expect(screen.queryByText(/E-mail:/)).toBeNull();
    expect(screen.getByRole("button", { name: "Trocar senha" })).toBeTruthy();
  });

  it("mostra o e-mail de login e a troca de senha, sem conta Microsoft nem assinatura", async () => {
    api.mockResolvedValue({ configurado: true, conectado: false, login: NENHUM, assinatura: false });
    render(<MinhaConta usuario={EU_DIRETORIA} />);
    expect(await screen.findByText("dir@lotufo.com")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Trocar senha" })).toBeTruthy();
    expect(screen.queryByText("Conta Microsoft")).toBeNull();
    expect(screen.queryByText("Assinatura de e-mail")).toBeNull();
    // sem a explicação de que a diretoria não manda e-mail
    expect(screen.queryByText(/não manda e-mail/)).toBeNull();
  });
});

// Redesenho (#165, opção A): uma coluna de cartões, erro embaixo de cada campo, estados da conta Microsoft
describe("MinhaConta › redesenho", () => {
  afterEach(() => { cleanup(); api.mockReset(); });
  const status = (extra: object = {}, login: object = NENHUM) =>
    ({ configurado: true, conectado: false, login, assinatura: false, ...extra });

  it("Sua conta mostra o e-mail e o perfil, e os quatro cartões vêm na ordem do desenho", async () => {
    api.mockResolvedValue(status());
    render(<MinhaConta usuario={ENG} />);
    await screen.findByText("Não conectada");
    expect(screen.getByText("maria@lotufo.com").closest("p")?.textContent).toBe("E-mail: maria@lotufo.com");
    expect(screen.getByText("Engenharia").closest("p")?.textContent).toBe("Perfil: Engenharia");
    // sem as frases de regra da conta Microsoft e da assinatura
    expect(document.body.textContent).not.toMatch(/saem da sua própria caixa|sugestões de contatos|vai no fim de todo e-mail|confere sozinha|Nenhuma assinatura cadastrada/);
    const titulos = screen.getAllByRole("heading", { level: 2 }).map(h => h.textContent);
    expect(titulos).toEqual(["Sua conta", "Trocar senha", "Conta Microsoft", "Assinatura de e-mail"]);
  });

  it("diretoria vê o perfil em Sua conta", () => {
    render(<MinhaConta usuario={EU_DIRETORIA} />);
    expect(screen.getByText("Diretoria").closest("p")?.textContent).toBe("Perfil: Diretoria");
  });

  it("campos vazios mostram um erro embaixo de cada um e não chamam a API", async () => {
    api.mockResolvedValue(status());
    render(<MinhaConta usuario={ENG} />);
    await screen.findByText("Não conectada");
    api.mockClear();
    fireEvent.click(screen.getByRole("button", { name: "Trocar senha" }));
    expect(screen.getByText("Digite a sua senha atual.")).toBeTruthy();
    expect(screen.getByText("Digite a senha nova.")).toBeTruthy();
    expect(screen.getByText("Repita a senha nova.")).toBeTruthy();
    expect(screen.getByLabelText("Senha atual").getAttribute("aria-invalid")).toBe("true");
    expect(api).not.toHaveBeenCalled();
  });

  it("senha nova curta: sem contador nem placeholder; o erro diz quantos caracteres tem", async () => {
    api.mockResolvedValue(status());
    render(<MinhaConta usuario={ENG} />);
    await screen.findByText("Não conectada");
    expect(screen.getByLabelText(/^Senha nova/).getAttribute("placeholder")).toBeNull();
    fireEvent.change(screen.getByLabelText(/^Senha nova/), { target: { value: "curta" } });
    expect(screen.queryByText(/\d+ de 10 caracteres/)).toBeNull();
    fireEvent.change(screen.getByLabelText("Senha atual"), { target: { value: "velha-123456" } });
    fireEvent.change(screen.getByLabelText("Confirmar a senha nova"), { target: { value: "curta" } });
    fireEvent.click(screen.getByRole("button", { name: "Trocar senha" }));
    expect(screen.getByText("A senha nova precisa de pelo menos 10 caracteres (tem 5).")).toBeTruthy();
    expect(api).not.toHaveBeenCalledWith("/api/auth/senha", expect.anything());
  });

  it("corrigir a senha nova tira o erro velho da confirmação", async () => {
    api.mockResolvedValue(status());
    render(<MinhaConta usuario={ENG} />);
    await screen.findByText("Não conectada");
    fireEvent.change(screen.getByLabelText("Senha atual"), { target: { value: "velha-123456" } });
    fireEvent.change(screen.getByLabelText(/^Senha nova/), { target: { value: "senha-nova-456" } });
    fireEvent.change(screen.getByLabelText("Confirmar a senha nova"), { target: { value: "outra-coisa-789" } });
    fireEvent.click(screen.getByRole("button", { name: "Trocar senha" }));
    expect(screen.getByText("A confirmação não bate com a senha nova.")).toBeTruthy();
    fireEvent.change(screen.getByLabelText(/^Senha nova/), { target: { value: "outra-coisa-789" } });
    expect(screen.queryByText("A confirmação não bate com a senha nova.")).toBeNull();
  });

  it("o olho mostra e esconde a senha", async () => {
    api.mockResolvedValue(status());
    render(<MinhaConta usuario={ENG} />);
    await screen.findByText("Não conectada");
    const campo = screen.getByLabelText("Senha atual") as HTMLInputElement;
    expect(campo.type).toBe("password");
    fireEvent.click(screen.getByRole("button", { name: "Mostrar a senha atual" }));
    expect(campo.type).toBe("text");
    expect(screen.getByRole("button", { name: "Mostrar a senha atual" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("depois de trocar a senha, os olhos voltam a esconder", async () => {
    api.mockImplementation(async (url: string) => url === "/api/correio/status" ? status() : { ok: true });
    render(<MinhaConta usuario={ENG} />);
    await screen.findByText("Não conectada");
    fireEvent.click(screen.getByRole("button", { name: "Mostrar a senha nova" }));
    fireEvent.change(screen.getByLabelText("Senha atual"), { target: { value: "velha-123456" } });
    fireEvent.change(screen.getByLabelText(/^Senha nova/), { target: { value: "senha-nova-456" } });
    fireEvent.change(screen.getByLabelText("Confirmar a senha nova"), { target: { value: "senha-nova-456" } });
    fireEvent.click(screen.getByRole("button", { name: "Trocar senha" }));
    await screen.findByText(/Senha trocada/);
    expect((screen.getByLabelText(/^Senha nova/) as HTMLInputElement).type).toBe("password");
  });

  const png = () => new File([new Uint8Array([1, 2, 3])], "a.png", { type: "image/png" });
  const alvo = () => screen.getByRole("button", { name: "Colar ou arrastar a imagem da assinatura" });
  // apiForm nao e' mockado (so' `api`): o envio da imagem aparece como chamada ao fetch

  it("colar imagem envia para /api/correio/assinatura; colar sem imagem avisa", async () => {
    const fetchFalso = vi.fn().mockResolvedValue(new Response(JSON.stringify(status({ conectado: true, assinatura: true })),
      { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchFalso);
    api.mockResolvedValue(status({ conectado: true }));
    render(<MinhaConta usuario={ENG} />);
    await screen.findByText("Não cadastrada");
    fireEvent.paste(alvo(), { clipboardData: { files: [] } });
    expect(screen.getByText(/A área de transferência não tem imagem/)).toBeTruthy();
    fireEvent.paste(alvo(), { clipboardData: { files: [png()] } });
    await waitFor(() => expect(fetchFalso).toHaveBeenCalled());
    expect(String(fetchFalso.mock.calls[0][0])).toContain("/api/correio/assinatura");
    expect(await screen.findByAltText("Sua assinatura")).toBeTruthy();
    expect(screen.getByText("Trocar a imagem")).toBeTruthy();
    vi.unstubAllGlobals();
  });

  it("soltar PNG envia; soltar outro arquivo avisa", async () => {
    const fetchFalso = vi.fn().mockResolvedValue(new Response(JSON.stringify(status({ assinatura: true })),
      { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchFalso);
    api.mockResolvedValue(status());
    render(<MinhaConta usuario={ENG} />);
    await screen.findByText("Não cadastrada");
    fireEvent.drop(alvo(), { dataTransfer: { files: [new File(["x"], "a.txt", { type: "text/plain" })] } });
    expect(screen.getByText("Arraste um arquivo PNG ou JPG.")).toBeTruthy();
    expect(fetchFalso).not.toHaveBeenCalled();
    fireEvent.drop(alvo(), { dataTransfer: { files: [png()] } });
    await waitFor(() => expect(fetchFalso).toHaveBeenCalled());
    vi.unstubAllGlobals();
  });

  it("arquivo .gif pelo seletor é recusado sem chamar a API", async () => {
    api.mockResolvedValue(status());
    render(<MinhaConta usuario={ENG} />);
    await screen.findByText("Não cadastrada");
    api.mockClear();
    const gif = new File(["x"], "a.gif", { type: "image/gif" });
    fireEvent.change(document.querySelector('input[type="file"]') as HTMLInputElement, { target: { files: [gif] } });
    expect(await screen.findByText("A imagem precisa ser PNG ou JPG.")).toBeTruthy();
    expect(api).not.toHaveBeenCalled();
  });

  it("'Pedir outro código' chama /api/correio/conectar", async () => {
    api.mockResolvedValueOnce(status({}, { estado: "aguardando", user_code: "ABCD-1234", verification_uri: "https://microsoft.com/devicelogin" }));
    api.mockResolvedValue(status());
    render(<MinhaConta usuario={ENG} />);
    fireEvent.click(await screen.findByRole("button", { name: "Pedir outro código" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/correio/conectar", { method: "POST" }));
  });

  it("erro do e-mail de teste aparece no cartão da assinatura", async () => {
    api.mockImplementation(async (url: string) => {
      if (url === "/api/correio/status") return status({ conectado: true });
      throw new ApiErro(502, "A Microsoft não respondeu.");
    });
    render(<MinhaConta usuario={ENG} />);
    fireEvent.click(await screen.findByRole("button", { name: "Enviar e-mail de teste" }));
    const msg = await screen.findByText("A Microsoft não respondeu.");
    expect(msg.closest("section")?.querySelector("h2")?.textContent).toBe("Assinatura de e-mail");
  });

  it("não conectada: o e-mail de teste fica desabilitado e a tela diz o motivo", async () => {
    api.mockResolvedValue(status());
    render(<MinhaConta usuario={ENG} />);
    await screen.findByText("Não conectada");
    expect((screen.getByRole("button", { name: "Enviar e-mail de teste" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("Conecte a sua conta Microsoft para enviar o teste.")).toBeTruthy();
  });

  it("conectada: 'Conectar de novo' e o teste habilitado, sem o motivo", async () => {
    api.mockResolvedValue(status({ conectado: true, assinatura: true }));
    render(<MinhaConta usuario={ENG} />);
    expect(await screen.findByRole("button", { name: "Conectar de novo" })).toBeTruthy();
    expect((screen.getByRole("button", { name: "Enviar e-mail de teste" }) as HTMLButtonElement).disabled).toBe(false);
    expect(screen.queryByText(/Conecte a sua conta Microsoft para enviar/)).toBeNull();
    expect(screen.getByText("Trocar a imagem")).toBeTruthy();
  });

  it("esperando o código mostra o código e 'Pedir outro código'", async () => {
    api.mockResolvedValue(status({}, { estado: "aguardando", user_code: "ABCD-1234", verification_uri: "https://microsoft.com/devicelogin" }));
    render(<MinhaConta usuario={ENG} />);
    expect(await screen.findByText("ABCD-1234")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Pedir outro código" })).toBeTruthy();
  });

  it("código expirado, acesso recusado, erro e Microsoft 365 não configurado têm cada um a sua mensagem", async () => {
    api.mockResolvedValueOnce(status({}, { estado: "expirado", user_code: null, verification_uri: null }));
    const r1 = render(<MinhaConta usuario={ENG} />);
    expect(await screen.findByText("O código expirou. Peça outro.")).toBeTruthy();
    r1.unmount();
    api.mockResolvedValueOnce(status({}, { estado: "recusado", user_code: null, verification_uri: null }));
    const r2 = render(<MinhaConta usuario={ENG} />);
    expect(await screen.findByText("A Microsoft recusou o acesso. Tente de novo.")).toBeTruthy();
    r2.unmount();
    api.mockResolvedValueOnce(status({}, { estado: "erro", user_code: null, verification_uri: null, erro: "Falha ao falar com a Microsoft." }));
    const r3 = render(<MinhaConta usuario={ENG} />);
    expect(await screen.findByText("Falha ao falar com a Microsoft.")).toBeTruthy();
    r3.unmount();
    api.mockResolvedValueOnce(status({ configurado: false }));
    render(<MinhaConta usuario={ENG} />);
    expect(await screen.findByText("O Microsoft 365 ainda não foi configurado neste servidor.")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Conectar minha conta Microsoft" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("assinatura: 'Onde achar a imagem' fica recolhido e imagem grande demais é recusada antes de enviar", async () => {
    api.mockResolvedValue(status({ assinatura: true }));
    render(<MinhaConta usuario={ENG} />);
    await screen.findByText("Cadastrada");
    const detalhes = screen.getByText("Onde achar a imagem").closest("details") as HTMLDetailsElement;
    expect(detalhes.open).toBe(false);
    expect(screen.getByText(/Signatures/)).toBeTruthy();
    api.mockClear();
    const grande = new File([new Uint8Array(1024 * 1024 + 1)], "a.png", { type: "image/png" });
    fireEvent.change(document.querySelector('input[type="file"]') as HTMLInputElement, { target: { files: [grande] } });
    expect(await screen.findByText(/A imagem passa de 1 MB/)).toBeTruthy();
    expect(api).not.toHaveBeenCalled();
  });
});
