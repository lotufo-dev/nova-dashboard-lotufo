import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ComporEmail from "./ComporEmail";
import { limparHtml } from "./htmlEmail";
import { ir } from "./rota";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", () => ({ api, ApiErro: class ApiErro extends Error { status = 0; } }));

// o corpo e' um editor (contentEditable): escrever = trocar o HTML e avisar como o navegador avisa
function escrever(corpo: HTMLElement, html: string) {
  corpo.innerHTML = html;
  fireEvent.input(corpo);
}

describe("ComporEmail", () => {
  afterEach(() => { cleanup(); api.mockReset(); });

  it("sem a imagem da assinatura: uma frase com o link para Minha conta, só quando falta", async () => {
    api.mockResolvedValue({ remetente: "eu@lotufo.com" });
    render(<ComporEmail ocupado={false} anexos={[]} aoEnviar={() => {}} aoDescartar={() => {}}
      inicial={{ para: [], copia: [], cco: [], assunto: "A", corpo: "B" }} />);
    const img = await screen.findByAltText("Sua assinatura");
    expect(screen.queryByText(/Sem assinatura/)).toBeNull();
    fireEvent.error(img);
    const frase = await screen.findByText(/Sem assinatura/);
    expect(frase.textContent).toBe("Sem assinatura: cadastre a sua em Minha conta.");
    expect(within(frase).getByRole("link", { name: "Minha conta" }).getAttribute("href")).toBe("/conta");
  });

  it("destinatario vira etiqueta pela sugestao ou pelo e-mail digitado e sai no envio", async () => {
    api.mockImplementation((caminho: string) => {
      if (caminho.startsWith("/api/correio/remetente")) return Promise.resolve({ remetente: "eu@lotufo.com" });
      if (caminho.includes("q=fat")) return Promise.resolve([{ nome: "Faturamento Exemplo", email: "faturamento@lotufo.com" }]);
      return Promise.resolve([]);
    });
    const aoEnviar = vi.fn();
    render(<ComporEmail ocupado={false} anexos={[{ nome: "ESPELHO.docx", tamanho: 28894 }]} aoEnviar={aoEnviar}
      aoDescartar={() => {}} inicial={{ para: [], copia: [], cco: [], assunto: "Emissão NF", corpo: "Bom dia." }} />);
    expect(await screen.findByText("De: eu@lotufo.com")).toBeTruthy();
    const para = screen.getByLabelText(/Para: digite/);
    fireEvent.change(para, { target: { value: "fat" } });
    fireEvent.mouseDown(await screen.findByText("Faturamento Exemplo"));
    expect(screen.getByTitle("faturamento@lotufo.com")).toBeTruthy();
    fireEvent.click(screen.getByText("Cco"));
    const cco = screen.getByLabelText(/Cco: digite/);
    fireEvent.change(cco, { target: { value: "oculto@lotufo.com" } });
    fireEvent.blur(cco);                       // digitou e foi direto ao Enviar: o endereco nao pode ficar para tras
    fireEvent.click(screen.getByRole("button", { name: "Enviar" }));
    await waitFor(() => expect(aoEnviar).toHaveBeenCalled());
    expect(aoEnviar.mock.calls[0][0]).toEqual({ para: ["faturamento@lotufo.com"], copia: [], cco: ["oculto@lotufo.com"],
      assunto: "Emissão NF", corpo: "Bom dia." });
  });

  // issue #11: o Enviar não fica apagado esperando o formulário valer; o clique diz o que falta, junto do campo
  it("Enviar fica clicável: sem destinatário ou sem assunto, o clique mostra o erro junto do campo", async () => {
    api.mockResolvedValue([]);
    const aoEnviar = vi.fn();
    render(<ComporEmail ocupado={false} anexos={[]} aoEnviar={aoEnviar} aoDescartar={() => {}}
      inicial={{ para: [], copia: [], cco: [], assunto: "", corpo: "Bom dia." }} />);
    const enviar = screen.getByRole("button", { name: "Enviar" }) as HTMLButtonElement;
    expect(enviar.disabled).toBe(false);
    fireEvent.click(enviar);
    const para = screen.getByLabelText(/Para: digite/);
    const erroPara = screen.getByText("Informe ao menos um destinatário.");
    expect(erroPara.getAttribute("role")).toBe("alert");
    expect(para.getAttribute("aria-invalid")).toBe("true");
    expect(document.getElementById(para.getAttribute("aria-describedby") ?? "")).toBe(erroPara);
    const assunto = screen.getByLabelText("Assunto");
    expect(document.getElementById(assunto.getAttribute("aria-describedby") ?? "")?.textContent).toContain("Informe o assunto.");
    expect(aoEnviar).not.toHaveBeenCalled();
    fireEvent.change(para, { target: { value: "fab@lotufo.com" } });
    fireEvent.blur(para);
    fireEvent.change(assunto, { target: { value: "Emissão NF" } });
    expect(screen.queryByText("Informe o assunto.")).toBeNull();
    fireEvent.click(enviar);
    await waitFor(() => expect(aoEnviar).toHaveBeenCalled());
  });

  it("o erro do campo que o ComporEmail não vê vem de quem o abriu (validarAntes)", () => {
    api.mockResolvedValue([]);
    const aoEnviar = vi.fn();
    const validarAntes = vi.fn(() => false);
    render(<ComporEmail ocupado={false} anexos={[]} aoEnviar={aoEnviar} aoDescartar={() => {}} validarAntes={validarAntes}
      inicial={{ para: ["a@lotufo.com"], copia: [], cco: [], assunto: "Assunto", corpo: "" }} />);
    fireEvent.click(screen.getByRole("button", { name: "Enviar" }));
    expect(validarAntes).toHaveBeenCalled();
    expect(aoEnviar).not.toHaveBeenCalled();
  });

  // issue #28: descartar o que a pessoa escreveu pede confirmação; sem nada mudado, não há o que perder
  it("Descartar com o e-mail mexido pede confirmação; sem mudança descarta direto", async () => {
    api.mockResolvedValue([]);
    const aoDescartar = vi.fn();
    const inicial = { para: [], copia: [], cco: [], assunto: "Emissão NF", corpo: "Bom dia." };
    render(<ComporEmail ocupado={false} anexos={[]} aoEnviar={() => {}} aoDescartar={aoDescartar} inicial={inicial} />);
    escrever(screen.getByLabelText("Corpo da mensagem"), "Bom dia, segue a nota.");
    fireEvent.click(screen.getByRole("button", { name: "Descartar" }));
    expect(aoDescartar).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Continuar escrevendo" }));
    expect(aoDescartar).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Corpo da mensagem").textContent).toBe("Bom dia, segue a nota.");
    fireEvent.click(screen.getByRole("button", { name: "Descartar" }));
    fireEvent.click(screen.getByRole("button", { name: "Descartar o e-mail" }));
    expect(aoDescartar).toHaveBeenCalledTimes(1);
    // quem abriu embutido não fecha a janela: o descarte volta o e-mail ao texto com que abriu (revisor, #28)
    expect(screen.getByLabelText("Corpo da mensagem").textContent).toBe("Bom dia.");
    cleanup();

    const aoDescartar2 = vi.fn();
    render(<ComporEmail ocupado={false} anexos={[]} aoEnviar={() => {}} aoDescartar={aoDescartar2} inicial={inicial} />);
    fireEvent.click(screen.getByRole("button", { name: "Descartar" }));
    expect(aoDescartar2).toHaveBeenCalledTimes(1);
  });

  it("e-mail editado e não enviado pede confirmação ao trocar de tela (issue #27)", async () => {
    api.mockResolvedValue([]);
    window.history.replaceState(null, "", "/notas/envio/3");
    const confirmar = vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<ComporEmail ocupado={false} anexos={[]} aoEnviar={() => {}} aoDescartar={() => {}}
      inicial={{ para: ["a@b.com"], copia: [], cco: [], assunto: "Emissão NF", corpo: "Bom dia." }} />);
    ir({ tela: "avisos" });   // intacto: não pergunta
    expect(confirmar).not.toHaveBeenCalled();
    window.history.replaceState(null, "", "/notas/envio/3");
    fireEvent.change(screen.getByLabelText("Assunto"), { target: { value: "Outro assunto" } });
    ir({ tela: "avisos" });
    expect(confirmar).toHaveBeenCalledTimes(1);
    expect(window.location.pathname).toBe("/notas/envio/3");
    ir({ tela: "avisos" }, { forcar: true });   // desfecho de ação concluída: não pergunta
    expect(confirmar).toHaveBeenCalledTimes(1);
    expect(window.location.pathname).toBe("/avisos");
    vi.restoreAllMocks();
  });
});

