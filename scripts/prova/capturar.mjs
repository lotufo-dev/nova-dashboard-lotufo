// Captura e conferencia das telas por perfil (issues #701 e #702), no servidor de prova.
//
// Com o servidor de prova no ar (`servidor.py`, mesma DASH_DB_PATH):
//   node scripts/prova/capturar.mjs                       todas as telas, os tres perfis, larguras 1440, 1024 e 390
//   node scripts/prova/capturar.mjs --perfis diretoria --telas inicio,obras --larguras 1440
//   node scripts/prova/capturar.mjs --conferir --capturas falha --larguras 1440     (o que a CI roda)
//
// Opcoes: --perfis a,b   --telas id,id   --larguras 1440,390   --escala 2 (pontos por pixel; padrao 1)
//         --capturas todas|falha|nenhuma (padrao todas)   --conferir (sai com 1 se alguma tela tiver problema ou se
//         nenhuma tela for aberta)   --estrito (os achados da auditoria visual tambem reprovam)
//         --obra N   --medicao N   --empresa N   o registro que entra nos caminhos com `:obra`, `:medicao` e `:empresa`,
//         no lugar do primeiro do banco (para ver outra obra numa copia do banco; --medicao pede --obra)
//         --rotulo nome   as capturas e o relato saem em `<saida>/capturas/<nome>/`, sem apagar os da rodada de antes
//
// Para cada perfil e largura: abre a tela de login, entra com o usuario de teste (digitando, como uma pessoa) e
// abre cada tela de `telas.mjs` numa aba nova. Uma tela tem PROBLEMA quando: da' erro de script ou de console;
// alguma resposta volta 4xx ou 5xx (fora as de RESPOSTAS_ESPERADAS); o conteudo principal nao aparece; fica em
// "Carregando…"; mostra a tela de erro ("A tela parou de responder") ou um aviso de erro; cai no login ou em
// outra tela; fica em branco; ou a pagina rola de lado. (A tela com `erro` ou `parou` e' a que DEVE mostrar isso.) Uma tela de `telas.mjs` pode trazer `passos` (cliques que
// abrem uma janela ou um formulario) e `simular` (respostas da API trocadas, para ver a tela vazia ou a de erro).
// A auditoria visual (`auditoria.mjs`: texto cortado, fora da vista ou sobreposto, letra e canto fora da fundacao)
// roda em cada tela e largura e sai como aviso; o resumo do fim junta os achados por tipo.
//
// Grava em `<saida>/capturas/`: `<perfil>/<tela>-<largura>.png` (pagina inteira), `login-<largura>.png` e o
// `relato.json` com o que foi visto em cada tela. A saida de uma copia do banco tem dado real: mora fora do
// repositorio (ver `comum.py`). Os estados do login (`ESTADOS_DO_LOGIN`) saem em `login-<estado>-<largura>.png`.
//
// Navegador: o Chromium do Playwright quando esta' instalado (`npx playwright install chromium`, o que a CI faz);
// senao, o Chrome da maquina. DASH_PROVA_CANAL=chrome|msedge escolhe na mao.
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { auditar, REPROVA } from "./auditoria.mjs";
import { LARGURAS, LOGIN, MENU, PERFIS, RESPOSTAS_ESPERADAS, ROTAS_FORA, TELAS, telasDoPerfil } from "./telas.mjs";
import { ESTADOS_DO_LOGIN } from "./telas.mjs";

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
const COM_VALOR = ["--perfis", "--telas", "--larguras", "--capturas", "--escala", "--obra", "--medicao", "--empresa", "--rotulo"];
const SEM_VALOR = ["--conferir", "--estrito"];
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
const inteiro = nome => {
  const v = opcao(nome);
  if (v === undefined) return null;
  if (!/^[1-9]\d*$/.test(v)) recusar(`${nome} pede o número do registro`);
  return Number(v);
};
const pedidos = { obra: inteiro("--obra"), medicao: inteiro("--medicao"), empresa: inteiro("--empresa") };
if (pedidos.medicao !== null && pedidos.obra === null) recusar("--medicao pede --obra (a medição é de uma obra)");
const rotulo = opcao("--rotulo") ?? "";
if (rotulo && !/^[\w-]+$/.test(rotulo)) recusar("--rotulo aceita letras, números, hífen e sublinhado");
const conferir = args.includes("--conferir");
const estrito = args.includes("--estrito");

