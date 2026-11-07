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
// continua na linha da nota.

type ProtocoloLido = { numero_orgao: string | null; situacao: string; medicoes: { id: number }[] };

/** Dias corridos entre duas datas "AAAA-MM-DD" (sem fuso: recorte de string, como fmtDataPura). */
export function diasEntre(de: string, ate: string): number | null {
  const a = /^(\d{4})-(\d{2})-(\d{2})/.exec(de);
  const b = /^(\d{4})-(\d{2})-(\d{2})/.exec(ate);
  if (!a || !b) return null;
  const ms = Date.UTC(+b[1], +b[2] - 1, +b[3]) - Date.UTC(+a[1], +a[2] - 1, +a[3]);
  return Math.max(0, Math.round(ms / 86400000));
}

/** A receber: o que falta das notas da Lotufo (no consorcio, so' a cota dela tem nota da Lotufo); sem nota ainda,
 *  o valor cheio fora do consorcio e "—" no consorcio (a cota so' se sabe pela nota). */
export function aReceber(grupo: Medicao[], consorcio: boolean): { falta: number | null; recebido: number; total: number | null } {
  const notas = grupo.flatMap(x => x.notas ?? []);
  if (notas.length > 0) {
    const total = notas.reduce((t, n) => t + n.valor_centavos, 0);
    const recebido = notas.reduce((t, n) => t + n.recebido_centavos, 0);
    return { falta: Math.max(0, total - recebido), recebido, total };
  }
  if (consorcio) return { falta: null, recebido: 0, total: null };
  const valores = grupo.map(x => x.valor_protocolado_centavos).filter((v): v is number => v !== null);
  const total = valores.length > 0 ? valores.reduce((a, b) => a + b, 0) : null;
  return { falta: total, recebido: 0, total };
}

