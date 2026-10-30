import { useRascunho } from "./rascunho";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { api } from "./api";
import EditorCorpo from "./EditorCorpo";
import ErroCampo from "./ErroCampo";
import { fmtTamanho as tamanho } from "./formato";
import { Link } from "./Link";

// Busca que nunca derruba a tela: sem resposta (servidor antigo, teste), a janela abre do mesmo jeito.
function buscar<T>(caminho: string): Promise<T> {
  return Promise.resolve().then(() => api<T>(caminho));
}

// Envio de e-mail como no Outlook (pedido do Leonardo em 2026-09-25): "De:" com a conta Microsoft,
// destinatarios em etiquetas com sugestao enquanto digita, botao "Para" que abre "Adicionar Destinatarios",
// Cc e Cco, "Adicionar um assunto", anexos em cartoes e a assinatura de quem envia no fim do corpo.
// Sugestoes: GET /api/correio/contatos (cadastro da dashboard + diretorio Microsoft quando a conta permite).

export type Mensagem = { para: string[]; copia: string[]; cco: string[]; assunto: string; corpo: string };
type Contato = { nome: string | null; email: string };
type Campo = "para" | "copia" | "cco";
const ROTULO: Record<Campo, string> = { para: "Para", copia: "Cc", cco: "Cco" };
const EMAIL = /^[^\s@;,]+@[^\s@;,]+\.[^\s@;,]{2,}$/;
const CORES = ["#e8d7f7", "#d6ebd8", "#fde2c8", "#d3e6f5", "#f6d5d8", "#e6e1c6"];

function iniciais(c: Contato): string {
  const base = (c.nome || c.email.split("@")[0]).replace(/[^A-Za-zÀ-ÿ ]/g, " ").trim();
  const partes = base.split(/\s+/).filter(Boolean);
  return ((partes[0]?.[0] ?? "?") + (partes.length > 1 ? partes[partes.length - 1][0] : "")).toUpperCase();
}

function Avatar({ c }: { c: Contato }) {
  const cor = CORES[[...c.email].reduce((s, ch) => s + ch.charCodeAt(0), 0) % CORES.length];
  return <span className="ol-avatar" style={{ background: cor }} aria-hidden="true">{iniciais(c)}</span>;
}

const IconePessoa = () => (
  <svg className="ol-chip__icone" viewBox="0 0 16 16" width="12" height="12" aria-hidden="true">
    <circle cx="8" cy="8" r="6.5" fill="none" stroke="currentColor" strokeWidth="1.2" />
    <path d="M5.8 5.8l4.4 4.4M10.2 5.8l-4.4 4.4" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
  </svg>
);
const IconeFechar = () => (
  <svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true">
    <path d="M3.5 3.5l9 9M12.5 3.5l-9 9" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
  </svg>
);


