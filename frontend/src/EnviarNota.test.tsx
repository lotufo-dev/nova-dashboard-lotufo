import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiErro } from "./api";
import EnviarNota from "./EnviarNota";

const { api, apiForm } = vi.hoisted(() => ({ api: vi.fn(), apiForm: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api, apiForm }));

// o corpo do e-mail e' um editor (contentEditable, issue #191): escrever = trocar o conteudo e avisar como o navegador
function escrever(corpo: HTMLElement, texto: string) {
  corpo.textContent = texto;
  fireEvent.input(corpo);
}

const det = {
  envio: { chave: "c20:m631-m632", contrato_id: 20, obra: "MT-401", orgao: "SINFRA", orgao_sub: "SUEF II", familia: "sinfra",
    grupo: "SINFRA", a_pedido: false, medicao_ids: [631, 632], descricao: "7ª medição + reajuste", notas: [],
    valor_centavos: 100, emitida_em: "2026-10-08", dias: 2, situacao: "pronto", aviso: null, protocolo_id: 3, itens: [] },
  familia: "sinfra", etapa: "nota", situacao_protocolo: "rascunho", carta: null,
  previa: { para: ["orgao@exemplo.com"], copia: [], assunto: "Notas", corpo: "Bom dia.", anexos: [], links: [] },
  bloqueio: null, pendencias: [] as string[], extras: [],
};

