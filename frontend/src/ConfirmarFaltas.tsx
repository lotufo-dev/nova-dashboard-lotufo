import { useRef, useState } from "react";
import { IconeAlerta } from "./icones";

// Issue #213 (decisao do Leo de 16/10/2026): documento faltando nao bloqueia o envio; o Enviar abre este aviso com
// tudo o que falta e a pessoa decide. "Cancelar" nao manda nada; "Continuar com o envio" manda a lista confirmada,
// que o servidor confere de novo (`mudou`: a lista que ele devolveu e' outra, entao a confirmacao e' pedida de novo).
// Janela modal para o teclado: o foco abre no Cancelar (um Enter a mais nao envia), Escape cancela, o Tab da' a volta
// dentro dela e, ao fechar, o foco volta ao botao que a abriu.
// Issue #230: o registro do envio feito por fora usa o mesmo aviso, com a pergunta e o botao do registro.
export default function ConfirmarFaltas({ itens, mudou = false, aoCancelar, aoContinuar,
  pergunta = "Deseja continuar com o envio?", rotuloContinuar = "Continuar com o envio" }: {
  itens: string[]; mudou?: boolean; aoCancelar: () => void; aoContinuar: () => void;
  pergunta?: string; rotuloContinuar?: string;
}) {
  const caixa = useRef<HTMLDivElement>(null);
  const [antes] = useState(() => document.activeElement as HTMLElement | null);
  // reaberto depois da recusa do servidor, o foco estava no Enviar desabilitado ("Enviando…") ou no <body>: volta
  // ao botao de envio do e-mail, que ja' esta' habilitado de novo quando o Cancelar e' clicado
  const cancelar = () => {
    aoCancelar();
    const alvo = antes && antes !== document.body && !(antes as HTMLButtonElement).disabled ? antes
      : document.querySelector<HTMLElement>(".ol-enviar");
    alvo?.focus();
  };
  function teclas(ev: React.KeyboardEvent<HTMLDivElement>) {
    // preventDefault (issue #230): dentro de um <dialog> (registro por fora), o Esc fecharia a janela de baixo junto
    if (ev.key === "Escape") { ev.preventDefault(); ev.stopPropagation(); cancelar(); return; }
    if (ev.key !== "Tab") return;
    const botoes = caixa.current?.querySelectorAll<HTMLElement>("button");
    if (!botoes || botoes.length === 0) return;
    const primeiro = botoes[0], ultimo = botoes[botoes.length - 1];
    if (ev.shiftKey && document.activeElement === primeiro) { ev.preventDefault(); ultimo.focus(); }
    else if (!ev.shiftKey && document.activeElement === ultimo) { ev.preventDefault(); primeiro.focus(); }
  }
  const um = itens.length === 1;
  return (
    <div className="ol-modal-fundo" role="presentation">
      <div ref={caixa} className="confirmar-faltas" role="alertdialog" aria-modal="true"
        aria-labelledby="confirmar-faltas-titulo" aria-describedby="confirmar-faltas-texto" onKeyDown={teclas}>
        <h2 className="confirmar-faltas__titulo" id="confirmar-faltas-titulo">
          <IconeAlerta className="icone icone--p" />ATENÇÃO
        </h2>
        <div id="confirmar-faltas-texto">
          <p>{mudou ? "O que falta mudou desde a sua confirmação. Agora falta:"
            : um ? "Falta neste envio:" : `Faltam ${itens.length} itens neste envio:`}</p>
          <ul className="confirmar-faltas__lista">{itens.map((x, i) => <li key={i}>{x}</li>)}</ul>
          <p className="confirmar-faltas__pergunta">{pergunta}</p>
        </div>
        <div className="confirmar-faltas__acoes">
          <button type="button" className="btn" autoFocus onClick={cancelar}>Cancelar</button>
          <button type="button" className="btn btn--primario" onClick={aoContinuar}>{rotuloContinuar}</button>
        </div>
      </div>
    </div>
  );
}
