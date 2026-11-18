import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import Caminho from "./Caminho";
import type { NomesDoCaminho } from "./navegacao";
import { useNomesDoCaminho } from "./nomesDoCaminho";

// O caminho no alto de toda página (#814): uma peça só, na barra do topo. A rota dá os trechos; a página que tem o
// objeto carregado diz o nome dele.

/** Uma página de mentira, que diz ao caminho os nomes que "carregou". */
function Pagina({ nomes }: { nomes: NomesDoCaminho }) {
  useNomesDoCaminho(nomes);
  return null;
}

const caminho = () => screen.getByRole("navigation", { name: "Você está em" });
const trechos = () => [...caminho().querySelectorAll("li")].map(li => li.textContent);
const link = (nome: string) => within(caminho()).getByRole("link", { name: nome }).getAttribute("href");

describe("Caminho", () => {
  afterEach(() => { cleanup(); window.history.replaceState(null, "", "/"); });

  it("cada trecho de antes é um link; o último é onde se está, sem link", () => {
    render(<Caminho rota={{ tela: "a-receber" }} ehH1 />);
    expect(trechos()).toEqual(["Financeiro", "A receber"]);
    expect(link("Financeiro")).toBe("/fechamento");
    expect(within(caminho()).queryByRole("link", { name: "A receber" })).toBeNull();
    const itens = [...caminho().querySelectorAll("li")];
    expect(itens.map(li => li.getAttribute("aria-current"))).toEqual([null, "page"]);
  });

  it("o trecho da página é o título: h1 nas listas, só texto onde a página tem o próprio h1", () => {
    const { rerender } = render(<Caminho rota={{ tela: "medicoes", aba: "quadro" }} ehH1 />);
    expect(trechos()).toEqual(["Medições", "Quadro do mês"]);
    // com a vista depois dele, o título é link para a vista padrão
    const h1 = within(caminho()).getByRole("heading", { level: 1, name: "Medições" });
    expect(within(h1).getByRole("link", { name: "Medições" }).getAttribute("href")).toBe("/medicoes");
    expect(caminho().querySelectorAll(".caminho__trecho--titulo")).toHaveLength(1);
    rerender(<Caminho rota={{ tela: "medicoes", aba: "quadro" }} ehH1={false} />);
    expect(within(caminho()).queryByRole("heading")).toBeNull();
    expect(caminho().querySelector(".caminho__trecho--titulo")!.textContent).toBe("Medições");
  });

  it("o nome do objeto vem da página que o carregou, e chega depois dela", () => {
    const { rerender } = render(<><Caminho rota={{ tela: "medicao", obra: 7, id: 723 }} ehH1={false} /><Pagina nomes={{}} /></>);
    expect(trechos()).toEqual(["Obras", "Obra", "Medições", "Medição"]);
    rerender(<><Caminho rota={{ tela: "medicao", obra: 7, id: 723 }} ehH1={false} />
      <Pagina nomes={{ obra: "MT-388", medicao: "15ª Medição", contratante: { nome: "SINFRA", chave: "sinfra" } }} /></>);
    expect(trechos()).toEqual(["Obras", "SINFRA", "MT-388", "Medições", "15ª Medição"]);
    expect([link("Obras"), link("SINFRA"), link("MT-388"), link("Medições")])
      .toEqual(["/obras", "/obras/contratante/sinfra", "/obras/7", "/obras/7/medicoes"]);
    // nada é cortado (o que não cabe desce para a linha de baixo): o trecho não precisa de dica com o nome inteiro
    expect(within(caminho()).getByText("15ª Medição").getAttribute("title")).toBeNull();
  });

  it("a página que sai da tela apaga os nomes: o de uma obra não aparece no caminho de outra", () => {
    const { rerender } = render(<><Caminho rota={{ tela: "obra", id: 7, aba: "ficha" }} ehH1={false} /><Pagina key="a" nomes={{ obra: "MT-388" }} /></>);
    expect(trechos()).toEqual(["Obras", "MT-388"]);
    rerender(<><Caminho rota={{ tela: "obra", id: 8, aba: "ficha" }} ehH1={false} /><Pagina key="b" nomes={{}} /></>);
    expect(trechos()).toEqual(["Obras", "Obra"]);
    rerender(<Caminho rota={{ tela: "obra", id: 8, aba: "ficha" }} ehH1={false} />);
    expect(trechos()).toEqual(["Obras", "Obra"]);
  });

  it("quando se chegou por um trecho do caminho, o link dele volta para lá como estava", () => {
    const nomes = { obra: "MT-388", contratante: { nome: "SINFRA", chave: "sinfra" } };
    const { rerender } = render(<><Caminho rota={{ tela: "obra", id: 7, aba: "ficha" }} ehH1={false}
      origem={{ tela: "obras", href: "/obras/todas?q=mt" }} /><Pagina nomes={nomes} /></>);
    expect([link("Obras"), link("SINFRA")]).toEqual(["/obras/todas?q=mt", "/obras/contratante/sinfra"]);
    rerender(<><Caminho rota={{ tela: "obra", id: 7, aba: "ficha" }} ehH1={false}
      origem={{ tela: "contratante", href: "/obras/contratante/sinfra?situacao=todas" }} /><Pagina nomes={nomes} /></>);
    expect([link("Obras"), link("SINFRA")]).toEqual(["/obras", "/obras/contratante/sinfra?situacao=todas"]);
    // de outro contratante, ou de uma tela que não está no caminho, os trechos ficam como são
    rerender(<><Caminho rota={{ tela: "obra", id: 7, aba: "ficha" }} ehH1={false}
      origem={{ tela: "contratante", href: "/obras/contratante/mtpar?situacao=todas" }} /><Pagina nomes={nomes} /></>);
    expect(link("SINFRA")).toBe("/obras/contratante/sinfra");
    rerender(<><Caminho rota={{ tela: "obra", id: 7, aba: "ficha" }} ehH1={false}
      origem={{ tela: "medicoes", href: "/medicoes?mes=2026-09" }} /><Pagina nomes={nomes} /></>);
    expect([link("Obras"), link("SINFRA")]).toEqual(["/obras", "/obras/contratante/sinfra"]);
  });

  it("a área não troca de endereço pela origem: só a página do mesmo assunto", () => {
    render(<><Caminho rota={{ tela: "documentos-empresa", id: 3, aba: "regularidade" }} ehH1={false}
      origem={{ tela: "documentos", href: "/documentos/regularidade?x=1" }} /><Pagina nomes={{ empresa: "Construtora Alfa" }} /></>);
    expect(trechos()).toEqual(["Documentos", "Regularidade mensal", "Construtora Alfa"]);
    expect([link("Documentos"), link("Regularidade mensal")]).toEqual(["/documentos", "/documentos/regularidade?x=1"]);
  });

  it("o trecho navega pelo roteador", async () => {
    window.history.replaceState(null, "", "/a-receber");
    render(<Caminho rota={{ tela: "a-receber" }} ehH1 />);
    await act(async () => { fireEvent.click(within(caminho()).getByRole("link", { name: "Financeiro" })); });
    expect(window.location.pathname).toBe("/fechamento");
  });

  it("a raiz não tem caminho", () => {
    const { container } = render(<Caminho rota={{ tela: "raiz" }} ehH1 />);
    expect(container.firstChild).toBeNull();
  });
});