describe("Enviar a nota", () => {
  afterEach(() => { cleanup(); api.mockReset(); apiForm.mockReset(); });

  it("o Cco escrito no e-mail vai no envio (testes de quebra 10/10, A-17)", async () => {
    api.mockImplementation((caminho: string) => {
      if (caminho === "/api/notas/envio/3") return Promise.resolve(det);
      if (caminho.startsWith("/api/correio/remetente")) return Promise.resolve({ remetente: "eu@lotufo.com" });
      return Promise.resolve({});
    });
    render(<EnviarNota protocoloId={3} podeEditar embutido={{ aoConcluir: () => {}, aoTrocar: () => {} }} />);
    fireEvent.click(await screen.findByText("Cco"));
    const cco = screen.getByLabelText(/Cco: digite/);
    fireEvent.change(cco, { target: { value: "oculto@exemplo.com" } });
    fireEvent.blur(cco);
    fireEvent.click(screen.getByRole("button", { name: "Enviar o e-mail" }));
    await waitFor(() => expect(api.mock.calls.some(c => c[0] === "/api/notas/envio/3/enviar")).toBe(true));
    const [, opcoes] = api.mock.calls.find(c => c[0] === "/api/notas/envio/3/enviar")!;
    expect(JSON.parse(opcoes.body).cco).toEqual(["oculto@exemplo.com"]);
  });

  it("ao concluir o envio embutido, avisa a página com a hora (B-06, 10/10/2026)", async () => {
    api.mockImplementation((caminho: string) => Promise.resolve(caminho === "/api/notas/envio/3" ? det : {}));
    const aoConcluir = vi.fn();
    render(<EnviarNota protocoloId={3} podeEditar embutido={{ aoConcluir, aoTrocar: () => {} }} />);
    fireEvent.click(await screen.findByRole("button", { name: "Enviar o e-mail" }));
    await waitFor(() => expect(aoConcluir).toHaveBeenCalled());
    expect(aoConcluir.mock.calls[0][0]).toMatch(/^Nota enviada às \d{2}:\d{2}\.$/);
  });

  it("diretoria vê o que vai no envio, sem e-mail, anexos nem registro por fora (B-09, 10/10/2026)", async () => {
    api.mockImplementation((caminho: string) => Promise.resolve(caminho === "/api/notas/envio/3" ? det : {}));
    render(<EnviarNota protocoloId={3} podeEditar={false} embutido={{ aoConcluir: () => {}, aoTrocar: () => {} }} />);
    expect(await screen.findByText("O que vai no e-mail")).toBeTruthy();
    expect(screen.queryByText(/Seu perfil só consulta esta tela/)).toBeNull();
    expect(screen.queryByRole("button", { name: "Enviar o e-mail" })).toBeNull();
    expect(screen.queryByText("Anexar outro documento")).toBeNull();
    expect(screen.queryByText("Registrar envio feito por fora")).toBeNull();
    expect(screen.queryByRole("button", { name: /Juntar outra nota/ })).toBeNull();
  });

  // issue #213 (decisão do Leo de 16/10/2026): documento faltando não bloqueia; o Enviar abre o aviso com a lista
  describe("aviso do que falta", () => {
    const FALTAM = ["FRC assinada não anexada", "Falta a certidão federal"];
    const enviados = () => api.mock.calls.filter(c => c[0] === "/api/notas/envio/3/enviar");

    it("abre o ATENÇÃO com a lista; Cancelar não envia nada", async () => {
      api.mockImplementation((caminho: string) => Promise.resolve(caminho === "/api/notas/envio/3"
        ? { ...det, pendencias: FALTAM } : {}));
      render(<EnviarNota protocoloId={3} podeEditar embutido={{ aoConcluir: () => {}, aoTrocar: () => {} }} />);
      const botao = await screen.findByRole("button", { name: "Enviar o e-mail" }) as HTMLButtonElement;
      expect(botao.disabled).toBe(false);
      expect(screen.queryByLabelText(/Justificativa/)).toBeNull();
      fireEvent.click(botao);
      const aviso = screen.getByRole("alertdialog", { name: "ATENÇÃO" });
      expect(within(aviso).getByText("Faltam 2 itens neste envio:")).toBeTruthy();
      for (const f of FALTAM) expect(within(aviso).getByText(f)).toBeTruthy();
      expect(within(aviso).getByText("Deseja continuar com o envio?")).toBeTruthy();
      expect(document.activeElement).toBe(within(aviso).getByRole("button", { name: "Cancelar" }));
      fireEvent.click(within(aviso).getByRole("button", { name: "Cancelar" }));
      expect(screen.queryByRole("alertdialog")).toBeNull();
      expect(enviados()).toHaveLength(0);
    });

    it("Continuar com o envio manda a lista confirmada", async () => {
      api.mockImplementation((caminho: string) => Promise.resolve(caminho === "/api/notas/envio/3"
        ? { ...det, pendencias: FALTAM } : {}));
      const aoConcluir = vi.fn();
      render(<EnviarNota protocoloId={3} podeEditar embutido={{ aoConcluir, aoTrocar: () => {} }} />);
      fireEvent.click(await screen.findByRole("button", { name: "Enviar o e-mail" }));
      fireEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Continuar com o envio" }));
      await waitFor(() => expect(aoConcluir).toHaveBeenCalled());
      expect(JSON.parse(enviados()[0][1].body).confirmadas).toEqual(FALTAM);
    });

    it("sem nada faltando não há aviso, e o envio não leva confirmação", async () => {
      api.mockImplementation((caminho: string) => Promise.resolve(caminho === "/api/notas/envio/3" ? det : {}));
      render(<EnviarNota protocoloId={3} podeEditar embutido={{ aoConcluir: () => {}, aoTrocar: () => {} }} />);
      fireEvent.click(await screen.findByRole("button", { name: "Enviar o e-mail" }));
      expect(screen.queryByRole("alertdialog")).toBeNull();
      await waitFor(() => expect(enviados()).toHaveLength(1));
      expect(JSON.parse(enviados()[0][1].body).confirmadas).toBeNull();
    });

    it("bloqueio continua desabilitando o envio, sem aviso", async () => {
      api.mockImplementation((caminho: string) => Promise.resolve(caminho === "/api/notas/envio/3"
        ? { ...det, bloqueio: "FRC assinada recusada", pendencias: FALTAM } : {}));
      render(<EnviarNota protocoloId={3} podeEditar embutido={{ aoConcluir: () => {}, aoTrocar: () => {} }} />);
      const botao = await screen.findByRole("button", { name: "Enviar o e-mail" }) as HTMLButtonElement;
      expect(botao.disabled).toBe(true);
      fireEvent.click(botao);
      expect(screen.queryByRole("alertdialog")).toBeNull();
      expect(enviados()).toHaveLength(0);
    });

    it("a lista mudou no servidor: o aviso abre de novo com a lista nova e pede nova confirmação", async () => {
      const NOVA = [...FALTAM, "Falta a regularidade"];
      let leituras = 0;
      api.mockImplementation((caminho: string) => {
        if (caminho === "/api/notas/envio/3") { leituras += 1; return Promise.resolve({ ...det, pendencias: leituras > 1 ? NOVA : FALTAM }); }
        if (caminho === "/api/notas/envio/3/enviar" && enviados().length === 1) {
          return Promise.reject(new ApiErro(422, "A lista do que falta mudou", { codigo: "CONFIRMAR_PENDENCIAS", pendencias: NOVA }));
        }
        return Promise.resolve({});
      });
      const aoConcluir = vi.fn();
      render(<EnviarNota protocoloId={3} podeEditar embutido={{ aoConcluir, aoTrocar: () => {} }} />);
      fireEvent.click(await screen.findByRole("button", { name: "Enviar o e-mail" }));
      fireEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Continuar com o envio" }));
      const aviso = await screen.findByText(/mudou desde a sua confirmação/);
      const caixa = aviso.closest("[role=alertdialog]") as HTMLElement;
      expect(within(caixa).getByText("Falta a regularidade")).toBeTruthy();
      expect(aoConcluir).not.toHaveBeenCalled();
      fireEvent.click(within(caixa).getByRole("button", { name: "Continuar com o envio" }));
      await waitFor(() => expect(aoConcluir).toHaveBeenCalled());
      expect(JSON.parse(enviados()[1][1].body).confirmadas).toEqual(NOVA);
    });
  });

  it("o link do OneDrive não tem frase de ajuda: o servidor recusa o endereço errado (testes de quebra 10/10, A-13)", async () => {
    api.mockImplementation((caminho: string) => Promise.resolve(caminho === "/api/notas/envio/3" ? det : {}));
    render(<EnviarNota protocoloId={3} podeEditar embutido={{ aoConcluir: () => {}, aoTrocar: () => {} }} />);
    expect(await screen.findByText("Arquivo grande por link do OneDrive")).toBeTruthy();
    expect(screen.queryByText(/link de outro endereço é recusado|25 MB somados|Vai como anexo separado|O e-mail sai da sua conta/)).toBeNull();
    // issue #118: o endereço permitido é do servidor (DASH_SHAREPOINT_HOSTS); a tela não traz o tenant da empresa
    expect(document.body.innerHTML).not.toMatch(/[a-z0-9-]+(-my)?\.sharepoint\.com/i);
  });

  // issue #100: como no protocolo (PR #92), o Enviar leva os anexos que a prévia mostrou, para o servidor recusar se mudaram
  describe("anexos da prévia", () => {
    const NF = { nome: "NFS 2301.pdf", origem: "nota", tamanho: 10 };
    const FRC = { nome: "FRC 77.pdf", origem: "nota", tamanho: 20 };
    const AVISO = "A prévia foi refeita com os anexos de agora e o texto voltou ao padrão; confira antes de enviar.";
    const comFrc = (anexos: object[]) => ({ ...det,
      envio: { ...det.envio, itens: [{ chave: "frc", rotulo: "FRC assinada", estado: "falta", acao: "anexar_frc", medicao_id: 631 }] },
      previa: { ...det.previa, anexos } });

    it("o envio leva nome e tamanho dos anexos mostrados na prévia", async () => {
      api.mockImplementation((caminho: string) => Promise.resolve(caminho === "/api/notas/envio/3" ? comFrc([NF]) : {}));
      render(<EnviarNota protocoloId={3} podeEditar embutido={{ aoConcluir: () => {}, aoTrocar: () => {} }} />);
      fireEvent.click(await screen.findByRole("button", { name: "Enviar o e-mail" }));
      await waitFor(() => expect(api.mock.calls.some(c => c[0] === "/api/notas/envio/3/enviar")).toBe(true));
      const [, opcoes] = api.mock.calls.find(c => c[0] === "/api/notas/envio/3/enviar")!;
      expect(JSON.parse(opcoes.body).anexos).toEqual([{ nome: "NFS 2301.pdf", tamanho: 10 }]);
    });

    it("anexar a FRC com a prévia aberta fecha a prévia: o e-mail editado é refeito com os anexos novos", async () => {
      let atual = comFrc([NF]);
      api.mockImplementation((caminho: string) => Promise.resolve(caminho === "/api/notas/envio/3" ? atual : {}));
      apiForm.mockImplementation(async () => { atual = comFrc([NF, FRC]); return {}; });
      render(<EnviarNota protocoloId={3} podeEditar embutido={{ aoConcluir: () => {}, aoTrocar: () => {} }} />);
      const assunto = await screen.findByLabelText("Assunto") as HTMLInputElement;
      fireEvent.change(assunto, { target: { value: "Assunto editado antes do anexo" } });
      const pdf = new File(["%PDF-1.4"], "FRC 77.pdf", { type: "application/pdf" });
      fireEvent.change(screen.getByLabelText("Anexar FRC assinada"), { target: { files: [pdf] } });
      await waitFor(() => expect(within(screen.getByRole("list", { name: "Anexos" })).queryByText("FRC 77.pdf")).toBeTruthy());
      expect((screen.getByLabelText("Assunto") as HTMLInputElement).value).toBe("Notas");
      fireEvent.click(screen.getByRole("button", { name: "Enviar o e-mail" }));
      await waitFor(() => expect(api.mock.calls.some(c => c[0] === "/api/notas/envio/3/enviar")).toBe(true));
      const [, opcoes] = api.mock.calls.find(c => c[0] === "/api/notas/envio/3/enviar")!;
      expect(JSON.parse(opcoes.body).anexos).toEqual([{ nome: "NFS 2301.pdf", tamanho: 10 }, { nome: "FRC 77.pdf", tamanho: 20 }]);
    });

    it("envio recusado porque a FRC entrou em outra aba recarrega e mostra a prévia nova, com o aviso", async () => {
      let atual = comFrc([NF]);
      const RECUSA = "Os anexos mudaram depois da prévia: descarte esta prévia e abra outra para conferir o que vai no e-mail";
      api.mockImplementation((caminho: string) => {
        if (caminho === "/api/notas/envio/3") return Promise.resolve(atual);
        if (caminho === "/api/notas/envio/3/enviar") { atual = comFrc([NF, FRC]); return Promise.reject(new ApiErro(422, RECUSA, { codigo: "ANEXOS_MUDARAM", mensagem: RECUSA })); }
        return Promise.resolve({});
      });
      render(<EnviarNota protocoloId={3} podeEditar embutido={{ aoConcluir: () => {}, aoTrocar: () => {} }} />);
      escrever(await screen.findByLabelText("Corpo da mensagem"), "Bom dia. Segue com a observação do fiscal.");
      expect(screen.queryByText(AVISO)).toBeNull();
      fireEvent.click(screen.getByRole("button", { name: "Enviar o e-mail" }));
      expect(await screen.findByText(RECUSA)).toBeTruthy();
      await waitFor(() => expect(within(screen.getByRole("list", { name: "Anexos" })).queryByText("FRC 77.pdf")).toBeTruthy());
      // revisor na PR #141: o texto editado se perdeu na prévia nova; a tela diz isso antes do próximo Enviar
      expect(screen.getByLabelText("Corpo da mensagem").textContent).toBe("Bom dia.");
      expect(screen.getAllByRole("status").some(x => x.textContent?.endsWith(AVISO))).toBe(true);
    });

    it("documento novo da medição avisado pela página (versao) relê o envio e refaz a prévia com o aviso", async () => {
      let atual = comFrc([NF]);
      api.mockImplementation((caminho: string) => Promise.resolve(caminho === "/api/notas/envio/3" ? atual : {}));
      const props = { protocoloId: 3, podeEditar: true, embutido: { aoConcluir: () => {}, aoTrocar: () => {} } };
      const { rerender } = render(<EnviarNota {...props} versao={0} />);
      await screen.findByRole("button", { name: "Enviar o e-mail" });
      atual = comFrc([NF, FRC]);
      rerender(<EnviarNota {...props} versao={1} />);
      await waitFor(() => expect(within(screen.getByRole("list", { name: "Anexos" })).queryByText("FRC 77.pdf")).toBeTruthy());
      expect(screen.getByText(AVISO)).toBeTruthy();
    });

    // gate Sol S2 (PR #141): 409 de envio em andamento (a outra aba enviou) nao relê o envio nem apaga o texto editado
    it("outro erro de envio mantém o e-mail editado e não relê o envio", async () => {
      api.mockImplementation((caminho: string) => {
        if (caminho === "/api/notas/envio/3") return Promise.resolve(comFrc([NF]));
        if (caminho === "/api/notas/envio/3/enviar") return Promise.reject(new ApiErro(409, "Envio em andamento por Admin.",
          { codigo: "ENVIO_RESERVADO", mensagem: "Envio em andamento por Admin.", reservado_em: null, reservado_por_nome: "Admin", liberavel_a_partir_de: null }));
        return Promise.resolve({});
      });
      render(<EnviarNota protocoloId={3} podeEditar embutido={{ aoConcluir: () => {}, aoTrocar: () => {} }} />);
      escrever(await screen.findByLabelText("Corpo da mensagem"), "Bom dia. Com a observação do fiscal.");
      fireEvent.click(screen.getByRole("button", { name: "Enviar o e-mail" }));
      expect(await screen.findByText("Envio em andamento por Admin.")).toBeTruthy();
      expect(api.mock.calls.filter(c => c[0] === "/api/notas/envio/3")).toHaveLength(1);
      expect(screen.getByLabelText("Corpo da mensagem").textContent).toBe("Bom dia. Com a observação do fiscal.");
    });

    // gate Sol S3 (PR #141): a conferência do servidor não depende da ordem; a tela também não
    it("os mesmos anexos em outra ordem não refazem a prévia nem mostram o aviso", async () => {
      let atual = comFrc([NF, FRC]);
      api.mockImplementation((caminho: string) => Promise.resolve(caminho === "/api/notas/envio/3" ? atual : {}));
      const props = { protocoloId: 3, podeEditar: true, embutido: { aoConcluir: () => {}, aoTrocar: () => {} } };
      const { rerender } = render(<EnviarNota {...props} versao={0} />);
      const assunto = await screen.findByLabelText("Assunto") as HTMLInputElement;
      fireEvent.change(assunto, { target: { value: "Assunto editado" } });
      atual = comFrc([FRC, NF]);
      rerender(<EnviarNota {...props} versao={1} />);
      await waitFor(() => expect(api.mock.calls.filter(c => c[0] === "/api/notas/envio/3")).toHaveLength(2));
      await waitFor(() => expect(within(screen.getByRole("list", { name: "Anexos" })).getAllByRole("listitem")[0].textContent).toContain("FRC 77.pdf"));
      expect((screen.getByLabelText("Assunto") as HTMLInputElement).value).toBe("Assunto editado");
      expect(screen.queryByText(AVISO)).toBeNull();
    });
  });

  // issue #148: a FRC aparece em "O que vai no e-mail" com a situação certa
  describe("FRC em O que vai no e-mail", () => {
    const itemFrc = (extra: object) => ({ ...det, envio: { ...det.envio, itens: [
      { chave: "frc:631", rotulo: "FRC assinada", medicao_id: 631, ...extra }] } });
    const secao = () => screen.getByRole("region", { name: "O que vai no e-mail" });

    it("gerada e sem a assinada: diz que falta a assinada e oferece baixar a gerada", async () => {
      api.mockImplementation((caminho: string) => Promise.resolve(caminho === "/api/notas/envio/3" ? itemFrc({
        estado: "falta", acao: "anexar_frc", frc_gerada: 77,
        detalhe: "Falta a assinada: baixe a FRC gerada, assine no DocuSign e anexe aqui" }) : {}));
      render(<EnviarNota protocoloId={3} podeEditar embutido={{ aoConcluir: () => {}, aoTrocar: () => {} }} />);
      await screen.findByText("O que vai no e-mail");
      expect(within(secao()).getByText(/Falta a assinada/)).toBeTruthy();
      const link = within(secao()).getByRole("link", { name: "Baixar a FRC gerada (nº 77)" });
      expect(link.getAttribute("href")).toBe("/api/medicoes/631/frc/pdf");
      expect(within(secao()).getByLabelText("Anexar FRC assinada")).toBeTruthy();
    });

    it("quem só consulta também vê o link da FRC gerada", async () => {
      api.mockImplementation((caminho: string) => Promise.resolve(caminho === "/api/notas/envio/3" ? itemFrc({
        estado: "falta", acao: "anexar_frc", frc_gerada: 77, detalhe: "Falta a assinada" }) : {}));
      render(<EnviarNota protocoloId={3} podeEditar={false} embutido={{ aoConcluir: () => {}, aoTrocar: () => {} }} />);
      await screen.findByText("O que vai no e-mail");
      expect(within(secao()).getByRole("link", { name: "Baixar a FRC gerada (nº 77)" })).toBeTruthy();
    });

    it("assinada anexada: mostra pronta, sem o link da gerada", async () => {
      api.mockImplementation((caminho: string) => Promise.resolve(caminho === "/api/notas/envio/3" ? itemFrc({
        estado: "ok", acao: null, frc_gerada: 77, detalhe: "Assinada anexada · FRC 77 assinada.pdf" }) : {}));
      render(<EnviarNota protocoloId={3} podeEditar embutido={{ aoConcluir: () => {}, aoTrocar: () => {} }} />);
      await screen.findByText("O que vai no e-mail");
      expect(within(secao()).getByText("Assinada anexada · FRC 77 assinada.pdf")).toBeTruthy();
      expect(within(secao()).getByTitle("Pronto")).toBeTruthy();
      expect(within(secao()).queryByRole("link", { name: /Baixar a FRC gerada/ })).toBeNull();
    });
  });

  it("remover documento complementar ou link pede confirmação antes do pedido (issue #28)", async () => {
    const comExtras = { ...det, extras: [{ id: 41, nome: "justificativa.pdf", tamanho: 4096 }],
      previa: { ...det.previa, links: [{ id: 5, nome: "relatorios.zip", url: "https://lotufoengmt.sharepoint.com/x" }] } };
    api.mockImplementation((caminho: string) => Promise.resolve(caminho === "/api/notas/envio/3" ? comExtras : {}));
    render(<EnviarNota protocoloId={3} podeEditar embutido={{ aoConcluir: () => {}, aoTrocar: () => {} }} />);
    fireEvent.click(await screen.findByRole("button", { name: "Remover justificativa.pdf" }));
    fireEvent.click(screen.getByRole("button", { name: "Remover o link relatorios.zip" }));
    expect(api.mock.calls.some(c => String(c[0]).endsWith("/remover"))).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: /Confirmar a remoção:\s*justificativa\.pdf/ }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/protocolos/3/pecas/41/remover", expect.objectContaining({ method: "POST" })));
    fireEvent.click(screen.getByRole("button", { name: /Confirmar a remoção:\s*o link relatorios\.zip/ }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/protocolos/3/links/5/remover", expect.objectContaining({ method: "POST" })));
  });

  it("com o e-mail editado, a confirmação de remover avisa que o texto será montado de novo (revisor, #28)", async () => {
    const comExtras = { ...det, extras: [{ id: 41, nome: "justificativa.pdf", tamanho: 4096 }] };
    api.mockImplementation((caminho: string) => Promise.resolve(caminho === "/api/notas/envio/3" ? comExtras : {}));
    render(<EnviarNota protocoloId={3} podeEditar embutido={{ aoConcluir: () => {}, aoTrocar: () => {} }} />);
    fireEvent.click(await screen.findByRole("button", { name: "Remover justificativa.pdf" }));
    expect(screen.queryByText(/será montado de novo/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));
    escrever(screen.getByLabelText("Corpo da mensagem"), "Bom dia, texto meu.");
    fireEvent.click(screen.getByRole("button", { name: "Remover justificativa.pdf" }));
    expect(screen.getByText("O texto do e-mail que você editou será montado de novo.")).toBeTruthy();
  });
});
