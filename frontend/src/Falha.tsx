import CaixaAviso from "./CaixaAviso";

/** A falha de uma acao ou de uma leitura (#768): a caixa de critico da fundacao (o octogono). E' a UNICA forma de
 *  erro do sistema: a caixa vermelha com triangulo saiu (o triangulo e' a forma de "vence em breve"). O papel de
 *  alerta fica no texto: a caixa acrescenta a palavra do nivel so' para o leitor de tela, e quem le o alerta recebe a
 *  mensagem como o servidor mandou. `aviso--falha` nao tem estilo: e' a marca que separa a falha do aviso critico de
 *  estado (backup atrasado, certidao vencida) para a prova das telas (`scripts/prova/capturar.mjs`). */
export default function Falha({ id, className, children }: { id?: string; className?: string; children: React.ReactNode }) {
  return (
    <CaixaAviso nivel="critico" className={`aviso--falha${className ? ` ${className}` : ""}`}>
      <span role="alert" id={id}>{children}</span>
    </CaixaAviso>
  );
}
