import { useState } from "react";
import { apiForm, mensagemDeErro } from "./api";
import ComporEmail, { type Mensagem } from "./ComporEmail";
import ErroCampo from "./ErroCampo";
import { IconeAlerta } from "./icones";
import LiberarEnvio from "./LiberarEnvio";
import type { Agir } from "./MedicaoAtos";
import Pendencias from "./Pendencias";
import { CampoArquivo } from "./PlanilhaCarta";
import { fmtHora, hojeLocal } from "./tempo";

// Issue #627 (SINFRA): depois do boletim, os documentos assinados vao ao orgao na conversa da planilha/carta, pelo
// sistema ou registrados por fora. Toda regra mora no servidor (`assinados_envio`); a tela so' confere o tamanho do
// PDF antes de mandar (a mesma recusa do servidor) e o motivo do reenvio.

export type EnvioAssinados = { id: number; origem: "sistema" | "externo"; assinado_em: string; motivo: string | null;
  envio_id: number | null; vigente: boolean };
export type SituacaoAssinados = {
  disponivel: boolean; motivo: string | null; reajuste: { id: number; numero: number } | null;
  limite: number | null; limite_recusa: string | null; envios: EnvioAssinados[];
  reserva: { id: number; envio_reservado_em: string; reservado_por: string | null } | null;
};
type Anexo = { nome: string; tamanho: number; sha256: string; origem: string };
type Previa = { para: string[]; copia: string[]; assunto: string; corpo: string; anexos: Anexo[]; total: number;
  limite: number; pendencias: { codigo: string; mensagem: string }[]; reenvio: boolean };

const MIN_MOTIVO = 10;     // o servidor recusa menos que isso (assinados_envio.MIN_MOTIVO)

type Arquivos = { arquivo: File | null; reajuste: File | null; justificativa: File | null };

function Erro({ erro }: { erro?: string }) {
  return erro ? <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erro}</p> : null;
}

/** Os arquivos no formulario: a recusa de tamanho aparece antes de qualquer envio (a mesma frase do servidor). */
function acimaDoLimite(s: SituacaoAssinados, a: Arquivos): string | undefined {
  if (!s.limite) return undefined;
  return [a.arquivo, a.reajuste, a.justificativa].some(f => f && f.size > s.limite!) ? s.limite_recusa ?? undefined : undefined;
}

function formDosArquivos(a: Arquivos): FormData {
  const fd = new FormData();
  if (a.arquivo) fd.append("arquivo", a.arquivo);
  if (a.reajuste) fd.append("arquivo_reajuste", a.reajuste);
  if (a.justificativa) fd.append("justificativa", a.justificativa);
  return fd;
}

function CamposArquivos({ prefixo, s, a, setA, erroArquivo }: {
  prefixo: string; s: SituacaoAssinados; a: Arquivos; setA: (a: Arquivos) => void; erroArquivo?: string;
}) {
  return (
    <div className="form-inline">
      <CampoArquivo id={`${prefixo}-arquivo`} rotulo="PDF assinado da medição" aceita="application/pdf,.pdf" arquivo={a.arquivo}
        aoEscolher={f => setA({ ...a, arquivo: f })} erro={erroArquivo} />
      {s.reajuste && (
        <CampoArquivo id={`${prefixo}-reajuste`} rotulo="PDF assinado do reajuste (opcional)" aceita="application/pdf,.pdf"
          arquivo={a.reajuste} aoEscolher={f => setA({ ...a, reajuste: f })} />
      )}
      <CampoArquivo id={`${prefixo}-justificativa`} rotulo="Justificativa de atraso (opcional)" aceita="application/pdf,.pdf"
        arquivo={a.justificativa} aoEscolher={f => setA({ ...a, justificativa: f })} />
    </div>
  );
}

function Reservado({ s, aoLiberar }: { s: SituacaoAssinados; aoLiberar: () => void }) {
  return s.reserva ? <LiberarEnvio tabela="medicao_assinados_envios" id={s.reserva.id} aoLiberar={aoLiberar} /> : null;
}

