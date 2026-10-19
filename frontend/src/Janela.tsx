import { useEffect, useRef } from "react";
import "./medicoes.css";

// Janela de dialogo da pagina da medicao (#152): as acoes que nao sao de uma etapa (atestado, medicao final,
// cancelar...) e os formularios pontuais (registrar envio feito fora, recebimento) abrem aqui, em vez de empurrar
// a pagina. <dialog> nativo com showModal(): o navegador prende o foco, o Esc fecha e o foco volta para quem abriu.
// Mesmo desenho da janela "Iniciar processo de medicao" (.iniciar).

export default function Janela({ titulo, aoFechar, children }: { titulo: string; aoFechar: () => void; children: React.ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d || d.open) return;
    // jsdom (testes) nao implementa showModal: la' a janela so' abre
    if (typeof d.showModal === "function") d.showModal(); else d.setAttribute("open", "");
  }, []);
  const fechar = () => { const d = ref.current; if (d && typeof d.close === "function") d.close(); else aoFechar(); };
  return (
    <dialog ref={ref} className="iniciar janela" aria-labelledby="janela-titulo" onClose={aoFechar}
      onClick={ev => { if (ev.target === ev.currentTarget) fechar(); }}>
      <div className="iniciar__caixa">
        <div className="iniciar__cabeca">
          <h2 className="iniciar__titulo" id="janela-titulo">{titulo}</h2>
          <button type="button" className="iniciar__fechar" aria-label="Fechar" onClick={fechar}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
              strokeLinecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>
          </button>
        </div>
        <div className="janela__corpo pilha">{children}</div>
      </div>
    </dialog>
  );
}
