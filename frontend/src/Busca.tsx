import { useCallback, useEffect, useId, useRef, useState } from "react";
import { api } from "./api";
import Contador from "./Contador";
import Falha from "./Falha";
import { ESPERA_MS, MAX_PERGUNTA, ehMac, secoesDe, type Opcao, type RespostaBusca } from "./buscaDados";
import { cliqueSimples, hrefDe, type Ir } from "./rota";
import "./busca.css";

// BUSCA UNICA no topo (decisao do dono de 18/11/2026, #805; issue #819): obra, numero de medicao e numero de processo.
// A barra do topo (Casca.tsx, #814) desenha a peca entre o caminho e a conta. O dado vem de GET /api/busca?q=, que
// aplica o recorte do perfil num lugar so': o perfil sem SIGA nao recebe o grupo de processos (nem a contagem dele).
// Aqui so' se desenha o que o servidor manda, na ordem Obras, Medicoes, Processos.
//
// Teclado: "/" (fora de campo de texto) ou a tecla de comando do sistema + K (Cmd+K no Mac, Ctrl+K nos outros) poem o
// foco no campo; setas andam pelos resultados; Enter abre; Esc fecha e devolve o foco a quem o tinha; sair do campo
// (Tab, clique fora) fecha a lista. O Ctrl+K do Mac fica com o sistema: em campo de texto ele apaga ate' o fim da
// linha. Com uma janela aberta (`dialog[open]`) o atalho nao age: o campo esta' inerte atras dela.
// Abaixo de 1024 px (celular, e o computador com a janela estreita, onde o menu largo ainda ocupa 232 px) o campo vira
// um botao com a lupa, que abre o campo por cima da barra; fechado, o caminho fica inteiro.

function IconeLupa({ className }: { className?: string }) {
  return (
    <svg className={className ?? "icone"} viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="10.5" cy="10.5" r="6" />
      <path d="m15 15 5 5" />
    </svg>
  );
}

function editavel(el: EventTarget | null): boolean {
  if (!(el instanceof HTMLElement)) return false;
  return el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName)
    || !!el.closest('[contenteditable=""], [contenteditable="true"]');
}

function visivel(el: HTMLElement | null): el is HTMLElement {
  return !!el && el.getClientRects().length > 0;
}

