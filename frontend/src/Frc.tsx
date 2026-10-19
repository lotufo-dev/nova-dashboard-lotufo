import { useCallback, useEffect, useState } from "react";
import { api, apiForm, baixarArquivo } from "./api";
import { brl } from "./formato";
import { IconeAlerta } from "./icones";
import { IconeCheck, mensagem } from "./NotasAEnviar";
import "./notas.css";
import { fmtDataPura } from "./tempo";

// FRC (Fatura de Recebimento de Consorcio) gerada pela dashboard (2026-10-09): na etapa 3 de obra de consorcio, a
// lista das notas esperadas (empresa x municipio, lidas do CONTEUDO do PDF), a area de arrastar as notas e o bloco
// da FRC (numero digitavel, gerar, baixar PDF e planilha). Gera sozinha quando a ultima nota chega; sai sem
// assinatura: a assinada (DocuSign) e' anexada no envio das notas (etapa 4). As regras moram no servidor.

type Item = {
  chave: string; empresa: string; municipio: string; esperado_centavos: number; situacao: "anexada" | "falta";
  documento_id: number | null; nome: string | null; numero: string | null; problema: string | null;
  valores: { bruto: number; inss: number; irrf: number; iss: number; retencoes: number; liquido: number } | null;
};
export type SituacaoFrc = {
  disponivel: boolean; consorcio: string | null; motivo: string | null; itens?: Item[];
  nao_lidas?: { documento_id: number; nome: string; motivo: string | null }[];
  sobras?: { documento_id: number; nome: string; numero: string; empresa: string }[];
  completa?: boolean; bloqueio?: string | null; ultima?: number; sugerido?: number; assinada?: boolean;
  frc?: { numero: number; data_geracao: string; gerada_em: string; gerada_por: string | null; bruto_centavos: number;
          liquido_centavos: number; desatualizada: boolean } | null;
};

const MOTIVO: Record<string, string> = {
  "sem-texto": "o PDF não tem texto", "leiaute-desconhecido": "leiaute de nota não reconhecido",
  "sem-numero": "nota sem número (rascunho?)",
};