// Toda tela do roteador (`frontend/src/rota.tsx`) tem de estar em TELAS ou em ROTAS_FORA, com o motivo: a tela aberta
// por link ou por aba, que o menu nao cobra, nao sai da prova em silencio.
{
  const fonte = fs.readFileSync(path.join(RAIZ, "frontend", "src", "rota.tsx"), "utf8");
  const tipo = fonte.match(/export type Rota =([\s\S]*?);\r?\n/)?.[1] ?? "";
  const rotas = [...tipo.matchAll(/tela: "([a-z-]+)"/g)].map(m => m[1]);
  if (!rotas.length) recusar("não achei as telas de frontend/src/rota.tsx (mudou o tipo Rota?)");
  const cobertas = new Set([...TELAS.map(t => t.rota), ...Object.keys(ROTAS_FORA)]);
  const semTela = rotas.filter(r => !cobertas.has(r));
  if (semTela.length) {
    recusar(`rota sem tela na prova: ${semTela.join(", ")}. Ponha em TELAS ou em ROTAS_FORA (scripts/prova/telas.mjs).`);
  }
}

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
const SAIDA = path.join(servidor.saida, "capturas", rotulo);

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

function vigiar(pagina, onde, simuladas = [], parou = false) {
  const problemas = [];
  const simulada = (metodo, caminho) => simuladas.some(s => (s.metodo ?? "GET") === metodo && s.caminho.test(caminho));
  // na tela que cai de proposito (`parou`), o erro de script e o do console sao a propria queda
  pagina.on("pageerror", e => { if (!parou) problemas.push(`erro de script: ${e.message}`); });
  pagina.on("console", m => {
    if (m.type() !== "error" || parou) return;
    // a resposta 4xx/5xx ja' e' julgada abaixo, com a lista de esperadas; esta linha do console e' a mesma coisa
    if (m.text().startsWith("Failed to load resource: the server responded with a status of")) return;
    problemas.push(`erro no console: ${m.text().slice(0, 300)}`);
  });
  pagina.on("response", r => {
    if (r.status() < 400) return;
    const caminho = new URL(r.url()).pathname, metodo = r.request().method();
    if (simulada(metodo, caminho)) return;      // a resposta de erro que a propria tela da prova pediu
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
      // a falha de leitura ou de acao e' a peca Falha (.aviso--falha); o aviso critico de estado nao e' erro
      avisosDeErro: [...document.querySelectorAll("#conteudo .aviso--falha [role=alert], dialog[open] .aviso--falha [role=alert]")].filter(visivel).map(limpo),
      texto: (conteudo?.innerText ?? "").trim().length,
      larguraDaPagina: document.documentElement.scrollWidth,
      larguraDaJanela: window.innerWidth,
      // no celular a casca deixa o conteudo rolar dentro do <main> em vez de alargar a pagina: e' rolagem lateral igual
      sobraNoConteudo: (() => { const m = document.querySelector("main"); return m ? m.scrollWidth - m.clientWidth : 0; })(),
    };
  });
}

function julgar(estado, caminhoEsperado, problemas, erroEsperado = false, parou = false) {
  if (parou) {
    if (!estado.falha) problemas.push("a queda simulada não mostrou a tela \"A tela parou de responder\"");
  } else if (estado.falha) problemas.push(`tela de erro: ${estado.falha}`);
  else if (estado.login) problemas.push("caiu na tela de login");
  else {
    const esperado = new URL(caminhoEsperado, BASE).pathname;
    if (estado.caminho !== esperado) problemas.push(`abriu ${estado.caminho} no lugar de ${esperado}`);
    if (estado.texto < TEXTO_MINIMO) problemas.push("tela em branco (sem texto no conteúdo)");
  }
  if (erroEsperado && !estado.avisosDeErro.length) problemas.push("a falha simulada não apareceu na tela como aviso de erro");
  if (!erroEsperado) for (const a of estado.avisosDeErro) problemas.push(`aviso de erro na tela: ${a}`);
  if (estado.larguraDaPagina > estado.larguraDaJanela + 1) {
    problemas.push(`rola de lado: página com ${estado.larguraDaPagina} px numa janela de ${estado.larguraDaJanela} px`);
  }
  if (estado.sobraNoConteudo > 1) problemas.push(`rola de lado: o conteúdo passa ${estado.sobraNoConteudo} px da largura da tela`);
}

// Os achados da auditoria visual entram como aviso; com --estrito, os de REPROVA viram problema.
async function conferirVisual(pagina, problemas, avisos) {
  const achados = await auditar(pagina).catch(e => { avisos.push(`sem auditoria visual: ${e.message}`); return []; });
  for (const a of achados) {
    const frase = `${a.tipo}: ${a.onde}${a.texto ? ` "${a.texto}"` : ""}${a.detalhe ? ` (${a.detalhe})` : ""}`;
    (estrito && REPROVA.includes(a.tipo) ? problemas : avisos).push(frase);
  }
  return achados;
}

