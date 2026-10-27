import { useEffect, useId, useRef, useState } from "react";
import { api } from "./api";
import { IconeAjustes, IconeAlerta, IconeCifrao, IconeDocumento, IconeGrade, IconeInicio, IconeMedicoes, IconeObras,
  IconeSeta, IconeSino } from "./icones";
import type { Usuario } from "./Login";
import { menuDe, ROTULO, rotaDoItem, type ItemMenu } from "./navegacao";
import { type Ir } from "./rota";
import { Link } from "./Link";
import Simbolo from "./Simbolo";

// Casca de todas as telas logadas (09/10/2026, prototipo aprovado pelo Leo; mecanismo copiado do trilho do
// TutorBird ja' medido em outro projeto): o TRILHO indigo a' esquerda e a BARRA SUPERIOR branca com o titulo da
// secao e a conta. O menu lateral antigo (232px, grupos Trabalho/Consulta/Sistema, conta e Sair no pe) saiu.
//
// Trilho: UM elemento so'. A <nav> e' fixa com 64px e anima a propria largura ate' 265px quando o ponteiro passa
// ou o teclado entra (tokens.css, `.trilho`). Dentro dela, um bloco de largura FIXA de 265px que nunca reflui: a
// animacao so' o descobre, pelo corte (`overflow-x: hidden` e' o mecanismo, nao higiene). Cada item e' uma celula
// de icone de 64px (por isso o icone fica parado) e o rotulo a' direita, que comeca em 64px e por isso esta'
// escondido com o trilho fechado. Abre POR CIMA do conteudo: no fluxo da pagina so' existe o espaco de 64px.
// Os links sao um conjunto so', sempre no DOM e focaveis, com o rotulo visivel como nome acessivel.

const ICONES: Record<ItemMenu, (p: { className?: string }) => React.ReactElement> = {
  inicio: IconeInicio, medicoes: IconeMedicoes, obras: IconeObras, avisos: IconeSino, documentos: IconeDocumento,
  "a-receber": IconeCifrao, carteira: IconeGrade, admin: IconeAjustes,
};

export function Trilho({ perfil, marcado, ir }: { perfil: string; marcado: ItemMenu | "conta" | null; ir: Ir }) {
  return (
    <nav className="trilho" aria-label="Navegação principal">
      <div className="trilho__bloco">
        {/* Marca: identidade, nao destino ("Início" ja' e' o primeiro item). Simbolo na celula de 64px, o nome
            revelado pelo corte como os rotulos. */}
        <span className="trilho__marca" aria-hidden="true">
          <span className="trilho__celula"><Simbolo className="trilho__simbolo" /></span>
          <span className="trilho__rotulo trilho__nome">
            <span className="trilho__nome-1">grupolotufo</span>
          </span>
        </span>
        {/* Links de verdade (<a href>): a URL e' o endereco da tela, e o navegador ganha "abrir em nova aba",
            copiar link e historico de graca. O item fica aceso tambem abaixo dele na hierarquia (navegacao.ts). */}
        {menuDe(perfil).map(i => {
          const Icone = ICONES[i];
          return (
            <Link key={i} className="trilho__item" para={rotaDoItem(i)} menu ir={ir}
              aria-current={marcado === i ? "page" : undefined}>
              <span className="trilho__celula"><Icone className="icone trilho__icone" /></span>
              <span className="trilho__rotulo">{ROTULO[i]}</span>
            </Link>
          );
        })}
      </div>
    </nav>
  );
}

/** Avatar da conta: a primeira letra do primeiro e do ultimo nome ("Leonardo Praeiro" → "LP"). */
function iniciais(nome: string): string {
  const partes = nome.trim().split(/\s+/).filter(Boolean);
  if (partes.length === 0) return "";
  const ult = partes.length > 1 ? partes[partes.length - 1] : "";
  return (partes[0][0] + (ult ? ult[0] : "")).toUpperCase();
}

/** Botao da conta, a' direita da barra: abre no clique (ou Enter/Espaco, que o <button> ja' da'), fecha com Esc
 *  (o foco volta ao botao) e com clique fora. Padrao de "disclosure" (aria-expanded), nao role=menu: sao dois
 *  destinos comuns, e um menu ARIA prometeria setas que nao fazem falta aqui. */
function Conta({ usuario, ir }: { usuario: Usuario; ir: Ir }) {
  const [aberto, setAberto] = useState(false);
  const [saindo, setSaindo] = useState(false);
  const [erro, setErro] = useState("");
  const caixa = useRef<HTMLDivElement>(null);
  const botao = useRef<HTMLButtonElement>(null);
  const id = useId();

  useEffect(() => {
    if (!aberto) return;
    const fora = (ev: MouseEvent) => { if (!caixa.current?.contains(ev.target as Node)) setAberto(false); };
    const tecla = (ev: KeyboardEvent) => {
      if (ev.key === "Escape") { setAberto(false); botao.current?.focus(); }
    };
    document.addEventListener("mousedown", fora);
    document.addEventListener("keydown", tecla);
    return () => { document.removeEventListener("mousedown", fora); document.removeEventListener("keydown", tecla); };
  }, [aberto]);

  // O reload so' acontece DEPOIS de o servidor confirmar o logout. Com o `await` sem catch, uma rede caida
  // rejeitava a promessa, o reload nunca rodava e o botao ficava mudo: quem clicou continuava logado achando que
  // tinha saido — e nesta tela isso e' o oposto do que a pessoa quis.
  async function sair() {
    setErro(""); setSaindo(true);
    try {
      await api("/api/auth/logout", { method: "POST" });
      location.reload();
      // sem reabilitar o botao: a pagina esta indo embora
    } catch {
      setErro("Não foi possível encerrar a sessão — tente novamente.");
      setSaindo(false);
    }
  }

  return (
    <div className="conta" ref={caixa}>
      {/* o nome some no celular: o rotulo acessivel nao depende dele */}
      <button ref={botao} type="button" className="conta__botao" aria-expanded={aberto} aria-controls={id}
        aria-label={`Conta de ${usuario.nome}`} onClick={() => setAberto(a => !a)}>
        <span className="conta__avatar" aria-hidden="true">{iniciais(usuario.nome)}</span>
        <span className="conta__nome" aria-hidden="true">{usuario.nome}</span>
        <IconeSeta className="icone icone--p conta__seta" />
      </button>
      <div className="conta__menu" id={id} hidden={!aberto}>
        <Link className="conta__item" para={{ tela: "conta" }} menu
          ir={(d, o) => { setAberto(false); ir(d, o); }}>Minha conta</Link>
        <button type="button" className="conta__item" disabled={saindo} onClick={() => void sair()}>
          {saindo ? "Saindo…" : "Sair"}
        </button>
        {erro && <p className="erro conta__erro" role="alert"><IconeAlerta className="icone icone--p" />{erro}</p>}
      </div>
    </div>
  );
}

/** Barra superior branca (56px): o titulo da SECAO a' esquerda e a conta a' direita. Nas telas de lista o titulo e'
 *  o h1 da pagina; na obra, na medicao, no envio da nota e no Inicio a pagina tem o proprio h1 (o objeto, ou o "Bom
 *  dia"), e a barra so' diz a secao. */
export function BarraSuperior({ titulo, ehH1, usuario, ir }: { titulo: string; ehH1: boolean; usuario: Usuario; ir: Ir }) {
  return (
    <header className="barra">
      {ehH1 ? <h1 className="barra__titulo">{titulo}</h1> : <p className="barra__titulo">{titulo}</p>}
      <Conta usuario={usuario} ir={ir} />
    </header>
  );
}
