import { Fragment, useEffect, useRef, useState } from "react";
import { apiForm, mensagemDeErro } from "./api";
import CampoCompetencia from "./CampoCompetencia";
import { IconeAlerta, IconeArquivo, IconeBaixar, IconeClipe, IconeLinkExterno } from "./icones";
import { Link } from "./Link";
import type { Usuario } from "./Login";
import {
  certidaoPendente, certidoesOrdenadas, NOME_CURTO, pendenciaMaisUrgente, resumoEmpresa, situacaoCertidao,
  situacaoGarantia, type EmpresaDoc,
} from "./matriz";
import { type AbaDocumentos, type Origem } from "./rota";
import Selo from "./Selo";
import { fmtCompetencia as mesBR, fmtDataPura } from "./tempo";
import { Migalhas, VoltarOrigem } from "./Topo";
import { AnexarCertidoes, CnpjCopiar, EmDia, Pilula, Ponto, SituacaoSelo, type AnexarRef } from "./documentosComum";
import { cnpjBR, competenciaDoNome, ROTULO_TIPO, useCopiarCnpj, usePainel } from "./documentosDados";

/* A pagina de UMA empresa em Documentos (#161): cabecalho com nome, CNPJ e situacao; tres abas, cada uma com
 * endereco (Certidoes, Regularidade do mes, Garantia por obra). A tabela de certidoes traz Emitir, Anexar e Ver
 * PDF; embaixo, a area de arrastar os PDFs e a fila de leitura. O perfil diretoria so' consulta: sem Anexar, sem
 * area de arrastar e sem gravar a regularidade.
 */

const ABAS: { id: AbaDocumentos; rotulo: string }[] = [
  { id: "certidoes", rotulo: "Certidões" },
  { id: "regularidade", rotulo: "Regularidade do mês" },
  { id: "garantia", rotulo: "Garantia por obra" },
];

const REG_TEXTO = { ok: "em dia", atrasada: "atrasada", faltando: "nenhuma anexada" } as const;

function Pontos({ e }: { e: EmpresaDoc }) {
  return (
    <ul className="doc-pontos" aria-label={`Certidões de ${e.entidade}`}>
      {certidoesOrdenadas(e).map(l => {
        const s = situacaoCertidao(l, l.certidao ? fmtDataPura(l.certidao.validade) : "");
        return <li key={l.chave} title={`${l.tipo}: ${s.texto}`}><Ponto nivel={s.nivel} />{NOME_CURTO[l.chave] ?? l.tipo}<span className="sr-only">: {s.texto}</span></li>;
      })}
    </ul>
  );
}

