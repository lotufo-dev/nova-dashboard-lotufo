import { useCallback, useEffect, useState } from "react";
import { api, mensagemDeErro } from "./api";
import { CartaoPleito, NovoPleito, type Pleito, type Reemissao } from "./FluxoOficio";
import { IconeAlerta } from "./icones";
import { focarPorId } from "./foco";
import { reajustePorDataBase, type CicloApi, type InstrumentoCadastro } from "./obra";
import { Link } from "./Link";
import { fmtCompetencia as mesAno, fmtDataPura } from "./tempo";
import { brl, fmtPercentual } from "./formato";
import Rolagem from "./Rolagem";
import Selo from "./Selo";
import { LinhaPleito, partesDoEnvio, pleitoEmLinha, type DesfechoPleito } from "./Prazos";

// Aba Reajuste da obra (bloco 7; spec §7.2; NAVEGACAO.md › Obra): um grupo por data-base, com ancora
// (`#db-2023-01`): o cartao do ciclo corrente (situacao, pleito e apostilamento), os oficios do ciclo e os
// ciclos passados recolhidos. Com mais de uma data-base, um indice no topo leva a cada uma. O calendario mora
// em `app/reajuste.py`; a tela so' desenha.

// o mes, a parte do contrato a que a base se aplica (D7: "itens SICRO", "itens SINAPI") e o indice que a corrige
function rotuloDataBase(mes: string, c: CicloApi) {
  return `${mesAno(mes)}${c.aplica_a ? ` (${c.aplica_a})` : ""}${c.indice ? ` · ${c.indice}` : ""}`;
}

// `pleito`: o enviado mais recente do ciclo (o servidor diz quem ele e'); e' nele que se reitera ou reemite
type Ciclo = CicloApi & { situacao: "futuro" | "pleito_pendente" | "apostilamento_pendente" | "apostilado";
  pleito?: { id: number } | null };

// issue #277: o que o botao faz no pleito vigente do ciclo (o servidor diz quais cabem, em `reemissoes_possiveis`)
const ACAO_REEMISSAO: Record<Reemissao, { botao: string; titulo: string }> = {
  reiteracao: { botao: "Reiterar", titulo: "Reiteração do pleito" },
  cronograma: { botao: "Reemitir cronograma", titulo: "Reemissão do cronograma do pleito" },
};

/** Competencia com previsao vigente de apostilamento (issue #271; `reajuste.competencias_apostiladas`): o termo
 *  com `corrige` aplicado depois ja' vem no lugar do anterior. */
type CompetenciaApostilada = { data_base_mes: string; ciclo: number; competencia: string; valor_centavos: number;
  medicao: number | null; instrumento_chave: string; instrumento_numero: string | null; instrumento_data: string };

