import { useEffect } from "react";
import { api } from "./api";

// Issue #644: a resposta do orgao chega pela conversa do e-mail que a dashboard enviou. O servidor le so' as conversas
// dos envios de quem esta' logado, com a conta Microsoft dela; a tela dispara a leitura ao entrar e a cada 5 minutos.

export type RespostaOrgao = {
  id: number; medicao_id: number; remetente: string; remetente_nome: string | null; recebida_em: string;
  assunto: string; trecho: string; anexos: string[];
  // #667: o processo do SIGA que esta resposta trouxe (o link de acompanhamento estava no corpo); null = resposta comum
  siga_processo_id?: number | null;
};

/** Disparado na janela quando uma leitura registrou resposta nova: a tela aberta rele a lista dela. */
export const EVENTO_RESPOSTAS_LIDAS = "respostas-orgao-lidas";
/** Issue #654: disparado depois de TODA leitura que o servidor respondeu, com ou sem resposta nova: o aviso flutuante
 *  rele as respostas nao vistas (a que outra sessao da mesma pessoa registrou tambem aparece). */
export const EVENTO_LEITURA_FEITA = "respostas-orgao-leitura-feita";
const INTERVALO_MS = 5 * 60_000;

/** `ativo`: so' para quem envia e-mail (quem so' consulta nao dispara leitura). Falha nao aparece na tela. */
export function useLeituraDasRespostas(ativo: boolean) {
  useEffect(() => {
    if (!ativo) return;
    const ler = () => api<{ novas?: RespostaOrgao[] }>("/api/correio/respostas/ler", { method: "POST" })
      .then(r => {
        if (r?.novas?.length) window.dispatchEvent(new Event(EVENTO_RESPOSTAS_LIDAS));
        window.dispatchEvent(new Event(EVENTO_LEITURA_FEITA));
      })
      .catch(() => {});
    ler();
    const id = window.setInterval(ler, INTERVALO_MS);
    return () => window.clearInterval(id);
  }, [ativo]);
}