function Destinatarios({ campo, valor, nomes, aoMudar, aoAbrirCatalogo, direita, idCampo, erro }: {
  campo: Campo; valor: string[]; nomes: Map<string, string | null>;
  aoMudar: (v: string[]) => void; aoAbrirCatalogo: () => void; direita?: React.ReactNode;
  idCampo: string; erro?: string;     // `erro`: a recusa do clique em Enviar, mostrada logo abaixo do campo
}) {
  const [texto, setTexto] = useState("");
  const [sugestoes, setSugestoes] = useState<Contato[]>([]);
  const [ativa, setAtiva] = useState(0);
  const entrada = useRef<HTMLInputElement>(null);
  const lista = useId();          // liga o campo (combobox) a' lista de sugestoes para o leitor de tela

  useEffect(() => {
    const q = texto.trim();
    if (q.length < 2) { setSugestoes([]); return; }
    let vivo = true;
    const t = setTimeout(() => {
      buscar<Contato[]>(`/api/correio/contatos?q=${encodeURIComponent(q)}`)
        .then(l => { if (vivo) { setSugestoes(l.filter(c => !valor.includes(c.email))); setAtiva(0); } })
        .catch(() => { if (vivo) setSugestoes([]); });
    }, 200);
    return () => { vivo = false; clearTimeout(t); };
  }, [texto, valor]);

  const adicionar = (email: string, focar = true) => {
    const e = email.trim().toLowerCase();
    if (e && EMAIL.test(e) && !valor.includes(e)) aoMudar([...valor, e]);
    setTexto(""); setSugestoes([]);
    if (focar) entrada.current?.focus();
  };

  const confirmar = () => {
    if (sugestoes.length > 0) adicionar(sugestoes[ativa].email);
    else if (EMAIL.test(texto.trim())) adicionar(texto);
  };

  const teclas = (ev: React.KeyboardEvent<HTMLInputElement>) => {
    if (ev.key === "ArrowDown" && sugestoes.length) { ev.preventDefault(); setAtiva(a => (a + 1) % sugestoes.length); }
    else if (ev.key === "ArrowUp" && sugestoes.length) { ev.preventDefault(); setAtiva(a => (a - 1 + sugestoes.length) % sugestoes.length); }
    else if (ev.key === "Enter" || ev.key === "Tab" || ev.key === ";" || ev.key === ",") {
      if (texto.trim()) { ev.preventDefault(); confirmar(); }
    } else if (ev.key === "Backspace" && !texto && valor.length) aoMudar(valor.slice(0, -1));
    else if (ev.key === "Escape") setSugestoes([]);
  };

  return (
    <>
    <div className="ol-linha">
      <button type="button" className="ol-rotulo" onClick={aoAbrirCatalogo}
        title={`Escolher destinatários (${ROTULO[campo]})`}>{ROTULO[campo]}</button>
      <div className="ol-campo" onClick={() => entrada.current?.focus()}>
        {valor.map(e => (
          <span className="ol-chip" key={e} title={e}>
            <IconePessoa />
            <span className="ol-chip__nome">{nomes.get(e) || e}</span>
            <button type="button" aria-label={`Remover ${nomes.get(e) || e}`}
              onClick={ev => { ev.stopPropagation(); aoMudar(valor.filter(x => x !== e)); }}><IconeFechar /></button>
          </span>
        ))}
        <input ref={entrada} id={idCampo} className="ol-entrada" value={texto} aria-label={`${ROTULO[campo]}: digite um nome ou e-mail`}
          aria-invalid={erro ? true : undefined} aria-describedby={erro ? `${idCampo}-erro` : undefined}
          role="combobox" aria-autocomplete="list" aria-expanded={sugestoes.length > 0} aria-controls={lista}
          aria-activedescendant={sugestoes.length > 0 ? `${lista}-${ativa}` : undefined}
          autoComplete="off" spellCheck={false}
          onChange={e => setTexto(e.target.value)} onKeyDown={teclas}
          onBlur={() => { if (EMAIL.test(texto.trim())) adicionar(texto, false); else setTimeout(() => setSugestoes([]), 150); }} />
        {sugestoes.length > 0 && (
          <ul className="ol-sugestoes" role="listbox" id={lista} aria-label={`Sugestões para ${ROTULO[campo]}`}>
            {sugestoes.map((c, i) => (
              <li key={c.email} id={`${lista}-${i}`} role="option" aria-selected={i === ativa} className={`ol-sugestao${i === ativa ? " ol-sugestao--ativa" : ""}`}
                onMouseDown={ev => { ev.preventDefault(); adicionar(c.email); }} onMouseEnter={() => setAtiva(i)}>
                <Avatar c={c} />
                <span className="ol-sugestao__texto"><span className="ol-sugestao__nome">{c.nome || c.email}</span>
                  <span className="ol-sugestao__email">{c.email}</span></span>
              </li>
            ))}
          </ul>
        )}
        {direita && <span className="ol-campo__direita">{direita}</span>}
      </div>
    </div>
    <ErroCampo id={`${idCampo}-erro`} erro={erro} />
    </>
  );
}

