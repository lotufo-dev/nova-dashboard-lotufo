import { useEffect, useState } from "react";
import { api } from "./api";
import { brl, fmtDias } from "./formato";
import { IconeLinkExterno } from "./icones";
import { Link } from "./Link";
import type { Usuario } from "./Login";
import { PROXIMOS, tituloMedicao } from "./medicao";
import type { Medicao } from "./Medicoes";
import { processoDa } from "./PassoAnalise";
import { diaMes } from "./Passos";
import type { Rota } from "./rota";
import Selo from "./Selo";
import type { PainelSiga } from "./siga";
import { fmtDataPura, hojeLocal } from "./tempo";

// Issue #514, passo 6 da pagina da obra (aprovado em 06/11/2026): o que falta receber (a cota da Lotufo no
// consorcio), o total da medicao, ha' quantos dias a nota esta' com o orgao, as notas no financeiro (as baixas do RM)
// e o processo no orgao. Sem botao de fluxo: a medicao recebida fecha o passo. O recebimento a mao (so' admin, #53)
// continua na linha da nota. #743: na obra sem o passo "Envio da nota", a nota emitida ja' esta' aqui, sem protocolo.

type ProtocoloLido = { numero_orgao: string | null; situacao: string; medicoes: { id: number }[] };

/** Dias corridos entre duas datas "AAAA-MM-DD" (sem fuso: recorte de string, como fmtDataPura). */
export function diasEntre(de: string, ate: string): number | null {
  const a = /^(\d{4})-(\d{2})-(\d{2})/.exec(de);
  const b = /^(\d{4})-(\d{2})-(\d{2})/.exec(ate);
  if (!a || !b) return null;
  const ms = Date.UTC(+b[1], +b[2] - 1, +b[3]) - Date.UTC(+a[1], +a[2] - 1, +a[3]);
  return Math.max(0, Math.round(ms / 86400000));
}

type NotaDaMedicao = NonNullable<Medicao["notas"]>[number];

/** A nota e' da coligada da Lotufo; a de outra coligada (a fatura do consorcio, ou a NFS-e de outra consorciada) e'
 *  so' marcada na linha dela: o servidor nao diz qual documento e', e a tela nao adivinha (gate Sol, rodada 4). */
export const daLotufo = (n: NotaDaMedicao) => n.da_lotufo !== false;

/** O que falta receber de uma nota, contra os TITULOS do RM (liquidos, sem as retencoes), nunca contra o bruto;
 *  null quando a nota ainda nao tem titulo (devido zero: nao ha' o que comparar). */
export function faltaDaNota(n: NotaDaMedicao): number | null {
  const devido = n.devido_centavos ?? 0;
  if (devido <= 0) return null;
  return n.falta_centavos ?? Math.max(0, devido - n.recebido_centavos);
}

/** O resumo do pagamento (#514): o servidor calcula, num lugar so', a cota da Lotufo da medicao e da irma valida do
 *  par (`pagamento_cota`, sincronizacao_rm.pagamento_cota); a tela so' exibe, sem somar nem escolher notas. Valores
 *  null ("—") quando o servidor diz que ainda nao fecham (sem espelho, nota faltando, nota sem titulo). */
export function aReceber(grupo: Medicao[]):
    { falta: number | null; recebido: number | null; total: number | null; parcial: boolean; completo: boolean } {
  const b = grupo[0]?.pagamento_cota ?? null;
  if (!b || !b.completo) return { falta: null, recebido: null, total: null, parcial: !!b?.parcial, completo: false };
  return { falta: b.falta_centavos, recebido: b.recebido_centavos, total: b.total_centavos, parcial: b.parcial, completo: true };
}

