import { useState } from "react";
import { ApiErro, apiForm, mensagemDeErro } from "./api";
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
  limite: number | null; limite_recusa: string | null; teto_registro?: number | null; limite_email?: number;
  envios: EnvioAssinados[];
  reserva: { id: number; envio_reservado_em: string; reservado_por: string | null } | null;
};
type Anexo = { nome: string; tamanho: number; sha256: string; origem: string };
type Previa = { para: string[]; copia: string[]; assunto: string; corpo: string; anexos: Anexo[]; total: number;
  limite: number; pendencias: { codigo: string; mensagem: string }[]; reenvio: boolean; anteriores?: number };

const MIN_MOTIVO = 10;     // o servidor recusa menos que isso (assinados_envio.MIN_MOTIVO)
const MB = 1024 * 1024;

type Arquivos = { arquivo: File | null; reajuste: File | null; justificativa: File | null };
/** Issue #637: no par com os dois atos disponiveis, o envio so' do reajuste vai pela medicao de reajuste. */
export type SoReajuste = { medicaoId: number; s: SituacaoAssinados };

/** O que vai no pedido: no envio so' do reajuste, o PDF dele e' o documento da medicao de reajuste. */
function doPedido(a: Arquivos, so: boolean): Arquivos {
  return so ? { arquivo: a.reajuste, reajuste: null, justificativa: a.justificativa } : a;
}

/** MB com uma casa, arredondado para cima: acima do limite nunca sai o mesmo numero dos dois lados (issue #637). */
function mbAcima(bytes: number): string {
  return String(Math.ceil(bytes / MB * 10) / 10).replace(".", ",");
}

function EscolhaSoReajuste({ so, setSo }: { so: boolean; setSo: (v: boolean) => void }) {
  return (
    <label className="campo--linha">
      <input type="checkbox" checked={so} onChange={ev => setSo(ev.target.checked)} />
      Só o PDF do reajuste
    </label>
  );
}

function Erro({ erro }: { erro?: string }) {
  return erro ? <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erro}</p> : null;
}

/** Os arquivos no formulario: a recusa de tamanho aparece antes de qualquer envio (a mesma frase do servidor). */
function acimaDoLimite(s: SituacaoAssinados, a: Arquivos): string | undefined {
  if (!s.limite) return undefined;
  return [a.arquivo, a.reajuste, a.justificativa].some(f => f && f.size > s.limite!) ? s.limite_recusa ?? undefined : undefined;
}

// a mesma frase da recusa do servidor (limites.MENSAGEM_ASSINADOS) para o pedido acima do teto
export const ACIMA_DO_TETO = "Os arquivos somam mais de 44 MB, o limite de um envio: deixe o .eml de fora";

/** Revisao da PR #635: o pedido com todos os arquivos passa do teto do servidor? A tela diz antes de mandar. */
function acimaDoTeto(s: SituacaoAssinados, arquivos: (File | null)[]): string | undefined {
  if (!s.teto_registro) return undefined;
  const soma = arquivos.reduce((t, f) => t + (f?.size ?? 0), 0);
  return soma > s.teto_registro ? ACIMA_DO_TETO : undefined;
}

/** No envio pelo sistema (sem .eml) vale o limite do e-mail, com a frase da pendencia de tamanho da previa. */
function acimaDoEmail(s: SituacaoAssinados, a: Arquivos): string | undefined {
  const limite = s.limite_email;
  if (!limite) return undefined;
  const soma = [a.arquivo, a.reajuste, a.justificativa].reduce((t, f) => t + (f?.size ?? 0), 0);
  return soma > limite ? `Anexos somam ${mbAcima(soma)} MB, acima do limite do e-mail (${Math.floor(limite / MB)} MB)` : undefined;
}

function formDosArquivos(a: Arquivos): FormData {
  const fd = new FormData();
  if (a.arquivo) fd.append("arquivo", a.arquivo);
  if (a.reajuste) fd.append("arquivo_reajuste", a.reajuste);
  if (a.justificativa) fd.append("justificativa", a.justificativa);
  return fd;
}

