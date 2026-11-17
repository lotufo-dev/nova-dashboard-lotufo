// Captura e conferencia das telas por perfil (issues #701 e #702), no servidor de prova.
//
// Com o servidor de prova no ar (`servidor.py`, mesma DASH_DB_PATH):
//   node scripts/prova/capturar.mjs                       todas as telas, os tres perfis, larguras 1440, 1024 e 390
//   node scripts/prova/capturar.mjs --perfis diretoria --telas inicio,obras --larguras 1440
//   node scripts/prova/capturar.mjs --conferir --capturas falha --larguras 1440     (o que a CI roda)
//
// Opcoes: --perfis a,b   --telas id,id   --larguras 1440,390   --escala 2 (pontos por pixel; padrao 1)
//         --capturas todas|falha|nenhuma (padrao todas)   --conferir (sai com 1 se alguma tela tiver problema ou se
//         nenhuma tela for aberta)
//
// Para cada perfil e largura: abre a tela de login, entra com o usuario de teste (digitando, como uma pessoa) e
// abre cada tela de `telas.mjs` numa aba nova. Uma tela tem PROBLEMA quando: da' erro de script ou de console;
// alguma resposta volta 4xx ou 5xx (fora as de RESPOSTAS_ESPERADAS); o conteudo principal nao aparece; fica em
// "Carregando…"; mostra a tela de erro ("A tela parou de responder") ou um aviso de erro; cai no login ou em
// outra tela; ou fica em branco. Rolagem lateral vira aviso, nao problema.
//
// Grava em `<saida>/capturas/`: `<perfil>/<tela>-<largura>.png` (pagina inteira), `login-<largura>.png` e o
// `relato.json` com o que foi visto em cada tela. A saida de uma copia do banco tem dado real: mora fora do
// repositorio (ver `comum.py`).
//
// Navegador: o Chromium do Playwright quando esta' instalado (`npx playwright install chromium`, o que a CI faz);
// senao, o Chrome da maquina. DASH_PROVA_CANAL=chrome|msedge escolhe na mao.
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { LARGURAS, LOGIN, PERFIS, RESPOSTAS_ESPERADAS, TELAS, telasDoPerfil } from "./telas.mjs";

const RAIZ = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const ESPERA = 15000;          // ms para o conteudo principal aparecer
const ESPERA_CARREGANDO = 8000;
const TEXTO_MINIMO = 20;       // caracteres no conteudo; menos que isso e' tela em branco
const ALTURA_MAXIMA = 16000;   // px de uma captura

function recusar(mensagem) {
  console.error(`RECUSADO: ${mensagem}`);
  process.exit(2);
}

// --- opcoes -----------------------------------------------------------------------------------------------------

const args = process.argv.slice(2);
const COM_VALOR = ["--perfis", "--telas", "--larguras", "--capturas", "--escala"];
const SEM_VALOR = ["--conferir"];
for (let i = 0; i < args.length; i++) {
  if (COM_VALOR.includes(args[i])) i++;
  else if (!SEM_VALOR.includes(args[i])) recusar(`opção desconhecida: ${args[i]} (veja o cabeçalho de scripts/prova/capturar.mjs)`);
}
const opcao = nome => { const i = args.indexOf(nome); return i >= 0 ? args[i + 1] : undefined; };
const lista = (nome, todos, rotulo) => {
  const pedidos = opcao(nome)?.split(",").map(s => s.trim()).filter(Boolean);
  if (!pedidos) return todos;
  if (!pedidos.length) recusar(`${nome} veio vazio: sem ${rotulo} não há o que abrir. Vale: ${todos.join(", ")}`);
  const fora = pedidos.filter(p => !todos.map(String).includes(p));
  if (fora.length) recusar(`${nome} não conhece ${rotulo} "${fora.join('", "')}". Vale: ${todos.join(", ")}`);
  return todos.filter(t => pedidos.includes(String(t)));
};
const perfis = lista("--perfis", PERFIS, "perfil");
const idsDasTelas = lista("--telas", TELAS.map(t => t.id), "tela");
const larguras = opcao("--larguras")?.split(",").map(Number) ?? LARGURAS;
if (larguras.some(l => !Number.isInteger(l) || l < 320 || l > 3840)) recusar("--larguras pede números entre 320 e 3840, separados por vírgula");
const capturas = opcao("--capturas") ?? "todas";
if (!["todas", "falha", "nenhuma"].includes(capturas)) recusar("--capturas aceita todas, falha ou nenhuma");
const escala = Number(opcao("--escala") ?? 1);
if (![1, 2, 3].includes(escala)) recusar("--escala aceita 1, 2 ou 3");
const conferir = args.includes("--conferir");

// --- servidor de prova ------------------------------------------------------------------------------------------

