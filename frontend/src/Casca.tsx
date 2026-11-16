import { useEffect, useId, useRef, useState } from "react";
import { api } from "./api";
import { IconeAjustes, IconeAlerta, IconeArquivo, IconeCifrao, IconeDocumento, IconeInicio, IconeMedicoes, IconeObras, IconeSiga,
  IconeSeta, IconeSino, IconeVoltar } from "./icones";
import type { Usuario } from "./Login";
import { menuDe, ROTULO, rotaDoItem, type ItemMenu } from "./navegacao";
import { type Ir } from "./rota";
import { Link } from "./Link";
import Simbolo from "./Simbolo";

// Casca de todas as telas logadas (#720, a casca da fundacao): o MENU LATERAL escuro a' esquerda (o simbolo e o nome
// da marca em dois pesos; icone e nome em cada item; o item ativo com fundo realcado e o icone no laranja da marca;
// recolhivel para so' icones) e o TOPO sobre o papel, com o titulo da secao e a conta.
//
// Estado: `largo` ou `recolhido`, no atributo `data-estado` da <nav>. No computador a escolha da pessoa fica
// guardada no navegador (padrao largo); no celular (< 768px) o menu nasce recolhido, abre POR CIMA da tela e fecha
// ao navegar. Os links ficam sempre no DOM e focaveis, com o nome visivel (largo) ou so' para leitor de tela
// (recolhido) como nome acessivel.

const CHAVE_MENU = "menu-lateral";

const CELULAR = "(max-width: 767px)";

function celular(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia(CELULAR).matches;
}

function estadoInicial(): "largo" | "recolhido" {
  if (celular()) return "recolhido";
  try { return localStorage.getItem(CHAVE_MENU) === "recolhido" ? "recolhido" : "largo"; } catch { return "largo"; }
}

const ICONES: Record<ItemMenu, (p: { className?: string }) => React.ReactElement> = {
  inicio: IconeInicio, medicoes: IconeMedicoes, obras: IconeObras, avisos: IconeSino, siga: IconeSiga, documentos: IconeDocumento,
  fechamento: IconeCifrao, "ancoras-docusign": IconeArquivo, admin: IconeAjustes,
};

export function Trilho({ perfil, marcado, ir }: { perfil: string; marcado: ItemMenu | "conta" | null; ir: Ir }) {
  const [estado, setEstado] = useState<"largo" | "recolhido">(estadoInicial);
  const largo = estado === "largo";
  const caixa = useRef<HTMLElement>(null);

  // Ao estreitar a janela para o celular o menu largo (que ali cobre a tela) recolhe sozinho.
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const m = window.matchMedia(CELULAR);
    const mudou = (ev: MediaQueryListEvent) => { if (ev.matches) setEstado("recolhido"); };
    m.addEventListener("change", mudou);
    return () => m.removeEventListener("change", mudou);
  }, []);

  // No celular o menu largo esta' por cima da tela: Esc e toque fora o fecham.
  useEffect(() => {
    if (!largo || !celular()) return;
    // celular() de novo a cada evento: com a janela alargada para o computador o menu volta ao fluxo da pagina
    const fora = (ev: MouseEvent) => { if (celular() && !caixa.current?.contains(ev.target as Node)) setEstado("recolhido"); };
    const tecla = (ev: KeyboardEvent) => { if (celular() && ev.key === "Escape") setEstado("recolhido"); };
    document.addEventListener("mousedown", fora);
    document.addEventListener("keydown", tecla);
    return () => { document.removeEventListener("mousedown", fora); document.removeEventListener("keydown", tecla); };
  }, [largo]);

  function alternar() {
    const novo = largo ? "recolhido" : "largo";
    setEstado(novo);
    if (!celular()) { try { localStorage.setItem(CHAVE_MENU, novo); } catch { /* sem armazenamento: vale so' agora */ } }
  }

  return (
    <nav className="menu" ref={caixa} aria-label="Navegação principal" data-estado={estado}
      // no celular o menu aberto cobre a tela: navegar o fecha
      onClick={ev => { if (celular() && (ev.target as HTMLElement).closest("a")) setEstado("recolhido"); }}>
      <div className="menu__bloco">
        {/* Marca: identidade, nao destino ("Início" ja' e' o primeiro item). O nome em dois pesos, como na marca. */}
        <span className="menu__marca" aria-hidden="true">
          <Simbolo className="menu__simbolo" />
          <span className="menu__rotulo menu__nome"><span className="menu__nome-apoio">grupo</span>lotufo</span>
        </span>
        {/* Links de verdade (<a href>): a URL e' o endereco da tela, e o navegador ganha "abrir em nova aba",
            copiar link e historico de graca. O item fica aceso tambem abaixo dele na hierarquia (navegacao.ts). */}
        <ul className="menu__lista">
          {menuDe(perfil).map(i => {
            const Icone = ICONES[i];
            return (
              <li key={i}>
                <Link className="menu__item" para={rotaDoItem(i)} menu ir={ir} title={largo ? undefined : ROTULO[i]}
                  aria-current={marcado === i ? "page" : undefined}>
                  <Icone className="icone menu__icone" />
                  <span className="menu__rotulo">{ROTULO[i]}</span>
                </Link>
              </li>
            );
          })}
        </ul>
        <button type="button" className="menu__recolher" aria-expanded={largo}
          aria-label={largo ? "Recolher o menu" : "Expandir o menu"} onClick={alternar}>
          <IconeVoltar className="icone menu__icone menu__seta" />
          <span className="menu__rotulo" aria-hidden="true">Recolher</span>
        </button>
      </div>
    </nav>
  );
}

/** Avatar da conta: a primeira letra do primeiro e do ultimo nome ("Admin Exemplo" → "AE"). */
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
        <IconeSeta className="icone conta__seta" />
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

/** Topo (56px): o titulo da SECAO a' esquerda e a conta a' direita. Nas telas de lista o titulo e'
 *  o h1 da pagina; na obra, na medicao, no envio da nota e no Inicio a pagina tem o proprio h1 (o objeto, ou o "Bom
 *  dia"), e a barra so' diz a secao. */
export function BarraSuperior({ titulo, ehH1, usuario, ir }: { titulo: string; ehH1: boolean; usuario: Usuario; ir: Ir }) {
  return (
    <header className="topo">
      {ehH1 ? <h1 className="topo__titulo">{titulo}</h1> : <p className="topo__titulo">{titulo}</p>}
      <Conta usuario={usuario} ir={ir} />
    </header>
  );
}