export function FrcConsorcio({ medicaoId, podeEditar, versao, aoMudar, aoLer }: {
  medicaoId: number; podeEditar: boolean; versao: number; aoMudar: () => void;
  aoLer?: (s: SituacaoFrc) => void;
}) {
  const [s, setS] = useState<SituacaoFrc | null>(null);
  const [numero, setNumero] = useState("");
  const [erro, setErro] = useState("");
  const [feito, setFeito] = useState("");
  const [ocupado, setOcupado] = useState(false);
  const [sobre, setSobre] = useState(false);

  const carregar = useCallback(async () => {
    const r = await api<SituacaoFrc>(`/api/medicoes/${medicaoId}/frc`);
    setS(r); setNumero(r.sugerido ? String(r.sugerido) : "");
    aoLer?.(r);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [medicaoId]);
  useEffect(() => { carregar().catch(e => setErro(mensagem(e))); }, [carregar, versao]);

  if (!s) return erro ? <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erro}</p> : null;
  if (!s.disponivel) return s.motivo ? <p className="campo__nota">FRC do {s.consorcio}: {s.motivo}.</p> : null;

  const itens = s.itens ?? [];
  const faltam = itens.filter(i => i.situacao === "falta").length;

  async function anexar(arquivos: FileList | null) {
    const pdfs = Array.from(arquivos ?? []).filter(f => f.type === "application/pdf" || f.name.toLowerCase().endsWith(".pdf"));
    if (pdfs.length === 0) return;
    setOcupado(true); setErro(""); setFeito("");
    try {
      let gerada: number | null = null;
      for (const f of pdfs) {
        const fd = new FormData();
        fd.append("arquivo", f);
        fd.append("tipo_doc", "nfs");
        const r = await apiForm<{ frc_gerada: number | null }>(`/api/medicoes/${medicaoId}/notas`, fd);
        gerada = r.frc_gerada ?? gerada;
      }
      if (gerada) setFeito(`Todas as notas chegaram: FRC nº ${gerada} gerada.`);
      await carregar();
      aoMudar();
    } catch (e) { setErro(mensagem(e)); } finally { setOcupado(false); }
  }

  async function gerar() {
    setOcupado(true); setErro(""); setFeito("");
    try {
      const r = await api<SituacaoFrc>(`/api/medicoes/${medicaoId}/frc`, { method: "POST", body: JSON.stringify({ numero: Number(numero) }) });
      setS(r); setNumero(String(r.sugerido ?? numero)); aoLer?.(r);
      setFeito(`FRC nº ${r.frc?.numero} gerada.`);
      aoMudar();
    } catch (e) { setErro(mensagem(e)); } finally { setOcupado(false); }
  }

  // issue #169: a FRC que ficou desatualizada depois de a tela carregar e' recusada pelo servidor; a tela recarrega
  async function baixar(formato: "pdf" | "xlsx") {
    setErro(""); setFeito("");
    try {
      await baixarArquivo(`/api/medicoes/${medicaoId}/frc/${formato}`, `FRC.${formato}`);
    } catch (e) {
      setErro(mensagem(e));
      await carregar().catch(() => undefined);
      aoMudar();
    }
  }

  const numeroOk = /^\d{1,5}$/.test(numero) && Number(numero) > 0;
  return (
    <div className="notas-v3 frc">
      <div className="frc__cabeca">
        <h3 className="frc__titulo">Notas das consorciadas</h3>
        <span className="campo__nota">{s.consorcio} · {itens.length === 0 ? "sem notas esperadas"
          : faltam === 0 ? `as ${itens.length} notas anexadas` : `falta${faltam > 1 ? "m" : ""} ${faltam} de ${itens.length}`}</span>
      </div>
      {itens.length > 0 && (
        <ul className="nota-itens frc__lista" aria-label="Notas esperadas da medição">
          {itens.map(i => {
            const ok = i.situacao === "anexada" && !i.problema;
            return (
              <li key={i.chave}>
                <span className={`nota-estado nota-estado--${ok ? "ok" : "falta"}`} title={ok ? "Anexada" : i.problema ? "Atenção" : "Falta"}>
                  {ok ? <IconeCheck /> : <span aria-hidden="true">!</span>}
                  <span className="sr-only">{ok ? "Anexada" : i.problema ? "Atenção" : "Falta"}</span>
                </span>
                <span className="nota-item">
                  <span className="nota-item__texto">
                    <span>{i.empresa} · {i.municipio}</span>
                    {i.situacao === "anexada" ? (
                      <span className={`nota-item__detalhe${i.problema ? " nota-item__detalhe--falta" : ""}`}>
                        anexada · NF nº <span className="nota-mono">{i.numero}</span>
                        {i.valores && <> · <span className="nota-mono">{brl(i.valores.bruto)}</span></>}
                        {i.problema && ` · ${i.problema}`}
                      </span>
                    ) : (
                      <span className="nota-item__detalhe nota-item__detalhe--falta">
                        falta · esperada <span className="nota-mono">{brl(i.esperado_centavos)}</span> pelo espelho
                      </span>
                    )}
                  </span>
                </span>
              </li>
            );
          })}
        </ul>
      )}
      {(s.nao_lidas ?? []).length > 0 && (
        <ul className="lista-simples">
          {(s.nao_lidas ?? []).map(d => (
            <li key={d.documento_id} className="notas__diverge">
              <IconeAlerta className="icone icone--p" />{d.nome}: não conta — {MOTIVO[d.motivo ?? ""] ?? "não foi possível ler"}
            </li>
          ))}
        </ul>
      )}
      {(s.sobras ?? []).length > 0 && (
        <ul className="lista-simples">
          {(s.sobras ?? []).map(d => (
            <li key={d.documento_id} className="campo__nota">NF {d.numero} ({d.empresa}) não corresponde a nenhuma nota esperada.</li>
          ))}
        </ul>
      )}
      {podeEditar && (
        <div className={`nota-complementares__soltar${sobre ? " nota-complementares__soltar--sobre" : ""}`}
          onDragOver={ev => { ev.preventDefault(); if (!sobre) setSobre(true); }}
          onDragLeave={() => setSobre(false)}
          onDrop={ev => { ev.preventDefault(); setSobre(false); if (!ocupado) void anexar(ev.dataTransfer.files); }}>
          <span>{ocupado ? "Lendo as notas…" : "Arraste as notas (PDF) aqui ou"}</span>
          <label className="btn btn--pequeno espelho__anexar">
            Anexar notas
            <input type="file" accept="application/pdf" multiple className="espelho__arquivo" disabled={ocupado}
              aria-label="Anexar notas das consorciadas em PDF" onChange={ev => { const fs = ev.currentTarget.files; void anexar(fs); ev.currentTarget.value = ""; }} />
          </label>
        </div>
      )}
      <span className="campo__nota">O número e os valores vêm do conteúdo de cada PDF, não do nome do arquivo.</span>

      <div className="frc__bloco">
        <div className="frc__cabeca">
          <h3 className="frc__titulo">FRC</h3>
          {s.frc && (
            <span className="campo__nota">
              nº <span className="nota-mono">{String(s.frc.numero).padStart(5, "0")}</span> gerada em {fmtDataPura(s.frc.data_geracao)}
              {s.frc.gerada_por ? ` por ${s.frc.gerada_por}` : ""} · bruto <span className="nota-mono">{brl(s.frc.bruto_centavos)}</span>
              {" "}· líquido <span className="nota-mono">{brl(s.frc.liquido_centavos)}</span>
            </span>
          )}
        </div>
        {s.frc?.desatualizada && (
          <p className="notas__diverge"><IconeAlerta className="icone icone--p" />As notas mudaram depois desta FRC: gere de novo.</p>
        )}
        {s.bloqueio && <p className="nota-item__detalhe--falta frc__bloqueio">{s.bloqueio}</p>}
        {!s.frc && !s.bloqueio && <p className="campo__nota">Todas as notas anexadas: gere a FRC.</p>}
        {!s.frc && s.bloqueio && <p className="campo__nota">A FRC é gerada sozinha quando todas as notas esperadas estiverem anexadas.</p>}
        <div className="form-inline frc__gerar">
          <div className="campo">
            <label className="campo__rotulo" htmlFor={`frc-numero-${medicaoId}`}>Número da FRC</label>
            <input id={`frc-numero-${medicaoId}`} name="numero_frc" className="entrada--curta entrada--num num" inputMode="numeric" autoComplete="off" spellCheck={false}
              value={numero} disabled={!podeEditar || ocupado} onChange={ev => setNumero(ev.target.value.replace(/\D/g, "").slice(0, 5))} />
          </div>
          <span className="campo__nota frc__ultima">Última registrada: <span className="nota-mono">{s.ultima}</span></span>
          {podeEditar && (
            <button type="button" className={`btn${s.frc ? "" : " btn--primario"}`} disabled={ocupado || !!s.bloqueio || !numeroOk}
              onClick={() => void gerar()}>{ocupado ? "Gerando…" : s.frc ? "Gerar de novo" : "Gerar a FRC"}</button>
          )}
          {s.frc && !s.frc.desatualizada && (
            <>
              <button type="button" className="btn" onClick={() => void baixar("pdf")}>Baixar PDF</button>
              <button type="button" className="btn" onClick={() => void baixar("xlsx")}>Baixar planilha</button>
            </>
          )}
        </div>
        <p className="frc__assinar">
          {s.assinada ? <><span className="feito">FRC assinada anexada no envio.</span> </> : null}
          Assine no DocuSign e anexe a FRC assinada no envio das notas (etapa 4).
        </p>
      </div>
      <p className={feito ? "notas__ok" : "sr-only"} role="status">{feito}</p>
      {erro && <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erro}</p>}
    </div>
  );
}
