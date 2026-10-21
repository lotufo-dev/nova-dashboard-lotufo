import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Contratos from "./Contratos";
import type { ObraLista } from "./listaObras";
import { useRota } from "./rota";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

// Dados sintéticos: dois contratantes (SINFRA com duas superintendências, MTPAR) e uma obra encerrada.
const obra = (id: number, nome: string, extra: Partial<ObraLista> = {}): ObraLista => ({
  id, orgao: "SINFRA - SUEF II", contratante: "SINFRA", orgao_sub: "SUEF II", numero_instrumento: `IC ${id}/2026`, nome_curto: nome,
  estado: "ativo", entidade_id: 1, valor_vigente_centavos: 1000_00, medido_execucao_centavos: 250_00, saldo_centavos: 750_00,
  execucao_fim_vigente: "2027-03-31", vigencia_fim_vigente: "2027-06-30", dias_execucao: 100, dias_vigencia: 200, ...extra });

const OBRAS: ObraLista[] = [
  obra(1, "Estações BRT"),
  obra(2, "MT-388", { orgao: "SINFRA - SUPU", orgao_sub: "SUPU", valor_vigente_centavos: 3000_00, medido_execucao_centavos: 1500_00, saldo_centavos: 1500_00 }),
  obra(3, "Granito", { orgao: "MTPAR", contratante: "MTPAR", orgao_sub: null, valor_vigente_centavos: 2000_00, medido_execucao_centavos: 500_00,
    saldo_centavos: 1500_00, estado: "suspenso", execucao_fim_vigente: "2026-12-31" }),
  obra(4, "Deciolândia", { orgao: "MTPAR", contratante: "MTPAR", orgao_sub: null, estado: "encerrado", execucao_fim_vigente: "2025-12-31" }),
];

const AVISOS = [
  { tipo: "execucao_vencendo", nivel: "critico", publico: ["operacao"], contrato_id: 1, obra: "Estações BRT", dias: 5, valor_centavos: null,
    mensagem: "Estações BRT: execução termina em 5 dias (04/11/2026)", destino: { tela: "contrato", id: 1, aba: "prazos" }, data: "2026-11-04", sentido: "prazo" },
  { tipo: "vigencia_vencendo", nivel: "atencao", publico: ["operacao"], contrato_id: 1, obra: "Estações BRT", dias: 50, valor_centavos: null,
    mensagem: "Estações BRT: vigência termina em 50 dias (20/12/2026)", destino: { tela: "contrato", id: 1, aba: "prazos" }, data: "2026-12-20", sentido: "prazo" },
  { tipo: "documento_vencendo", nivel: "atencao", publico: ["operacao"], contrato_id: null, obra: null, entidade_id: 1, entidade: "Construtora Alfa",
    dias: 9, valor_centavos: null, mensagem: "Construtora Alfa: certidão vence em 9 dias", destino: null, data: "2026-10-25", sentido: "prazo" },
];

function Pagina() {
  const { busca, ir } = useRota();
  return <Contratos ir={ir} busca={busca} perfil="admin" />;
}

function abrir(url: string) {
  window.history.replaceState(null, "", url);
  return render(<Pagina />);
}