/** "Enviar documentos assinados": os PDFs, a previa do e-mail (para, copia e assunto da planilha/carta) e o envio. */
export function FormEnviarAssinados({ medicaoId, s, salvando, agir, aoFechar, erro, aoLiberar }: {
  medicaoId: number; s: SituacaoAssinados; salvando: boolean; agir: Agir; aoFechar: () => void; erro?: string;
  aoLiberar: () => void;
}) {
  const [a, setA] = useState<Arquivos>({ arquivo: null, reajuste: null, justificativa: null });
  const [data, setData] = useState(hojeLocal());
  const [previa, setPrevia] = useState<Previa | null>(null);
  const [motivo, setMotivo] = useState("");
  const [tentou, setTentou] = useState(false);
  const [tentouMotivo, setTentouMotivo] = useState(false);
  const [erroPrevia, setErroPrevia] = useState("");
  const [abrindo, setAbrindo] = useState(false);
  const falta = !a.arquivo ? "Anexe o PDF assinado da medição." : acimaDoLimite(s, a);
  const faltaMotivo = previa?.reenvio && [...motivo.trim()].length < MIN_MOTIVO
    ? `Escreva o motivo do reenvio, com pelo menos ${MIN_MOTIVO} caracteres.` : undefined;

  async function abrirPrevia(ev: React.FormEvent) {
    ev.preventDefault();
    setTentou(true); setErroPrevia("");
    if (falta) { document.getElementById("assinados-arquivo")?.focus(); return; }
    setAbrindo(true);
    try {
      setPrevia(await apiForm<Previa>(`/api/medicoes/${medicaoId}/assinados/previa`, formDosArquivos(a)));
    } catch (e) {
      setErroPrevia(mensagemDeErro(e));
    } finally { setAbrindo(false); }
  }

  async function enviar(m: Mensagem) {
    if (!previa) return;
    const fd = formDosArquivos(a);
    fd.append("dados", JSON.stringify({ para: m.para, copia: m.copia, cco: m.cco, assunto: m.assunto, corpo: m.corpo,
      motivo: motivo.trim() || null, assinado_em: data || null,
      anexos_previa: previa.anexos.map(x => ({ nome: x.nome, tamanho: x.tamanho, sha256: x.sha256 })) }));
    const ok = await agir(() => apiForm(`/api/medicoes/${medicaoId}/assinados/enviar`, fd),
      `Documentos assinados enviados às ${fmtHora(new Date().toISOString())}.`);
    if (ok) aoFechar();
  }

  return (
    <div>
      <p className="painel__titulo">Enviar documentos assinados</p>
      <Erro erro={erroPrevia || erro} />
      <Reservado s={s} aoLiberar={aoLiberar} />
      {!previa ? (
        <form onSubmit={abrirPrevia} noValidate onKeyDown={ev => ev.key === "Escape" && aoFechar()}>
          <CamposArquivos prefixo="assinados" s={s} a={a} setA={setA} erroArquivo={tentou ? falta : undefined} />
          <div className="form-inline painel__rodape">
            <button type="submit" className="btn btn--primario" disabled={abrindo || salvando}>{abrindo ? "Abrindo…" : "Prévia do e-mail"}</button>
            <button type="button" className="btn" onClick={aoFechar}>Cancelar</button>
          </div>
        </form>
      ) : (
        <div aria-label="Prévia do e-mail">
          {previa.pendencias.length > 0 && <Pendencias itens={previa.pendencias} />}
          <ComporEmail ocupado={salvando} anexos={previa.anexos} rotuloEnviar="Enviar"
            bloqueado={previa.total > previa.limite}
            inicial={{ para: previa.para, copia: previa.copia, cco: [], assunto: previa.assunto, corpo: previa.corpo }}
            validarAntes={() => {
              setTentouMotivo(true);
              if (faltaMotivo) document.getElementById("assinados-motivo")?.focus();
              return !faltaMotivo;
            }}
            antes={
              <div className="form-inline">
                <div className="campo">
                  <label className="campo__rotulo" htmlFor="assinados-data">Data da assinatura</label>
                  <input id="assinados-data" type="date" name="assinado_em" className="entrada--media" max={hojeLocal()}
                    value={data} onChange={ev => setData(ev.target.value)} />
                </div>
                {previa.reenvio && (
                  <div className="campo">
                    <label className="campo__rotulo" htmlFor="assinados-motivo">Motivo do reenvio</label>
                    <input id="assinados-motivo" name="motivo" autoComplete="off" className="entrada--larga" maxLength={1000}
                      value={motivo} aria-invalid={tentouMotivo && faltaMotivo ? true : undefined}
                      aria-describedby={tentouMotivo && faltaMotivo ? "assinados-motivo-erro" : undefined}
                      onChange={ev => setMotivo(ev.target.value)} />
                    <ErroCampo id="assinados-motivo-erro" erro={tentouMotivo ? faltaMotivo : undefined} />
                  </div>
                )}
              </div>
            }
            aoEnviar={m => void enviar(m)} aoDescartar={() => setPrevia(null)} />
        </div>
      )}
    </div>
  );
}

