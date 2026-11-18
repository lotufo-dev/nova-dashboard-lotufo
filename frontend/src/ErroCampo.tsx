import Falha from "./Falha";

/** O erro de validação junto do campo que o causou (issue #11): o campo aponta para ele por `aria-describedby`
 *  e marca `aria-invalid`; some sozinho quando `erro` fica vazio. */
export default function ErroCampo({ id, erro }: { id: string; erro?: string }) {
  return erro ? <Falha id={id}>{erro}</Falha> : null;
}
