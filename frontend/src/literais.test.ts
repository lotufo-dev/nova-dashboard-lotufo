/// <reference types="node" />
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// #719: cor, familia e tamanho de letra moram so' nas variaveis da fundacao (bloco :root de tokens.css). Este teste
// barra a volta do literal em src/**/*.css e nos estilos escritos em .tsx. Valor novo entra em tokens.css primeiro.
// Limites conhecidos (o leitor e' por linha, nao entende o codigo): nome de cor guardado numa const fora de estilo,
// cor montada em template (`#${x}`) e px literal no meio de um clamp() com as pontas em var() passam sem aviso.

const SRC = join(process.cwd(), "src");

type Achado = { arquivo: string; linha: number; tipo: "cor" | "familia" | "tamanho"; trecho: string };

// Excecoes: arquivo + pedaco da linha + motivo, uma por linha. Cada uma precisa continuar achando o que desculpa.
export const EXCECOES: { arquivo: string; trecho: string; motivo: string }[] = [
  { arquivo: "EditorCorpo.tsx", trecho: 'cor: "#', motivo: "cores de texto e de realce que o usuario escolhe no corpo do e-mail: dado, nao estilo" },
  { arquivo: "EditorCorpo.tsx", trecho: 'background: "#FF0000"', motivo: "o A do botao de cor mostra o Vermelho da lista do usuario, como no cliente de e-mail" },
  { arquivo: "tokens.css", trecho: "background: #FFFF00", motivo: "o icone do botao de realce mostra o Amarelo da lista do usuario" },
  { arquivo: "tokens.css", trecho: "font-size: .92em", motivo: "code: tamanho relativo ao texto em volta" },
  { arquivo: "EditorCorpo.tsx", trecho: 'fontSize="5"', motivo: "numeral desenhado no icone de lista numerada, em unidades do viewBox de 16" },
];

// as 148 cores com nome do CSS (sem transparent e currentColor, que nao sao tom)
const NOMES = new Set(("aliceblue antiquewhite aqua aquamarine azure beige bisque black blanchedalmond blue blueviolet brown " +
  "burlywood cadetblue chartreuse chocolate coral cornflowerblue cornsilk crimson cyan darkblue darkcyan darkgoldenrod " +
  "darkgray darkgreen darkgrey darkkhaki darkmagenta darkolivegreen darkorange darkorchid darkred darksalmon darkseagreen " +
  "darkslateblue darkslategray darkslategrey darkturquoise darkviolet deeppink deepskyblue dimgray dimgrey dodgerblue " +
  "firebrick floralwhite forestgreen fuchsia gainsboro ghostwhite gold goldenrod gray green greenyellow grey honeydew " +
  "hotpink indianred indigo ivory khaki lavender lavenderblush lawngreen lemonchiffon lightblue lightcoral lightcyan " +
  "lightgoldenrodyellow lightgray lightgreen lightgrey lightpink lightsalmon lightseagreen lightskyblue lightslategray " +
  "lightslategrey lightsteelblue lightyellow lime limegreen linen magenta maroon mediumaquamarine mediumblue mediumorchid " +
  "mediumpurple mediumseagreen mediumslateblue mediumspringgreen mediumturquoise mediumvioletred midnightblue mintcream " +
  "mistyrose moccasin navajowhite navy oldlace olive olivedrab orange orangered orchid palegoldenrod palegreen " +
  "paleturquoise palevioletred papayawhip peachpuff peru pink plum powderblue purple rebeccapurple red rosybrown royalblue " +
  "saddlebrown salmon sandybrown seagreen seashell sienna silver skyblue slateblue slategray slategrey snow springgreen " +
  "steelblue tan teal thistle tomato turquoise violet wheat white whitesmoke yellow yellowgreen").split(" "));