export default function PassoPagamento({ grupo, junta, usuario, protocolos, aqui, percentualBp, aoReceber }: {
  grupo: Medicao[]; junta: boolean; usuario: Usuario; protocolos: ProtocoloLido[]; aqui: Rota;
  /** a cota da Lotufo no contrato, em pontos-base (10000 = obra so' da Lotufo) */
  percentualBp: number;
  aoReceber: (m: Medicao) => void;
}) {
  const [siga, setSiga] = useState<PainelSiga | null>(null);
  const chave = grupo.map(x => x.id).join(",");
  useEffect(() => {
    let vivo = true;
    api<PainelSiga>("/api/siga").then(p => { if (vivo) setSiga(p); }).catch(() => {});
    return () => { vivo = false; };
  }, [chave]);

  const consorcio = percentualBp !== 10000;
  const receber = aReceber(grupo, consorcio);
  const valores = grupo.map(x => x.valor_protocolado_centavos).filter((v): v is number => v !== null);
  const total = valores.length > 0 ? valores.reduce((a, b) => a + b, 0) : null;
  const recebida = grupo.length > 0 && grupo.every(x => x.estado === "recebida");
  const enviada = grupo.flatMap(x => x.protocolos.map(p => p.data)).sort().at(-1) ?? null;
  const dias = enviada && !recebida ? diasEntre(enviada, hojeLocal()) : null;
  const notas = grupo.flatMap(x => (x.notas ?? []).map(n => ({ n, m: x })));
  const nfsDocs = notas.length === 0 ? grupo.flatMap(x => (x.documentos ?? []).filter(d => d.tipo_doc === "nfs" && d.numero_nf)) : [];
  const pct = receber.total ? Math.min(100, Math.floor((receber.recebido * 100) / receber.total)) : 0;
  // onde o orgao junta medicao e reajuste, um processo so'; onde separa, um por medicao
  const linhas = junta && grupo.length > 1 ? [grupo] : grupo.map(x => [x]);
  const recebiveis = usuario.perfil === "admin" ? grupo.filter(x => (PROXIMOS[x.estado] ?? []).includes("recebida")) : [];

  return (
    <section className="med-passo" id="passo-6" aria-labelledby="passo-6-titulo">
      <h2 className="sr-only" id="passo-6-titulo">Pagamento</h2>
      <div className="cartao pag-numeros">
        <div>
          <p className="pag-numeros__rotulo">A receber{consorcio ? " · cota da Lotufo" : ""}</p>
          <p className="pag-numeros__valor pag-numeros__valor--acento num" aria-label={`A receber: ${brl(receber.falta)}`}>{brl(receber.falta)}</p>
        </div>
        <div>
          <p className="pag-numeros__rotulo">Total da medição</p>
          <p className="pag-numeros__valor num">{brl(total)}</p>
        </div>
        <div>
          {recebida ? (
            <>
              <p className="pag-numeros__rotulo">Recebida</p>
              <p className="pag-numeros__valor num">{grupo[0].recebida_em ? fmtDataPura(grupo[0].recebida_em.slice(0, 10)) : "—"}</p>
            </>
          ) : (
            <>
              <p className="pag-numeros__rotulo">Aguardando há</p>
              <p className="pag-numeros__valor num">{dias === null ? "—" : fmtDias(dias)}</p>
              {enviada && <p className="pag-numeros__nota">nota enviada em {fmtDataPura(enviada)}</p>}
            </>
          )}
        </div>
      </div>

      <div className="med-duas">
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
                  const paga = n.recebido_centavos >= n.valor_centavos && n.valor_centavos > 0;
                  return (
                    <tr key={n.nota_id}>
                      <td>NF {Number(n.numero) || n.numero}{grupo.length > 1 ? ` · ${m.tipo === "reajuste" ? "reajuste" : "medição"}` : ""}</td>
                      <td className="col-num num">{brl(n.valor_centavos)}</td>
                      <td>{paga ? <Selo classe="selo--ok">paga{n.recebido_em ? ` em ${fmtDataPura(n.recebido_em.slice(0, 10))}` : ""}</Selo>
                        : n.recebido_centavos > 0 ? <Selo classe="selo--atencao">paga em parte</Selo>
                        : <Selo classe="selo--atencao">em aberto</Selo>}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {receber.total !== null && receber.total > 0 && (
            <div className="medidor" aria-label="Recebido">
              <div className="medidor__barra"><div className="medidor__cheio" style={{ width: `${pct}%` }} /></div>
              <span className="medidor__texto">{pct}%</span>
            </div>
          )}
          {receber.total !== null && receber.total > 0 && (
            <p className="num">{brl(receber.recebido)} recebido de {brl(receber.total)}</p>
          )}
          <p>{recebida ? <Selo classe="selo--ok">Recebida</Selo>
            : grupo.some(x => ["protocolada", "nf_emitida"].includes(x.estado)) ? <Selo classe={receber.recebido > 0 ? "selo--ok" : "selo--atencao"}>{receber.recebido > 0 ? "Recebido em parte" : "Aguardando o órgão"}</Selo> : null}</p>
          {/* issue #53: o recebimento a mao e' so' do admin (o servidor recusa outro perfil) */}
          {recebiveis.map(x => (
            <div key={x.id}>
              <button type="button" className="btn btn--pequeno" title={tituloMedicao(x)} onClick={() => aoReceber(x)}>Registrar recebimento</button>
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
                    ? <Link className="link" para={aqui} secao="etapa-4">Registrar o protocolo</Link> : "—")}</dd></div>
                  <div><dt>Enviada em</dt><dd className="num">{env ? fmtDataPura(env) : "—"}</dd></div>
                </dl>
                {proc?.link && (
                  <a className="link" href={proc.link} target="_blank" rel="noreferrer">Abrir o acompanhamento <IconeLinkExterno className="icone icone--p" /></a>
                )}
              </div>
            );
          })}
        </section>
      </div>
    </section>
  );
}