function Catalogo({ campo, inicial, aoSalvar, aoCancelar }: {
  campo: Campo; inicial: string[]; aoSalvar: (v: string[]) => void; aoCancelar: () => void;
}) {
  const [busca, setBusca] = useState("");
  const [lista, setLista] = useState<Contato[] | null>(null);
  const [escolhidos, setEscolhidos] = useState<string[]>(inicial);
  const [nomes, setNomes] = useState<Map<string, string | null>>(new Map());

  useEffect(() => {
    let vivo = true;
    const t = setTimeout(() => {
      buscar<Contato[]>(`/api/correio/contatos?todos=true&q=${encodeURIComponent(busca.trim())}`)
        .then(l => { if (vivo) { setLista(l); setNomes(n => new Map([...n, ...l.map(c => [c.email, c.nome] as const)])); } })
        .catch(() => { if (vivo) setLista([]); });
    }, 200);
    return () => { vivo = false; clearTimeout(t); };
  }, [busca]);

  const alternar = (e: string) => setEscolhidos(v => v.includes(e) ? v.filter(x => x !== e) : [...v, e]);

  // Janela modal de verdade para o teclado: Escape fecha, o Tab da' a volta dentro dela e, ao fechar,
  // o foco volta ao botao Para/Cc/Cco que a abriu (sem isto ele caia no <body>).
  const caixa = useRef<HTMLDivElement>(null);
  // Capturado no PRIMEIRO render: num efeito, o `autoFocus` da busca ja' teria roubado o foco e o
  // "anterior" seria o proprio campo, que sai da pagina junto com a janela. A devolucao mora nos
  // comandos de fechar, e nao no cleanup de um efeito: no StrictMode do dev o efeito desmonta e
  // remonta ao abrir, e o cleanup devolveria o foco com a janela ainda aberta.
  const [antes] = useState(() => document.activeElement as HTMLElement | null);
  const cancelar = () => { aoCancelar(); antes?.focus(); };
  const salvar = () => { aoSalvar(escolhidos); antes?.focus(); };
  function teclas(ev: React.KeyboardEvent<HTMLDivElement>) {
    if (ev.key === "Escape") { ev.stopPropagation(); cancelar(); return; }
    if (ev.key !== "Tab") return;
    const focaveis = caixa.current?.querySelectorAll<HTMLElement>("button, input, [tabindex]:not([tabindex='-1'])");
    if (!focaveis || focaveis.length === 0) return;
    const primeiro = focaveis[0], ultimo = focaveis[focaveis.length - 1];
    if (ev.shiftKey && document.activeElement === primeiro) { ev.preventDefault(); ultimo.focus(); }
    else if (!ev.shiftKey && document.activeElement === ultimo) { ev.preventDefault(); primeiro.focus(); }
  }

  return (
    <div className="ol-modal-fundo" role="presentation" onMouseDown={cancelar}>
      <div ref={caixa} className="ol-modal" role="dialog" aria-modal="true" aria-label="Adicionar Destinatários"
        onMouseDown={ev => ev.stopPropagation()} onKeyDown={teclas}>
        <div className="ol-modal__cabeca">
          <span>Adicionar Destinatários</span>
          <button type="button" className="ol-icone" aria-label="Fechar" onClick={cancelar}><IconeFechar /></button>
        </div>
        <div className="ol-modal__corpo">
          <input className="ol-busca" type="search" autoFocus placeholder="Pesquisar contatos…" aria-label="Pesquisar contatos"
            autoComplete="off" spellCheck={false} value={busca} onChange={e => setBusca(e.target.value)} />
          <div className="ol-tabela-wrap">
            <table className="ol-tabela">
              <thead><tr><th aria-label="Escolher" /><th>Nome</th><th>Email</th></tr></thead>
              <tbody>
                {lista === null && <tr><td colSpan={3} className="ol-vazio">Carregando…</td></tr>}
                {lista?.length === 0 && <tr><td colSpan={3} className="ol-vazio">Nenhum resultado correspondente</td></tr>}
                {lista?.map(c => (
                  <tr key={c.email} onClick={() => alternar(c.email)}>
                    <td><input type="checkbox" checked={escolhidos.includes(c.email)} onChange={() => alternar(c.email)}
                      onClick={ev => ev.stopPropagation()} aria-label={`Escolher ${c.nome || c.email}`} /></td>
                    <td><span className="ol-pessoa"><Avatar c={c} /><span><span className="ol-sugestao__nome">{c.nome || c.email}</span>
                      <span className="ol-sugestao__email">{c.email}</span></span></span></td>
                    <td>{c.email}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="ol-escolhidos">
            <span className="ol-escolhidos__rotulo">{ROTULO[campo]}</span>
            <div>{escolhidos.map(e => (
              <span className="ol-chip" key={e} title={e}><IconePessoa /><span className="ol-chip__nome">{nomes.get(e) || e}</span>
                <button type="button" aria-label={`Remover ${e}`} onClick={() => alternar(e)}><IconeFechar /></button></span>
            ))}</div>
          </div>
        </div>
        <div className="ol-modal__rodape">
          <button type="button" className="ol-enviar" onClick={salvar}>Salvar</button>
          <button type="button" className="ol-botao" onClick={cancelar}>Cancelar</button>
        </div>
      </div>
    </div>
  );
}

// `bloqueado`: o envio nao pode sair nem tentado (o motivo esta' na tela de quem abriu). O que falta preencher nao
// bloqueia o botao: o clique mostra o erro junto do campo (issue #11); `validarAntes` e' a parte de quem abriu
// (ex.: a justificativa que fica acima do e-mail) -- mostra o proprio erro e devolve false se nao pode enviar.
// `aoMexer`: avisa quem abriu se o e-mail difere do que abriu (ex.: para avisar antes de uma acao que remonta o e-mail).
export default function ComporEmail({ inicial, anexos, ocupado, bloqueado, antes, aoEnviar, aoDescartar, validarAntes, rotuloEnviar = "Enviar", aoMexer }: {
  inicial: Mensagem; anexos: { nome: string; tamanho?: number }[]; ocupado: boolean; bloqueado?: boolean;
  antes?: React.ReactNode; aoEnviar: (m: Mensagem) => void; aoDescartar: () => void; validarAntes?: () => boolean;
  rotuloEnviar?: string; aoMexer?: (mexido: boolean) => void;
}) {
  const base = useId();
  const [tentou, setTentou] = useState(false);
  const [m, setM] = useState<Mensagem>(inicial);
  const [comCco, setComCco] = useState(inicial.cco.length > 0);
  const [catalogo, setCatalogo] = useState<Campo | null>(null);
  const [remetente, setRemetente] = useState<string | null>(null);
  const [nomes, setNomes] = useState<Map<string, string | null>>(new Map());
  const [assinatura, setAssinatura] = useState<"carregando" | "sim" | "nao">("carregando");
  const versao = useMemo(() => Date.now(), []);
  useRascunho(JSON.stringify(m) !== JSON.stringify(inicial));   // e-mail editado e ainda nao enviado

  useEffect(() => {
    buscar<{ remetente: string | null }>("/api/correio/remetente").then(r => setRemetente(r.remetente)).catch(() => setRemetente(null));
    buscar<Contato[]>("/api/correio/contatos?todos=true")
      .then(l => setNomes(new Map(l.map(c => [c.email, c.nome] as const)))).catch(() => {});
  }, []);

  const erroPara = tentou && m.para.length === 0 ? "Informe ao menos um destinatário." : undefined;
  const erroAssunto = tentou && !m.assunto.trim() ? "Informe o assunto." : undefined;

  function enviar() {
    setTentou(true);
    const deFora = validarAntes ? validarAntes() : true;
    if (!deFora) return;          // quem abriu ja' mostrou o erro dele e levou o foco (o campo fica acima do e-mail)
    if (m.para.length === 0) document.getElementById(`${base}-para`)?.focus();
    else if (!m.assunto.trim()) document.getElementById(`${base}-assunto`)?.focus();
    else aoEnviar(m);
  }

  // issue #28: descartar o que a pessoa escreveu pede confirmacao; sem nada mudado desde que abriu, nao ha' o
  // que perder e fecha direto. Confirmado, o e-mail volta ao que abriu (quem esta' embutido nao fecha a janela).
  const [confirmarDescarte, setConfirmarDescarte] = useState(false);
  const [versaoCorpo, setVersaoCorpo] = useState(0);
  const mexido = JSON.stringify(m) !== JSON.stringify(inicial);
  const avisarMexido = useRef(aoMexer);
  useEffect(() => { avisarMexido.current = aoMexer; });
  useEffect(() => { avisarMexido.current?.(mexido); }, [mexido]);
  function descartar() {
    if (!mexido) aoDescartar();
    else setConfirmarDescarte(true);
  }
  function confirmarDescartar() {
    // flushSync: o e-mail volta ao que abriu e solta a marca de rascunho ANTES de quem abriu navegar; senao o
    // roteador ainda o veria sujo e perguntaria de novo o que a pessoa acabou de confirmar.
    flushSync(() => {
      setConfirmarDescarte(false);
      setM(inicial); setComCco(inicial.cco.length > 0); setTentou(false);
      setVersaoCorpo(v => v + 1);          // o editor do corpo nao e' controlado: remonta com o texto do inicio
    });
    aoDescartar();
  }

  const campo = (c: Campo, direita?: React.ReactNode) => (
    <Destinatarios campo={c} valor={m[c]} nomes={nomes} aoMudar={v => setM({ ...m, [c]: v })}
      aoAbrirCatalogo={() => setCatalogo(c)} direita={direita} idCampo={`${base}-${c}`} erro={c === "para" ? erroPara : undefined} />
  );

  return (
    <div className="ol-janela">
      {antes}
      <div className="ol-topo">
        <button type="button" className="ol-enviar" disabled={ocupado || bloqueado} onClick={enviar}>
          <svg viewBox="0 0 20 20" width="16" height="16" aria-hidden="true"><path fill="currentColor"
            d="M2.2 2.3a.5.5 0 0 1 .6-.1l15 7.5a.5.5 0 0 1 0 .9l-15 7.5a.5.5 0 0 1-.7-.6L4.4 10 2.1 2.9a.5.5 0 0 1 .1-.6ZM5.3 10.5l-1.9 5.6L16.4 10 3.4 3.9l1.9 5.6H11a.5.5 0 0 1 0 1H5.3Z" /></svg>
          {ocupado ? "Enviando…" : rotuloEnviar}
        </button>
        <span className="ol-de">De: {remetente ?? "sua conta Microsoft"}</span>
        <button type="button" className="ol-icone ol-descartar" onClick={descartar} title="Descartar" aria-label="Descartar">
          <svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true"><path fill="currentColor"
            d="M8.5 4h3a1.5 1.5 0 0 0-3 0Zm-1 0a2.5 2.5 0 0 1 5 0h5a.5.5 0 0 1 0 1h-1.05l-1.2 10.34A3 3 0 0 1 12.27 18H7.73a3 3 0 0 1-2.98-2.66L3.55 5H2.5a.5.5 0 0 1 0-1h5ZM5.74 15.23A2 2 0 0 0 7.73 17h4.54a2 2 0 0 0 1.99-1.77L15.44 5H4.56l1.18 10.23Z" /></svg>
        </button>
      </div>
      {confirmarDescarte && (
        <div className="ol-confirmar" role="group" aria-label="Confirmar o descarte">
          <span aria-live="polite">Descartar o que foi escrito neste e-mail? O texto não fica guardado.</span>
          <button type="button" className="btn btn--pequeno btn--destrutivo" onClick={confirmarDescartar}>
            Descartar o e-mail
          </button>
          <button type="button" className="btn btn--pequeno" autoFocus onClick={() => setConfirmarDescarte(false)}>Continuar escrevendo</button>
        </div>
      )}
      {campo("para", !comCco && <button type="button" className="ol-cco" onClick={() => setComCco(true)}>Cco</button>)}
      {campo("copia")}
      {comCco && campo("cco")}
      <div className="ol-assunto">
        <input id={`${base}-assunto`} value={m.assunto} maxLength={300} placeholder="Adicionar um assunto…" aria-label="Assunto"
          aria-invalid={erroAssunto ? true : undefined} aria-describedby={erroAssunto ? `${base}-assunto-erro` : undefined}
          onChange={e => setM({ ...m, assunto: e.target.value })} />
        <ErroCampo id={`${base}-assunto-erro`} erro={erroAssunto} />
      </div>
      {anexos.length > 0 && (
        <ul className="ol-anexos" aria-label="Anexos">
          {anexos.map(a => (
            <li className="ol-anexo" key={a.nome} title={a.nome}>
              <span className={`ol-anexo__tipo ol-anexo__tipo--${a.nome.split(".").pop()?.toLowerCase()}`} aria-hidden="true">
                {a.nome.split(".").pop()?.toUpperCase()}</span>
              <span className="ol-anexo__texto"><span className="ol-anexo__nome">{a.nome}</span>
                {a.tamanho !== undefined && <span className="ol-anexo__tamanho">{tamanho(a.tamanho)}</span>}</span>
            </li>
          ))}
        </ul>
      )}
      <div className="ol-corpo">
        <EditorCorpo key={versaoCorpo} inicial={inicial.corpo} aoMudar={corpo => setM(x => ({ ...x, corpo }))} />
        <div className="ol-assinatura">
          {assinatura !== "nao" && (
            <img src={`/api/correio/assinatura?v=${versao}`} alt="Sua assinatura"
              onLoad={() => setAssinatura("sim")} onError={() => setAssinatura("nao")} />
          )}
          {assinatura === "nao" && (
            <p className="ol-sem-assinatura">Sem assinatura: cadastre a sua em <Link para={{ tela: "conta" }}>Minha conta</Link>.</p>
          )}
        </div>
      </div>
      {catalogo && (
        <Catalogo campo={catalogo} inicial={m[catalogo]}
          aoSalvar={v => { setM({ ...m, [catalogo]: v }); setCatalogo(null); }} aoCancelar={() => setCatalogo(null)} />
      )}
    </div>
  );
}