const HEX = /#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})(?![\w-])/;
const FUNCAO_COR = /\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch)\(/i;
// propriedades em que uma palavra solta nunca e' cor (nome de animacao, de area, texto)
const SEM_COR = /^(?:grid|animation|transition|content|font|will-change|counter|list-style|quotes|container)/;

const linhaDe = (texto: string, i: number) => texto.slice(0, i).split("\n").length;
// troca o trecho por espacos, mantendo as quebras (a linha do achado continua certa)
const apagar = (s: string) => s.replace(/[^\n]/g, " ");
const ehLiteralDeCor = (valor: string) =>
  HEX.test(valor) || FUNCAO_COR.test(valor) || valor.toLowerCase().split(/[^a-z]+/).some(p => NOMES.has(p));

/** Tamanho aceito: var(), palavra que herda, ou clamp/min/max com as duas pontas em var() (o meio pode ser fluido). */
export function tamanhoAceito(valor: string): boolean {
  const v = valor.replace(/!important/, "").trim();
  if (/^(?:inherit|initial|unset|revert)$/.test(v)) return true;
  if (/^var\(--[\w-]+\)$/.test(v)) return true;
  const f = /^(?:clamp|min|max)\((.*)\)$/.exec(v);
  if (!f) return false;
  const args: string[] = [];
  let nivel = 0, ini = 0;
  for (let i = 0; i < f[1].length; i++) {
    const c = f[1][i];
    if (c === "(") nivel++;
    else if (c === ")") nivel--;
    else if (c === "," && nivel === 0) { args.push(f[1].slice(ini, i)); ini = i + 1; }
  }
  args.push(f[1].slice(ini));
  const ponta = (a: string) => /^var\(--[\w-]+\)$/.test(a.trim());
  return ponta(args[0]) && ponta(args[args.length - 1]);
}

export function achadosCss(arquivo: string, fonte: string): Achado[] {
  let css = fonte.replace(/\/\*[\s\S]*?\*\//g, apagar).replace(/url\([^)]*\)/g, apagar);
  if (arquivo === "tokens.css") {
    // o bloco de variaveis (os :root) e as declaracoes de fonte sao o lugar do literal
    css = css.replace(/(^|\n):root\s*\{[^}]*\}/g, apagar).replace(/@font-face\s*\{[^}]*\}/g, apagar);
  }
  const achados: Achado[] = [];
  const decl = /(?<=^|[;{\s])(--[\w-]+|[a-zA-Z-]+)\s*:\s*([^;{}]+?)\s*(?=[;}])/g;
  for (const m of css.matchAll(decl)) {
    const [, prop, valor] = m;
    const p = prop.toLowerCase();
    const linha = linhaDe(css, m.index);
    const trecho = `${prop}: ${valor}`.replace(/\s+/g, " ");
    if (p.startsWith("--") ? ehLiteralDeCor(valor) : (!SEM_COR.test(p) && ehLiteralDeCor(valor)) || HEX.test(valor) || FUNCAO_COR.test(valor))
      achados.push({ arquivo, linha, tipo: "cor", trecho });
    if (p === "font-family" && !/^(?:var\(--[\w-]+\)|inherit|initial|unset)$/.test(valor.trim()))
      achados.push({ arquivo, linha, tipo: "familia", trecho });
    if (p === "font-size" && !tamanhoAceito(valor)) achados.push({ arquivo, linha, tipo: "tamanho", trecho });
    // atalho `font`: so' var(), a barra da entrelinha e palavras que herdam
    if (p === "font" && valor.replace(/var\(--[\w-]+\)|\/|\b(?:inherit|initial|unset)\b|\s/g, "") !== "")
      achados.push({ arquivo, linha, tipo: "tamanho", trecho });
  }
  return achados;
}

const PROPS_COR_TSX = "color|background|backgroundColor|borderColor|border|borderLeft|borderTop|borderRight|borderBottom|" +
  "borderLeftColor|borderTopColor|borderRightColor|borderBottomColor|outline|outlineColor|fill|stroke|boxShadow|textDecorationColor|caretColor|accentColor";

