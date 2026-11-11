import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { tituloMedicao } from "./medicao";
import { EVENTO_LEITURA_FEITA } from "./respostasOrgao";
import { cliqueSimples, hrefDe, type Ir, type Rota } from "./rota";

// Issue #654: quem enviou a planilha e' avisado, em qualquer pagina, de que o orgao respondeu. A lista vem do servidor
// ("respostas ainda nao vistas por quem enviou"), nao do retorno da leitura: a resposta que chegou com a pessoa fora
// aparece ao entrar. Uma linha por medicao; fechar ou abrir a resposta marca como vista e o aviso nao volta.

export type RespostaNaoVista = {
  medicao_id: number; contrato_id: number; orgao: string; obra: string; numero: number; tipo: string;
  respostas: number; ate: number; recebida_em: string;
};

const MAXIMO = 3;

export default function AvisoRespostas({ ir }: { ir: Ir }) {
  const [avisos, setAvisos] = useState<RespostaNaoVista[]>([]);
  // o que a pessoa ja' fechou nesta sessao (medicao -> ultima resposta mostrada): a lista pedida antes de fechar e que
  // chega depois nao traz o aviso de volta; resposta mais nova da mesma medicao (`ate` maior) avisa
  const fechados = useRef(new Map<number, number>());

  useEffect(() => {
    let vivo = true;
    let pedido = 0;
    const ler = () => {
      const meu = ++pedido;
      api<RespostaNaoVista[]>("/api/correio/respostas/nao-vistas")
        .then(lista => {
          if (!vivo || meu !== pedido || !Array.isArray(lista)) return;
          setAvisos(lista.filter(a => a.ate > (fechados.current.get(a.medicao_id) ?? 0)));
        })
        .catch(() => {});
    };
    ler();
    window.addEventListener(EVENTO_LEITURA_FEITA, ler);
    return () => { vivo = false; window.removeEventListener(EVENTO_LEITURA_FEITA, ler); };
  }, []);

  const marcar = (a: RespostaNaoVista) => {
    fechados.current.set(a.medicao_id, a.ate);
    setAvisos(atual => atual.filter(x => x.medicao_id !== a.medicao_id));
    // falhou: o aviso volta na proxima vez que a pessoa entrar
    api(`/api/correio/respostas/vistas/${a.medicao_id}`, { method: "POST", body: JSON.stringify({ ate: a.ate }) })
      .catch(() => {});
  };

  const resto = avisos.length - MAXIMO;
  return (
    <div className="aviso-respostas" role="status" aria-live="polite">
      {avisos.slice(0, MAXIMO).map(a => {
        const destino: Rota = { tela: "medicao", obra: a.contrato_id, id: a.medicao_id };
        const medicao = `${a.obra}, ${tituloMedicao(a)}`;
        return (
          <div className="aviso-resposta" key={a.medicao_id}>
            <p className="aviso-resposta__texto"><strong>{a.orgao} respondeu:</strong> {medicao}</p>
            <a className="btn btn--pequeno btn--primario" href={hrefDe(destino, undefined, "passo-2")}
              onClick={ev => {
                // Ctrl/Cmd+clique abre a medicao em outra aba; nos dois casos a resposta foi aberta
                if (cliqueSimples(ev)) { ev.preventDefault(); ir(destino, { secao: "passo-2" }); }
                marcar(a);
              }}>Ver resposta</a>
            <button type="button" className="aviso-resposta__fechar" aria-label={`Fechar o aviso de ${medicao}`}
              onClick={() => marcar(a)}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                strokeLinecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>
            </button>
          </div>
        );
      })}
      {resto > 0 && <p className="aviso-respostas__mais">e mais {resto}</p>}
    </div>
  );
}