const banco = (process.env.DASH_DB_PATH ?? "").trim();
if (!banco) recusar("DASH_DB_PATH não definida. Use a mesma do servidor de prova (scripts/prova/servidor.py).");
const arquivoServidor = path.join(path.dirname(path.resolve(banco)), "prova-servidor.json");
if (!fs.existsSync(arquivoServidor)) {
  recusar("O servidor de prova deste banco não está no ar (falta prova-servidor.json ao lado do banco). "
    + "Suba com: python3 scripts/prova/servidor.py");
}
const servidor = JSON.parse(fs.readFileSync(arquivoServidor, "utf8"));
if (!servidor.frontend) recusar("O servidor de prova subiu com --sem-frontend: não há tela para abrir.");
const BASE = servidor.base;
const SENHA = fs.readFileSync(servidor.senha, "utf8").trim();
const SAIDA = path.join(servidor.saida, "capturas");

let chromium;
try {
  ({ chromium } = createRequire(path.join(RAIZ, "frontend", "package.json"))("playwright"));
} catch {
  recusar("Falta o Playwright: rode `npm ci` em frontend/ (na pasta principal, não num worktree).");
}

let qualNavegador = "Chromium do Playwright";
async function abrirNavegador() {
  const canal = process.env.DASH_PROVA_CANAL;
  if (canal) {
    qualNavegador = canal;
    return chromium.launch({ channel: canal });
  }
  try {
    return await chromium.launch();
  } catch (e) {
    if (!/Executable doesn't exist/.test(String(e))) throw e;
    try {
      qualNavegador = "Chrome da máquina";
      return await chromium.launch({ channel: "chrome" });
    } catch {
      recusar("Nenhum navegador para a prova: instale o do Playwright (`npx playwright install chromium`, em "
        + "frontend/) ou o Chrome.");
    }
  }
}

// --- o que reprova uma tela ---------------------------------------------------------------------------------------

function vigiar(pagina, onde) {
  const problemas = [];
  pagina.on("pageerror", e => problemas.push(`erro de script: ${e.message}`));
  pagina.on("console", m => {
    if (m.type() !== "error") return;
    // a resposta 4xx/5xx ja' e' julgada abaixo, com a lista de esperadas; esta linha do console e' a mesma coisa
    if (m.text().startsWith("Failed to load resource: the server responded with a status of")) return;
    problemas.push(`erro no console: ${m.text().slice(0, 300)}`);
  });
  pagina.on("response", r => {
    if (r.status() < 400) return;
    const caminho = new URL(r.url()).pathname, metodo = r.request().method();
    const esperada = RESPOSTAS_ESPERADAS.some(e => e.metodo === metodo && e.status === r.status()
      && e.caminho.test(caminho) && (!e.so || e.so === onde));
    if (!esperada) problemas.push(`resposta ${r.status()} em ${metodo} ${caminho}`);
  });
  pagina.on("requestfailed", r => {
    const erro = r.failure()?.errorText ?? "";
    if (erro.includes("ERR_ABORTED")) return;       // pedido cancelado por troca de tela
    problemas.push(`pedido sem resposta: ${r.method()} ${new URL(r.url()).pathname} (${erro})`);
  });
  return problemas;
}

async function assentar(pagina, espera, problemas) {
  try {
    await pagina.locator(espera).first().waitFor({ state: "visible", timeout: ESPERA });
  } catch {
    problemas.push(`o conteúdo principal não apareceu em ${ESPERA / 1000} s (${espera})`);
  }
  await pagina.waitForLoadState("networkidle", { timeout: ESPERA })
    .catch(() => problemas.push(`a tela não parou de pedir dados em ${ESPERA / 1000} s`));
  await pagina.waitForFunction(() => !/Carregando…/.test(document.getElementById("conteudo")?.innerText ?? ""), null,
    { timeout: ESPERA_CARREGANDO })
    .catch(() => problemas.push(`ainda mostrava "Carregando…" depois de ${ESPERA_CARREGANDO / 1000} s`));
  await pagina.evaluate(() => document.fonts.ready).catch(() => {});
}

async function estadoDaTela(pagina) {
  return pagina.evaluate(() => {
    const visivel = el => {
      const b = el.getBoundingClientRect();
      return b.width > 0 && b.height > 0 && getComputedStyle(el).visibility !== "hidden";
    };
    const limpo = el => el.innerText.replace(/\s+/g, " ").trim().slice(0, 200);
    const conteudo = document.getElementById("conteudo");
    const falha = document.querySelector(".falha");
    return {
      caminho: location.pathname,
      login: !!document.querySelector("form.entrar__form"),
      falha: falha ? limpo(falha) : null,
      avisosDeErro: [...document.querySelectorAll("#conteudo .erro[role=alert]")].filter(visivel).map(limpo),
      texto: (conteudo?.innerText ?? "").trim().length,
      larguraDaPagina: document.documentElement.scrollWidth,
      larguraDaJanela: window.innerWidth,
    };
  });
}

function julgar(estado, caminhoEsperado, problemas, avisos) {
  if (estado.falha) problemas.push(`tela de erro: ${estado.falha}`);
  else if (estado.login) problemas.push("caiu na tela de login");
  else {
    const esperado = new URL(caminhoEsperado, BASE).pathname;
    if (estado.caminho !== esperado) problemas.push(`abriu ${estado.caminho} no lugar de ${esperado}`);
    if (estado.texto < TEXTO_MINIMO) problemas.push("tela em branco (sem texto no conteúdo)");
  }
  for (const a of estado.avisosDeErro) problemas.push(`aviso de erro na tela: ${a}`);
  if (estado.larguraDaPagina > estado.larguraDaJanela + 1) {
    avisos.push(`rola de lado: página com ${estado.larguraDaPagina} px numa janela de ${estado.larguraDaJanela} px`);
  }
}

// O menu e' fixo na altura da janela: a janela cresce ate' a altura da pagina e a captura sai inteira, sem a
// captura de "pagina inteira" do Playwright, que encolhe a janela por um instante e pode recolher o menu.
async function fotografar(pagina, arquivo, largura) {
  fs.mkdirSync(path.dirname(arquivo), { recursive: true });
  const altura = await pagina.evaluate(() => document.documentElement.scrollHeight);
  await pagina.setViewportSize({ width: largura, height: Math.min(Math.max(altura, 900), ALTURA_MAXIMA) });
  await pagina.waitForTimeout(150);
  await pagina.evaluate(() => window.scrollTo(0, 0));
  await pagina.mouse.move(0, 0);
  await pagina.screenshot({ path: arquivo, animations: "disabled" });
}

// --- percurso ---------------------------------------------------------------------------------------------------

const relato = [];
const fotosDoLogin = new Set();

function registrar(item) {
  relato.push(item);
  const onde = `${item.perfil} ${item.largura} ${item.tela} ${item.caminho ?? ""}`.trim();
  if (item.problemas.length) console.log(`FALHA ${onde}\n` + item.problemas.map(p => `        ${p}`).join("\n"));
  else console.log(`ok    ${onde} (${item.ms} ms)` + item.avisos.map(a => `\n        aviso: ${a}`).join(""));
}

const querFoto = problemas => capturas === "todas" || (capturas === "falha" && problemas.length > 0);

async function entrar(contexto, perfil, largura) {
  const pagina = await contexto.newPage();
  const problemas = vigiar(pagina, "login"), avisos = [], t0 = Date.now();
  let captura = null, entrou = false;
  try {
    await pagina.goto(BASE + LOGIN.caminho, { waitUntil: "load" });
    await pagina.locator(LOGIN.espera).waitFor({ state: "visible", timeout: ESPERA });
    if (capturas === "todas" && !fotosDoLogin.has(largura)) {
      fotosDoLogin.add(largura);
      captura = path.join(SAIDA, `login-${largura}.png`);
      await fotografar(pagina, captura, largura);
    }
    await pagina.locator('input[name="email"]').fill(servidor.usuarios[perfil]);
    await pagina.locator('input[name="senha"]').fill(SENHA);
    await pagina.locator('form.entrar__form button[type="submit"]').click();
    await pagina.locator("#conteudo").waitFor({ state: "visible", timeout: ESPERA });
    entrou = true;
    // item do menu sem tela na lista reprova: e' o que mantem `telas.mjs` em dia quando o menu muda
    const menu = await pagina.locator("nav.menu a.menu__item").evaluateAll(as => as.map(a => new URL(a.href).pathname));
    const cobertos = telasDoPerfil(perfil).map(t => t.menu ?? t.caminho);
    for (const item of menu.filter(m => !cobertos.includes(m))) {
      problemas.push(`o menu de ${perfil} tem ${item} e scripts/prova/telas.mjs não tem tela para ele`);
    }
    if (menu.length === 0) problemas.push("o menu não tem nenhum item (mudou o seletor nav.menu a.menu__item?)");
  } catch (e) {
    problemas.push(`não entrou como ${perfil}: ${String(e.message ?? e).split("\n")[0]}`);
    if (capturas !== "nenhuma") {
      captura = path.join(SAIDA, perfil, `login-${largura}.png`);
      await fotografar(pagina, captura, largura).catch(() => { captura = null; });
    }
  }
  await pagina.close();
  registrar({ perfil, largura, tela: LOGIN.id, caminho: LOGIN.caminho, ms: Date.now() - t0, problemas, avisos, captura });
  return entrou;
}

// Os registros que entram nos caminhos com `:obra`, `:medicao` e `:empresa`: lidos da API, com a sessao do perfil.
async function registros(contexto) {
  const ler = async caminho => {
    const r = await contexto.request.get(BASE + caminho);
    return r.ok() ? r.json() : [];
  };
  const contratos = await ler("/api/contratos");
  let obra = null, medicao = null;
  for (const c of contratos) {
    const medicoes = await ler(`/api/contratos/${c.id}/medicoes`);
    if (medicoes.length) { obra = c.id; medicao = medicoes[0].id; break; }
  }
  obra ??= contratos[0]?.id ?? null;
  const empresas = await ler("/api/entidades");
  return { obra, medicao, empresa: empresas[0]?.id ?? null };
}

async function abrirTela(contexto, perfil, largura, tela, reg) {
  const faltam = [...tela.caminho.matchAll(/:(\w+)/g)].map(m => m[1]).filter(n => reg[n] == null);
  if (faltam.length) {
    // sem o registro nao ha' o que abrir; na conferencia isso reprova, para a tela nao sair da prova em silencio
    const frase = `pulada: o banco da prova não tem ${faltam.join(" nem ")}`;
    registrar({ perfil, largura, tela: tela.id, caminho: tela.caminho, ms: 0, captura: null,
      problemas: conferir ? [frase] : [], avisos: conferir ? [] : [frase] });
    return;
  }
  const caminho = tela.caminho.replace(/:(\w+)/g, (_, n) => String(reg[n]));
  const pagina = await contexto.newPage();
  const problemas = vigiar(pagina, tela.id), avisos = [], t0 = Date.now();
  let captura = null;
  try {
    await pagina.goto(BASE + caminho, { waitUntil: "load" });
    await assentar(pagina, tela.espera, problemas);
    julgar(await estadoDaTela(pagina), caminho, problemas, avisos);
  } catch (e) {
    problemas.push(`não abriu: ${String(e.message ?? e).split("\n")[0]}`);
  }
  const ms = Date.now() - t0;
  if (querFoto(problemas)) {
    captura = path.join(SAIDA, perfil, `${tela.id}-${largura}.png`);
    await fotografar(pagina, captura, largura).catch(e => { avisos.push(`sem captura: ${e.message}`); captura = null; });
  }
  await pagina.close();
  registrar({ perfil, largura, tela: tela.id, caminho, ms, problemas, avisos, captura });
}

async function percorrer(navegador, perfil) {
  const telas = telasDoPerfil(perfil).filter(t => idsDasTelas.includes(t.id));
  for (const largura of larguras) {
    const contexto = await navegador.newContext({
      viewport: { width: largura, height: 900 }, deviceScaleFactor: escala, locale: "pt-BR",
      timezoneId: "America/Cuiaba", reducedMotion: "reduce", colorScheme: "light",
    });
    try {
      if (!(await entrar(contexto, perfil, largura))) continue;
      const reg = await registros(contexto);
      for (const tela of telas) await abrirTela(contexto, perfil, largura, tela, reg);
    } finally {
      await contexto.close();
    }
  }
}

const inicio = Date.now();
const navegador = await abrirNavegador();
const versao = `${qualNavegador} ${navegador.version()}`;
console.log(`prova em ${BASE} · ${versao} · perfis: ${perfis.join(", ")} · `
  + `larguras: ${larguras.join(", ")}`);
try {
  // um perfil ao lado do outro: cada um na sua sessao, como tres pessoas usando ao mesmo tempo
  await Promise.all(perfis.map(p => percorrer(navegador, p)));
} finally {
  await navegador.close();
}

const comProblema = relato.filter(i => i.problemas.length);
fs.mkdirSync(SAIDA, { recursive: true });
fs.writeFileSync(path.join(SAIDA, "relato.json"), JSON.stringify({
  base: BASE, navegador: versao, perfis, larguras, segundos: Math.round((Date.now() - inicio) / 1000),
  telas: relato,
}, null, 1));
console.log(`\n${relato.length} tela(s) abertas em ${Math.round((Date.now() - inicio) / 1000)} s; `
  + `${comProblema.length} com problema. Relato: ${path.join(SAIDA, "relato.json")}`);
for (const i of comProblema) console.log(`  FALHA ${i.perfil} ${i.largura} ${i.tela}: ${i.problemas[0]}`);
// conferencia que nao abriu tela nenhuma (fora o login) nao conferiu nada: reprova, em vez de passar vazia
const semTela = !relato.some(i => i.tela !== LOGIN.id);
if (conferir && semTela) {
  console.log("  FALHA nenhuma tela foi aberta: --perfis ou --telas ficou vazio, ou nenhum perfil pedido tem as telas pedidas");
}
process.exit(conferir && (comProblema.length || semTela) ? 1 : 0);