describe("Obras: escolha do contratante e lista", () => {
  beforeEach(() => {
    api.mockImplementation(async (caminho: string) => {
      if (caminho === "/api/contratos") return OBRAS;
      if (caminho === "/api/entidades") return [{ id: 1, nome: "Construtora Alfa Ltda", nome_curto: "Alfa" }];
      if (caminho === "/api/inicio") return { avisos: AVISOS };
      throw new Error(`chamada inesperada: ${caminho}`);
    });
  });
  afterEach(() => { cleanup(); api.mockReset(); window.history.replaceState(null, "", "/"); });

  it("a entrada escolhe o contratante: 'Todas as obras' primeiro, com a soma das linhas, e o saldo a executar", async () => {
    abrir("/obras");
    const linhas = await screen.findAllByRole("link", { name: /executado/ });
    expect(linhas).toHaveLength(3);
    expect(linhas[0].textContent).toContain("Todas as obras");
    // 3 obras em andamento (a encerrada fica de fora): vigente 6000,00 e medido 2250,00 -> 38%; saldo 3750,00
    expect(linhas[0].textContent).toContain("3 obras");
    expect(linhas[0].textContent).toContain("38%");
    expect(linhas[0].textContent).toMatch(/Saldo a executar \(valor cheio\)\s*R\$\s*3\.750,00/);
    // #262: a nota diz a base do saldo e do %: o vigente de execucao (sem o aditivo de reajuste)
    expect(screen.getByText(/saldo a executar = vigente de execução − medido \(execução\)/)).toBeTruthy();
    expect(linhas[1].textContent).toContain("MTPAR");
    expect(linhas[1].textContent).toContain("1 encerrada");
    expect(linhas[2].textContent).toContain("SINFRA");
    expect(linhas[2].textContent).toContain("2 obras");
    expect(linhas[2].textContent).toMatch(/Saldo a executar \(valor cheio\)\s*R\$\s*2\.250,00/);
    // os avisos do contratante: 1 obra com aviso, 1 crítico
    expect(linhas[2].textContent).toContain("1 com aviso");
    expect(linhas[2].textContent).toMatch(/1\scrítico/);
    expect(linhas[1].textContent).toContain("sem avisos");
    expect(linhas[2].getAttribute("href")).toBe("/obras?c=SINFRA");
    expect(linhas[0].getAttribute("href")).toBe("/obras?c=todas");
    expect(screen.getByRole("heading", { level: 1, name: "Contratantes" })).toBeTruthy();
    // o botão Avisos (N) leva à lista com os avisos abertos; o N é o de todas as obras (com o sem obra)
    expect(screen.getByRole("link", { name: "Avisos (3)" }).getAttribute("href")).toBe("/obras?c=todas&avisos=1");
  });

  it("a soma das linhas dos contratantes é a linha 'Todas as obras' (obras e saldo)", async () => {
    abrir("/obras");
    const linhas = await screen.findAllByRole("link", { name: /executado/ });
    const n = (el: HTMLElement) => Number(/(\d+) obras?/.exec(el.textContent!)![1]);
    const saldo = (el: HTMLElement) => Number(/R\$\s*([\d.]+),(\d\d)/.exec(el.textContent!)!.slice(1, 3).join("").replace(/\./g, ""));
    expect(n(linhas[1]) + n(linhas[2])).toBe(n(linhas[0]));
    expect(saldo(linhas[1]) + saldo(linhas[2])).toBe(saldo(linhas[0]));
  });

  it("o contratante abre a lista dele em cartões: nome, órgão, % em destaque, término e a linha de aviso", async () => {
    abrir("/obras?c=SINFRA");
    const lista = await screen.findByRole("list", { name: "Obras" });
    const cartoes = within(lista).getAllByRole("link");
    expect(cartoes).toHaveLength(2);                       // só as duas da SINFRA
    const brt = cartoes.find(c => c.textContent!.includes("Estações BRT"))!;
    expect(brt.getAttribute("href")).toBe("/obras/1");
    expect(brt.textContent).toContain("SINFRA - SUEF II");
    expect(brt.textContent).toContain("25%");
    expect(brt.textContent).toContain("executado");
    expect(brt.textContent).toContain("execução termina em 5 dias");   // o aviso mais grave, sem o nome da obra
    expect(brt.textContent).toContain("mais 1");
    expect(brt.textContent).toContain("termina em 31/03/2027");
    expect(brt.textContent).not.toContain("Ativo");        // o status só aparece quando não é "Ativo"
    expect(screen.getByRole("heading", { level: 1, name: "SINFRA" })).toBeTruthy();
    const caminho = screen.getByRole("navigation", { name: "Você está em" });
    expect(within(caminho).getByRole("link", { name: "Obras" }).getAttribute("href")).toBe("/obras");
    expect(caminho.textContent).toContain("SINFRA");
  });

  it("obra suspensa mostra o status e as encerradas só entram com o filtro", async () => {
    abrir("/obras?c=MTPAR");
    const lista = await screen.findByRole("list", { name: "Obras" });
    expect(within(lista).getAllByRole("link")).toHaveLength(1);
    expect(lista.textContent).toContain("Suspenso");
    expect(lista.textContent).toContain("Granito");
    expect(lista.textContent).not.toContain("Deciolândia");
    fireEvent.click(screen.getByRole("checkbox", { name: "Mostrar as encerradas" }));
    expect(window.location.search).toBe("?c=MTPAR&situacao=todas");
    const todas = await screen.findByRole("list", { name: "Obras" });
    expect(todas.textContent).toContain("Deciolândia");
    expect(todas.textContent).toContain("terminou em 31/12/2025");
  });

  it("a visão em tabela traz as colunas de hoje (e o Executado) e o endereço guarda a visão", async () => {
    abrir("/obras?c=SINFRA");
    await screen.findByRole("list", { name: "Obras" });
    fireEvent.click(screen.getByRole("link", { name: "tabela" }));
    expect(window.location.search).toBe("?c=SINFRA&ver=tabela");
    const tabela = await screen.findByRole("table");
    const cabecas = within(tabela).getAllByRole("columnheader").map(c => c.textContent);
    expect(cabecas).toEqual(["Obra", "Órgão", "Empresa", "Status", "Valor vigente", "Executado", "Fim da execução", "Fim da vigência",
      "Pedido de prorrogação", "Avisos"]);
    const brt = within(tabela).getAllByRole("row").find(r => r.textContent!.includes("Estações BRT"))!;
    expect(brt.textContent).toContain("Alfa");
    expect(brt.textContent).toContain("25%");
    expect(within(brt).getByRole("link", { name: /2 avisos de Estações BRT, 1 crítico/ }).getAttribute("href"))
      .toBe("/obras?c=SINFRA&ver=tabela&avisos=1&obra=1");
  });

  it("a busca acha pelo nome da empresa e o prazo 'terminam em 90 dias' filtra a lista", async () => {
    abrir("/obras?c=todas&q=alfa");
    const lista = await screen.findByRole("list", { name: "Obras" });
    expect(within(lista).getAllByRole("link")).toHaveLength(3);      // as três em andamento são da Alfa
    cleanup();
    abrir("/obras?c=todas&termina=90");
    expect(await screen.findByText("Nenhuma obra com esses filtros.")).toBeTruthy();   // as execuções acabam em 100 dias
    cleanup();
    abrir("/obras?c=todas&termina=180");
    const so180 = await screen.findByRole("list", { name: "Obras" });
    // 'Granito' está suspensa: a execução dela não vence, e a vigência (200 dias) fica de fora
    expect(within(so180).getAllByRole("link").map(a => a.textContent!.includes("Granito"))).toEqual([false, false]);
  });

  it("os Avisos abrem na própria página, do recorte do contratante, e se fecham", async () => {
    abrir("/obras?c=SINFRA");
    await screen.findByRole("list", { name: "Obras" });
    const botao = screen.getByRole("button", { name: "Avisos (2)" });   // só os da SINFRA (os sem obra ficam em Todas)
    expect(botao.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("heading", { name: /Avisos ·/ })).toBeNull();
    fireEvent.click(botao);
    expect(window.location.search).toBe("?c=SINFRA&avisos=1");
    const titulo = await screen.findByRole("heading", { name: "Avisos · SINFRA" });
    expect(titulo).toBeTruthy();
    expect(screen.getByRole("button", { name: "Esconder os avisos (2)" }).getAttribute("aria-expanded")).toBe("true");
    const area = document.getElementById("avisos-area")!;
    expect(area.textContent).toContain("execução termina em 5 dias");
    expect(area.textContent).not.toContain("Construtora Alfa: certidão");
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Fechar os avisos" })); });
    expect(window.location.search).toBe("?c=SINFRA");
    expect(screen.queryByRole("heading", { name: /Avisos ·/ })).toBeNull();
  });

  it("'Todas as obras' com os Avisos abertos inclui os avisos sem obra (documentos da empresa)", async () => {
    abrir("/obras?c=todas&avisos=1");
    await screen.findByRole("heading", { name: "Avisos · Todas as obras" });
    const area = document.getElementById("avisos-area")!;
    expect(area.textContent).toContain("Construtora Alfa");
    expect(area.textContent).toContain("execução termina em 5 dias");
  });

  it("link de antes com filtro solto ganha o c=todas: limpar o último filtro não volta à escolha do contratante", async () => {
    abrir("/obras?q=granito");
    await screen.findByRole("list", { name: "Obras" });
    expect(window.location.search).toBe("?q=granito&c=todas");
    fireEvent.click(screen.getByRole("link", { name: "Limpar os filtros" }));
    expect(window.location.search).toBe("?c=todas");
    expect(await screen.findByRole("heading", { level: 1, name: "Todas as obras" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Contratantes" })).toBeNull();
  });

  it("?orgao= vira ?c= na URL", async () => {
    abrir("/obras?orgao=MTPAR");
    await screen.findByRole("heading", { level: 1, name: "MTPAR" });
    expect(window.location.search).toBe("?c=MTPAR");
  });

  it("o link da coluna Avisos da tabela leva a página até os avisos abertos", async () => {
    const rolar = vi.fn();
    window.HTMLElement.prototype.scrollIntoView = rolar;
    abrir("/obras?c=SINFRA&ver=tabela&avisos=1&obra=1");
    await screen.findByRole("heading", { name: "Avisos · SINFRA" });
    expect(rolar).toHaveBeenCalled();
  });

  it("o link de antes (?orgao=, nome inteiro do órgão do cadastro) continua abrindo a lista", async () => {
    abrir("/obras?orgao=SINFRA%20-%20SUPU");
    const lista = await screen.findByRole("list", { name: "Obras" });
    expect(within(lista).getAllByRole("link")).toHaveLength(1);
    expect(lista.textContent).toContain("MT-388");
  });
});