function CamposArquivos({ prefixo, s, a, setA, erroArquivo, so = false }: {
  prefixo: string; s: SituacaoAssinados; a: Arquivos; setA: (a: Arquivos) => void; erroArquivo?: string; so?: boolean;
}) {
  return (
    <div className="form-inline">
      {so ? (
        <CampoArquivo id={`${prefixo}-reajuste`} rotulo="PDF assinado do reajuste" aceita="application/pdf,.pdf"
          arquivo={a.reajuste} aoEscolher={f => setA({ ...a, reajuste: f })} erro={erroArquivo} />
      ) : (
        <CampoArquivo id={`${prefixo}-arquivo`} rotulo="PDF assinado da medição" aceita="application/pdf,.pdf" arquivo={a.arquivo}
          aoEscolher={f => setA({ ...a, arquivo: f })} erro={erroArquivo} />
      )}
      {!so && s.reajuste && (
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
export function FormEnviarAssinados({ medicaoId: idDoAto, s: sDoAto, salvando, agir, aoFechar, erro, aoLiberar, soReajuste }: {
  medicaoId: number; s: SituacaoAssinados; salvando: boolean; agir: Agir; aoFechar: () => void; erro?: string;
  aoLiberar: () => void; soReajuste?: SoReajuste;
}) {
  const [todos, setA] = useState<Arquivos>({ arquivo: null, reajuste: null, justificativa: null });
  const [escolheuSo, setSo] = useState(false);
  const so = !!soReajuste && escolheuSo;
  const medicaoId = so ? soReajuste.medicaoId : idDoAto;
  const s = so ? soReajuste.s : sDoAto;
  const a = doPedido(todos, so);
  const [data, setData] = useState(hojeLocal());
  const [previa, setPrevia] = useState<Previa | null>(null);
  const [motivo, setMotivo] = useState("");
  const [tentou, setTentou] = useState(false);
  const [tentouMotivo, setTentouMotivo] = useState(false);
  const [erroPrevia, setErroPrevia] = useState("");
  const [abrindo, setAbrindo] = useState(false);
  const falta = !a.arquivo ? (so ? "Anexe o PDF assinado do reajuste." : "Anexe o PDF assinado da medição.")
    : acimaDoLimite(s, a) ?? acimaDoEmail(s, a);
  const faltaMotivo = previa?.reenvio && [...motivo.trim()].length < MIN_MOTIVO
    ? `Escreva o motivo do reenvio, com pelo menos ${MIN_MOTIVO} caracteres.` : undefined;

  async function abrirPrevia(ev: React.FormEvent) {
    ev.preventDefault();
    setTentou(true); setErroPrevia("");
    if (falta) { document.getElementById(so ? "assinados-reajuste" : "assinados-arquivo")?.focus(); return; }
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
      motivo: motivo.trim() || null, assinado_em: data || null, anteriores: previa.anteriores ?? null,
      anexos_previa: previa.anexos.map(x => ({ nome: x.nome, tamanho: x.tamanho, sha256: x.sha256 })) }));
    const ok = await agir(async () => {
      try {
        return await apiForm(`/api/medicoes/${medicaoId}/assinados/enviar`, fd);
      } catch (e) {
        // outro envio terminou depois da previa (revisao da PR #635): a previa abre de novo, agora com o motivo
        if (e instanceof ApiErro && e.status === 409 && e.corpo?.codigo === "ENVIO_CONCLUIDO_NO_MEIO") {
          setTentouMotivo(false);
          let nova: Previa | null = null;
          try { nova = await apiForm<Previa>(`/api/medicoes/${medicaoId}/assinados/previa`, formDosArquivos(a)); }
          catch { /* sem a previa nova, vale a mensagem do servidor (abrir a previa de novo) */ }
          setPrevia(nova);
          // issue #637: a previa ja' esta' refeita na tela; a mensagem diz o que falta, nao manda abrir de novo
          if (nova) throw new ApiErro(409, "Outro envio dos documentos assinados terminou depois da sua prévia. "
            + (nova.reenvio ? "A prévia foi refeita: escreva o motivo do reenvio." : "A prévia foi refeita: confira e envie de novo."),
            e.corpo);
        }
        throw e;
      }
    }, `Documentos assinados enviados às ${fmtHora(new Date().toISOString())}.`);
    if (ok) aoFechar();
  }

  return (
    <div>
      <p className="painel__titulo">Enviar documentos assinados</p>
      <Erro erro={erroPrevia || erro} />
      <Reservado s={s} aoLiberar={aoLiberar} />
      {!previa ? (
        <form onSubmit={abrirPrevia} noValidate onKeyDown={ev => ev.key === "Escape" && aoFechar()}>
          {soReajuste && <EscolhaSoReajuste so={so} setSo={setSo} />}
          <CamposArquivos prefixo="assinados" s={s} a={todos} setA={setA} so={so} erroArquivo={tentou ? falta : undefined} />
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
export function FormAssinadosPorFora({ medicaoId: idDoAto, s: sDoAto, salvando, agir, aoFechar, erro, aoLiberar, soReajuste }: {
  medicaoId: number; s: SituacaoAssinados; salvando: boolean; agir: Agir; aoFechar: () => void; erro?: string;
  aoLiberar: () => void; soReajuste?: SoReajuste;
}) {
  const [todos, setA] = useState<Arquivos>({ arquivo: null, reajuste: null, justificativa: null });
  const [escolheuSo, setSo] = useState(false);
  const so = !!soReajuste && escolheuSo;
  const medicaoId = so ? soReajuste.medicaoId : idDoAto;
  const s = so ? soReajuste.s : sDoAto;
  const a = doPedido(todos, so);
  const [data, setData] = useState(hojeLocal());
  const [eml, setEml] = useState<File | null>(null);
  const [tentou, setTentou] = useState(false);
  const hoje = hojeLocal();
  const faltaData = !data ? "Informe a data do envio." : data > hoje ? "A data do envio não pode ser futura." : undefined;
  const falta = !a.arquivo ? (so ? "Anexe o PDF assinado do reajuste." : "Anexe o PDF assinado da medição.")
    : acimaDoLimite(s, a) ?? acimaDoTeto(s, [a.arquivo, a.reajuste, a.justificativa, eml]);

  async function registrar(ev: React.FormEvent) {
    ev.preventDefault();
    setTentou(true);
    if (faltaData) { document.getElementById("assinados-fora-data")?.focus(); return; }
    if (falta) { document.getElementById(so ? "assinados-fora-reajuste" : "assinados-fora-arquivo")?.focus(); return; }
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
      {soReajuste && <EscolhaSoReajuste so={so} setSo={setSo} />}
      <CamposArquivos prefixo="assinados-fora" s={s} a={todos} setA={setA} so={so} erroArquivo={tentou ? falta : undefined} />
      <div className="form-inline painel__rodape">
        <button type="submit" className="btn btn--primario" disabled={salvando}>{salvando ? "Registrando…" : "Registrar envio"}</button>
        <button type="button" className="btn" onClick={aoFechar}>Cancelar</button>
      </div>
    </form>
  );
}
