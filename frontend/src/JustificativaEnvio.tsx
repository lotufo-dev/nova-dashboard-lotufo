import ErroCampo from "./ErroCampo";

// Issue #278: o reajuste sem apostilamento que cubra a competencia so' sai com justificativa escrita (o servidor recusa
// menos que isso, protocolo.MIN_JUSTIFICATIVA). O campo fica acima do e-mail; o clique em Enviar sem ela mostra o erro
// junto do campo, leva o foco a ele e nao abre o aviso do que falta.
export const MIN_JUSTIFICATIVA = 10;

export function erroDaJustificativa(texto: string): string | undefined {
  return texto.trim().length < MIN_JUSTIFICATIVA
    ? `Escreva a justificativa, com pelo menos ${MIN_JUSTIFICATIVA} caracteres.` : undefined;
}

/** Chamado pelo Enviar (o `validarAntes` do ComporEmail): devolve false, com o foco no campo, se a justificativa falta. */
export function conferirJustificativa(id: string, texto: string): boolean {
  if (!erroDaJustificativa(texto)) return true;
  document.getElementById(id)?.focus();
  return false;
}

/** Issue #562: as pendencias que pedem o texto escrito (o servidor confere o mesmo, protocolo.exige_justificativa). */
export const PEDEM_JUSTIFICATIVA = ["sem_apostilamento", "nota_divergente"];
export const pedeJustificativa = (itens: { codigo: string }[]) => itens.some(x => PEDEM_JUSTIFICATIVA.includes(x.codigo));

export default function JustificativaEnvio({ id, valor, aoMudar, erro, notaDivergente = false }: {
  id: string; valor: string; aoMudar: (v: string) => void; erro?: string;
  /** issue #562: a nota diverge do espelho; o campo pede o motivo do envio */
  notaDivergente?: boolean;
}) {
  return (
    <div className="campo ol-pendencias">
      <label className="campo__rotulo" htmlFor={id}>
        {notaDivergente ? "Motivo do envio com a nota divergente (obrigatório)" : "Justificativa (obrigatória para enviar sem apostilamento)"}
      </label>
      <textarea id={id} name="justificativa" autoComplete="off" rows={2} maxLength={2000} value={valor}
        aria-invalid={erro ? true : undefined} aria-describedby={erro ? `${id}-erro` : undefined}
        onChange={e => aoMudar(e.target.value)} />
      <ErroCampo id={`${id}-erro`} erro={erro} />
    </div>
  );
}