/** As competencias que o apostilamento lista, mes a mes, com o nº da medicao que ele cita e o termo. */
function TabelaApostilada({ dataBase, linhas }: { dataBase: string; linhas: CompetenciaApostilada[] }) {
  const rotulo = `Competências apostiladas da data-base ${mesAno(dataBase)}`;
  return (
    <>
      <p className="resumo__rotulo">Competências apostiladas</p>
      <Rolagem rotulo={rotulo}>
        <table className="tabela">
          <caption className="sr-only">{rotulo}</caption>
          <thead>
            <tr>
              <th scope="col">Competência</th>
              <th scope="col">Ciclo</th>
              <th scope="col">Medição</th>
              <th scope="col" className="col-num">Valor</th>
              <th scope="col">Apostilamento</th>
            </tr>
          </thead>
          <tbody>
            {linhas.map((l, i) => (
              <tr key={`${l.ciclo}-${l.competencia}`} className={`linha${i % 2 === 1 ? " par" : ""}`}>
                <td className="forte num">{mesAno(l.competencia)}</td>
                <td className="num">{l.ciclo}</td>
                <td className="num">{l.medicao ? `${l.medicao}ª` : "—"}</td>
                <td className="col-num dinheiro num">{brl(l.valor_centavos)}</td>
                <td className="num" title={`de ${fmtDataPura(l.instrumento_data)}`}>{l.instrumento_numero ?? "s/n"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Rolagem>
    </>
  );
}

// Pleito nao enviado e' a vez da engenharia: nivel "Acao" do D2 (ambar com contorno cheio), o
// mesmo com que o fato aparece nos avisos. Vermelho fica para o critico.
const SITUACAO: Record<Ciclo["situacao"], { rotulo: string; classe: string; forte?: boolean }> = {
  futuro: { rotulo: "ainda não abriu", classe: "" },
  pleito_pendente: { rotulo: "pleito não enviado", classe: "selo--atencao", forte: true },
  apostilamento_pendente: { rotulo: "apostilamento pendente", classe: "selo--atencao" },
  apostilado: { rotulo: "apostilado", classe: "selo--ok" },
};

// espaco nao separavel: "3 dias" nao quebra no meio da linha do ciclo
function dias(n: number): string {
  return `${n}\u00a0${n === 1 ? "dia" : "dias"}`;
}

/** A linha do ciclo: o ano, o aniversario e, com os dias do servidor, ha quanto tempo ou em quanto tempo. */
function linhaDoCiclo(c: Ciclo): string {
  const aniv = fmtDataPura(c.aniversario);
  const quando = c.dias === null ? `aniversário em ${aniv}`
    : c.situacao === "apostilamento_pendente" ? `aniversário em ${aniv} · pleito enviado há ${dias(c.dias)}`
    : c.dias >= 0 ? `faz aniversário em ${aniv} (faltam ${dias(c.dias)})`
    : `fez aniversário em ${aniv} (há ${dias(-c.dias)})`;
  return `Ciclo de ${c.ciclo} · ${quando}`;
}

function textoApostilamento(i: InstrumentoCadastro): string {
  const pct = i.dados.percentual;
  const eficacia = typeof i.dados.eficacia === "string" ? i.dados.eficacia : null;
  return [`${i.numero ?? "s/n"}, de ${fmtDataPura(i.data)}`,
          pct !== undefined && pct !== null ? fmtPercentual(Number(pct) / 100) : "",
          eficacia ? `eficácia ${fmtDataPura(eficacia.slice(0, 10))}` : ""].filter(Boolean).join(" · ");
}

/** O desfecho de um pleito enviado (F-71): com o ciclo corrente, o selo diz se o apostilamento veio (Em dia) ou
 *  se falta (Atencao, com os dias que o servidor conta); a data do envio e' texto de apoio. Sem o ciclo (ciclo
 *  anterior, data-base que saiu do cadastro), o dado nao diz o desfecho: selo neutro. */
function desfechoDoPleito(p: Pleito, apostilamentos: InstrumentoCadastro[], c?: Ciclo): DesfechoPleito {
  const envio = partesDoEnvio(p);
  const neutro = { classe: "", texto: p.situacao, partes: envio };
  // o cadastro ligou o pleito ao termo que o atendeu (issue #271): vale em qualquer ciclo, corrente ou passado
  const termo = p.situacao === "enviado" && p.instrumento_chave
    ? apostilamentos.find(i => i.chave === p.instrumento_chave) : undefined;
  if (termo) {
    return { classe: "selo--ok", texto: `atendido pelo apostilamento ${termo.numero ?? "s/n"}`,
      partes: [...envio, `apostilamento de ${fmtDataPura(termo.data)}`] };
  }
  // so' o pleito vigente do ciclo (o enviado mais recente) leva o desfecho; os anteriores (reiterados ou
  // reemitidos) ficam com o envio e a cadeia, sem repetir a espera do ciclo (issue #277)
  if (!c || p.situacao !== "enviado" || (c.pleito && c.pleito.id !== p.id)) return neutro;
  if (c.situacao === "apostilamento_pendente") {
    return { classe: "selo--atencao", partes: envio,
      texto: c.dias !== null && c.dias >= 0 ? `sem apostilamento há ${dias(c.dias)}` : "sem apostilamento ainda" };
  }
  if (c.situacao === "apostilado" && c.apostilamento) {
    return { classe: "selo--ok", texto: `atendido pelo apostilamento ${c.apostilamento.numero ?? "s/n"}`,
      partes: [...envio, `apostilamento de ${fmtDataPura(c.apostilamento.data)}`] };
  }
  return neutro;
}

// pleito que ainda se trabalha: feito no sistema, nem enviado nem descartado (o mesmo corte do CartaoPleito)
const emAberto = (p: Pleito) => p.origem === "sistema" && p.situacao !== "enviado" && p.situacao !== "descartado";

export default function Reajuste({ contratoId, podeEditar }: { contratoId: number; podeEditar: boolean }) {
  const [dados, setDados] = useState<{ ciclos: Ciclo[]; pleitos: Pleito[]; competencias?: CompetenciaApostilada[] } | null>(null);
  const [apostilamentos, setApostilamentos] = useState<InstrumentoCadastro[]>([]);
  const [erro, setErro] = useState("");
  const [novo, setNovo] = useState<string | null>(null);            // data-base do pleito sendo criado
  // reiteracao ou reemissao sendo criada: a data-base, o pleito anterior e o que se faz com ele
  const [reemitir, setReemitir] = useState<{ dataBase: string; anterior: Pleito; reemissao: Reemissao } | null>(null);
  // para onde o foco vai quando o formulario fecha: o botao que o abriu (cancelar) ou o pleito criado
  const [foco, setFoco] = useState<string | null>(null);

  const carregar = useCallback(async () => {
    try {
      setDados(await api(`/api/contratos/${contratoId}/reajuste`));
      const cad = await api<{ instrumentos: InstrumentoCadastro[] }>(`/api/contratos/${contratoId}/cadastro`);
      setApostilamentos(cad.instrumentos.filter(i => i.tipo === "apostilamento_reajuste"));
    } catch (e) { setErro(mensagemDeErro(e)); }
  }, [contratoId]);
  useEffect(() => { void carregar(); }, [carregar]);
  // o pleito criado so' existe depois que a lista recarrega: tenta de novo a cada leitura
  useEffect(() => { if (foco && focarPorId(foco)) setFoco(null); }, [foco, dados]);

  if (erro) return <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erro}</p>;
  if (!dados) return <section className="cartao"><div className="vazio"><p>Carregando…</p></div></section>;
  if (dados.ciclos.length === 0 && dados.pleitos.length === 0 && apostilamentos.length === 0) {
    return <section className="cartao"><div className="vazio vazio--curto"><p>Sem data-base no cadastro, ou contrato sem reajuste.</p></div></section>;
  }
  const { dataBases, semDataBase, outrosPleitos } = reajustePorDataBase(dados.ciclos, dados.pleitos, apostilamentos);
  const aqui = { tela: "obra" as const, id: contratoId, aba: "reajuste" as const };
  const contrato = { tela: "obra" as const, id: contratoId, aba: "contrato" as const };
  // cada pleito e' uma secao do cartao pai (F-74): o enviado vira linha com o desfecho no selo; o que ainda se
  // trabalha segue no CartaoPleito, que traz o formulario
  const cartoes = (ps: Pleito[], ciclo?: Ciclo) => ps.map(p => {
    const contexto = p.ciclo ? `ciclo de ${p.ciclo}` : undefined;
    return pleitoEmLinha(p)
      ? <LinhaPleito key={p.id} p={p} desfecho={desfechoDoPleito(p, apostilamentos, ciclo)} contexto={contexto} />
      : <CartaoPleito key={p.id} p={p} podeEditar={podeEditar} aoMudar={() => void carregar()} contexto={contexto} />;
  });
  const nota = "O reajuste vale a partir do mês do aniversário da data-base; o aviso começa 30 dias antes.";

  return (
    <div className="pilha">
      {/* com mais de uma data-base, o indice leva a cada uma sem rolar a aba inteira */}
      {dataBases.length > 1 ? (
        <section className="cartao" aria-labelledby="titulo-databases">
          <div className="cartao__cabeca">
            <h2 className="cartao__titulo" id="titulo-databases">Data-bases</h2>
            <span className="cartao__dica">{nota}</span>
          </div>
          <ul className="lista-simples cartao__corpo indice-db">
            {dataBases.map(db => {
              const s = SITUACAO[db.atual.situacao] ?? { rotulo: db.atual.situacao, classe: "" };
              return (
                <li key={db.data_base_mes}>
                  <Link para={aqui} secao={`db-${db.data_base_mes}`}>{rotuloDataBase(db.data_base_mes, db.atual)}</Link>
                  <Selo classe={s.classe} forte={s.forte}>{s.rotulo}</Selo>
                </li>
              );
            })}
          </ul>
        </section>
      ) : <p className="campo__nota">{nota}</p>}

      {dataBases.map(db => {
        const c = db.atual;
        const s = SITUACAO[c.situacao] ?? { rotulo: c.situacao, classe: "" };
        const titulo = `titulo-db-${db.data_base_mes}`;
        const outrosAp = db.apostilamentos.filter(i => i.id !== c.apostilamento?.id);
        const anteriores = db.pleitosAnteriores.length + outrosAp.length;
        const aberto = db.pleitosDoCiclo.find(emAberto);
        const apostiladas = (dados.competencias ?? []).filter(x => x.data_base_mes === db.data_base_mes);
        // o pleito vigente do ciclo e o que o servidor deixa fazer com ele (reiterar, reemitir o cronograma)
        const vigente = c.pleito ? dados.pleitos.find(p => p.id === c.pleito!.id) : undefined;
        const possiveis = vigente?.reemissoes_possiveis ?? [];
        const reemitindo = reemitir?.dataBase === db.data_base_mes ? reemitir : null;
        const formAberto = novo === db.data_base_mes || reemitindo !== null;
        return (
          // o cartao e' a data-base: o ciclo, e embaixo, como secoes, os oficios dele e os ciclos anteriores; o
          // aviso de reajuste cai na ancora dele
          <section className="cartao" id={`db-${db.data_base_mes}`} key={db.data_base_mes} aria-labelledby={titulo}>
            <div className="cartao__cabeca">
              <h2 className="cartao__titulo" id={titulo}>Data-base {rotuloDataBase(db.data_base_mes, c)}</h2>
              <Selo classe={s.classe} forte={s.forte}>{s.rotulo}</Selo>
              {/* com um pleito em aberto no ciclo, o caminho e' continuar nele, nao abrir outro oficio */}
              {podeEditar && aberto && (
                <div className="cartao__acoes">
                  <Link className="btn btn--pequeno" para={aqui} secao={`oficio-${aberto.id}`}>
                    Continuar o pleito{aberto.numero_oficio ? ` ${aberto.numero_oficio}` : ""}
                  </Link>
                </div>
              )}
              {podeEditar && !aberto && c.situacao === "pleito_pendente" && !formAberto && (
                <div className="cartao__acoes">
                  <button type="button" className="btn btn--pequeno" id={`enviar-pleito-${db.data_base_mes}`} onClick={() => setNovo(db.data_base_mes)}>
                    Enviar pleito
                  </button>
                </div>
              )}
              {/* depois do envio, o oficio novo nasce ligado ao vigente: reiteracao (MT-PAR e Prefeitura) ou
                  reemissao do cronograma (apos aditivo); issue #277 */}
              {podeEditar && !aberto && vigente && possiveis.length > 0 && c.situacao !== "futuro" && !formAberto && (
                <div className="cartao__acoes">
                  {possiveis.map(r => (
                    <button key={r} type="button" className="btn btn--pequeno" id={`reemitir-${r}-${db.data_base_mes}`}
                      onClick={() => setReemitir({ dataBase: db.data_base_mes, anterior: vigente, reemissao: r })}>
                      {ACAO_REEMISSAO[r].botao}
                    </button>
                  ))}
                </div>
              )}
            </div>
            <div className="cartao__corpo linhas">
              <p className="num">{linhaDoCiclo(c)}</p>
              {c.apostilamento && (
                <p><span className="resumo__rotulo">Apostilamento</span>{" "}{textoApostilamento(c.apostilamento)}
                  {" · "}<Link para={contrato} secao="instrumentos">ver em Contrato › Instrumentos</Link></p>
              )}
              {c.situacao === "apostilamento_pendente" && <p className="campo__nota">Pleito enviado; falta o apostilamento, que entra pelo cadastro.</p>}
              {apostiladas.length > 0 && <TabelaApostilada dataBase={db.data_base_mes} linhas={apostiladas} />}
            </div>
            {(formAberto || db.pleitosDoCiclo.length > 0 || anteriores > 0) && (
              <div className="secoes-pleito">
                {reemitindo && (
                  <section className="cartao" aria-labelledby={`titulo-reemitir-${db.data_base_mes}`}>
                    <div className="cartao__cabeca">
                      <h3 className="cartao__titulo" id={`titulo-reemitir-${db.data_base_mes}`}>
                        {ACAO_REEMISSAO[reemitindo.reemissao].titulo} {reemitindo.anterior.numero_oficio ?? "sem número"}
                      </h3>
                    </div>
                    <NovoPleito contratoId={contratoId} tipo="reajuste" dataBase={db.data_base_mes}
                      reemite={{ id: reemitindo.anterior.id, reemissao: reemitindo.reemissao }}
                      aoCriar={p => { setReemitir(null); setFoco(`oficio-${p.id}`); void carregar(); }}
                      aoCancelar={() => { setReemitir(null); setFoco(`reemitir-${reemitindo.reemissao}-${db.data_base_mes}`); }} />
                  </section>
                )}
                {novo === db.data_base_mes && (
                  <section className="cartao" aria-labelledby={`titulo-novo-${db.data_base_mes}`}>
                    <div className="cartao__cabeca">
                      <h3 className="cartao__titulo" id={`titulo-novo-${db.data_base_mes}`}>Novo pleito da data-base {mesAno(db.data_base_mes)}</h3>
                    </div>
                    <NovoPleito contratoId={contratoId} tipo="reajuste" dataBase={db.data_base_mes}
                      aoCriar={p => { setNovo(null); setFoco(`oficio-${p.id}`); void carregar(); }}
                      aoCancelar={() => { setNovo(null); setFoco(`enviar-pleito-${db.data_base_mes}`); }} />
                  </section>
                )}
                {cartoes(db.pleitosDoCiclo, c)}
                {anteriores > 0 && (
                  <details className="detalhes pleito-anteriores">
                    <summary>Ciclos anteriores: {[
                      db.pleitosAnteriores.length ? `${db.pleitosAnteriores.length} ${db.pleitosAnteriores.length === 1 ? "pleito" : "pleitos"}` : "",
                      outrosAp.length ? `${outrosAp.length} ${outrosAp.length === 1 ? "apostilamento" : "apostilamentos"}` : ""].filter(Boolean).join(" e ")}</summary>
                    <div className="secoes-pleito">
                      {outrosAp.length > 0 && (
                        <section className="cartao__corpo" aria-label={`Apostilamentos anteriores da data-base ${mesAno(db.data_base_mes)}`}>
                          <ul className="lista-simples">{outrosAp.map(i => <li key={i.id} className="num">{textoApostilamento(i)}</li>)}</ul>
                        </section>
                      )}
                      {cartoes(db.pleitosAnteriores)}
                    </div>
                  </details>
                )}
              </div>
            )}
          </section>
        );
      })}

      {semDataBase.length > 0 && (
        <section className="cartao" aria-labelledby="titulo-apostilamentos-sem-base">
          <div className="cartao__cabeca">
            <h2 className="cartao__titulo" id="titulo-apostilamentos-sem-base">Apostilamentos sem data-base no cadastro</h2>
            <span className="cartao__dica">Aparecem na data-base deles quando o cadastro trouxer a data-base.</span>
          </div>
          <ul className="lista-simples cartao__corpo">{semDataBase.map(i => <li key={i.id} className="num">{textoApostilamento(i)}</li>)}</ul>
        </section>
      )}

      {outrosPleitos.length > 0 && (
        <section className="cartao" aria-labelledby="titulo-outros-pleitos">
          <div className="cartao__cabeca">
            <h2 className="cartao__titulo" id="titulo-outros-pleitos">Pleitos de data-base que o cadastro não tem mais</h2>
          </div>
          <div className="secoes-pleito">{cartoes(outrosPleitos)}</div>
        </section>
      )}
    </div>
  );
}
