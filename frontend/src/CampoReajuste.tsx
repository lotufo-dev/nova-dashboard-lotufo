import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import CampoValor from "./CampoValor";
import { digitosParaBrl } from "./formato";
import { fmtCompetencia } from "./tempo";

// Issue #276 (spec 2026-10-20 §2.2, decisao do Leo de 08/11/2026): o campo "Reajuste" da medicao de reajuste, ja'
// preenchido com a sugestao do servidor (o apostilado da competencia, senao o previsto, senao vazio) e a origem dela.
// Com duas datas-base (D7), o campo "Data-base" escolhe; vem escolhida quando so' uma tem previsao na competencia. O
// sistema nao calcula nada: a sugestao e o ciclo vem de `/reajuste/sugestao`.

export type BaseSugerida = {
  data_base_mes: string; aplica_a: string; ciclo: number | null;
  valor_centavos: number | null; origem: string | null; origem_texto: string | null;
};
export type SugestaoReajuste = { competencia: string; bases: BaseSugerida[]; data_base_mes: string | null };
export type ValorReajuste = { valor: string; dataBase: string };

function rotuloBase(b: BaseSugerida): string {
  return b.aplica_a ? `${fmtCompetencia(b.data_base_mes)} (${b.aplica_a})` : fmtCompetencia(b.data_base_mes);
}

/** O valor que o campo mostra para a base: o sugerido em "1.234,56", ou vazio. */
function sugerido(s: SugestaoReajuste, dataBase: string): string {
  const b = s.bases.find(x => x.data_base_mes === dataBase);
  // reajuste negativo (indice deflacionario) nao cabe no campo, que so' aceita digitos: fica vazio para digitar
  return b?.valor_centavos != null && b.valor_centavos >= 0 ? digitosParaBrl(String(b.valor_centavos)) : "";
}

/** `numero`: o da planilha/carta; se a medicao de reajuste desse nº ja' nao recebe o reajuste, o servidor devolve
 *  nenhuma base e o campo nao aparece. Campo escondido (sem base, competencia incompleta, leitura que falhou) zera o
 *  valor: nada vai ao servidor sem a pessoa ver. */
export default function CampoReajuste({ contratoId, competencia, numero, prefixo, valor, aoMudar }: {
  contratoId: number; competencia: string; numero?: string; prefixo: string; valor: ValorReajuste;
  aoMudar: (v: ValorReajuste) => void;
}) {
  const [sug, setSug] = useState<SugestaoReajuste | null>(null);
  // o que a pessoa digitou nao e' trocado pela sugestao de outra competencia ou base
  const editado = useRef(false);
  // o valor e o aoMudar de agora, lidos quando a sugestao chega (sem refazer a leitura a cada tecla)
  const atual = useRef(valor);
  const mudar = useRef(aoMudar);
  useEffect(() => { atual.current = valor; mudar.current = aoMudar; });

  useEffect(() => {
    let vivo = true;
    const esconder = () => {
      if (!vivo) return;
      setSug(null);
      editado.current = false;
      const v = atual.current;
      if (v.valor || v.dataBase) mudar.current({ valor: "", dataBase: "" });
    };
    const num = numero !== undefined && /^\d{1,3}$/.test(numero) ? `&numero=${numero}` : "";
    if (!/^\d{4}-\d{2}$/.test(competencia)) { esconder(); return () => { vivo = false; }; }
    const t = setTimeout(() => {
      api<SugestaoReajuste>(`/api/contratos/${contratoId}/reajuste/sugestao?competencia=${competencia}${num}`)
        .then(r => {
          if (!vivo) return;
          const s = { ...r, bases: r.bases ?? [] };
          if (s.bases.length === 0) { esconder(); return; }
          setSug(s);
          const v = atual.current;
          const dataBase = s.bases.some(b => b.data_base_mes === v.dataBase) ? v.dataBase : (s.data_base_mes ?? "");
          mudar.current({ dataBase, valor: editado.current ? v.valor : sugerido(s, dataBase) });
        })
        .catch(esconder);
    }, 250);
    return () => { vivo = false; clearTimeout(t); };
  }, [contratoId, competencia, numero]);

  if (!sug || sug.bases.length === 0) return null;
  const base = sug.bases.find(b => b.data_base_mes === valor.dataBase);
  // a origem so' vale enquanto o campo mostra o valor sugerido
  const origem = base?.origem_texto && valor.valor !== "" && valor.valor === sugerido(sug, valor.dataBase) ? base.origem_texto : null;

  return (
    <div className="form-inline">
      {sug.bases.length > 1 && (
        <div className="campo">
          <label className="campo__rotulo" htmlFor={`${prefixo}-data-base`}>Data-base</label>
          <select id={`${prefixo}-data-base`} className="entrada--media" value={valor.dataBase}
            onChange={e => {
              const dataBase = e.target.value;
              aoMudar({ dataBase, valor: editado.current ? valor.valor : sugerido(sug, dataBase) });
            }}>
            <option value="">—</option>
            {sug.bases.map(b => <option key={b.data_base_mes} value={b.data_base_mes}>{rotuloBase(b)}</option>)}
          </select>
        </div>
      )}
      <div className="campo">
        <label className="campo__rotulo" htmlFor={`${prefixo}-reajuste`}>Reajuste</label>
        <CampoValor id={`${prefixo}-reajuste`} name="reajuste" value={valor.valor}
          onChange={v => { editado.current = true; aoMudar({ ...valor, valor: v }); }} />
        {origem && <span className="campo__nota" id={`${prefixo}-reajuste-origem`}>{origem}</span>}
      </div>
    </div>
  );
}