// issue #191: formatação como no Outlook (barra na seleção e fixa acima do corpo)
describe("ComporEmail: formatação do corpo", () => {
  const exec = vi.fn((..._a: unknown[]) => true);
  beforeEach(() => {
    api.mockResolvedValue([]);
    Object.defineProperty(document, "execCommand", { value: exec, configurable: true, writable: true });
  });
  afterEach(() => { cleanup(); api.mockReset(); exec.mockClear(); });

  const abrir = (aoEnviar = vi.fn()) => {
    render(<ComporEmail ocupado={false} anexos={[]} aoEnviar={aoEnviar} aoDescartar={() => {}}
      inicial={{ para: ["a@lotufo.com"], copia: [], cco: [], assunto: "Emissão NF", corpo: "Bom dia.\n\nSegue a nota." }} />);
    return screen.getByLabelText("Corpo da mensagem");
  };
  const comandos = () => exec.mock.calls.filter(c => c[0] !== "styleWithCSS").map(c => [c[0], c[2]]);

  it("barra fixa acima do corpo tem os efeitos do Outlook, em português", () => {
    abrir();
    const barra = screen.getByRole("toolbar", { name: "Formatação" });
    for (const nome of ["Negrito", "Itálico", "Sublinhado", "Tachado", "Cor da fonte", "Realce", "Lista com marcadores",
      "Lista numerada", "Limpar formatação"]) expect(within(barra).getByRole("button", { name: nome })).toBeTruthy();
    fireEvent.click(within(barra).getByRole("button", { name: "Realce" }));
    for (const nome of ["Amarelo", "Verde", "Azul-claro", "Rosa", "Sem realce"])
      expect(within(barra).getByRole("button", { name: nome })).toBeTruthy();
  });

  it("selecionar um trecho mostra a barra perto da seleção, que aplica negrito e cor", () => {
    const corpo = abrir();
    expect(screen.queryByRole("toolbar", { name: "Formatação da seleção" })).toBeNull();
    const r = document.createRange();
    r.selectNodeContents(corpo.firstChild!);
    document.getSelection()!.removeAllRanges();
    document.getSelection()!.addRange(r);
    fireEvent.mouseUp(corpo);
    const barra = screen.getByRole("toolbar", { name: "Formatação da seleção" });
    fireEvent.click(within(barra).getByRole("button", { name: "Negrito" }));
    fireEvent.click(within(barra).getByRole("button", { name: "Cor da fonte" }));
    fireEvent.click(within(barra).getByRole("button", { name: "Vermelho" }));
    expect(comandos()).toEqual([["bold", undefined], ["foreColor", "#FF0000"]]);
    // a cor sai em <span style> (o que o servidor aceita); o negrito em <b>
    expect(exec.mock.calls.filter(c => c[0] === "styleWithCSS").map(c => c[2])).toEqual(["false", "true"]);
    // selecao desfeita: a barra some
    document.getSelection()!.collapse(corpo.firstChild!, 0);
    fireEvent.mouseUp(corpo);
    expect(screen.queryByRole("toolbar", { name: "Formatação da seleção" })).toBeNull();
  });

  it("atalhos Ctrl+B, Ctrl+I e Ctrl+U (Cmd no Mac)", () => {
    const corpo = abrir();
    fireEvent.keyDown(corpo, { key: "b", ctrlKey: true });
    fireEvent.keyDown(corpo, { key: "i", metaKey: true });
    fireEvent.keyDown(corpo, { key: "u", ctrlKey: true });
    fireEvent.keyDown(corpo, { key: "b" });
    expect(comandos()).toEqual([["bold", undefined], ["italic", undefined], ["underline", undefined]]);
  });

  it("corpo formatado vai em HTML; intacto, vai o texto pré-montado", async () => {
    const aoEnviar = vi.fn();
    const corpo = abrir(aoEnviar);
    expect(corpo.innerHTML).toBe("<div>Bom dia.</div><div><br></div><div>Segue a nota.</div>");
    fireEvent.click(screen.getByRole("button", { name: "Enviar" }));
    await waitFor(() => expect(aoEnviar).toHaveBeenCalledTimes(1));
    expect(aoEnviar.mock.calls[0][0].corpo).toBe("Bom dia.\n\nSegue a nota.");
    escrever(corpo, '<div>Bom dia.</div><div>Segue a <b>nota</b> <span style="color: rgb(255, 0, 0);">hoje</span>.</div>');
    fireEvent.click(screen.getByRole("button", { name: "Enviar" }));
    await waitFor(() => expect(aoEnviar).toHaveBeenCalledTimes(2));
    expect(aoEnviar.mock.calls[1][0].corpo).toBe(
      '<div>Bom dia.</div><div>Segue a <b>nota</b> <span style="color: rgb(255, 0, 0);">hoje</span>.</div>');
  });

  it("corpo apagado e redigitado sem linha nova vai embrulhado, para o servidor não o escapar de novo", async () => {
    const aoEnviar = vi.fn();
    const corpo = abrir(aoEnviar);
    escrever(corpo, "Segue NF &amp; boleto");
    fireEvent.click(screen.getByRole("button", { name: "Enviar" }));
    await waitFor(() => expect(aoEnviar).toHaveBeenCalled());
    expect(aoEnviar.mock.calls[0][0].corpo).toBe("<div>Segue NF &amp; boleto</div>");
  });

  it("seleção que saiu do corpo não volta no clique da barra", () => {
    const corpo = abrir();
    const r = document.createRange();
    r.selectNodeContents(corpo.firstChild!);
    document.getSelection()!.removeAllRanges();
    document.getSelection()!.addRange(r);
    fireEvent.mouseUp(corpo);
    const assunto = screen.getByLabelText("Assunto");
    assunto.focus();
    document.getSelection()!.selectAllChildren(assunto.parentElement!);
    document.dispatchEvent(new Event("selectionchange"));
    fireEvent.click(within(screen.getByRole("toolbar", { name: "Formatação" })).getByRole("button", { name: "Negrito" }));
    // o negrito vale para o que se digitar em seguida (cursor no corpo), e nao para o trecho selecionado antes
    expect(document.getSelection()!.toString()).toBe("");
    expect(comandos()).toEqual([["bold", undefined]]);
  });

  it("colar do Word ou do Outlook mantém só a formatação da lista fechada", () => {
    const corpo = abrir();
    const word = '<html><head><style>p{font-family:Calibri}</style></head><body><!--StartFragment-->'
      + '<p class="MsoNormal" style="margin:0;font-size:11pt"><b><span style="font-size:14pt;color:#C00000">Atenção</span></b>'
      + '<span style="background:yellow"> prazo</span><o:p></o:p><img src="x" onerror="alert(1)">'
      + '<a href="https://x.exemplo.com.br">link</a><script>alert(2)</script></p></body></html>';
    fireEvent.paste(corpo, { clipboardData: { getData: (t: string) => (t === "text/html" ? word : "texto") } });
    expect(comandos()).toEqual([["insertHTML",
      '<p><b><span style="color: rgb(192, 0, 0)">Atenção</span></b><span style="background-color: yellow"> prazo</span>link</p>']]);
  });

  // revisor na PR #195: arrastar de outra janela e soltar no corpo passa pela mesma limpeza do colar
  it("arrastar e soltar de fora mantém só a formatação da lista fechada", () => {
    const corpo = abrir();
    const html = '<p style="font-size:30pt"><b>Prazo</b> <a href="https://x.exemplo.com.br">aqui</a><img src="https://x.exemplo.com.br/a.png"></p>';
    fireEvent.drop(corpo, { dataTransfer: { getData: (t: string) => (t === "text/html" ? html : "") } });
    expect(comandos()).toEqual([["insertHTML", "<p><b>Prazo</b> aqui</p>"]]);
    exec.mockClear();
    fireEvent.drop(corpo, { dataTransfer: { getData: (t: string) => (t === "text/plain" ? "só texto" : "") } });
    expect(comandos()).toEqual([["insertText", "só texto"]]);
  });

  // revisor na PR #195 (rodada 2): mover uma linha dentro do corpo apaga o no' de origem e o dragend nao chega;
  // o proximo soltar de fora tem de passar pela limpeza do mesmo jeito
  it("depois de mover um trecho dentro do corpo, soltar de fora continua limpo", () => {
    const corpo = abrir();
    fireEvent.dragStart(corpo);
    fireEvent.drop(corpo, { dataTransfer: { getData: () => "Bom dia." } });      // interno: fica com o navegador
    expect(comandos()).toEqual([]);
    const html = '<p><b>Prazo</b><img src="https://x.exemplo.com.br/a.png"></p>';
    fireEvent.drop(corpo, { dataTransfer: { getData: (t: string) => (t === "text/html" ? html : "") } });
    expect(comandos()).toEqual([["insertHTML", "<p><b>Prazo</b></p>"]]);
  });
});

