import { useEffect, useId, useRef, useState } from "react";
import { api } from "./api";
import Busca from "./Busca";
import Caminho from "./Caminho";
import { IconeAjustes, IconeAReceber, IconeArquivo, IconeCifrao, IconeDocumento, IconeDocumentoVisto, IconeEscudo, IconeEstrela, IconeFunil, IconeLupa,
  IconeGrade, IconeInicio, IconeMedicoes, IconeObras, IconePessoa, IconeSiga, IconeSeta, IconeSino, IconeVoltar } from "./icones";
import type { Usuario } from "./Login";
import { areaEhAPagina, menuDe, ROTULO, rotaDoItem, type ItemMenu } from "./navegacao";
// `Busca` aqui e' a peca da busca unica; os filtros do endereco (o tipo `Busca` do roteador) entram como `Filtros`
import { type Busca as Filtros, type Ir, type Origem, type Rota } from "./rota";
import { Link } from "./Link";
import Simbolo from "./Simbolo";
import Falha from "./Falha";

// Casca de todas as telas logadas (#720, a casca da fundacao): o MENU LATERAL escuro a' esquerda (o simbolo e o nome
// da marca em dois pesos; icone e nome em cada item; o item ativo com fundo realcado e o icone no laranja da marca;
// recolhivel para so' icones) e o TOPO sobre o papel, com o caminho da pagina, o lugar da busca e a conta.
//
// MENU EM AREAS (decisao do dono de 18/11/2026, #805; issue #814): os itens ficam agrupados por area, com o nome da
// area escrito em cima das paginas dela (navegacao.ts). A area que e' a propria pagina (Obras) e' um item so', sem o
// nome repetido. A area da pagina aberta fica com o nome aceso. Recolhido, some o nome da area e fica um fio entre
// uma area e a outra; o nome continua sendo o nome da lista para o leitor de tela.
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

/** A escolha guardada no computador (padrao largo). */
function escolhaGuardada(): "largo" | "recolhido" {
  try { return localStorage.getItem(CHAVE_MENU) === "recolhido" ? "recolhido" : "largo"; } catch { return "largo"; }
}

function estadoInicial(): "largo" | "recolhido" {
  return celular() ? "recolhido" : escolhaGuardada();
}

const ICONES: Record<ItemMenu, (p: { className?: string }) => React.ReactElement> = {
  inicio: IconeInicio, medicoes: IconeMedicoes, "resumo-medicoes": IconeGrade, obras: IconeObras, fechamento: IconeCifrao,
  "a-receber": IconeAReceber, avisos: IconeSino, siga: IconeSiga, licitacoes: IconeFunil, "licitacoes-favoritas": IconeEstrela, "licitacoes-todas": IconeLupa,
  certidoes: IconeDocumento, regularidade: IconeDocumentoVisto,
  garantias: IconeEscudo, "ancoras-docusign": IconeArquivo, admin: IconeAjustes, conta: IconePessoa,
};

// `permissoes`: as que o servidor informou em /api/auth/eu; o item SIGA e' de quem tem `ver_siga` (#829) e a area
// Licitacoes, de quem tem `ver_licitacoes` (#908)
export function Trilho({ perfil, permissoes, marcado, ir }: {
  perfil: string; permissoes?: readonly string[]; marcado: ItemMenu | null; ir: Ir;
}) {
  const [estado, setEstado] = useState<"largo" | "recolhido">(estadoInicial);
  const largo = estado === "largo";
  const caixa = useRef<HTMLElement>(null);
  const id = useId();

  // Ao estreitar a janela para o celular o menu largo (que ali cobre a tela) recolhe sozinho. Ao alargar de volta,
  // vale de novo a escolha guardada: sem isso o menu ficava recolhido ate' recarregar a pagina, sem ninguem ter
  // clicado (era o menu "recolhido em umas capturas e aberto em outras", #779).
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const m = window.matchMedia(CELULAR);
    const mudou = (ev: MediaQueryListEvent) => setEstado(ev.matches ? "recolhido" : escolhaGuardada());
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
        {/* Uma lista por area, com o nome dela em cima. Links de verdade (<a href>): a URL e' o endereco da tela, e o
            navegador ganha "abrir em nova aba", copiar link e historico de graca. O item fica aceso tambem abaixo
            dele na hierarquia (navegacao.ts). */}
        <div className="menu__areas">
          {menuDe(perfil, permissoes).map(a => {
            const sozinha = areaEhAPagina(a);
            const acesa = marcado !== null && a.paginas.includes(marcado);
            return (
              <div key={a.id} className={acesa ? "menu__area menu__area--acesa" : "menu__area"}>
                {!sozinha && <p className="menu__area-nome" id={`${id}-${a.id}`}>{a.rotulo}</p>}
                <ul className="menu__lista" aria-labelledby={sozinha ? undefined : `${id}-${a.id}`}>
                  {a.paginas.map(i => {
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
              </div>
            );
          })}
        </div>
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
        {erro && <Falha className="conta__erro">{erro}</Falha>}
      </div>
    </div>
  );
}

/** Topo: o CAMINHO da pagina a' esquerda (#814), o lugar da busca unica e a conta a' direita. O trecho da pagina e' o
 *  titulo: nas telas de lista ele e' o h1; na obra, na medicao e no Inicio a pagina tem o proprio h1 (o objeto, ou o
 *  "Bom dia"), e a barra so' escreve o trecho, na letra dos outros (19/11/2026). Quando o caminho nao cabe numa linha (celular, nome
 *  longo), ele quebra e a barra cresce; nada e' cortado. */
export function BarraSuperior({ rota, busca, origem, ehH1, usuario, ir }: {
  rota: Rota; busca?: Filtros; origem?: Origem | null; ehH1: boolean; usuario: Usuario; ir: Ir;
}) {
  return (
    <header className="topo">
      <Caminho rota={rota} perfil={usuario.perfil} permissoes={usuario.permissoes} busca={busca} origem={origem} ehH1={ehH1} />
      <Busca perfil={usuario.perfil} ir={ir} />
      <Conta usuario={usuario} ir={ir} />
    </header>
  );
}
