import { useEffect, useState } from "react";
import { api, apiForm, mensagemDeErro } from "./api";
import { AceiteDiferenca, FormBoletim } from "./Boletim";
import { brl } from "./formato";
import { IconeAlerta, IconeLinkExterno } from "./icones";
import type { Agir } from "./MedicaoAtos";
import type { Medicao } from "./Medicoes";
import { IconeCheck } from "./NotasAEnviar";
import { diaMes } from "./Passos";
import { type DetalhePlanilha, NumeroSiga, Revisao } from "./PlanilhaCarta";
import { EVENTO_RESPOSTAS_LIDAS, type RespostaOrgao } from "./respostasOrgao";
import { quemDaMovimentacao, sigla, tituloDoEvento, type PainelSiga, type ProcessoSiga } from "./siga";
import { fmtDataPura, fmtHora } from "./tempo";
import "./passos.css";

// Issue #508, passo 2 da pagina da obra (aprovado em 06/11/2026): "com o orgao ha N dias uteis", a data do envio, o
// processo SIGA, "onde esta' o processo" (setor atual e ultimas movimentacoes, da tela SIGA) e a resposta do orgao:
// aprovou (o boletim, com valor e data, leva ao passo 3) ou pediu revisao (nova versao da planilha, que volta ao
// passo 1 para ser enviada).

/** "Com o órgão há N dias úteis" (o servidor conta: o dia do envio entra, hoje nao). */
export function frasePrazo(dias: number | null | undefined): string {
  if (dias === null || dias === undefined) return "Com o órgão";
  if (dias < 1) return "Com o órgão há menos de 1 dia útil";
  return dias === 1 ? "Com o órgão há 1 dia útil" : `Com o órgão há ${dias} dias úteis`;
}

/** O processo do SIGA desta medicao: o ligado a ela (o do nº da planilha, se houver), senao o avulso (sem medicao)
 *  com o mesmo nº. O ligado a outra medicao nunca aparece aqui. */
export function processoDa(processos: ProcessoSiga[], medicaoId: number, numero: string | null): ProcessoSiga | null {
  const daMedicao = processos.filter(p => p.medicao_id === medicaoId);
  return daMedicao.find(p => numero && p.numero === numero) ?? daMedicao[0]
    ?? (numero ? processos.find(p => p.medicao_id === null && p.numero === numero) ?? null : null);
}

type Resposta = "aprovou" | "revisao" | null;

/** Issue #668: o link de acompanhamento que o orgao manda poe o processo da medicao em acompanhamento (o nº sozinho
 *  nao cria processo: o robo so' abre o que tem o codigo do link). O erro do servidor (link invalido, codigo ligado a
 *  outra medicao) fica no campo. */
function LinkSiga({ medicaoId, aoGravar }: { medicaoId: number; aoGravar: () => void }) {
  const [aberto, setAberto] = useState(false);
  const [link, setLink] = useState("");
  const [ocupado, setOcupado] = useState(false);
  const [erro, setErro] = useState("");
  async function gravar(ev: React.FormEvent) {
    ev.preventDefault();
    setOcupado(true); setErro("");
    try {
      await api(`/api/siga/medicoes/${medicaoId}/link`, { method: "POST", body: JSON.stringify({ link: link.trim() }) });
      setAberto(false); setLink("");
      aoGravar();
    } catch (e) { setErro(mensagemDeErro(e)); } finally { setOcupado(false); }
  }
  if (!aberto) {
    return <p><button type="button" className="btn btn--pequeno" onClick={() => setAberto(true)}>Colar o link de acompanhamento</button></p>;
  }
  const idErro = `link-siga-erro-${medicaoId}`;
  return (
    <div className="pilha">
      <form className="form-inline" onSubmit={gravar} aria-label="Link de acompanhamento">
        <div className="campo">
          <label className="campo__rotulo" htmlFor={`link-siga-${medicaoId}`}>Link de acompanhamento</label>
          <input id={`link-siga-${medicaoId}`} name="link_siga_processo" autoComplete="off" spellCheck={false} required
            className="entrada--larga" maxLength={500} placeholder="Cole o link que o órgão mandou…" value={link} aria-invalid={erro ? true : undefined}
            aria-describedby={erro ? idErro : undefined} onChange={e => { setLink(e.target.value); setErro(""); }} />
        </div>
        <button type="submit" className="btn" disabled={ocupado || !link.trim()}>{ocupado ? "Gravando…" : "Gravar"}</button>
        <button type="button" className="btn" onClick={() => { setAberto(false); setLink(""); setErro(""); }}>Voltar</button>
      </form>
      {erro && <p className="erro" role="alert" id={idErro}><IconeAlerta className="icone icone--p" />{erro}</p>}
    </div>
  );
}

