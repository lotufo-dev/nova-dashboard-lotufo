import { useEffect, useMemo, useState } from "react";
import { type Aviso } from "./Alertas";
import { api, mensagemDeErro } from "./api";
import AvisosPagina from "./AvisosPagina";
import { baseDosValores } from "./formato";
import { IconeAlerta } from "./icones";
import {
  cDaUrlAntiga, contratanteDaObra, contratantesDe, ehDoContratante, escopoDaUrl, nomeDaObra, pctExecutado, totaisDe, vigenteDe, medidoDe,
  type ObraLista,
} from "./listaObras";
import { brl } from "./Medicoes";
import { trocarBusca, type Busca, type Ir } from "./rota";
import { Link } from "./Link";
import Rolagem from "./Rolagem";
import "./obras.css";

// Obras (lista), redesenho aprovado pelo Leo em 06/11/2026 (#509): uma tabela so' de posicao financeira, o contratante
// como filtro em chips e os totais sob o titulo. Valores CHEIOS; a cota do consorcio aparece so' como rotulo. O estado
// fica na URL: ?c=<contratante> | todas, ?situacao=todas (com as encerradas). Os links de antes (?orgao=) seguem abrindo.
// Os Avisos (?avisos=1) continuam abrindo acima da tabela enquanto a tela propria deles nao existe.

type Entidade = { id: number; nome: string; nome_curto?: string | null };
type Obra = ObraLista;

const FORA = new Set(["encerrado", "rescindido"]);

/** "R$ 1.712,6 mi", como nos totais da imagem. */
function emMilhoes(centavos: number): string {
  return `R$ ${(centavos / 100_000_000).toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} mi`;
}

function Chip({ rotulo, n, ativo, c, busca }: { rotulo: string; n: number; ativo: boolean; c: string; busca: Busca }) {
  const resto: Busca = { ...busca, c };
  for (const k of ["avisos", "familia", "nivel", "obra", "agrupar"]) delete resto[k];
  return (
    <Link className={`chip${ativo ? " chip--ativo" : ""}`} para={{ tela: "obras" }} busca={resto} aria-current={ativo ? "true" : undefined}>
      {rotulo}{n >= 0 && <span className="chip__n num">{n}</span>}
    </Link>
  );
}

