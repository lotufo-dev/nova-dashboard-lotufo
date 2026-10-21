import { useState } from "react";
import CampoValor from "./CampoValor";
import { api, apiForm, mensagemDeErro } from "./api";
import { brl, contar } from "./formato";
import { IconeAlerta } from "./icones";
import { fmtCompetencia } from "./tempo";

// Previsao de reajuste do pleito (issue #272; spec 2026-10-20 §2.2): a pessoa arrasta a planilha do modelo
// "Mem. e Cron. - Prev. de Reajuste", o servidor le (`app/leitura_planilha_reajuste.py`) e a tela mostra
// competencia x valor para conferir; aceitar grava com origem "pleito". Fora do modelo, a tabela vem vazia para
// digitar e grava com origem "manual". Ler nao grava nada; cada aceite e' um evento novo.

type LinhaLida = { competencia: string; valor_centavos: number; medicao: string; periodo: string };
type Leitura = { reconhecida: boolean; linhas: LinhaLida[]; sha256?: string; mensagem?: string; motivo?: string };
type Gravada = { previsao_gravada: number };
type LinhaDigitada = { chave: number; competencia: string; valor: string; negativo: boolean };

let proximaChave = 1;
const linhaVazia = (): LinhaDigitada => ({ chave: proximaChave++, competencia: "", valor: "", negativo: false });
// o CampoValor devolve "1.500,25": os digitos sao os centavos, sem float no caminho
const centavos = (texto: string) => Number(texto.replace(/\D/g, ""));

