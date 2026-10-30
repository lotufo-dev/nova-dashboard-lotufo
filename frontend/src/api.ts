let csrf: string | null = null;

export class ApiErro extends Error {
  status: number;
  // `detail` cru quando o servidor manda um objeto (10/10/2026: 409 de envio reservado traz `codigo`, quem e
  // quando). A tela decide por ele, nunca pelo texto da mensagem.
  corpo?: any;
  constructor(status: number, mensagem: string, corpo?: any) {
    super(mensagem);
    this.status = status;
    this.corpo = corpo;
  }
}

export function setCsrf(token: string | null) { csrf = token; }

// O FastAPI manda `detail` como string nos nossos HTTPException, mas como LISTA de
// objetos {loc, msg, ...} quando a validacao do Pydantic falha (ex.: campo obrigatorio
// em branco). Sem normalizar, a lista virava "[object Object]" na tela.
function mensagemErro(corpo: any, padrao: string, status = 0): string {
  const detail = corpo?.detail;
  // B-09 (10/10/2026): "Permissão necessária: editar_cadastros" e' codigo interno; quem so' consulta le o porque
  if (status === 403 && typeof detail === "string" && detail.startsWith("Permissão necessária")) {
    return "Seu perfil só consulta esta tela: a ação é da engenharia ou da administração.";
  }
  if (typeof detail === "string") return detail;
  if (typeof detail?.mensagem === "string") return detail.mensagem;      // detail estruturado (envio reservado)
  if (Array.isArray(detail)) {
    const itens = detail.map((e: any) => {
      const campo = Array.isArray(e?.loc) ? e.loc[e.loc.length - 1] : undefined;
      return campo ? `${campo} (${e?.msg})` : e?.msg;
    }).filter(Boolean);
    if (itens.length) return `Campos obrigatórios ausentes ou inválidos: ${itens.join("; ")}`;
  }
  return padrao;
}

// Sem `detail`, o fallback era o `r.statusText` cru: "Bad Gateway", "Service
// Unavailable", "Forbidden" — ingles tecnico do protocolo no meio de uma tela em
// portugues, e que nao diz o que fazer. A FAIXA do status ja diz o suficiente e e' a
// unica coisa confiavel aqui (proxy e servidor de arquivos respondem sem corpo): 5xx
// e' do lado do servidor e insistir costuma resolver; 4xx e' do pedido, e insistir
// nao resolve — por isso o codigo aparece, para quem for reportar ter o que dizer.
function padraoDoStatus(status: number): string {
  if (status >= 500) return "Servidor indisponível — tente novamente em instantes.";
  return `Pedido recusado (código ${status}).`;
}

// `fetch` so' REJEITA quando a requisicao nem chegou (rede caida, servidor fora, DNS,
// CORS): o erro nativo e' um TypeError com mensagem em ingles que as telas jogavam na
// tela via `String(e)`. Vira `ApiErro` com status 0 — nao ha resposta HTTP, e nenhum
// status real e' 0 — para as telas tratarem a falha de rede como qualquer outra.
async function pedir(caminho: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(caminho, init);
  } catch {
    throw new ApiErro(0, "Sem conexão com o servidor.");
  }
}

export async function api<T = unknown>(caminho: string, opts: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json", ...(opts.headers as any) };
  if (csrf) headers["X-CSRF-Token"] = csrf;
  const r = await pedir(caminho, { credentials: "include", ...opts, headers });
  if (!r.ok) {
    const corpo = await r.json().catch(() => ({}));
    throw new ApiErro(r.status, mensagemErro(corpo, padraoDoStatus(r.status), r.status), corpo?.detail);
  }
  return r.json();
}

/** POST de multipart (upload de PDF e leitura do PDF). Irmao de `api`, nao atalho.
 *
 * Nao da' para reaproveitar `api` aqui por um detalhe que falha em SILENCIO: o
 * `Content-Type` do multipart carrega o `boundary`, e quem o gera e' o navegador —
 * mas so' se o header NAO tiver sido declarado. O `"application/json"` fixo do `api`
 * substituiria esse header, o servidor nao acharia o boundary e o upload chegaria
 * como corpo ilegivel. Por isso este helper nao declara `Content-Type` nenhum.
 *
 * O resto e' identico, de proposito: mesmo cookie de sessao, mesmo header de CSRF
 * (o token vive na mesma variavel de modulo) e mesmo `ApiErro` com status + mensagem
 * pt-BR — a tela de certidoes exibe essa mensagem tal como o servidor a mandou
 * (arquivo recusado: 415/413/422).
 */
export async function apiForm<T = unknown>(caminho: string, dados: FormData): Promise<T> {
  const headers: Record<string, string> = {};
  if (csrf) headers["X-CSRF-Token"] = csrf;
  const r = await pedir(caminho, { method: "POST", credentials: "include", body: dados, headers });
  if (!r.ok) {
    const corpo = await r.json().catch(() => ({}));
    throw new ApiErro(r.status, mensagemErro(corpo, padraoDoStatus(r.status), r.status), corpo?.detail);
  }
  return r.json();
}

/** Download que pode ser recusado (issue #169: FRC desatualizada). Um `<a href>` abriria o JSON do erro no lugar da
 * tela; aqui a recusa vira `ApiErro` com a mensagem do servidor, e o arquivo baixa com o nome que o servidor deu. */
export async function baixarArquivo(caminho: string, nomePadrao: string): Promise<void> {
  const r = await pedir(caminho, { credentials: "include" });
  if (!r.ok) {
    const corpo = await r.json().catch(() => ({}));
    throw new ApiErro(r.status, mensagemErro(corpo, padraoDoStatus(r.status), r.status), corpo?.detail);
  }
  const disp = r.headers.get("Content-Disposition") ?? "";
  const utf8 = /filename\*=utf-8''([^;]+)/i.exec(disp);
  const simples = /filename="?([^";]+)"?/i.exec(disp);
  const nome = utf8 ? decodeURIComponent(utf8[1]) : simples ? simples[1] : nomePadrao;
  const url = URL.createObjectURL(await r.blob());
  const a = document.createElement("a");
  a.href = url; a.download = nome;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60_000);     // Firefox e Safari cancelam se revogar ja' no clique
}

/** Texto de erro para a tela. `ApiErro` ja traz mensagem em portugues (inclusive a falha de rede, status 0);
 * qualquer outra coisa lancada (bug de codigo, erro nativo) nao pode vazar "TypeError: ..." em ingles. */
export function mensagemDeErro(e: unknown): string {
  if (e instanceof ApiErro) return e.message;
  console.error(e);
  return "Algo deu errado. Tente de novo.";
}
