import { useEffect } from "react";
import { api } from "./api";

// Issue #644: a resposta do orgao chega pela conversa do e-mail que a dashboard enviou. O servidor le so' as conversas
// dos envios de quem esta' logado, com a conta Microsoft dela; a tela dispara a leitura ao entrar e a cada 5 minutos.

export type RespostaOrgao = {
  id: number; medicao_id: number; remetente: string; remetente_nome: string | null; recebida_em: string;
  assunto: string; trecho: string; anexos: string[];
};

/** Disparado na janela quando uma leitura registrou resposta nova: a tela aberta rele a lista dela. */
export const EVENTO_RESPOSTAS_LIDAS = "respostas-orgao-lidas";
const INTERVALO_MS = 5 * 60_000;

/** `ativo`: so' para quem envia e-mail (quem so' consulta nao dispara leitura). Falha nao aparece na tela. */
export function useLeituraDasRespostas(ativo: boolean) {
  useEffect(() => {
    if (!ativo) return;
    const ler = () => api<{ novas?: RespostaOrgao[] }>("/api/correio/respostas/ler", { method: "POST" })
      .then(r => { if (r?.novas?.length) window.dispatchEvent(new Event(EVENTO_RESPOSTAS_LIDAS)); })
      .catch(() => {});
    ler();
    const id = window.setInterval(ler, INTERVALO_MS);
    return () => window.clearInterval(id);
  }, [ativo]);
}