export default function Busca({ ir }: { perfil: string; ir: Ir }) {
  const [texto, setTexto] = useState("");
  // a ultima resposta do servidor e a pergunta dela (ou a falha dela)
  const [resultado, setResultado] = useState<{ pergunta: string; dados?: RespostaBusca; erro?: boolean } | null>(null);
  const [lista, setLista] = useState(false);        // os resultados estao abertos
  const [painel, setPainel] = useState(false);      // celular: o campo aberto por cima da barra
  const [ativo, setAtivo] = useState(-1);
  const campo = useRef<HTMLInputElement>(null);
  const botao = useRef<HTMLButtonElement>(null);
  const caixa = useRef<HTMLDivElement>(null);
  const anterior = useRef<HTMLElement | null>(null);  // quem tinha o foco antes do atalho
  const id = useId();
  const idLista = `${id}-lista`;

  const pergunta = texto.trim();

  // Espera a pessoa parar de digitar e cancela a pergunta anterior: a lista nao pisca a cada letra; o resultado
  // antigo fica na tela ate' o novo chegar.
  useEffect(() => {
    if (!pergunta) return;
    const controle = new AbortController();
    const t = window.setTimeout(() => {
      api<RespostaBusca>(`/api/busca?q=${encodeURIComponent(pergunta)}`, { signal: controle.signal })
        .then(dados => { if (!controle.signal.aborted) { setResultado({ pergunta, dados }); setAtivo(-1); } })
        .catch(() => { if (!controle.signal.aborted) setResultado({ pergunta, erro: true }); });
    }, ESPERA_MS);
    return () => { window.clearTimeout(t); controle.abort(); };
  }, [pergunta]);

  const atual = pergunta ? resultado : null;
  const erro = !!atual?.erro;
  const pronta = !!atual && atual.pergunta === pergunta;        // a resposta e' da pergunta que esta' no campo
  const buscando = !!pergunta && !pronta;
  const secoes = atual?.dados ? secoesDe(atual.dados) : [];
  const opcoes = secoes.flatMap(s => s.opcoes);
  const aberta = lista && !!atual;

  const fechar = useCallback((devolverFoco: boolean) => {
    setLista(false); setPainel(false); setAtivo(-1);
    if (!devolverFoco) return;
    const volta = anterior.current;
    anterior.current = null;
    if (volta && volta.isConnected && volta !== campo.current) volta.focus();
    else if (visivel(botao.current)) botao.current.focus();
  }, []);

  const focar = useCallback(() => {
    const atual = document.activeElement;
    if (atual instanceof HTMLElement && atual !== campo.current && atual !== document.body) anterior.current = atual;
    setPainel(true);
    // o campo do celular so' existe na tela depois de aberto o painel
    window.setTimeout(() => { campo.current?.focus(); campo.current?.select(); }, 0);
  }, []);

  // atalho: "/" fora de campo de texto; Cmd+K (Mac) ou Ctrl+K (outros) em qualquer lugar
  useEffect(() => {
    const mac = ehMac();
    const tecla = (ev: KeyboardEvent) => {
      const k = ev.key.toLowerCase();
      const comando = mac ? ev.metaKey && !ev.ctrlKey : ev.ctrlKey && !ev.metaKey;
      const atalhoK = k === "k" && comando && !ev.altKey && !ev.shiftKey;
      const barra = ev.key === "/" && !ev.ctrlKey && !ev.metaKey && !ev.altKey && !editavel(ev.target);
      if (!atalhoK && !barra) return;
      if (document.querySelector("dialog[open]")) return;
      ev.preventDefault();
      focar();
    };
    document.addEventListener("keydown", tecla);
    return () => document.removeEventListener("keydown", tecla);
  }, [focar]);

  // clique fora fecha os resultados (e o painel do celular)
  useEffect(() => {
    if (!lista && !painel) return;
    const fora = (ev: MouseEvent) => { if (!caixa.current?.contains(ev.target as Node)) fechar(false); };
    document.addEventListener("mousedown", fora);
    return () => document.removeEventListener("mousedown", fora);
  }, [lista, painel, fechar]);

  // sair da caixa com o teclado (Tab) fecha a lista e o painel; o clique num item nao tira o foco do campo
  // (`onMouseDown` com preventDefault na lista), entao nao passa por aqui
  function aoSair(ev: React.FocusEvent<HTMLDivElement>) {
    const para = ev.relatedTarget as Node | null;
    if (para && caixa.current?.contains(para)) return;
    setLista(false); setPainel(false); setAtivo(-1);
  }

  function abrir(o: Opcao) {
    setTexto(""); setResultado(null);
    fechar(false);
    anterior.current = null;
    campo.current?.blur();
    ir(o.para, o.busca ? { busca: o.busca } : undefined);
  }

  function teclas(ev: React.KeyboardEvent<HTMLInputElement>) {
    if (ev.key === "Escape") {
      ev.preventDefault();
      setTexto("");
      fechar(true);
      return;
    }
    if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
      ev.preventDefault();
      setLista(true);
      if (opcoes.length === 0) return;
      const passo = ev.key === "ArrowDown" ? 1 : -1;
      setAtivo(a => (a + passo + opcoes.length + (a < 0 && passo < 0 ? 1 : 0)) % opcoes.length);
      return;
    }
    if (ev.key === "Enter") {
      const o = opcoes[ativo] ?? (opcoes.length === 1 ? opcoes[0] : undefined);
      if (o && aberta) { ev.preventDefault(); abrir(o); }
    }
  }

  // a opcao ativa fica a' vista quando a lista rola
  useEffect(() => {
    if (ativo < 0) return;
    document.getElementById(`${id}-op-${ativo}`)?.scrollIntoView?.({ block: "nearest" });
  }, [ativo, id]);

  const total = secoes.reduce((n, s) => n + s.opcoes.length, 0);
  // o leitor de tela ouve a contagem quando a resposta da pergunta atual chega (a falha ja' tem role="alert")
  const anuncio = !aberta || erro || !pronta ? "" : total === 0 ? "Nada encontrado." : total === 1 ? "1 resultado." : `${total} resultados.`;

  let i = -1;
  return (
    <div className={`busca${painel ? " busca--aberta" : ""}`} ref={caixa} onBlur={aoSair}>
      <button ref={botao} type="button" className="busca__abrir" aria-label="Buscar obra, medição ou processo"
        aria-expanded={painel} onClick={focar}>
        <IconeLupa />
      </button>
      <div className="busca__caixa" role="search">
        <div className="busca__linha">
          <IconeLupa className="icone busca__lupa" />
          <input ref={campo} type="search" className="busca__campo" value={texto} maxLength={MAX_PERGUNTA}
            placeholder="Obra, medição ou processo…" aria-label="Buscar obra, medição ou processo"
            role="combobox" aria-autocomplete="list" aria-expanded={aberta} aria-controls={idLista}
            aria-activedescendant={aberta && ativo >= 0 ? `${id}-op-${ativo}` : undefined}
            aria-keyshortcuts={ehMac() ? "/ Meta+K" : "/ Control+K"} autoComplete="off" spellCheck={false}
            onChange={ev => { setTexto(ev.target.value); setLista(true); setAtivo(-1); }}
            onFocus={() => setLista(true)} onKeyDown={teclas} />
          <button type="button" className="btn btn--pequeno busca__fechar" onClick={() => { setTexto(""); fechar(true); }}>
            Fechar
          </button>
        </div>
        <div className="busca__resultado" hidden={!aberta} aria-busy={buscando} onMouseDown={ev => ev.preventDefault()}>
          {erro && <Falha className="busca__falha">Não deu para buscar agora. Tente de novo em instantes.</Falha>}
          <div id={idLista} role="listbox" aria-label="Resultados da busca" className="busca__lista">
            {!erro && secoes.map(s => (
              <div key={s.id} role="group" aria-labelledby={`${id}-${s.id}`} className="busca__grupo">
                <div className="busca__titulo" id={`${id}-${s.id}`} role="presentation">
                  {s.rotulo}{" "}
                  <Contador rotulo={s.total > s.opcoes.length ? `${s.opcoes.length} de ${s.total} ${s.varios}`
                    : `${s.total} ${s.total === 1 ? s.um : s.varios}`}>
                    {s.total > s.opcoes.length ? `${s.opcoes.length} de ${s.total}` : s.total}
                  </Contador>
                </div>
                {s.opcoes.map(o => {
                  i += 1;
                  const n = i;
                  return (
                    <a key={o.chave} id={`${id}-op-${n}`} role="option" aria-selected={n === ativo} tabIndex={-1}
                      className="busca__opcao" href={hrefDe(o.para, o.busca)}
                      onMouseDown={ev => ev.preventDefault()} onMouseEnter={() => setAtivo(n)}
                      onClick={ev => { if (cliqueSimples(ev)) { ev.preventDefault(); abrir(o); } }}>
                      <span className="busca__principal">{o.principal}</span>
                      {o.detalhe && <span className="busca__detalhe">{o.detalhe}</span>}
                    </a>
                  );
                })}
              </div>
            ))}
          </div>
          {!erro && pronta && total === 0 && <p className="busca__vazio">Nada encontrado para “{pergunta}”.</p>}
        </div>
        <span className="sr-only" aria-live="polite">{anuncio}</span>
      </div>
    </div>
  );
}
