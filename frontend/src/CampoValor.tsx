import { useLayoutEffect, useRef, useState } from "react";
import ErroCampo from "./ErroCampo";
import { coladoParaBrl, digitosParaBrl, MAX_DIGITOS_VALOR } from "./formato";

// Campo unico de valor em dinheiro (issue #190): espelho (medicao e reajuste), nota manual e valor da medicao.
// Os digitos entram pela direita com 2 casas ("5000000" -> "50.000,00"); apagar tira o ultimo digito; colar
// "50.000,00", "50000,5" ou "50000" le em reais. O valor que sai e' o texto "50.000,00" (ou "" quando vazio),
// o mesmo formato que as telas ja' mandavam ao servidor.

const ERRO_COLADO = "Valor colado em formato inválido: use vírgula nos centavos, ex.: 1.234,56";

const soDigitos = (texto: string) => texto.replace(/\D/g, "").replace(/^0+/, "");

type Resultado = string | null | { erro: true };   // `null`: a edicao nao entra; `erro`: formato que o servidor recusa

/** Um digito no fim, como caixa registradora. */
function acrescentar(antes: string, digito: string): Resultado {
  const digitos = soDigitos(antes + digito);
  if (digitos.length > MAX_DIGITOS_VALOR) return null;   // acima do teto do servidor: o digito nao entra
  return digitosParaBrl(digitos || "0");   // "0" digitado e' R$ 0,00 (glosa total), nao vazio (S3)
}

/** Texto inteiro em reais (colar, arrastar, preenchimento automatico, teclado que insere varios de uma vez). */
const emReais = (texto: string): Resultado => coladoParaBrl(texto) ?? { erro: true };

/** Novo texto do campo pelo TIPO da edicao (InputEvent.inputType), nao pela diferenca entre os textos (rodada 2
 *  da PR #193): o digito entra sempre no fim, apagar tira sempre um digito do fim, onde quer que esteja o cursor. */
function editar(antes: string, depois: string, tipo: string | undefined, dado: string | null): Resultado {
  if (tipo === "insertText" && dado !== null) {
    if (dado.length > 1) return emReais(dado);
    if (!/\d/.test(dado)) return null;   // letra, virgula ou ponto digitados: nao entram
    // o campo inteiro selecionado e substituido pelo digito: comeca do zero com ele
    return depois === dado ? acrescentar("", dado) : acrescentar(antes, dado);
  }
  if (tipo?.startsWith("delete")) {
    if (!depois) return "";   // tudo selecionado e apagado
    const digitos = soDigitos(antes).slice(0, -1);   // um digito so', com ou sem selecao parcial
    return digitos ? digitosParaBrl(digitos) : "";   // apagar ate' o fim volta a vazio
  }
  if (tipo?.startsWith("history")) return null;   // desfazer/refazer do navegador nao conhece o formato: recusa
  // colar ou arrastar: o texto que entrou substitui o campo (sem ele, o campo inteiro)
  if (tipo === "insertFromPaste" || tipo === "insertFromDrop") return emReais(dado || depois);
  // troca de texto, preenchimento automatico ou tipo desconhecido: o campo inteiro, em reais
  return depois ? emReais(depois) : "";
}

export default function CampoValor({ id, name, value, onChange, className = "entrada--media entrada--num num",
  placeholder = "Ex.: 50.000,00…", required, autoFocus }: {
  id: string; name: string; value: string; onChange: (valor: string) => void;
  className?: string; placeholder?: string; required?: boolean; autoFocus?: boolean;
}) {
  const ref = useRef<HTMLInputElement>(null);
  const tudoSelecionado = useRef(false);   // o campo inteiro estava selecionado quando a composicao comecou
  const [erro, setErro] = useState("");
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    // enquanto houver erro, o formulario nao envia (validacao nativa): nada de gravar o valor antigo calado (C3)
    el.setCustomValidity(erro);
    // o cursor fica no fim: e' la' que o digito entra
    if (document.activeElement === el) el.setSelectionRange(el.value.length, el.value.length);
  });
  const aplicar = (r: Resultado) => {
    if (r === null) return;
    if (typeof r === "object") { setErro(ERRO_COLADO); return; }
    setErro("");
    onChange(r);
  };
  return (
    <>
      <input ref={ref} id={id} name={name} autoComplete="off" spellCheck={false} className={className} inputMode="numeric"
        placeholder={placeholder} required={required} autoFocus={autoFocus} value={value}
        aria-invalid={erro ? true : undefined} aria-describedby={erro ? `${id}-erro` : undefined}
        onChange={ev => {
          const nativo = ev.nativeEvent as Partial<InputEvent>;
          if (nativo.isComposing) return;   // composicao (IME): so' no fim dela
          aplicar(editar(value, ev.target.value, nativo.inputType, nativo.data ?? null));
        }}
        onCompositionStart={ev => {
          // teclado que manda numeros por composicao (Firefox Android + SwiftKey): o campo inteiro selecionado no
          // comeco dela e' substituido, como no insertText (gate Sol, rodada extra da PR #193)
          const el = ev.currentTarget;
          tudoSelecionado.current = el.selectionStart === 0 && el.selectionEnd === el.value.length;
        }}
        onCompositionEnd={ev => {
          const base = tudoSelecionado.current ? "" : value;
          tudoSelecionado.current = false;
          if (ev.data) aplicar(ev.data.length === 1 ? (/\d/.test(ev.data) ? acrescentar(base, ev.data) : null) : emReais(ev.data));
        }}
        onPaste={ev => {
          // colar substitui o campo inteiro; texto que o servidor recusaria (ex.: "1234.56") nao entra e avisa
          ev.preventDefault();
          aplicar(emReais(ev.clipboardData.getData("text")));
        }} />
      <ErroCampo id={`${id}-erro`} erro={erro} />
    </>
  );
}
