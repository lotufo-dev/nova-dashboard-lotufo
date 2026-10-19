import { useId, useState } from "react";
import { api, ApiErro, mensagemDeErro } from "./api";
import { IconeAlerta } from "./icones";

// Reserva de envio presa (10/10/2026): o servidor nao a toma sozinho, porque nao sabe se o e-mail saiu. Quem
// decide e' a pessoa, depois de conferir a caixa de Enviados; a liberacao fica na auditoria com o motivo e a
// declaracao. O servidor recusa liberar antes de 15 minutos (o envio do outro pode ainda estar saindo).

/** `detail` do 409 de envio reservado (envio_reserva.EnvioEmAndamento.detalhe). */
export type Reserva = {
  mensagem: string; codigo: string; reservado_em: string | null; reservado_por_nome: string | null;
  liberavel_a_partir_de: string | null;
};

export function envioReservado(e: unknown): e is ApiErro & { corpo: Reserva } {
  return e instanceof ApiErro && e.status === 409 && e.corpo?.codigo === "ENVIO_RESERVADO";
}

const hora = (iso: string | null) => (iso ? iso.slice(11, 16) : "—");     // ISO local: "2026-10-10T10:05:00-04:00"

export default function LiberarEnvio({ tabela, id, reserva, aoLiberar }: {
  tabela: "protocolos" | "espelhos" | "pleitos"; id: number; aoLiberar: () => void;
  /** Sem a reserva (a pessoa abriu a liberacao pelo menu da medicao), a tela nao sabe quem iniciou nem desde quando:
   *  o servidor decide se ha' o que liberar e se ja' passaram os 15 minutos. */
  reserva?: Reserva | null;
}) {
  const campo = useId();
  const declaracao = useId();
  const [motivo, setMotivo] = useState("");
  const [conferi, setConferi] = useState(false);
  const [ocupado, setOcupado] = useState(false);
  const [erro, setErro] = useState("");
  const [liberado, setLiberado] = useState(false);

  if (liberado) return <p className="feito" role="status">Trava removida. Confira os dados e envie de novo.</p>;

  async function liberar() {
    setOcupado(true); setErro("");
    try {
      await api("/api/envios/liberar", { method: "POST",
        body: JSON.stringify({ tabela, id, justificativa: motivo, conferi_enviados: conferi }) });
      setLiberado(true);
      aoLiberar();
    } catch (e) { setErro(mensagemDeErro(e)); } finally { setOcupado(false); }
  }

  return (
    <div className="campo">
      <span className="campo__nota">
        {reserva
          ? <>Iniciado às {hora(reserva.reservado_em)} por {reserva.reservado_por_nome ?? "outro usuário"}. Só pode ser
              liberado a partir das {hora(reserva.liberavel_a_partir_de)}.</>
          : <>Para o envio que ficou preso: a tela não sabe se o e-mail saiu. O servidor só libera depois de 15 minutos do início.</>}
      </span>
      <label className="campo__rotulo" htmlFor={campo}>Por que liberar (confira antes a caixa de Enviados)</label>
      <textarea id={campo} rows={2} maxLength={2000} value={motivo} onChange={ev => setMotivo(ev.target.value)}
        placeholder="Mínimo de 10 caracteres — ex.: conferi os Enviados, o e-mail não saiu…" />
      <label htmlFor={declaracao}>
        <input id={declaracao} type="checkbox" checked={conferi} onChange={ev => setConferi(ev.target.checked)} />{" "}
        Conferi a caixa de Enviados do Outlook e este e-mail NÃO consta
      </label>
      <div>
        <button type="button" className="btn btn--pequeno" disabled={ocupado || !conferi} onClick={() => void liberar()}>
          Liberar envio
        </button>
      </div>
      {erro && <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erro}</p>}
    </div>
  );
}