/** `aoRevisar`: a revisao foi gravada; a pagina descarta a conferencia antiga e espera o detalhe novo (gate Sol, PR
 *  #553): ate' la' nem outra revisao nem o espelho sem o boletim se oferecem. */
export default function PassoAnalise({ m, planilha, podeEditar, salvando, agir, aoMudarSiga, aoRevisar }: {
  m: Medicao; planilha: DetalhePlanilha | null; podeEditar: boolean; salvando: boolean; agir: Agir;
  aoMudarSiga: () => void; aoRevisar?: () => void;
}) {
  const [siga, setSiga] = useState<PainelSiga | null>(null);
  const [aberta, setAberta] = useState<Resposta>(null);
  const numero = planilha?.planilha_siga?.numero ?? null;
  const [relido, setRelido] = useState(0);     // #668: o link gravado cria o processo; a tela SIGA e' relida
  useEffect(() => {
    let vivo = true;
    // a tela SIGA e' a fonte (relida quando o nº do SIGA muda); sem ela (falha, sem processo), o passo mostra o que a
    // medicao tem
    api<PainelSiga>("/api/siga").then(p => { if (vivo) setSiga(p); }).catch(() => {});
    return () => { vivo = false; };
  }, [m.id, numero, relido]);
  // #644: as respostas do orgao lidas da conversa do e-mail enviado; relidas quando uma leitura registra resposta nova
  const [respostas, setRespostas] = useState<RespostaOrgao[]>([]);
  useEffect(() => {
    let vivo = true;
    const ler = () => api<RespostaOrgao[]>(`/api/medicoes/${m.id}/respostas-orgao`)
      .then(r => { if (vivo) setRespostas(Array.isArray(r) ? r : []); }).catch(() => {});
    // #667: a resposta nova pode ter trazido o protocolo do SIGA (o processo nasce na leitura): a tela SIGA e' relida
    const reler = () => { ler(); setRelido(n => n + 1); };
    ler();
    window.addEventListener(EVENTO_RESPOSTAS_LIDAS, reler);
    return () => { vivo = false; window.removeEventListener(EVENTO_RESPOSTAS_LIDAS, reler); };
  }, [m.id]);

  const proc = siga ? processoDa(siga.processos ?? [], m.id, numero) : null;
  // #668: com o nº digitado e sem processo ligado a' medicao (o avulso de mesmo nº nao conta), oferece o link
  const ofereceLink = podeEditar && siga !== null && numero !== null && proc?.medicao_id !== m.id;
  const movs = proc ? [...proc.movimentacoes].sort((a, b) => Date.parse(b.data) - Date.parse(a.data)).slice(0, 3) : [];
  const esperando = m.estado === "planilha_enviada";
  const podeResponder = podeEditar && esperando;
  const vigente = planilha?.planilhas.at(-1) ?? null;
  // o envio mais recente (a revisao enviada recomeca a conta, gate Sol PR #553); sem ele, o 1o envio
  const enviadaEm = m.planilha_ultimo_envio_em ?? m.planilha_enviada_em ?? planilha?.planilha_enviada_em ?? null;
  const alternar = (r: Exclude<Resposta, null>) => setAberta(a => (a === r ? null : r));
  // o boletim vigente: a resposta que o orgao ja' deu (valor aprovado e data)
  const aprovado = (m.boletins ?? []).filter(b => b.tem_arquivo).at(-1) ?? null;

  return (
    <div className="pilha">
      <section className="cartao orgao-faixa" aria-labelledby="orgao-prazo">
        <h2 id="orgao-prazo">{esperando ? frasePrazo(m.dias_uteis_no_orgao) : aprovado ? "Aprovada pelo órgão" : "Análise concluída"}</h2>
        <dl className="orgao-faixa__dados">
          <div><dt>Enviada em</dt><dd>{enviadaEm ? fmtDataPura(enviadaEm.slice(0, 10)) : "—"}</dd></div>
          <div><dt>Processo SIGA</dt><dd>{numero ?? proc?.numero ?? "—"}</dd></div>
          <div><dt>Valor pedido</dt><dd>{brl(m.valor_protocolado_centavos)}</dd></div>
          {proc?.link && (
            <a className="link orgao-faixa__link" href={proc.link} target="_blank" rel="noreferrer">
              Abrir no SIGA <IconeLinkExterno className="icone icone--p" /></a>
          )}
        </dl>
      </section>

      <div className="med-duas med-duas--iguais">
        <section className="cartao med-painel" aria-labelledby="orgao-onde">
          <h3 className="med-painel__titulo" id="orgao-onde">Onde está o processo</h3>
          {proc ? (
            <>
              <div className="orgao-setor">
                <p className="orgao-setor__rotulo">Setor atual</p>
                <p className="orgao-setor__nome">{proc.setor || "—"}</p>
                {(proc.com_quem || proc.desde) && (
                  <p>{proc.com_quem}{proc.desde ? ` desde ${diaMes(proc.desde)}` : ""}</p>
                )}
              </div>
              {movs.length > 0 && (
                <ol className="orgao-mov" aria-label="Últimas movimentações">
                  {movs.map((x, i) => (
                    <li key={`${x.data}-${i}`}>
                      <time dateTime={x.data}>{diaMes(x.data)} {fmtHora(x.data)}</time>
                      <span>{[tituloDoEvento(x.evento), quemDaMovimentacao(x) || sigla(x.at_lotacao)].filter(Boolean).join(" · ")}</span>
                    </li>
                  ))}
                </ol>
              )}
              {siga?.lido_em && <p className="orgao-lido">Lido do SIGA às <span className="num">{fmtHora(siga.lido_em)}</span></p>}
            </>
          ) : (
            enviadaEm ? <NumeroSiga medicaoId={m.id} atual={numero} podeEditar={podeEditar && esperando} aoGravar={aoMudarSiga} /> : <p>—</p>
          )}
          {ofereceLink && <LinkSiga medicaoId={m.id} aoGravar={() => setRelido(n => n + 1)} />}
        </section>

        <section className="cartao med-painel" aria-labelledby="orgao-resposta">
          <h3 className="med-painel__titulo" id="orgao-resposta">Resposta do órgão</h3>
          {!esperando && aprovado ? (
            <>
              <dl className="orgao-faixa__dados" aria-label="Aprovação">
                <div><dt>Valor aprovado</dt><dd>{brl(aprovado.valor_centavos ?? null)}</dd></div>
                <div><dt>Data da aprovação</dt><dd>{aprovado.atestado_em ? fmtDataPura(aprovado.atestado_em) : "—"}</dd></div>
                {/* #288: a diferenca do aprovado vigente abaixo do pedido, so' enquanto existe (aceita, vira o selo) */}
                {m.valor_atestado_centavos !== null && m.valor_protocolado_centavos !== null
                  && m.valor_atestado_centavos < m.valor_protocolado_centavos && !m.diferenca_aceita && (
                  <div><dt>Diferença</dt><dd className="num">{brl(m.valor_atestado_centavos - m.valor_protocolado_centavos)}</dd></div>
                )}
              </dl>
              <AceiteDiferenca m={m} podeEditar={podeEditar} salvando={salvando} agir={agir} />
            </>
          ) : !podeResponder ? <p>{esperando ? "Aguardando a resposta do órgão" : "—"}</p> : (
            <>
              <div className={`resposta${aberta === "aprovou" ? " resposta--aberta" : ""}`}>
                <button type="button" aria-expanded={aberta === "aprovou"} onClick={() => alternar("aprovou")}>
                  <span className="resposta__marca resposta__marca--ok" aria-hidden="true"><IconeCheck /></span>
                  <span className="resposta__texto"><span className="resposta__titulo">Aprovou a medição</span></span>
                </button>
                {aberta === "aprovou" && (
                  <div className="resposta__corpo">
                    <FormBoletim m={m} salvando={salvando} agir={agir} aoFechar={() => setAberta(null)} />
                  </div>
                )}
              </div>
              {/* a revisao parte da versao vigente: so' se oferece depois de a planilha/carta ser lida */}
              {planilha && vigente && <div className={`resposta${aberta === "revisao" ? " resposta--aberta" : ""}`}>
                <button type="button" aria-expanded={aberta === "revisao"} onClick={() => alternar("revisao")}>
                  <span className="resposta__marca resposta__marca--rev" aria-hidden="true">↻</span>
                  <span className="resposta__texto"><span className="resposta__titulo">Pediu revisão</span>
                    <span className="resposta__sub">registrar nova versão da planilha</span></span>
                </button>
                {aberta === "revisao" && (
                  <div className="resposta__corpo">
                    <Revisao medicao={planilha} vigente={vigente} ocupado={salvando} aoFechar={() => setAberta(null)}
                      aoRegistrar={async fd => {
                        const ok = await agir(async () => {
                          await apiForm(`/api/medicoes/${m.id}/planilhas`, fd);
                          aoRevisar?.();
                        }, "Revisão registrada.");
                        if (ok) setAberta(null);
                      }} />
                  </div>
                )}
              </div>}
            </>
          )}
        </section>
      </div>

      {respostas.length > 0 && (
        <section className="cartao med-painel" aria-labelledby="orgao-emails">
          <h3 className="med-painel__titulo" id="orgao-emails">Respostas do órgão por e-mail</h3>
          <ol className="orgao-emails" aria-labelledby="orgao-emails">
            {respostas.map(r => {
              // #667: a resposta que trouxe o link de acompanhamento; o processo vem da tela SIGA (sem ela, so' a marca)
              const protocolo = r.siga_processo_id ? siga?.processos?.find(p => p.id === r.siga_processo_id) ?? null : null;
              return (
                <li key={r.id}>
                  <p className="orgao-emails__de">
                    <span>{r.remetente_nome || r.remetente}</span>
                    <time dateTime={r.recebida_em}>{diaMes(r.recebida_em)} {fmtHora(r.recebida_em)}</time>
                  </p>
                  {r.siga_processo_id ? (
                    <p className="orgao-emails__siga">
                      <span className="selo selo--ok"><span className="selo__ponto" aria-hidden="true" /><span className="selo__texto">Protocolo do SIGA</span></span>
                      {protocolo && <span>{[`Processo ${protocolo.numero ?? protocolo.codigo ?? ""}`.trim(), protocolo.setor].filter(Boolean).join(" · ")}</span>}
                      {protocolo?.link && (
                        <a className="link" href={protocolo.link} target="_blank" rel="noreferrer">
                          Abrir no SIGA <IconeLinkExterno className="icone icone--p" /></a>
                      )}
                    </p>
                  ) : null}
                  <p>{r.trecho}</p>
                </li>
              );
            })}
          </ol>
        </section>
      )}
    </div>
  );
}
