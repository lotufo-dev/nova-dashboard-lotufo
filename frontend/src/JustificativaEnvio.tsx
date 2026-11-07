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

export default function JustificativaEnvio({ id, valor, aoMudar, erro }: {
  id: string; valor: string; aoMudar: (v: string) => void; erro?: string;
}) {
  return (
    <div className="campo ol-pendencias">
      <label className="campo__rotulo" htmlFor={id}>Justificativa (obrigatória para enviar sem apostilamento)</label>
      <textarea id={id} name="justificativa" autoComplete="off" rows={2} maxLength={2000} value={valor}
        aria-invalid={erro ? true : undefined} aria-describedby={erro ? `${id}-erro` : undefined}
        onChange={e => aoMudar(e.target.value)} />
      <ErroCampo id={`${id}-erro`} erro={erro} />
    </div>
  );
}