export default function Contratos({ ir, busca = {} }: { ir: Ir; busca?: Busca }) {
  const [lista, setLista] = useState<Obra[] | null>(null);
  const [empresas, setEmpresas] = useState<Map<number, string> | null>(new Map());
  const [avisos, setAvisos] = useState<Aviso[] | null | undefined>(undefined);
  const [erro, setErro] = useState("");

  useEffect(() => {
    let vivo = true;
    api<Obra[]>("/api/contratos").then(l => { if (vivo) setLista(l); })
      .catch(e => { if (vivo) setErro(mensagemDeErro(e)); });
    api<Entidade[]>("/api/entidades")
      .then(l => { if (vivo) setEmpresas(new Map(l.map(e => [e.id, e.nome_curto || e.nome]))); })
      .catch(() => { if (vivo) setEmpresas(null); });
    api<{ avisos: Aviso[] }>("/api/inicio").then(d => { if (vivo) setAvisos(d.avisos); })
      .catch(() => { if (vivo) setAvisos(null); });
    return () => { vivo = false; };
  }, []);

  const { orgao } = escopoDaUrl(busca);
  // link de antes (?orgao=...): a URL ganha o `c`
  const cAntigo = cDaUrlAntiga(busca);
  useEffect(() => { if (cAntigo !== null) trocarBusca({ c: cAntigo, orgao: null }); }, [cAntigo]);
  const comEncerradas = busca.situacao === "todas";
  const avisosAbertos = busca.avisos === "1";

  const doContratante = useMemo(() => (lista ?? []).filter(o => !orgao || ehDoContratante(o, orgao)), [lista, orgao]);
  const idsDoContratante = useMemo(() => (orgao ? new Set(doContratante.map(o => o.id)) : null), [orgao, doContratante]);
  const linhas = useMemo(() => doContratante
    .filter(o => comEncerradas || !FORA.has(o.estado))
    .sort((a, b) => nomeDaObra(a).localeCompare(nomeDaObra(b), "pt-BR")), [doContratante, comEncerradas]);
  const totais = totaisDe(linhas);
  const contratantes = lista ? contratantesDe(lista) : [];
  const nomeLista = orgao ?? "Todas as obras";
  const aqui = { tela: "obras" as const };

  return (
    <>
      <header className="topbar topbar--detalhe">
        <div className="topbar__linha topbar__linha--quebra obras-topo">
          <h1 className="topbar__titulo topbar__titulo--grande">Obras <span className="obras-topo__sub">posição financeira</span></h1>
          {lista && (
            <nav className="chips" aria-label="Contratante">
              <Chip rotulo="Todas" n={lista.length} ativo={!orgao} c="todas" busca={busca} />
              {contratantes.map(nome => (
                <Chip key={nome} rotulo={nome} n={lista.filter(o => contratanteDaObra(o) === nome).length}
                  ativo={orgao === nome} c={nome} busca={busca} />
              ))}
            </nav>
          )}
        </div>
        {lista && (
          <p className="obras-totais" aria-label="Totais">
            <span>Contratado <strong className="num">{emMilhoes(totais.contratado)}</strong></span>
            <span>Medido <strong className="num">{emMilhoes(totais.medido)}</strong></span>
            <span>Saldo <strong className="num">{emMilhoes(totais.saldo)}</strong></span>
            <span>A receber <strong className="num">{totais.temReceber ? emMilhoes(totais.aReceber) : "—"}</strong></span>
          </p>
        )}
      </header>
      <div className="pagina">
        {!lista && !erro && <div className="vazio"><p>Carregando as obras…</p></div>}
        {erro && <p className="erro" role="alert">
          <IconeAlerta className="icone icone--p" />{erro} Recarregue a página para tentar de novo.
        </p>}
        {lista && (empresas === null || avisos === null) && avisosAbertos && (
          <p className="campo__nota" role="alert">
            Não foi possível carregar {[empresas === null && "os nomes das empresas", avisos === null && "os avisos"].filter(Boolean).join(" nem ")};
            recarregue a página para tentar de novo.
          </p>
        )}

        {lista && avisosAbertos && (
          <AvisosPagina busca={busca} avisos={avisos} escopo={idsDoContratante} nome={nomeLista}
            onFechar={() => { trocarBusca({ avisos: null, familia: null, nivel: null, obra: null, agrupar: null }); }} />
        )}

        {lista && (
          <section className="cartao">
            {linhas.length === 0 ? (
              <div className="vazio vazio--curto"><p className="vazio__titulo">Nenhuma obra.</p></div>
            ) : (
              <Rolagem rotulo="Obras" alta>
                <table className="tabela obras-posicao">
                  <caption className="sr-only">Obras, posição financeira</caption>
                  <thead>
                    <tr>
                      <th scope="col">Obra</th>
                      <th scope="col" className="col-num">Valor vigente</th>
                      <th scope="col" className="col-num">Medido</th>
                      <th scope="col" className="col-num">Saldo a executar</th>
                      <th scope="col">Executado</th>
                      <th scope="col" className="col-num">A receber</th>
                    </tr>
                  </thead>
                  <tbody>
                    {linhas.map(o => {
                      const pct = pctExecutado(o);
                      const cota = baseDosValores(o.percentual_direito_bp ?? 10000);
                      const vigente = vigenteDe(o);
                      return (
                        <tr key={o.id} className="linha linha--obra" onClick={e => { if (!(e.target as HTMLElement).closest("a")) ir({ tela: "obra", id: o.id, aba: "medicoes" }); }}>
                          <td data-rotulo="Obra">
                            <Link className="nome-link obras-posicao__nome" para={{ tela: "obra", id: o.id, aba: "medicoes" }} ir={ir}
                              >{nomeDaObra(o)}</Link>
                            <div className="obras-posicao__sub">
                              <span>{contratanteDaObra(o)}</span>
                              {cota && <span className="obras-posicao__cota">{` · ${cota}`}</span>}
                            </div>
                          </td>
                          <td data-rotulo="Valor vigente" className="col-num dinheiro num">{brl(vigente)}</td>
                          <td data-rotulo="Medido" className="col-num dinheiro num">{brl(medidoDe(o))}</td>
                          <td data-rotulo="Saldo a executar" className="col-num dinheiro num">{brl(vigente - medidoDe(o))}</td>
                          <td data-rotulo="Executado">
                            <div className="obras-exec">
                              <div className="progresso progresso--feito" role="img" aria-label={pct === null ? "sem valor vigente" : `${pct}% executado`}>
                                <span className="progresso__barra" style={{ width: `${Math.min(100, Math.max(0, pct ?? 0))}%` }} />
                              </div>
                              <span className="pilula-info pilula-info--feito obras-exec__pct num">{pct === null ? "—" : `${pct}%`}</span>
                            </div>
                          </td>
                          <td data-rotulo="A receber" className="col-num dinheiro num">{o.a_receber_centavos == null ? "—" : brl(o.a_receber_centavos)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </Rolagem>
            )}
            <footer className="obras-rodape">
              <span>Mostrando <span className="num">{linhas.length}</span> de <span className="num">{doContratante.length}</span> obras</span>
              {!comEncerradas && linhas.length < doContratante.length && (
                <Link para={aqui} busca={{ ...busca, situacao: "todas" }}>Ver todas</Link>
              )}
              {comEncerradas && (
                <Link para={aqui} busca={{ ...busca, situacao: "" }}>Só em andamento</Link>
              )}
            </footer>
          </section>
        )}
      </div>
    </>
  );
}