describe("limparHtml", () => {
  it("lista fechada: tags e só cor e realce no span", () => {
    expect(limparHtml('<b onclick="x()">a</b><strike>b</strike><font color="#0070c0">c</font>'
      + '<span style="position:fixed;color:red">d</span><span style="color:url(javascript:x)">e</span><div>f</div>'))
      .toBe('<b>a</b><s>b</s><span style="color: #0070c0">c</span><span style="color: red">d</span>e<div>f</div>');
  });

  // gate Sol S3 (PR #195): os mesmos blocos que o servidor transforma em linha
  it("blocos consecutivos (citação, seção, pre) viram linhas, como no servidor", () => {
    expect(limparHtml("<blockquote>Primeiro</blockquote><blockquote>Segundo</blockquote><section>Terceiro</section>"
      + "<pre>Quarto</pre><dl><dt>Quinto</dt><dd>Sexto</dd></dl><noembed>fora</noembed>"))
      .toBe("<div>Primeiro</div><div>Segundo</div><div>Terceiro</div><div>Quarto</div><div>Quinto</div><div>Sexto</div>");
  });

  it("tabela e título colados viram linhas, e não texto grudado", () => {
    expect(limparHtml("<h2>Itens</h2><table><tr><td>Item 1</td><td>R$ 100,00</td></tr></table>"))
      .toBe("<div>Itens</div><div><div><div>Item 1</div><div>R$ 100,00</div></div></div>");
  });
});
