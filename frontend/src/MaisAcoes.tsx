import { useEffect, useRef, useState } from "react";

// "Mais ações" da pagina da medicao (#152): so' o que nao e' de uma etapa -- atestado, medicao final, cancelar,
// desistir e liberar envio preso. Cada item abre uma janela (a pagina decide qual). O menu fecha com Esc, com o
// clique fora e depois de escolher; o foco volta para o botao.

export type ItemAcao = { id: string; rotulo: string; perigo?: boolean; separador?: boolean };

export default function MaisAcoes({ itens, aoEscolher, desabilitado }: {
  itens: ItemAcao[]; aoEscolher: (id: string) => void; desabilitado?: boolean;
}) {
  const [aberto, setAberto] = useState(false);
  const caixa = useRef<HTMLDivElement>(null);
  const botao = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!aberto) return;
    const fora = (ev: MouseEvent) => { if (!caixa.current?.contains(ev.target as Node)) setAberto(false); };
    const tecla = (ev: KeyboardEvent) => { if (ev.key === "Escape") { setAberto(false); botao.current?.focus(); } };
    document.addEventListener("mousedown", fora);
    document.addEventListener("keydown", tecla);
    return () => { document.removeEventListener("mousedown", fora); document.removeEventListener("keydown", tecla); };
  }, [aberto]);

  if (itens.length === 0) return null;
  return (
    <div className="med-mais" ref={caixa}>
      <button type="button" className="btn" ref={botao} id="mais-acoes" aria-haspopup="menu" aria-expanded={aberto} aria-controls="mais-acoes-menu"
        disabled={desabilitado} onClick={() => setAberto(!aberto)}>
        Mais ações
        <svg className="icone icone--p" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 9l6 6 6-6" /></svg>
      </button>
      <div className="conta__menu" id="mais-acoes-menu" role="menu" hidden={!aberto}>
        {itens.map(i => (
          <div key={i.id}>
            {i.separador && <hr />}
            <button type="button" role="menuitem" className={`conta__item${i.perigo ? " conta__item--perigo" : ""}`}
              onClick={() => { setAberto(false); aoEscolher(i.id); }}>{i.rotulo}</button>
          </div>
        ))}
      </div>
    </div>
  );
}