export default function PassoPagamento({ grupo, junta, usuario, protocolos, aqui, percentualBp, total, aoReceber }: {
  grupo: Medicao[]; junta: boolean; usuario: Usuario; protocolos: ProtocoloLido[]; aqui: Rota;
  /** o valor cheio da pagina (o mesmo do cabecalho) */
  total: number | null;
  /** a cota da Lotufo no contrato, em pontos-base (10000 = obra so' da Lotufo; null = cabecalho ainda nao lido) */
  percentualBp: number | null;
  aoReceber: (m: Medicao) => void;
}) {
  const [siga, setSiga] = useState<PainelSiga | null>(null);
  const chave = grupo.map(x => x.id).join(",");
  useEffect(() => {
    let vivo = true;
    api<PainelSiga>("/api/siga").then(p => { if (vivo) setSiga(p); }).catch(() => {});
    return () => { vivo = false; };
  }, [chave]);

  // o rotulo so' fala de cota com o cabecalho lido e a obra em consorcio
  const rotuloCota = percentualBp !== null && percentualBp !== 10000;
  const receber = aReceber(grupo);
  const quitado = receber.falta === 0 && (receber.total ?? 0) > 0;
  // espelho sem saida da Lotufo nesta natureza: a cota fecha em zero, e nao ha' orgao a esperar nem nada recebido
  // (gate Sol, rodada 4); zero nao ganha frase (regra texto-na-tela), so' o R$ 0,00 do "A receber"
  const nadaAReceber = receber.completo && receber.total === 0;
  const recebida = grupo.length > 0 && grupo.every(x => x.estado === "recebida");
  // o par so' esta' recebido quando a ultima metade entra: a data e' a maior (gate Sol, rodada 5)
  const recebidaEm = grupo.map(x => x.recebida_em).filter((d): d is string => !!d).sort().at(-1) ?? null;
  const enviada = grupo.flatMap(x => x.protocolos.map(p => p.data)).sort().at(-1) ?? null;
  // #743: na obra sem o passo "Envio da nota" nao ha' protocolo; a espera conta da emissao da nota (a mais recente)
  const emitida = !enviada && grupo.some(x => x.recebe_sem_protocolo)
    ? grupo.map(x => x.nota_emitida_em).filter((d): d is string => !!d).sort().at(-1) ?? null : null;
  const inicio = enviada ?? emitida;
  const dias = inicio && !recebida ? diasEntre(inicio, hojeLocal()) : null;
  const notas = grupo.flatMap(x => (x.notas ?? []).map(n => ({ n, m: x })));
  const nfsDocs = notas.length === 0 ? grupo.flatMap(x => (x.documentos ?? []).filter(d => d.tipo_doc === "nfs" && d.numero_nf)) : [];
  const pct = receber.total && receber.recebido !== null ? Math.min(100, Math.floor((receber.recebido * 100) / receber.total)) : 0;
  // onde o orgao junta medicao e reajuste, um processo so'; onde separa, um por medicao
  const linhas = junta && grupo.length > 1 ? [grupo] : grupo.map(x => [x]);
  const recebiveis = usuario.perfil === "admin"
    ? grupo.filter(x => (PROXIMOS[x.estado] ?? []).includes("recebida") || x.recebe_sem_protocolo) : [];

  return (
    <section className="med-passo" id="passo-6" aria-labelledby="passo-6-titulo">
      <div className="med-quadro__cab"><h2 className="med-quadro__titulo" id="passo-6-titulo">Pagamento</h2></div>
      {/* #722: os tres numeros no alto do passo, sem caixa propria */}
      <div className="pag-numeros">
        <div>
          <p className="pag-numeros__rotulo">A receber{rotuloCota ? " · cota da Lotufo" : ""}</p>
          <p className="pag-numeros__valor pag-numeros__valor--acento num" aria-label={`A receber: ${brl(receber.falta)}`}>{brl(receber.falta)}</p>
          {/* issue #562: o a receber sai de nota que diverge do espelho */}
          {(grupo[0]?.pagamento_cota?.falta_divergente_centavos ?? 0) > 0 && <Selo situacao="critico">Nota divergente do espelho</Selo>}
        </div>
        <div>
          <p className="pag-numeros__rotulo">Total da medição</p>
          <p className="pag-numeros__valor num">{brl(total)}</p>
        </div>
        <div>
          {recebida ? (
            <>
              <p className="pag-numeros__rotulo">Recebida</p>
              <p className="pag-numeros__valor num">{recebidaEm ? fmtDataPura(recebidaEm.slice(0, 10)) : "—"}</p>
            </>
          ) : (
            <>
              <p className="pag-numeros__rotulo">Aguardando há</p>
              <p className="pag-numeros__valor num">{dias === null ? "—" : fmtDias(dias)}</p>
              {enviada && <p className="pag-numeros__nota">nota enviada em {fmtDataPura(enviada)}</p>}
              {emitida && <p className="pag-numeros__nota">nota emitida em {fmtDataPura(emitida.slice(0, 10))}</p>}
            </>
          )}
        </div>
      </div>

      {/* a caixa mede a largura do passo: notas e processo ficam lado a lado quando ha' largura */}
      <div className="pag-par">
      <div className="med-duas pag-duas">
        <section className="cartao med-painel" aria-labelledby="pag-notas">
          <h3 className="med-painel__titulo" id="pag-notas">Notas e pagamento</h3>
          <div className="med-caixa">
            <table className="tabela">
              <thead><tr><th scope="col">Nota</th><th scope="col" className="col-num">Valor</th><th scope="col">No financeiro</th></tr></thead>
              <tbody>
                {notas.length === 0 && nfsDocs.length === 0 && <tr><td colSpan={3}>—</td></tr>}
                {nfsDocs.map(d => (
                  <tr key={`d${d.id}`}><td>NF {d.numero_nf}{d.municipio ? ` · ${d.municipio}` : ""}</td><td className="col-num">—</td><td>—</td></tr>
                ))}
                {notas.map(({ n, m }) => {
                  // o valor e' o nominal da NF (bruto); a situacao no financeiro e' a dos titulos (liquidos)
                  const falta = faltaDaNota(n);
                  // #756: a fatura do consorcio que a nota da propria empresa tirou da conta: o bruto dela nao e' o
                  // cobrado e nao entra em numero nenhum; aparece sem valor e sem situacao, como no Fechamento
                  if (n.fora_da_conta) return (
                    <tr key={n.nota_id}>
                      <td>NF {Number(n.numero) || n.numero}{grupo.length > 1 ? ` · ${m.tipo === "reajuste" ? "reajuste" : "medição"}` : ""}</td>
                      <td colSpan={2}>fatura do consórcio, não entra na conta</td>
                    </tr>
                  );
                  return (
                    <tr key={n.nota_id}>
                      <td>NF {Number(n.numero) || n.numero}{grupo.length > 1 ? ` · ${m.tipo === "reajuste" ? "reajuste" : "medição"}` : ""}
                        {!daLotufo(n) ? " · outra coligada" : ""}</td>
                      <td className="col-num num">{brl(n.valor_centavos)}</td>
                      {/* #722: a nota por pagar ou paga em parte esta' em andamento; "vence em breve" e' so' de prazo */}
                      <td>{falta === null ? "—"
                        : falta === 0 ? <Selo situacao="feito">paga{n.recebido_em ? ` em ${fmtDataPura(n.recebido_em.slice(0, 10))}` : ""}</Selo>
                        : n.recebido_centavos > 0 ? <Selo situacao="andamento">paga em parte</Selo>
                        : <Selo situacao="andamento">em aberto</Selo>}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {receber.falta !== null && receber.total !== null && receber.total > 0 && (
            <div className="medidor" aria-label="Recebido">
              <span className="medidor__rotulo" aria-hidden="true">Recebido</span>
              <div className="medidor__barra"><div className="medidor__cheio" style={{ width: `${pct}%` }} /></div>
              <span className="medidor__texto">{pct}%</span>
            </div>
          )}
          <div className="pag-recebido">
            {receber.falta !== null && receber.total !== null && receber.total > 0 && (
              <p className="num">{brl(receber.recebido)} recebido de {brl(receber.total)}</p>
            )}
            {/* #722: recebido em parte e aguardando o orgao sao andamento; o visto de feito so' com tudo recebido.
                #743: a nota emitida da obra sem o passo "Envio da nota" tambem aguarda o orgao */}
            <p>{recebida ? <Selo situacao="feito">Recebida</Selo>
              : quitado ? <Selo situacao="feito">Recebido</Selo>
              : nadaAReceber ? null
              : grupo.some(x => ["protocolada", "nf_emitida"].includes(x.estado) || x.recebe_sem_protocolo) ? <Selo situacao="andamento">{receber.parcial ? "Recebido em parte" : "Aguardando o órgão"}</Selo> : null}</p>
          </div>
          {/* issue #53: o recebimento a mao e' so' do admin (o servidor recusa outro perfil) */}
          {recebiveis.map(x => (
            <div key={x.id}>
              <button type="button" className="btn" title={tituloMedicao(x)} onClick={() => aoReceber(x)}>Registrar recebimento</button>
            </div>
          ))}
        </section>

        <section className="cartao med-painel" aria-labelledby="pag-processo">
          <h3 className="med-painel__titulo" id="pag-processo">Processo no órgão</h3>
          {linhas.map(g => {
            const env = g.flatMap(x => x.protocolos.map(p => p.data)).sort().at(-1);
            const numero = g.flatMap(x => [
              ...protocolos.filter(p => p.situacao === "enviado" && p.medicoes.some(y => y.id === x.id)).map(p => p.numero_orgao),
              ...x.protocolos.map(p => p.numero_processo)]).find(Boolean) ?? null;
            const proc = siga ? processoDa(siga.processos ?? [], g[0].id, numero) : null;
            return (
              <div key={g.map(x => x.id).join("-")} className="pilha">
                {linhas.length > 1 && <p className="med-sub">{tituloMedicao(g[0])}</p>}
                {proc && (
                  <div className="orgao-setor">
                    <p className="orgao-setor__rotulo">Setor atual</p>
                    <p className="orgao-setor__nome">{proc.setor || "—"}</p>
                    {proc.desde && <p>desde {diaMes(proc.desde)}{proc.dias_uteis !== null ? ` · ${proc.dias_uteis} ${proc.dias_uteis === 1 ? "dia útil" : "dias úteis"}` : ""}</p>}
                  </div>
                )}
                <dl className="pag-dados">
                  <div><dt>Processo</dt><dd>{numero ?? (env
                    ? <Link className="link" para={aqui} secao="passo-5">Registrar o protocolo</Link> : "—")}</dd></div>
                  <div><dt>Enviada em</dt><dd className="num">{env ? fmtDataPura(env) : "—"}</dd></div>
                </dl>
                {proc?.link && (
                  <a className="link pag-externo" href={proc.link} target="_blank" rel="noreferrer">Abrir o acompanhamento <IconeLinkExterno className="icone icone--p" /></a>
                )}
              </div>
            );
          })}
        </section>
      </div>
      </div>
    </section>
  );
}