/** "Registrar envio dos assinados por fora": a data, o PDF assinado, os opcionais e o .eml. */
export function FormAssinadosPorFora({ medicaoId, s, salvando, agir, aoFechar, erro, aoLiberar }: {
  medicaoId: number; s: SituacaoAssinados; salvando: boolean; agir: Agir; aoFechar: () => void; erro?: string;
  aoLiberar: () => void;
}) {
  const [a, setA] = useState<Arquivos>({ arquivo: null, reajuste: null, justificativa: null });
  const [data, setData] = useState(hojeLocal());
  const [eml, setEml] = useState<File | null>(null);
  const [tentou, setTentou] = useState(false);
  const hoje = hojeLocal();
  const faltaData = !data ? "Informe a data do envio." : data > hoje ? "A data do envio não pode ser futura." : undefined;
  const falta = !a.arquivo ? "Anexe o PDF assinado da medição." : acimaDoLimite(s, a);

  async function registrar(ev: React.FormEvent) {
    ev.preventDefault();
    setTentou(true);
    if (faltaData) { document.getElementById("assinados-fora-data")?.focus(); return; }
    if (falta) { document.getElementById("assinados-fora-arquivo")?.focus(); return; }
    const fd = formDosArquivos(a);
    fd.append("enviado_em", data);
    if (eml) fd.append("eml", eml);
    const ok = await agir(() => apiForm(`/api/medicoes/${medicaoId}/assinados/envio-externo`, fd),
      "Envio dos documentos assinados registrado.");
    if (ok) aoFechar();
  }

  return (
    <form onSubmit={registrar} noValidate onKeyDown={ev => ev.key === "Escape" && aoFechar()}>
      <p className="painel__titulo">Registrar envio dos assinados por fora</p>
      <Erro erro={erro} />
      <Reservado s={s} aoLiberar={aoLiberar} />
      <div className="form-inline">
        <div className="campo">
          <label className="campo__rotulo" htmlFor="assinados-fora-data">Data do envio</label>
          <input id="assinados-fora-data" type="date" name="enviado_em" className="entrada--media" max={hoje} value={data}
            aria-invalid={tentou && faltaData ? true : undefined}
            aria-describedby={tentou && faltaData ? "assinados-fora-data-erro" : undefined}
            onChange={ev => setData(ev.target.value)} />
          <ErroCampo id="assinados-fora-data-erro" erro={tentou ? faltaData : undefined} />
        </div>
        <div className="campo">
          <span className="campo__rotulo">E-mail (.eml)</span>
          <label className="btn btn--pequeno espelho__anexar">
            {eml ? eml.name : "Escolher"}
            <input type="file" accept=".eml,message/rfc822" className="espelho__arquivo" aria-label="E-mail do envio (.eml)"
              onChange={ev => { setEml(ev.currentTarget.files?.[0] ?? null); ev.currentTarget.value = ""; }} />
          </label>
        </div>
      </div>
      <CamposArquivos prefixo="assinados-fora" s={s} a={a} setA={setA} erroArquivo={tentou ? falta : undefined} />
      <div className="form-inline painel__rodape">
        <button type="submit" className="btn btn--primario" disabled={salvando}>{salvando ? "Registrando…" : "Registrar envio"}</button>
        <button type="button" className="btn" onClick={aoFechar}>Cancelar</button>
      </div>
    </form>
  );
}
