import { Component, type ErrorInfo, type ReactNode } from "react";

// Ultima rede do app (fase 3,5). Um erro de render num cartao — dado inesperado do
// servidor, bug num formato — derrubava a arvore inteira do React e a tela ficava
// BRANCA, sem uma palavra: quem estava no meio de um protocolo nao sabia se gravou.
// Aqui a tela diz o que aconteceu e oferece o unico caminho que sempre funciona:
// recarregar. O estado do servidor nao e' tocado — nada foi perdido do que ja gravou.
//
// Class component por exigencia do React: nao existe hook para getDerivedStateFromError.
type Estado = { erro: Error | null };

export default class ErrorBoundary extends Component<{ children: ReactNode }, Estado> {
  state: Estado = { erro: null };

  static getDerivedStateFromError(erro: Error): Estado {
    return { erro };
  }

  componentDidCatch(erro: Error, info: ErrorInfo) {
    // O console e' o unico log do frontend: e' onde quem reporta vai olhar.
    console.error("Erro de renderização", erro, info.componentStack);
  }

  render() {
    if (this.state.erro === null) return this.props.children;
    return (
      <div className="falha" role="alert">
        <h1 className="falha__titulo">A tela parou de responder</h1>
        {/* a mensagem da excecao fica so' no console (componentDidCatch): na tela, palavras da pessoa */}
        <p>O que já foi gravado está salvo. Recarregue a página para continuar.</p>
        <button type="button" className="btn btn--primario" onClick={() => location.reload()}>
          Recarregar a página
        </button>
      </div>
    );
  }
}
