/// <reference types="node" />
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// Texto na tela (.claude/rules/texto-na-tela.md, 26/10/2026): a limpeza geral tirou 576 frases de apoio. Esta guarda
// falha se uma das classes ou props que so' existiam para frase de apoio voltar a algum componente.
const pasta = join(process.cwd(), "src");
const fontes = readdirSync(pasta)
  .filter(n => /\.tsx?$/.test(n) && !n.includes(".test."))
  .map(n => ({ nome: n, texto: readFileSync(join(pasta, n), "utf8") }));

const CLASSES = [
  "pagina__descricao", "ini-numero__base", "ini-numero__nota", "ini-cartao__detalhe", "ini-painel__rodape",
  "ar-numero__apoio", "cart-numero__apoio", "kpi__comparacao", "curva__rodape", "resumo-nota", "alerta__onde",
  "grupo__conta", "detalhes__resto", "en-dica", "nota-porfora__dica", "iniciar__dica", "medicoes__legenda",
  "aba-nota__info", "frc__ultima", "frc__assinar", "med-etapa__resumo", "carta-rec__dica", "saldo__nota",
  "notas__arredonda", "doc-painel__dica", "doc-zona__nota", "doc-cabeca__meta", "entrar__ajuda", "conta__perfil",
];

describe("texto na tela: frase de apoio removida não volta", () => {
  it.each(CLASSES)("ninguém usa a classe %s", classe => {
    const re = new RegExp(`["\\s\`]${classe}(?![\\w-])`);
    expect(fontes.filter(f => re.test(f.texto)).map(f => f.nome)).toEqual([]);
  });

  it("nenhum componente recebe frase de apoio por prop (dica, detalhe, resumo)", () => {
    const re = /\s(dica|detalhe|resumo)=[{"]/;
    expect(fontes.filter(f => re.test(f.texto)).map(f => f.nome)).toEqual([]);
  });
});