export default function DocumentosEmpresa({ usuario, id, aba = "certidoes", origem = null }:
    { usuario: Usuario; id: number; aba?: AbaDocumentos; origem?: Origem | null }) {
  const podeEditar = usuario.perfil !== "diretoria";
  const { painel, erro, carregar } = usePainel();
  const [anuncio, setAnuncio] = useState("");
  const [dataZip, setDataZip] = useState("");
  const { copiar, copia } = useCopiarCnpj(setAnuncio);
  const anexar = useRef<AnexarRef>(null);

  // regularidade: o PDF do DP, um por competencia; a competencia sugerida e' a esperada, ou a do nome do arquivo
  const [arquivoReg, setArquivoReg] = useState<File | null>(null);
  const [compReg, setCompReg] = useState<string | null>(null);
  const [chaveReg, setChaveReg] = useState(0);
  const [gravandoReg, setGravandoReg] = useState(false);
  const [erroReg, setErroReg] = useState("");
  const [gravada, setGravada] = useState("");

  const e = painel?.empresas.find(x => x.entidade_id === id) ?? null;
  const porId = new Map((painel?.empresas ?? []).map(x => [x.entidade_id, x]));
  useEffect(() => { document.title = `${e ? e.entidade : "Empresa"} · Documentos · grupolotufo`; }, [e]);

  const limparReg = () => { setArquivoReg(null); setCompReg(null); setChaveReg(k => k + 1); setErroReg(""); };

  const enviarRegularidade = async (ev: React.FormEvent, emp: EmpresaDoc) => {
    ev.preventDefault();
    if (!arquivoReg || !emp.regularidade) return;
    const competencia = compReg ?? emp.regularidade.esperada;
    setGravandoReg(true); setErroReg(""); setGravada("");
    const fd = new FormData();
    fd.append("arquivo", arquivoReg);
    fd.append("entidade_id", String(emp.entidade_id));
    fd.append("competencia", competencia);
    try {
      await apiForm("/api/documentos/regularidades", fd);
      setGravada(`Regularidade de ${mesBR(competencia)} gravada para ${emp.entidade}.`);
      limparReg();
      await carregar();
    } catch (x) { setErroReg(mensagemDeErro(x)); } finally { setGravandoReg(false); }
  };

  const obrasDaEmpresa = (painel?.contratos ?? []).filter(k => k.entidade_id === id);
  const nGarantia = obrasDaEmpresa.filter(k => {
    const g = situacaoGarantia(k.garantia, k.garantia ? fmtDataPura(k.garantia.vigencia_fim) : "");
    return g.nivel === "acao" || g.nivel === "atencao";
  }).length;
  const nCert = e ? e.certidoes.filter(certidaoPendente).length : 0;
  const nReg = e?.regularidade && e.regularidade.situacao !== "ok" ? 1 : 0;
  const contas: Record<AbaDocumentos, number> = { certidoes: nCert, regularidade: nReg, garantia: nGarantia };

  const r = e ? resumoEmpresa(e, painel?.contratos ?? []) : null;
  const linkEmpresa = (x: number) => {
    const o = porId.get(x);
    return o ? <Link para={{ tela: "documentos-empresa", id: x }}>{o.entidade}</Link> : null;
  };
  const lista = (ids: number[]) => ids.map((x, i) => <Fragment key={x}>{i > 0 && ", "}{linkEmpresa(x)}</Fragment>);

  return (
    <>
      <header className="topbar topbar--detalhe">
        <div className="topbar__trilha">
          <VoltarOrigem origem={origem} alemDe={["documentos"]} />
          <Migalhas origem={origem} itens={[{ rotulo: "Documentos", para: { tela: "documentos" } }, { rotulo: e?.entidade ?? "Empresa" }]} />
        </div>
        <div className="doc-cabeca">
          <div className="doc-cabeca__id">
            <h1 className="doc-cabeca__titulo">{e ? e.entidade : "Empresa"}</h1>
            {e && r && (
              <>
                <div className="doc-cabeca__linha">
                  <CnpjCopiar e={e} copia={copia} aoCopiar={() => void copiar(e.entidade_id, e.cnpj, e.entidade)} />
                  <Pilula nivel={r.nivel} texto={r.texto} />
                </div>
                <p className="doc-cabeca__meta">
                  {e.papel === "consorcio" && (e.consorciadas ?? []).length > 0 && <>Consórcio · consorciadas: {lista(e.consorciadas!)}</>}
                  {e.papel === "consorciada" && (e.consorcios ?? []).length > 0 && <>Consorciada em {lista(e.consorcios!)}</>}
                  {e.papel === "consorcio" && (e.consorciadas ?? []).length === 0 && "Consórcio"}
                  {e.papel === "consorciada" && (e.consorcios ?? []).length === 0 && "Consorciada"}
                  {e.papel === "lotufo" && <>Empresa{(e.consorcios ?? []).length > 0 && <> · também consorciada em {lista(e.consorcios!)}</>}</>}
                  {(e.obras ?? []).length > 0 && (
                    <> · exigida em {e.obras!.map((o, i) => (
                      <Fragment key={o.contrato_id}>{i > 0 && ", "}<Link para={{ tela: "obra", id: o.contrato_id, aba: "documentos" }}>{o.obra}</Link></Fragment>
                    ))}</>
                  )}
                </p>
              </>
            )}
          </div>
          {e && (
            <div className="doc-cabeca__zip">
              <div className="campo">
                <label className="campo__rotulo" htmlFor="data-zip">ZIP: certidões vigentes em</label>
                <input id="data-zip" type="date" value={dataZip || painel!.hoje} onChange={ev => setDataZip(ev.target.value)}
                  title="O ZIP junta as certidões vigentes nessa data (para licitação ou protocolo)." />
              </div>
              <a className="btn" href={`/api/documentos/zip?entidade_id=${e.entidade_id}&data=${dataZip || painel!.hoje}`}
                aria-label={`Baixar o ZIP das certidões vigentes de ${e.entidade}`}>
                <IconeBaixar className="icone icone--p" />Baixar ZIP
              </a>
            </div>
          )}
        </div>
      </header>

      <div className="pagina">
        {erro && <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erro}</p>}
        {/* sempre montada: o Copiar e a fila anunciam aqui */}
        <p className="sr-only" role="status">{anuncio}</p>

        {!painel && !erro && <p className="campo__nota">Carregando…</p>}
        {painel && !e && (
          <div className="cartao vazio">
            <p className="vazio__titulo">Essa empresa não tem documento exigido.</p>
            <p><Link para={{ tela: "documentos" }}>Ver todas as empresas</Link></p>
          </div>
        )}

        {painel && e && (
          <section className="cartao doc-abas-cartao">
            <nav className="abas" aria-label="Documentos da empresa">
              {ABAS.map(a => (
                <Link key={a.id} className="aba" para={{ tela: "documentos-empresa", id, aba: a.id }}
                  aria-current={a.id === aba ? "page" : undefined}>
                  {a.rotulo}
                  {contas[a.id] > 0 && <span className="aba__conta" aria-label={contas[a.id] === 1 ? "1 com pendência" : `${contas[a.id]} com pendência`}>{contas[a.id]}</span>}
                </Link>
              ))}
            </nav>

            {aba === "certidoes" && (() => {
              const urgente = pendenciaMaisUrgente(e);
              return (
                <div className="doc-painel">
                  <p className="doc-painel__dica">
                    Pendência: vencida, falta ou vence em até 30 dias. “Emitir” abre o site do órgão emissor; “Anexar” lê o PDF e
                    coloca na linha certa.
                  </p>
                  <div className="tabela-wrap">
                    <table className="tabela tabela--empilha">
                      <caption className="sr-only">Certidões de {e.entidade}</caption>
                      <thead>
                        <tr><th scope="col">Certidão</th><th scope="col">Emissão</th><th scope="col">Válida até</th>
                          <th scope="col">Situação</th><th scope="col">Ações</th></tr>
                      </thead>
                      <tbody>
                        {certidoesOrdenadas(e).map(l => {
                          const nome = ROTULO_TIPO[l.chave] ?? l.tipo;
                          const curto = NOME_CURTO[l.chave] ?? l.tipo;
                          const s = situacaoCertidao(l, l.certidao ? fmtDataPura(l.certidao.validade) : "");
                          const notas: string[] = [];
                          if (l.situacao === "nao_se_aplica") notas.push("declarado");
                          if (l.certidao?.natureza === "positiva_efeito_negativa" && l.situacao !== "vencida") notas.push("positiva c/ efeito de negativa");
                          const aplica = l.situacao !== "nao_se_aplica";
                          return (
                            <tr key={l.chave} id={`cert-${l.chave}`}>
                              <td className="doc-forte col-largo" data-rotulo="Certidão">{nome}</td>
                              <td className="doc-data" data-rotulo="Emissão">{l.certidao ? fmtDataPura(l.certidao.emissao) : "—"}</td>
                              <td className="doc-data" data-rotulo="Válida até">
                                {l.certidao ? fmtDataPura(l.certidao.validade) : "—"}
                                {/* A-19 (10/10/2026): a data digitada a mao nao veio do documento; o selo diz isso a quem confere */}
                                {l.certidao?.leitura === "manual" && <> <Selo classe="">digitada</Selo></>}
                              </td>
                              <td className="doc-sit col-largo" data-rotulo="Situação">
                                <SituacaoSelo nivel={s.nivel} texto={s.texto} />
                                {notas.map(n => <div key={n} className="campo__nota">{n}</div>)}
                              </td>
                              <td className="col-largo">
                                <div className="doc-acoes">
                                  {l.exigida && aplica && l.link_emissao && (
                                    <a href={l.link_emissao} target="_blank" rel="noreferrer"
                                      className={`btn btn--pequeno${l === urgente ? " btn--primario" : ""}`}
                                      aria-label={`Emitir ${curto} de ${e.entidade} (abre o site do órgão)`}>
                                      <IconeLinkExterno className="icone" />Emitir
                                    </a>
                                  )}
                                  {podeEditar && aplica && (
                                    <button type="button" className="btn btn--pequeno" aria-label={`Anexar certidão ${curto}`}
                                      onClick={() => anexar.current?.escolher(l.chave)}>
                                      <IconeClipe className="icone" />Anexar
                                    </button>
                                  )}
                                  {l.certidao ? (
                                    <a href={`/api/certidoes/${l.certidao.id}/arquivo`} target="_blank" rel="noreferrer" className="btn btn--pequeno"
                                      aria-label={`Ver PDF da certidão ${curto}`}>
                                      <IconeArquivo className="icone" />Ver PDF
                                    </a>
                                  ) : (
                                    <button type="button" className="btn btn--pequeno" disabled title="Sem PDF anexado"
                                      aria-label={`Ver PDF da certidão ${curto}`}>
                                      <IconeArquivo className="icone" />Ver PDF
                                    </button>
                                  )}
                                </div>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>

                  {/* consorcio: a habilitacao e' por CNPJ (o consorcio e cada consorciada); a situacao de cada uma */}
                  {e.papel === "consorcio" && (e.consorciadas ?? []).length > 0 && (
                    <div className="pilha doc-consorciadas-bloco">
                      <h2 className="doc-secao-titulo">Consorciadas</h2>
                      <p className="doc-painel__dica">A obra do consórcio cobra as certidões dele e as de cada consorciada.</p>
                      <ul className="doc-consorciadas">
                        {e.consorciadas!.map(x => {
                          const o = porId.get(x);
                          if (!o) return null;
                          const ro = resumoEmpresa(o, painel.contratos ?? []);
                          return (
                            <li key={x}>
                              <div>
                                <Link para={{ tela: "documentos-empresa", id: x }}>{o.entidade}</Link>
                                <div className="campo__nota num">CNPJ {cnpjBR(o.cnpj)}</div>
                              </div>
                              <Pilula nivel={ro.nivel} texto={ro.texto} />
                              <Pontos e={o} />
                            </li>
                          );
                        })}
                      </ul>
                    </div>
                  )}

                  {podeEditar && (
                    <AnexarCertidoes ref={anexar} empresas={painel.empresas} empresaPadrao={e} aoGravar={carregar} anunciar={setAnuncio}
                      nota="O sistema lê a validade de cada PDF e coloca na linha certa; confira e grave." />
                  )}
                </div>
              );
            })()}

            {aba === "regularidade" && (
              <div className="doc-painel">
                {!e.regularidade ? (
                  <div className="vazio">
                    <p className="vazio__titulo">{e.papel === "consorcio" ? "O consórcio não entrega regularidade mensal" : "Regularidade mensal não exigida"}</p>
                    {e.papel === "consorcio" && (e.consorciadas ?? []).length > 0 && (
                      <p>Quem entrega o PDF do DP é cada consorciada:{" "}
                        {e.consorciadas!.map((x, i) => {
                          const o = porId.get(x);
                          return o ? <Fragment key={x}>{i > 0 && " e "}<Link para={{ tela: "documentos-empresa", id: x, aba: "regularidade" }}>{o.entidade}</Link></Fragment> : null;
                        })}.</p>
                    )}
                  </div>
                ) : (
                  <>
                    <p className="doc-painel__dica">
                      O PDF do Departamento Pessoal, um por competência. O nome “MMAAAA - …” do arquivo já preenche a competência.
                    </p>
                    {/* regiao viva sempre montada (o anuncio falha quando ela nasce ja' com o texto) */}
                    <p className={gravada ? "notas__ok" : "sr-only"} role="status">{gravada}</p>
                    <div className="doc-reg">
                      <div className="doc-reg__bloco">
                        <h3>Situação</h3>
                        {/* fora do dia, a regularidade e' de acao (como o aviso dela) */}
                        {e.regularidade.situacao === "ok" ? <EmDia texto={REG_TEXTO.ok} />
                          : <Selo classe="selo--atencao" forte>{REG_TEXTO[e.regularidade.situacao]}</Selo>}
                        <dl className="doc-pares">
                          <dt>Competência anexada</dt><dd className="num">{mesBR(e.regularidade.competencia)}</dd>
                          <dt>Competência esperada</dt><dd className="num">{mesBR(e.regularidade.esperada)}</dd>
                        </dl>
                      </div>
                      {podeEditar && (
                        <form className="doc-reg__bloco" aria-label={`Regularidade de ${e.entidade}`} onSubmit={ev => void enviarRegularidade(ev, e)}>
                          <h3>Anexar regularidade</h3>
                          {erroReg && <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erroReg}</p>}
                          <div className="form-inline">
                            <label className="btn btn--pequeno espelho__anexar">
                              <span className="arquivo-nome" title={arquivoReg?.name}>{arquivoReg ? arquivoReg.name : "Escolher PDF"}</span>
                              <span className="sr-only"> da regularidade de {e.entidade}</span>
                              <input key={chaveReg} type="file" accept="application/pdf" className="espelho__arquivo"
                                onChange={ev => {
                                  const f = ev.currentTarget.files?.[0] ?? null;
                                  setArquivoReg(f);
                                  setCompReg((f && competenciaDoNome(f.name)) || compReg);
                                }} />
                            </label>
                            <div className="campo">
                              <label className="campo__rotulo" htmlFor="reg-comp">Competência</label>
                              <CampoCompetencia id="reg-comp" value={compReg ?? e.regularidade.esperada} onChange={setCompReg} />
                            </div>
                            <button type="submit" className="btn btn--primario btn--pequeno" disabled={gravandoReg || !arquivoReg}>
                              {gravandoReg ? "Gravando…" : "Gravar regularidade"}
                            </button>
                            <button type="button" className="btn btn--pequeno" disabled={gravandoReg} onClick={limparReg}>Limpar</button>
                          </div>
                        </form>
                      )}
                      <div className="doc-reg__bloco">
                        <h3>Anexadas</h3>
                        {(e.regularidades_anexadas ?? []).length === 0 ? <p className="campo__nota">Nenhuma regularidade anexada ainda.</p> : (
                          <div className="tabela-wrap">
                            <table className="tabela">
                              <thead><tr><th scope="col">Competência</th><th scope="col">Anexada em</th><th scope="col"><span className="sr-only">PDF</span></th></tr></thead>
                              <tbody>
                                {e.regularidades_anexadas!.map(h => (
                                  <tr key={h.id}>
                                    <td className="doc-data">{mesBR(h.competencia)}</td>
                                    <td className="doc-data">{fmtDataPura(h.anexada_em)}</td>
                                    <td><a href={`/api/documentos/regularidades/${h.id}/arquivo`} target="_blank" rel="noreferrer"
                                      aria-label={`Ver PDF da regularidade de ${mesBR(h.competencia)}`}>Ver PDF</a></td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        )}
                      </div>
                    </div>
                  </>
                )}
              </div>
            )}

            {aba === "garantia" && (
              <div className="doc-painel">
                {obrasDaEmpresa.length === 0 ? (
                  <div className="vazio">
                    <p className="vazio__titulo">Nenhuma obra contratada direto por esta empresa</p>
                    {(e.consorcios ?? []).length > 0 && (
                      <p>A garantia das obras em consórcio fica no consórcio:{" "}
                        {e.consorcios!.map((x, i) => {
                          const o = porId.get(x);
                          return o ? <Fragment key={x}>{i > 0 && ", "}<Link para={{ tela: "documentos-empresa", id: x, aba: "garantia" }}>{o.entidade}</Link></Fragment> : null;
                        })}.</p>
                    )}
                  </div>
                ) : (
                  <>
                    <p className="doc-painel__dica">A garantia avisa 30 dias antes do fim (ação aos 15).</p>
                    <div className="tabela-wrap">
                      <table className="tabela tabela--empilha">
                        <caption className="sr-only">Garantia por obra</caption>
                        <thead><tr><th scope="col">Obra</th><th scope="col">Garantia</th></tr></thead>
                        <tbody>
                          {obrasDaEmpresa.map(k => {
                            const g = situacaoGarantia(k.garantia, k.garantia ? fmtDataPura(k.garantia.vigencia_fim) : "");
                            return (
                              <tr key={k.contrato_id}>
                                <th scope="row" className="col-largo" data-rotulo="Obra">
                                  <Link para={{ tela: "obra", id: k.contrato_id, aba: "documentos" }}>{k.obra}</Link>
                                </th>
                                <td data-rotulo="Garantia">
                                  <SituacaoSelo nivel={g.nivel} texto={g.texto} forte={g.forte} />
                                  {g.nota && <div className="campo__nota num">{g.nota}</div>}
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  </>
                )}
              </div>
            )}
          </section>
        )}
      </div>
    </>
  );
}
