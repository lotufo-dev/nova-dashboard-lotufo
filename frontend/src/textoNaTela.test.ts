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

  // Issue #515: a cópia do dono por e-mail mostra erro em português operacional, sem arquivo de configuração,
  // chave, variável de ambiente nem classe de exceção
  it("a tela de Saúde não traz código interno do envio da cópia do dono", () => {
    const admin = fontes.find(f => f.nome === "Admin.tsx")!.texto;
    const literais = admin.match(/"[^"\n]*"|`[^`\n]*`/g) ?? [];
    const proibidos = /geral\.yaml|copia_dono\.|enviada_por|DASH_[A-Z_]+|TimeoutError|\bGraph\b/;
    expect(literais.filter(l => proibidos.test(l))).toEqual([]);
  });

  // as frases vêm do backend (copia_dono_envio.py); esta lista espelha as que ele devolve
  it("as frases de erro da cópia do dono não trazem código interno", () => {
    const frases = [
      "Configure o destinatário da cópia do dono no cadastro", "Configure quem envia a cópia do dono no cadastro",
      "Nenhum usuário ativo é quem envia a cópia do dono: corrija o cadastro",
      "o serviço de e-mail não respondeu; tente de novo mais tarde",
      "o serviço de e-mail recusou o envio; tente de novo mais tarde",
      "a conta Microsoft de quem envia não foi aceita pelo serviço de e-mail: reconecte em Minha conta",
      "o arquivo da cópia do dono está danificado: gere outra cópia; nada foi enviado",
    ];
    const proibidos = /geral\.yaml|copia_dono\.|enviada_por|DASH_[A-Z_]+|TimeoutError|\bGraph\b|sha256|\bage\b/;
    expect(frases.filter(f => proibidos.test(f))).toEqual([]);
  });
});