// Os passos de uma tela: cliques e preenchimentos que abrem a janela ou o formulario a conferir.
async function darPassos(pagina, passos) {
  for (const passo of passos) {
    if (passo.clicar) await pagina.locator(passo.clicar).first().click({ timeout: ESPERA });
    else if (passo.preencher) await pagina.locator(passo.preencher[0]).first().fill(passo.preencher[1], { timeout: ESPERA });
    else if (passo.arquivo) {
      await pagina.locator(passo.arquivo[0]).first().setInputFiles(
        { name: passo.arquivo[1], mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4\n% arquivo de prova, sem conteudo\n") },
        { timeout: ESPERA });
    }
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
    await pagina.evaluate(() => document.fonts.ready).catch(() => {});
    await conferirVisual(pagina, problemas, avisos);
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
    const menu = await pagina.locator(MENU).evaluateAll(as => as.map(a => new URL(a.href).pathname));
    const cobertos = telasDoPerfil(perfil).map(t => t.menu ?? t.caminho);
    for (const item of menu.filter(m => !cobertos.includes(m))) {
      problemas.push(`o menu de ${perfil} tem ${item} e scripts/prova/telas.mjs não tem tela para ele`);
    }
    if (menu.length === 0) problemas.push(`o menu não tem nenhum item (mudou o seletor ${MENU}, em telas.mjs?)`);
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

// Os estados da tela de login (`ESTADOS_DO_LOGIN`, em telas.mjs; #821): a recusa, o limite de tentativas e a
// espera. Antes de entrar, uma vez por largura (o primeiro perfil que chega abre), com e-mail e senha de mentira e
// a resposta do servidor simulada: nenhuma tentativa errada chega ao servidor de prova.
const estadosDoLoginVistos = new Set();

async function abrirEstadosDoLogin(contexto, perfil, largura) {
  if (estadosDoLoginVistos.has(largura)) return;
  estadosDoLoginVistos.add(largura);
  for (const estado of ESTADOS_DO_LOGIN) {
    const pagina = await contexto.newPage();
    const problemas = vigiar(pagina, "login", estado.simular), avisos = [], t0 = Date.now();
    let captura = null, achados = [];
    try {
      for (const s of estado.simular) {
        await pagina.route(u => s.caminho.test(u.pathname), (rota, pedido) => {
          if (pedido.method() !== (s.metodo ?? "GET")) return rota.fallback();
          if (s.pendurar) return undefined;      // sem resposta: o pedido fica aberto ate' a aba fechar
          return rota.fulfill({ status: s.status ?? 200, contentType: "application/json", body: JSON.stringify(s.corpo ?? {}) });
        });
      }
      await pagina.goto(BASE + LOGIN.caminho, { waitUntil: "load" });
      await pagina.locator(LOGIN.espera).waitFor({ state: "visible", timeout: ESPERA });
      await pagina.locator('input[name="email"]').fill("ninguem@exemplo.com.br");
      await pagina.locator('input[name="senha"]').fill("senha-de-mentira");
      await pagina.locator('form.entrar__form button[type="submit"]').click();
      await pagina.locator(estado.espera).first().waitFor({ state: "visible", timeout: ESPERA });
      await pagina.evaluate(() => document.fonts.ready).catch(() => {});
      const [pagina_, janela] = await pagina.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
      if (pagina_ > janela + 1) problemas.push(`rola de lado: página com ${pagina_} px numa janela de ${janela} px`);
      achados = await conferirVisual(pagina, problemas, avisos);
    } catch (e) {
      problemas.push(`o login não chegou ao estado "${estado.id}": ${String(e.message ?? e).split("\n")[0]}`);
    }
    if (querFoto(problemas)) {
      captura = path.join(SAIDA, `login-${estado.id}-${largura}.png`);
      await fotografar(pagina, captura, largura).catch(e => { avisos.push(`sem captura: ${e.message}`); captura = null; });
    }
    await pagina.close();
    registrar({ perfil, largura, tela: `${LOGIN.id}-${estado.id}`, doLogin: true, caminho: LOGIN.caminho, ms: Date.now() - t0,
      problemas, avisos, captura, achados });
  }
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
  // --obra e --medicao: outra obra da copia do banco, no lugar da primeira
  if (pedidos.obra !== null) {
    obra = contratos.some(c => c.id === pedidos.obra) ? pedidos.obra : null;
    const medicoes = obra === null ? [] : await ler(`/api/contratos/${obra}/medicoes`);
    medicao = pedidos.medicao === null ? medicoes[0]?.id ?? null : medicoes.find(m => m.id === pedidos.medicao)?.id ?? null;
  }
  // a empresa da pagina de Documentos: a primeira com certidao exigida (a que nao tem nenhuma abre uma pagina sem
  // o que conferir, e numa copia do banco a primeira de `/api/entidades` costuma ser assim)
  const documentos = await ler("/api/documentos");
  const empresas = documentos.empresas ?? [];
  const empresa = empresas.find(e => (e.certidoes ?? []).some(c => c.exigida)) ?? empresas[0];
  const daEmpresa = pedidos.empresa === null ? empresa?.entidade_id ?? null
    : empresas.find(e => e.entidade_id === pedidos.empresa)?.entidade_id ?? null;
  return { obra, medicao, empresa: daEmpresa };
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
  const preencher = c => c.replace(/:(\w+)/g, (_, n) => String(reg[n]));
  const caminho = preencher(tela.caminho);
  const pagina = await contexto.newPage();
  const simuladas = tela.simular ?? [];
  const problemas = vigiar(pagina, tela.id, simuladas, tela.parou === true), avisos = [], t0 = Date.now();
  let captura = null, achados = [];
  try {
    for (const s of simuladas) {
      await pagina.route(u => u.pathname.startsWith("/api/") && s.caminho.test(u.pathname), (rota, pedido) => {
        if (pedido.method() !== (s.metodo ?? "GET")) return rota.fallback();
        // `ajustar` muda a resposta verdadeira (um campo, um estado); `corpo` a troca inteira. Os dois podem ser
        // funcao dos registros da prova (obra, medicao, empresa).
        if (s.ajustar) {
          return rota.fetch().then(async r => rota.fulfill({ response: r, json: s.ajustar(await r.json(), reg) }));
        }
        const corpo = typeof s.corpo === "function" ? s.corpo(reg) : s.corpo ?? {};
        return rota.fulfill({ status: s.status ?? 200, contentType: "application/json", body: JSON.stringify(corpo) });
      });
    }
    await pagina.goto(BASE + caminho, { waitUntil: "load" });
    await assentar(pagina, tela.passos ? (tela.antes ?? "#conteudo") : tela.espera, problemas);
    if (tela.passos) {
      await darPassos(pagina, tela.passos);
      await assentar(pagina, tela.espera, problemas);
    }
    // `destino`: a tela que so' leva a outra (o endereco antigo do envio da nota abre a pagina da medicao)
    julgar(await estadoDaTela(pagina), preencher(tela.destino ?? tela.caminho).split("?")[0], problemas, tela.erro === true, tela.parou === true);
    achados = await conferirVisual(pagina, problemas, avisos);
  } catch (e) {
    problemas.push(`não abriu: ${String(e.message ?? e).split("\n")[0]}`);
  }
  const ms = Date.now() - t0;
  if (querFoto(problemas)) {
    captura = path.join(SAIDA, perfil, `${tela.id}-${largura}.png`);
    await fotografar(pagina, captura, largura).catch(e => { avisos.push(`sem captura: ${e.message}`); captura = null; });
  }
  await pagina.close();
  registrar({ perfil, largura, tela: tela.id, caminho, ms, problemas, avisos, captura, achados });
}

async function percorrer(navegador, perfil) {
  const telas = telasDoPerfil(perfil).filter(t => idsDasTelas.includes(t.id));
  for (const largura of larguras) {
    const contexto = await navegador.newContext({
      viewport: { width: largura, height: 900 }, deviceScaleFactor: escala, locale: "pt-BR",
      timezoneId: "America/Cuiaba", reducedMotion: "reduce", colorScheme: "light",
    });
    try {
      await abrirEstadosDoLogin(contexto, perfil, largura);
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
// resumo da auditoria visual: cada achado uma vez, com as telas e larguras em que apareceu
const porAchado = new Map();
for (const i of relato) {
  for (const a of i.achados ?? []) {
    const chave = `${a.tipo}: ${a.onde}${a.detalhe ? ` (${a.detalhe})` : ""}`;
    if (!porAchado.has(chave)) porAchado.set(chave, { texto: a.texto, onde: new Set() });
    porAchado.get(chave).onde.add(`${i.tela}@${i.largura}`);
  }
}
if (porAchado.size) {
  console.log(`\nauditoria visual: ${porAchado.size} achado(s)`);
  for (const [chave, v] of [...porAchado].sort()) {
    const onde = [...v.onde];
    console.log(`  ${chave}${v.texto ? ` "${v.texto}"` : ""}\n      em ${onde.slice(0, 6).join(", ")}${onde.length > 6 ? ` e mais ${onde.length - 6}` : ""}`);
  }
} else console.log("\nauditoria visual: nada achado");
// conferencia que nao abriu tela nenhuma (fora o login) nao conferiu nada: reprova, em vez de passar vazia
const semTela = !relato.some(i => i.tela !== LOGIN.id && !i.doLogin);
if (conferir && semTela) {
  console.log("  FALHA nenhuma tela foi aberta: --perfis ou --telas ficou vazio, ou nenhum perfil pedido tem as telas pedidas");
}
process.exit(conferir && (comProblema.length || semTela) ? 1 : 0);
