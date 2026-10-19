import { describe, expect, it } from "vitest";
import { entradaDe, itemDe, menuDe, tituloDaSecao } from "./navegacao";

describe("navegação por perfil", () => {
  it("todo perfil entra pelo Início (08/10/2026)", () => {
    expect(entradaDe("diretoria")).toEqual({ tela: "inicio" });
    expect(entradaDe("engenharia")).toEqual({ tela: "inicio" });
    expect(entradaDe("admin")).toEqual({ tela: "inicio" });
  });

  it("trilho sem grupos, na ordem do trabalho, com o recorte do perfil; as Notas saíram (viraram abas de Medições)", () => {
    expect(menuDe("engenharia")).toEqual(["inicio", "medicoes", "obras", "avisos", "documentos", "a-receber"]);
    // decisão 3: a diretoria sem Medições, com a Carteira
    expect(menuDe("diretoria")).toEqual(["inicio", "obras", "avisos", "documentos", "a-receber", "carteira"]);
    expect(menuDe("admin")).toEqual(["inicio", "medicoes", "obras", "avisos", "documentos", "a-receber", "carteira", "admin"]);
  });

  it("o item fica marcado também abaixo dele na hierarquia", () => {
    expect(itemDe({ tela: "obra", id: 7, aba: "prazos" })).toBe("obras");
    expect(itemDe({ tela: "carteira" })).toBe("carteira");
    expect(itemDe({ tela: "obras" })).toBe("obras");
    expect(itemDe({ tela: "obras" }, { c: "todas", avisos: "1" })).toBe("avisos");   // Avisos abertos dentro de Obras
    expect(itemDe({ tela: "inicio" })).toBe("inicio");
    // a medição, a nova medição e o envio da nota ficam sob Medições
    expect(itemDe({ tela: "medicao", obra: 7, id: 723 })).toBe("medicoes");
    expect(itemDe({ tela: "nova-medicao", obra: 7 })).toBe("medicoes");
    expect(itemDe({ tela: "notas-envio", id: 55 })).toBe("medicoes");
    expect(itemDe({ tela: "documentos-empresa", id: 3, aba: "garantia" })).toBe("documentos");      // #161
    expect(itemDe({ tela: "medicoes", aba: "enviar-nota" })).toBe("medicoes");
  });

  it("a barra superior diz a seção, não o objeto", () => {
    expect(tituloDaSecao({ tela: "obra", id: 7, aba: "medicoes" })).toBe("Obras");
    expect(tituloDaSecao({ tela: "medicao", obra: 7, id: 723 })).toBe("Medições");
    expect(tituloDaSecao({ tela: "medicoes", aba: "aguardando-nota" })).toBe("Medições");
    expect(tituloDaSecao({ tela: "conta" })).toBe("Minha conta");
    expect(tituloDaSecao({ tela: "a-receber" })).toBe("A receber");
  });
});
