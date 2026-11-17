import CaixaAviso from "./CaixaAviso";

/** A falha de uma acao ou de uma leitura (#768): a caixa de critico da fundacao (o octogono), no lugar da caixa
 *  vermelha com triangulo, que e' a forma de "vence em breve". O papel de alerta fica no texto: a caixa acrescenta a
 *  palavra do nivel so' para o leitor de tela, e quem le o alerta recebe a mensagem como o servidor mandou. */
export default function Falha({ id, children }: { id?: string; children: React.ReactNode }) {
  return <CaixaAviso nivel="critico"><span role="alert" id={id}>{children}</span></CaixaAviso>;
}