export default function PleitoPrevisao({ pleitoId, dataBase, ciclo, aoGravar }: {
  pleitoId: number; dataBase: string | null; ciclo: number | null; aoGravar: () => void;
}) {
  const [lidas, setLidas] = useState<LinhaLida[] | null>(null);
  // o aceite manda a MESMA planilha de volta: o servidor rele e grava o que leu (a tela nao decide a origem)
  const [planilha, setPlanilha] = useState<{ arquivo: File; sha256: string } | null>(null);
  const [digitadas, setDigitadas] = useState<LinhaDigitada[] | null>(null);
  const [naoReconhecida, setNaoReconhecida] = useState<{ mensagem: string; motivo?: string } | null>(null);
  const [erro, setErro] = useState("");
  const [ok, setOk] = useState("");
  const [ocupado, setOcupado] = useState(false);

  function limpar() { setLidas(null); setPlanilha(null); setDigitadas(null); setNaoReconhecida(null); setErro(""); }

  async function ler(input: HTMLInputElement) {
    const f = input.files?.[0];
    input.value = "";
    if (!f) return;
    limpar(); setOk(""); setOcupado(true);
    try {
      const fd = new FormData();
      fd.append("arquivo", f);
      const r = await apiForm<Leitura>(`/api/pleitos/${pleitoId}/previsao/ler`, fd);
      if (r.reconhecida && r.sha256) { setLidas(r.linhas); setPlanilha({ arquivo: f, sha256: r.sha256 }); }
      else {
        setNaoReconhecida({ mensagem: r.mensagem ?? "Não reconheci a planilha; digite a previsão", motivo: r.motivo });
        setDigitadas([linhaVazia()]);
      }
    } catch (e) { setErro(mensagemDeErro(e)); } finally { setOcupado(false); }
  }

  // a confirmacao diz quantas competencias o SERVIDOR gravou, nao quantas a tela mandou
  async function gravar(enviar: () => Promise<Gravada>) {
    setOcupado(true); setErro("");
    try {
      const r = await enviar();
      limpar();
      setOk(`Previsão gravada: ${contar(r.previsao_gravada, "competência", "competências")}.`);
      aoGravar();
    } catch (e) { setErro(mensagemDeErro(e)); } finally { setOcupado(false); }
  }

  function aceitarLida() {
    if (!planilha || !lidas) return;
    const fd = new FormData();
    fd.append("arquivo", planilha.arquivo);
    fd.append("sha256", planilha.sha256);      // o servidor recusa se o arquivo relido nao for o conferido
    void gravar(() => apiForm<Gravada>(`/api/pleitos/${pleitoId}/previsao/planilha`, fd));
  }

  function gravarDigitadas() {
    if (!digitadas) return;
    if (digitadas.some(l => !l.competencia || !l.valor)) {
      setErro("Preencha a competência e o valor de todas as linhas (ou remova a linha).");
      return;
    }
    const linhas = digitadas.map(l => ({ competencia: l.competencia, valor_centavos: (l.negativo ? -1 : 1) * centavos(l.valor) }));
    void gravar(() => api<Gravada>(`/api/pleitos/${pleitoId}/previsao/digitada`,
      { method: "POST", body: JSON.stringify({ linhas }) }));
  }

  const mudar = (chave: number, campo: "competencia" | "valor", v: string) =>
    setDigitadas(ls => ls && ls.map(l => l.chave === chave ? { ...l, [campo]: v } : l));
  const total = (lidas ?? []).reduce((s, l) => s + l.valor_centavos, 0);

  return (
    <div className="pilha">
      <span className="painel__titulo" id={`previsao-${pleitoId}`}>Previsão de reajuste</span>
      <p className="campo__nota">A planilha “Mem. e Cron. - Prev. de Reajuste” é lida aqui; confira competência e valor antes de aceitar.</p>
      <div className="acoes acoes--inicio">
        <label className="btn btn--pequeno espelho__anexar">
          Anexar planilha de previsão
          <input type="file" className="espelho__arquivo" aria-label="Anexar planilha de previsão" name="planilha-previsao"
            accept=".xlsx" disabled={ocupado} onChange={ev => void ler(ev.currentTarget)} />
        </label>
        {!digitadas && (
          <button type="button" className="btn btn--pequeno" disabled={ocupado}
            onClick={() => { limpar(); setOk(""); setDigitadas([linhaVazia()]); }}>Digitar a previsão</button>
        )}
      </div>
      {(lidas || digitadas) && dataBase && (
        <p className="campo__nota num">Data-base {fmtCompetencia(dataBase)}{ciclo ? `, ciclo ${ciclo}` : ""}</p>
      )}
      <p aria-live="polite" className="campo__nota">{ok}</p>
      {erro && <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erro}</p>}
      {naoReconhecida && (
        <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{naoReconhecida.mensagem}
          {naoReconhecida.motivo ? ` (${naoReconhecida.motivo}).` : "."}</p>
      )}

      {lidas && (
        <>
          <table className="tabela tabela--densa" aria-label="Previsão lida da planilha">
            <thead><tr><th scope="col">Competência</th><th scope="col">Medição</th><th scope="col">Período</th>
              <th scope="col" className="num">Reajuste previsto</th></tr></thead>
            <tbody>
              {lidas.map(l => (
                <tr key={l.competencia}>
                  <th scope="row" className="num">{fmtCompetencia(l.competencia)}</th>
                  <td>{l.medicao}</td><td className="num">{l.periodo}</td>
                  <td className="num">{brl(l.valor_centavos)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot><tr><th scope="row" colSpan={3}>Total</th><td className="num">{brl(total)}</td></tr></tfoot>
          </table>
          <div className="acoes acoes--inicio">
            <button type="button" className="btn btn--primario btn--pequeno" disabled={ocupado}
              onClick={aceitarLida}>
              Aceitar previsão
            </button>
            <button type="button" className="btn btn--pequeno" disabled={ocupado} onClick={limpar}>Descartar leitura</button>
          </div>
        </>
      )}

      {digitadas && (
        <>
          <table className="tabela tabela--densa" aria-label="Previsão digitada">
            <thead><tr><th scope="col">Competência</th><th scope="col">Reajuste previsto</th><th scope="col"><span className="sr-only">Ações</span></th></tr></thead>
            <tbody>
              {digitadas.map((l, i) => (
                <tr key={l.chave}>
                  <td>
                    <input type="month" className="entrada--media" id={`prev-comp-${pleitoId}-${l.chave}`}
                      aria-label={`Competência da linha ${i + 1}`} value={l.competencia}
                      onChange={ev => mudar(l.chave, "competencia", ev.target.value)} />
                  </td>
                  <td>
                    <label className="sr-only" htmlFor={`prev-valor-${pleitoId}-${l.chave}`}>Valor previsto da linha {i + 1}</label>
                    <CampoValor id={`prev-valor-${pleitoId}-${l.chave}`} name={`valor-${l.chave}`} value={l.valor}
                      ajudaId={`previsao-${pleitoId}`} onChange={v => mudar(l.chave, "valor", v)} />
                    {/* indice deflacionario da' reajuste negativo; o campo de valor so' aceita digitos */}
                    <label className="campo__nota">
                      <input type="checkbox" aria-label={`Reajuste negativo na linha ${i + 1}`} checked={l.negativo}
                        onChange={ev => setDigitadas(ls => ls && ls.map(x =>
                          x.chave === l.chave ? { ...x, negativo: ev.target.checked } : x))} />{" "}negativo
                    </label>
                  </td>
                  <td>
                    {digitadas.length > 1 && (
                      <button type="button" className="btn btn--pequeno" aria-label={`Remover a linha ${i + 1}`}
                        onClick={() => setDigitadas(ls => ls && ls.filter(x => x.chave !== l.chave))}>Remover</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="acoes acoes--inicio">
            <button type="button" className="btn btn--pequeno" disabled={ocupado}
              onClick={() => setDigitadas(ls => [...(ls ?? []), linhaVazia()])}>Adicionar competência</button>
            <button type="button" className="btn btn--primario btn--pequeno" disabled={ocupado} onClick={gravarDigitadas}>
              Gravar previsão
            </button>
            <button type="button" className="btn btn--pequeno" disabled={ocupado} onClick={limpar}>Cancelar</button>
          </div>
        </>
      )}
    </div>
  );
}