export function achadosTsx(arquivo: string, fonte: string): Achado[] {
  // tira comentario (bloco, JSX e de linha; o "//" de um endereco "http://" fica)
  const tsx = fonte.replace(/\/\*[\s\S]*?\*\//g, apagar).replace(/(^|[^:"'`\\])\/\/[^\n]*/g, (_, a: string, ) => a);
  const achados: Achado[] = [];
  const linhas = tsx.split("\n");
  const original = fonte.split("\n");
  const corEmString = new RegExp(`["'\`(\\s,]${HEX.source}`);
  const nomeEmProp = new RegExp(`\\b(?:${PROPS_COR_TSX})\\s*[:=]\\s*\\{?\\s*["'\`]([^"'\`]*)["'\`]`, "g");
  linhas.forEach((l, i) => {
    const trecho = original[i].trim();
    const add = (tipo: Achado["tipo"]) => achados.push({ arquivo, linha: i + 1, tipo, trecho });
    const nomes = [...l.matchAll(nomeEmProp)].some(m => m[1].toLowerCase().split(/[^a-z]+/).some(p => NOMES.has(p)));
    if (corEmString.test(l) || FUNCAO_COR.test(l) || nomes) add("cor");
    if (/\bfontFamily\s*[:=]\s*(?!\{?\s*["'`]var\()/.test(l)) add("familia");
    if (/\bfontSize\s*[:=]\s*(?!\{?\s*["'`]var\()/.test(l)) add("tamanho");
    // atalho `font` num objeto de estilo: so' var() e palavras que herdam
    for (const m of l.matchAll(/\bfont\s*:\s*["'`]([^"'`]*)["'`]/g))
      if (m[1].replace(/var\(--[\w-]+\)|\/|\b(?:inherit|initial|unset)\b|\s/g, "") !== "") add("tamanho");
  });
  return achados;
}

function arquivos(): string[] {
  return readdirSync(SRC, { recursive: true, encoding: "utf8" })
    .filter(f => (f.endsWith(".css") || f.endsWith(".tsx")) && !/\.test\.tsx?$/.test(f))
    .sort();
}

export function todosOsAchados(): Achado[] {
  return arquivos().flatMap(f => {
    const fonte = readFileSync(join(SRC, f), "utf8");
    return f.endsWith(".css") ? achadosCss(f, fonte) : achadosTsx(f, fonte);
  });
}

const desculpado = (a: Achado) => EXCECOES.some(e => a.arquivo.endsWith(e.arquivo) && a.trecho.includes(e.trecho));

describe("estilos sem literal (#719)", () => {
  it("nenhuma cor, familia ou tamanho de letra escrito fora das variaveis da fundacao", () => {
    const soltos = todosOsAchados().filter(a => !desculpado(a)).map(a => `${a.arquivo}:${a.linha} [${a.tipo}] ${a.trecho}`);
    expect(soltos).toEqual([]);
  });

  it("cada excecao ainda desculpa algum achado (a lista nao guarda sobra)", () => {
    const todos = todosOsAchados();
    const sobras = EXCECOES.filter(e => !todos.some(a => a.arquivo.endsWith(e.arquivo) && a.trecho.includes(e.trecho)));
    expect(sobras).toEqual([]);
  });

  it("o leitor acha cada tipo de literal (o teste falha de verdade)", () => {
    const css = ".a { color: #fff; background: rgb(0 0 0); border-color: white; font-family: Arial; font-size: 13px; }\n" +
      ".b { font-size: clamp(12px, 2vw, var(--texto-corpo)); font: 12px sans-serif; }";
    const tiposCss = achadosCss("x.css", css).map(a => a.tipo);
    expect(tiposCss.filter(t => t === "cor")).toHaveLength(3);
    expect(tiposCss).toContain("familia");
    expect(tiposCss.filter(t => t === "tamanho")).toHaveLength(3);

    const ok = ".a:hover { color: var(--cor-tinta); font-size: clamp(var(--texto-mini), 5vw, var(--texto-corpo)); }\n" +
      ".b { font: inherit; transition: color .2s; grid-area: tan; }";
    expect(achadosCss("x.css", ok)).toEqual([]);

    const tsx = '<span style={{ background: "#ccc", color: "red", fontSize: 12, fontFamily: "Arial" }} />\n' +
      '<span style={{ color: "var(--cor-tinta)", fontSize: "var(--texto-meta)" }} />\n' +
      '<b style={{ font: "12px Arial", borderLeft: "1px solid red", borderTopColor: "#abc" }} />\n' +
      '<i style={{ font: "inherit", borderLeft: "1px solid var(--cor-linha)" }} />\n' +
      '// issue #123: comentario nao conta\n<a href="https://exemplo.com.br/#abc">x</a>';
    const tiposTsx = achadosTsx("x.tsx", tsx);
    expect(tiposTsx.map(a => [a.linha, a.tipo])).toEqual([[1, "cor"], [1, "familia"], [1, "tamanho"], [3, "cor"], [3, "tamanho"]]);

    // o bloco de variaveis de tokens.css e' o lugar do literal; fora dele, nao
    const tokens = ":root {\n  --cor-x: #123456;\n}\n.c { color: #123456; }";
    expect(achadosCss("tokens.css", tokens).map(a => a.linha)).toEqual([4]);
  });
});
