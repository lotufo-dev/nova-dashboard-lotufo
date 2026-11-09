import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import CampoValor from "./CampoValor";
import { digitosParaBrl } from "./formato";
import { fmtCompetencia } from "./tempo";

// Issue #276 (spec 2026-10-20 §2.2, decisao do Leo de 08/11/2026): o campo "Reajuste" da medicao de reajuste, ja'
// preenchido com a sugestao do servidor (o apostilado da competencia, senao o previsto, senao vazio) e a origem dela.
// Com duas datas-base (D7), o campo "Data-base" escolhe; vem escolhida quando so' uma tem previsao na competencia. O
// sistema nao calcula nada: a sugestao, o ciclo e o aviso (ja' pedido em outra medicao, ciclo em aberto) vem de
// `/reajuste/sugestao`. Issue #589: o reajuste aceita valor negativo (apostilamento ou previsao negativos).

export type BaseSugerida = {
  data_base_mes: string; aplica_a: string; ciclo: number | null;
  valor_centavos: number | null; origem: string | null; origem_texto: string | null; aviso?: string | null;
};
export type SugestaoReajuste = { competencia: string; bases: BaseSugerida[]; data_base_mes: string | null };
export type ValorReajuste = { valor: string; dataBase: string };

function rotuloBase(b: BaseSugerida): string {
  return b.aplica_a ? `${fmtCompetencia(b.data_base_mes)} (${b.aplica_a})` : fmtCompetencia(b.data_base_mes);
}

/** O valor que o campo mostra para a base: o sugerido em "1.234,56" (issue #589: o apostilado negativo com o sinal,
 *  "-10,01"), ou vazio. */
function sugerido(s: SugestaoReajuste, dataBase: string): string {
  const b = s.bases.find(x => x.data_base_mes === dataBase);
  if (b?.valor_centavos == null) return "";
  const texto = digitosParaBrl(String(Math.abs(b.valor_centavos)));
  return b.valor_centavos < 0 ? `-${texto}` : texto;
}

/** `numero`: o da planilha/carta; se a medicao de reajuste desse nº ja' nao recebe o reajuste, o servidor devolve
 *  nenhuma base e o campo nao aparece. Campo escondido (sem base, competencia incompleta, leitura que falhou) zera o
 *  valor: nada vai ao servidor sem a pessoa ver. Trocar a competencia, o nº ou a data-base volta o campo a' sugestao
 *  da chave nova: o digitado para uma competencia nao vai para outra. */
export default function CampoReajuste({ contratoId, competencia, numero, prefixo, valor, aoMudar }: {
  contratoId: number; competencia: string; numero?: string; prefixo: string; valor: ValorReajuste;
  aoMudar: (v: ValorReajuste) => void;
}) {
  const [sug, setSug] = useState<SugestaoReajuste | null>(null);
  // o valor e o aoMudar de agora, lidos quando a sugestao chega (sem refazer a leitura a cada tecla)
  const atual = useRef(valor);
  const mudar = useRef(aoMudar);
  useEffect(() => { atual.current = valor; mudar.current = aoMudar; });

  useEffect(() => {
    let vivo = true;
    const zerar = () => {
      const v = atual.current;
      if (v.valor || v.dataBase) mudar.current({ valor: "", dataBase: "" });
    };
    const esconder = () => { if (vivo) { setSug(null); zerar(); } };
    // a chave mudou: ate' a sugestao nova chegar, o campo nao carrega o valor da chave anterior
    setSug(null);
    zerar();
    const num = numero !== undefined && /^\d{1,3}$/.test(numero) ? `&numero=${numero}` : "";
    if (!/^\d{4}-\d{2}$/.test(competencia)) return () => { vivo = false; };
    const t = setTimeout(() => {
      api<SugestaoReajuste>(`/api/contratos/${contratoId}/reajuste/sugestao?competencia=${competencia}${num}`)
        .then(r => {
          if (!vivo) return;
          const s = { ...r, bases: r.bases ?? [] };
          if (s.bases.length === 0) { esconder(); return; }
          setSug(s);
          const dataBase = s.data_base_mes ?? "";
          mudar.current({ dataBase, valor: sugerido(s, dataBase) });
        })
        .catch(esconder);
    }, 250);
    return () => { vivo = false; clearTimeout(t); };
  }, [contratoId, competencia, numero]);

  if (!sug || sug.bases.length === 0) return null;
  const base = sug.bases.find(b => b.data_base_mes === valor.dataBase);
  // a origem so' vale enquanto o campo mostra o valor sugerido
  const origem = base?.origem_texto && valor.valor !== "" && valor.valor === sugerido(sug, valor.dataBase) ? base.origem_texto : null;
  const nota = base?.aviso ?? origem;

  return (
    <div className="form-inline">
      {sug.bases.length > 1 && (
        <div className="campo">
          <label className="campo__rotulo" htmlFor={`${prefixo}-data-base`}>Data-base</label>
          <select id={`${prefixo}-data-base`} className="entrada--media" value={valor.dataBase}
            onChange={e => { const dataBase = e.target.value; aoMudar({ dataBase, valor: sugerido(sug, dataBase) }); }}>
            <option value="">—</option>
            {sug.bases.map(b => <option key={b.data_base_mes} value={b.data_base_mes}>{rotuloBase(b)}</option>)}
          </select>
        </div>
      )}
      <div className="campo">
        <label className="campo__rotulo" htmlFor={`${prefixo}-reajuste`}>Reajuste</label>
        <CampoValor id={`${prefixo}-reajuste`} name="reajuste" value={valor.valor} comSinal
          onChange={v => aoMudar({ ...valor, valor: v })} />
        {nota && <span className="campo__nota" id={`${prefixo}-reajuste-origem`}>{nota}</span>}
      </div>
    </div>
  );
}
