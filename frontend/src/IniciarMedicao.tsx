import { useEffect, useRef, useState } from "react";
import { filtrarObras, porContratante, type ObraResumo } from "./resumoMedicoes";
import { ir, type Rota } from "./rota";
import { Link } from "./Link";

// "Iniciar processo de medição" (PROVISORIO, 09/10/2026, ate' o prototipo da janela): escolher a obra e ir para a
// etapa 1. Obra com medicao `prevista` (criada pelo cronograma) abre a pagina DESSA medicao em vez de criar outra
// com o mesmo numero; as outras vao para a nova medicao da obra (/obras/:id/medicoes/nova).
//
// <dialog> nativo com showModal(): o navegador prende o foco dentro dela (o resto da pagina fica inerte), o Esc
// fecha e o foco volta para o botao que a abriu. O fechar, por qualquer caminho, passa pelo evento `close`.

export function destino(o: ObraResumo): Rota {
  return o.prevista_id !== null ? { tela: "medicao", obra: o.contrato_id, id: o.prevista_id } : { tela: "nova-medicao", obra: o.contrato_id };
}

export default function IniciarMedicao({ obras, aoFechar }: { obras: ObraResumo[]; aoFechar: () => void }) {
  const janela = useRef<HTMLDialogElement>(null);
  const [termo, setTermo] = useState("");

  useEffect(() => {
    const d = janela.current;
    if (!d) return;
    // jsdom (testes) nao implementa showModal: la' a janela so' abre. Sem `close()` na limpeza: tirar o <dialog> do
    // DOM ja' o fecha, e o `close` disparado na limpeza dupla do StrictMode (dev) fechava a janela recem-aberta.
    if (d.open) return;
    if (typeof d.showModal === "function") d.showModal(); else d.setAttribute("open", "");
  }, []);

  const grupos = porContratante(filtrarObras(obras, termo));
  const fechar = () => janela.current?.close();

  return (
    <dialog ref={janela} className="iniciar" aria-labelledby="iniciar-titulo" aria-describedby="iniciar-dica" onClose={aoFechar}
      // clique no fundo (fora da caixa) fecha, como numa janela comum
      onClick={ev => { if (ev.target === ev.currentTarget) fechar(); }}>
      <div className="iniciar__caixa">
        <div className="iniciar__cabeca">
          <div>
            <h2 id="iniciar-titulo" className="iniciar__titulo">Iniciar processo de medição</h2>
            <p id="iniciar-dica" className="iniciar__dica">Escolha a obra</p>
          </div>
          <button type="button" className="iniciar__fechar" aria-label="Fechar" onClick={fechar}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
              strokeLinecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>
          </button>
        </div>
        <input type="search" className="iniciar__busca" placeholder="Buscar obra ou contratante…" aria-label="Buscar obra ou contratante"
          autoComplete="off" autoFocus value={termo} onChange={ev => setTermo(ev.target.value)} />
        <div className="iniciar__lista">
          {grupos.length === 0 && <p className="iniciar__vazio" role="status">Nenhuma obra ativa com “{termo.trim()}”.</p>}
          {grupos.map(g => (
            <section key={g.contratante} className="iniciar__grupo" aria-label={g.contratante}>
              <h3 className="iniciar__contratante">{g.contratante}</h3>
              <ul>
                {g.obras.map(o => (
                  <li key={o.contrato_id}>
                    <Link className="iniciar__obra" para={destino(o)} ir={(d, op) => { fechar(); ir(d, op); }}>
                      <span className="iniciar__obra-nome">{o.obra}</span>
                      <span className="iniciar__obra-sub">
                        {[o.orgao_sub, o.prevista_id !== null ? "medição prevista no cronograma" : o.aberta ? "já tem medição em andamento" : null]
                          .filter(Boolean).join(" · ")}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      </div>
    </dialog>
  );
}
