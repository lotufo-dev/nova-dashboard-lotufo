import { useCallback, useEffect, useState } from "react";
import CaixaAviso from "./CaixaAviso";
import { api, apiForm, baixarArquivo, mensagemDeErro } from "./api";
import { brl } from "./formato";
import { IconeAlerta } from "./icones";
import { trocarBusca, type Busca } from "./rota";
import { Link } from "./Link";
import Selo from "./Selo";
import { fmtDataPura } from "./tempo";
import "./notas.css";
import "./enviarNota.css";

// Notas a enviar (2026-10-09; plano docs/superpowers/plans/2026-10-09-notas-envio.md): as notas emitidas que
// ainda nao foram ao contratante, por grupo de orgao, e o painel do envio escolhido. As regras (o que vai junto,
// o que bloqueia) moram no servidor (GET /api/notas/a-enviar); a tela so' desenha.

export type ItemEnvio = {
  chave: string; rotulo: string; detalhe?: string | null; estado: "ok" | "aviso" | "falta" | "vencida";
  acao?: string | null; entidade_id?: number | null; competencia?: string | null; medicao_id?: number | null;
  frc_gerada?: number | null;   // issue #148: numero da FRC gerada (sem assinatura) vigente, no item da FRC
};
export type NotaEnvio = { numero: string; natureza: string; municipio?: string | null; arquivo?: string | null; valor_centavos: number };
export type Envio = {
  chave: string; contrato_id: number; obra: string; orgao: string; orgao_sub?: string | null; familia: string;
  grupo: string; a_pedido: boolean; medicao_ids: number[]; descricao: string; notas: NotaEnvio[];
  valor_centavos: number; emitida_em: string | null; dias: number | null; situacao: string;
  aviso: string | null; itens: ItemEnvio[]; protocolo_id: number | null;
  envio_reservado_em?: string | null;   // so' leitura: o e-mail do envio comecado pode estar saindo (so' entao ha' o que liberar)
  irmas?: Irma[];   // issue #172: SINFRA e Pref. VG: a medicao/reajuste irma com nota emitida fora deste envio
  // issue #188: onde o orgao junta, a outra metade ainda sem as notas segura o envio (situacao "esperando")
  espera?: { medicao_id: number; titulo: string; tipo: string; texto: string } | null;
};
export type Irma = { medicao_id: number; titulo: string; tipo: string };
export type ListaEnvios = { envios: Envio[]; contadores: Record<string, number> };

const GRUPOS = ["SINFRA", "MTPAR", "SES-MT", "Pref. VG", "Pref. Cuiabá"];

export function mensagem(e: unknown): string {
  return mensagemDeErro(e);
}

/** "NF 2322" / "NF 2322, 2323" (vazio sem nota) */
export function notasDe(e: Envio): string {
  return e.notas.length ? `NF ${e.notas.map(n => n.numero).join(", ")}` : "";
}

/** Orgaos que levam carta com numero de oficio (MTPAR, SES e prefeituras); a SINFRA (etapa nota) nao. */
export const pedeOficio = (familia: string) => familia !== "sinfra";

/** Inicia (ou reabre) o protocolo do envio com estas medicoes; devolve o id. O numero do oficio (so' onde o orgao
 *  pede carta) vem da janela da etapa 4. */
export async function iniciarEnvio(contratoId: number, medicaoIds: number[], numeroOficio?: string): Promise<number> {
  const corpo: Record<string, unknown> = { contrato_id: contratoId, medicao_ids: medicaoIds };
  if (numeroOficio !== undefined) corpo.numero_oficio = numeroOficio.trim();
  const r = await api<{ protocolo_id: number }>("/api/notas/envio/iniciar", { method: "POST",
    body: JSON.stringify(corpo) });
  return r.protocolo_id;
}

const ESTADO_ITEM: Record<ItemEnvio["estado"], string> = { ok: "Pronto", aviso: "Atenção", falta: "Falta", vencida: "Vencida" };

/** Check (pronto/concluido); serve tambem ao passo concluido do envio. */
export function IconeCheck() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3.5" strokeLinecap="round"
      strokeLinejoin="round" aria-hidden="true"><path d="M20 6L9 17l-5-5" /></svg>
  );
}

/** Estado do item: a forma (check verde, "!" ambar ou vermelho) e a palavra (leitor de tela e title). */
function EstadoItem({ estado }: { estado: ItemEnvio["estado"] }) {
  const e = ESTADO_ITEM[estado] ? estado : "aviso";
  return (
    <span className={`nota-estado nota-estado--${e}`} title={ESTADO_ITEM[e]}>
      {e === "ok" ? <IconeCheck /> : <span aria-hidden="true">!</span>}
      <span className="sr-only">{ESTADO_ITEM[e]}</span>
    </span>
  );
}

/** O que vai junto no e-mail: um item por documento, com o estado (forma + palavra) e o detalhe. A regularidade
 *  que falta ganha o "Anexar" (o mesmo upload da tela de Documentos); quem so' consulta (B-09) nao ve o "Anexar". */
export function ItensEnvio({ itens, aoMudar, podeEditar = true }: { itens: ItemEnvio[]; aoMudar: () => void; podeEditar?: boolean }) {
  const [erro, setErro] = useState("");
  const [ocupado, setOcupado] = useState(false);
  const [sobre, setSobre] = useState<string | null>(null);

  async function anexar(it: ItemEnvio, input: HTMLInputElement) {
    const f = input.files?.[0];
    input.value = "";
    if (!f) return;
    const fd = new FormData();
    fd.append("arquivo", f);
    fd.append("entidade_id", String(it.entidade_id));
    // sem "competencia": o servidor usa a impressa no PDF (o mes sugerido gravou o Integra 08/2026 como 07, 09/10/2026)
    setOcupado(true); setErro("");
    try { await apiForm("/api/documentos/regularidades", fd); aoMudar(); } catch (e) { setErro(mensagem(e)); } finally { setOcupado(false); }
  }

  // FRC assinada (2026-10-09): o PDF assinado no DocuSign entra como a fatura do consorcio da medicao
  async function anexarFrc(it: ItemEnvio, arquivos: FileList | null) {
    const f = Array.from(arquivos ?? []).find(x => x.type === "application/pdf" || x.name.toLowerCase().endsWith(".pdf"));
    if (!f || !it.medicao_id) return;
    const fd = new FormData();
    fd.append("arquivo", f);
    fd.append("tipo_doc", "fatura");
    setOcupado(true); setErro("");
    try { await apiForm(`/api/medicoes/${it.medicao_id}/notas`, fd); aoMudar(); } catch (e) { setErro(mensagem(e)); } finally { setOcupado(false); }
  }

  // issue #148: falta a assinada mas a FRC ja' foi gerada: o link para baixa-la fica no proprio item. Issue #169: a FRC
  // que ficou desatualizada depois de a tela carregar e' recusada pelo servidor; a mensagem aparece e a tela recarrega
  async function baixar(caminho: string) {
    setErro("");
    try { await baixarArquivo(caminho, "FRC.pdf"); } catch (e) { setErro(mensagem(e)); aoMudar(); }
  }
  const baixarFrc = (it: ItemEnvio) => it.frc_gerada && it.estado !== "ok" && it.medicao_id ? (
    <span className="nota-item__detalhe">
      <a className="link forte" href={`/api/medicoes/${it.medicao_id}/frc/pdf`}
        onClick={ev => { ev.preventDefault(); void baixar(`/api/medicoes/${it.medicao_id}/frc/pdf`); }}>
        Baixar a FRC gerada (nº {it.frc_gerada})
      </a>
    </span>
  ) : null;

  return (
    <>
      <ul className="nota-itens">
        {itens.map(it => {
          if (it.acao === "anexar_frc" && podeEditar) {
            return (
              <li key={it.chave}>
                <EstadoItem estado={it.estado} />
                <span className="nota-item nota-item--soltar">
                  <span className="nota-item__texto">
                    <span>{it.rotulo}</span>
                    {it.detalhe && <span className={`nota-item__detalhe nota-item__detalhe--${it.estado}`}>{it.detalhe}</span>}
                    {baixarFrc(it)}
                  </span>
                  <span className={`nota-complementares__soltar${sobre === it.chave ? " nota-complementares__soltar--sobre" : ""}`}
                    onDragOver={ev => { ev.preventDefault(); if (sobre !== it.chave) setSobre(it.chave); }}
                    onDragLeave={() => setSobre(null)}
                    onDrop={ev => { ev.preventDefault(); setSobre(null); if (!ocupado) void anexarFrc(it, ev.dataTransfer.files); }}>
                    <span>{ocupado ? "Anexando…" : "Arraste a FRC assinada aqui ou"}</span>
                    <label className="btn espelho__anexar nota-anexar">
                      Anexar
                      <input type="file" accept="application/pdf" className="espelho__arquivo" disabled={ocupado}
                        aria-label={`Anexar ${it.rotulo}`} onChange={ev => { const fs = ev.currentTarget.files; void anexarFrc(it, fs); ev.currentTarget.value = ""; }} />
                    </label>
                  </span>
                </span>
              </li>
            );
          }
          return (
            <li key={it.chave}>
              <EstadoItem estado={it.estado} />
              <span className="nota-item">
                <span className="nota-item__texto">
                  <span>{it.rotulo}</span>
                  {it.detalhe && <span className={`nota-item__detalhe nota-item__detalhe--${it.estado}`}>{it.detalhe}</span>}
                  {baixarFrc(it)}
                </span>
                {podeEditar && it.acao === "anexar_regularidade" && (it.entidade_id && it.competencia ? (
                  <label className="btn espelho__anexar nota-anexar">
                    {ocupado ? "Anexando…" : "Anexar"}
                    <input type="file" accept="application/pdf" className="espelho__arquivo" disabled={ocupado}
                      aria-label={`Anexar ${it.rotulo}`} onChange={ev => void anexar(it, ev.currentTarget)} />
                  </label>
                ) : <Link className="btn nota-anexar" para={{ tela: "documentos" }}>Anexar</Link>)}
              </span>
            </li>
          );
        })}
      </ul>
      {erro && <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erro}</p>}
    </>
  );
}

/** Aviso da pagina da medicao depois do registro por fora: a irma que foi junto e' dita pelo nome. */
export function avisoPorFora(juntas: Irma[], qtdEnvio: number): string {
  const estas = qtdEnvio > 1 ? "as notas deste envio" : "esta nota";
  if (juntas.length) return `Envio registrado: ${estas} e a do ${juntas.map(i => i.titulo).join(", ")} foram para Aguardando pagamento.`;
  return qtdEnvio > 1 ? "Envio registrado: as notas foram para Aguardando pagamento." : "Envio registrado: a nota foi para Aguardando pagamento.";
}

/* ------------------------------------------------------ certidoes, com a validade de cada uma */

export type ItemCertidao = { entidade_id: number; entidade: string | null; tipo: string; chave?: string | null; situacao: string;
  validade: string | null; dias: number | null; competencia?: string | null };

/** A natureza que decide quais documentos o orgao exige deste envio: reajuste so' quando o envio e' so' de reajuste. */
export const naturezaDoEnvio = (e: Envio) => (e.notas.length > 0 && e.notas.every(n => n.natureza === "reajuste") ? "reajuste" : "execucao");

/** Os documentos exigidos da obra para o envio, com a validade de cada um (o servidor decide o que vale). */
export function useCertidoes(contratoId: number, natureza: string): ItemCertidao[] | null {
  const [itens, setItens] = useState<ItemCertidao[] | null>(null);
  useEffect(() => {
    let vivo = true;
    setItens(null);
    if (!contratoId) return;
    api<{ itens: ItemCertidao[] }>(`/api/contratos/${contratoId}/checklist-protocolo?natureza=${natureza}`)
      .then(r => { if (vivo) setItens(r.itens.filter(i => i.situacao !== "nao_se_aplica" && i.chave !== "regularidade")); })
      .catch(() => { if (vivo) setItens(null); });
    return () => { vivo = false; };
  }, [contratoId, natureza]);
  return itens;
}

function textoCertidao(i: ItemCertidao): string | null {
  if (i.situacao === "pendente") return "sem validade hoje";
  // em dia, o ponto verde basta: a data so' aparece quando esta' para vencer
  return i.situacao === "vencendo" && i.validade ? `vence em ${fmtDataPura(i.validade.slice(0, 10))}` : null;
}

/** Uma linha por certidao: o ponto (verde, ambar, vermelho) e a validade so' da que vence, por empresa quando ha mais de uma. O
 *  caminho para emitir a nova so' aparece com certidao vencida. */
export function ListaCertidoes({ itens }: { itens: ItemCertidao[] }) {
  const empresas = [...new Map(itens.map(i => [i.entidade_id, i.entidade] as const)).entries()];
  const vencida = itens.some(i => i.situacao === "pendente");
  return (
    <div className="certidoes-bloco">
      <p className="med-sub">Certidões</p>
      {empresas.map(([eid, nome]) => (
        <div key={eid}>
          {empresas.length > 1 && <p className="campo__nota certidoes__empresa">{nome ?? "—"}</p>}
          <ul className="certidoes">
            {itens.filter(i => i.entidade_id === eid).map(i => (
              <li key={`${i.entidade_id}-${i.tipo}`}>
                <span className={`ponto${i.situacao === "pendente" ? " ponto--acao" : i.situacao === "vencendo" ? " ponto--atencao" : ""}`} aria-hidden="true" />
                <span>{i.tipo}</span>{textoCertidao(i) && <> <small>· {textoCertidao(i)}</small></>}
              </li>
            ))}
          </ul>
        </div>
      ))}
      {vencida && <p className="campo__nota certidoes__nota">Certidão vencida: emita a nova em{" "}
        <Link para={{ tela: "documentos" }}>Documentos</Link>.</p>}
    </div>
  );
}

/* --------------------------------------------------------------- a aba Enviar nota */

// Medicoes › Enviar nota (#157, opcao B, aprovada em 16/10/2026): a lista a esquerda e, a direita, a nota escolhida
// com o que vai junto e o que falta. A aba so' mostra e leva a etapa 4 da pagina da medicao.

type Situacao = "pronto" | "pendencia";
type FiltroId = "todas" | "prontas" | "pendencia";
const FILTROS: { id: FiltroId; rotulo: string }[] = [
  { id: "todas", rotulo: "Todas" }, { id: "prontas", rotulo: "Prontas" }, { id: "pendencia", rotulo: "Com pendência" },
];

type Resumo = { situacao: Situacao; selo: string; nivel: "" | "selo--ok" | "selo--atencao" | "selo--acao";
  motivo: string; tom: "neutro" | "atencao" | "bloqueio" };

/** O selo do cartao e a frase do rodape. So' o bloqueio apaga o botao; a frase (`motivo`) so' existe quando o envio
 *  esta' bloqueado ou esperando a outra metade: o que falta ja' esta' no selo e na lista. */
export function resumoDe(e: Envio): Resumo {
  if (e.situacao === "bloqueado") {
    const venc = e.itens.find(i => i.estado === "vencida");
    return { situacao: "pendencia", selo: venc ? "Certidão vencida" : "Bloqueado", nivel: "selo--acao",
      motivo: e.aviso ? (/^bloque/i.test(e.aviso) ? e.aviso : `Envio bloqueado: ${e.aviso}`) : "Envio bloqueado.", tom: "bloqueio" };
  }
  if (e.situacao === "esperando") {
    const qual = e.espera?.tipo === "execucao" ? "a medição" : "o reajuste";
    return { situacao: "pendencia", selo: `Esperando ${qual}`, nivel: "selo--atencao",
      motivo: `Esperando as notas d${qual}.`, tom: "atencao" };
  }
  // certidao a menos de 15 dias do vencimento so' avisa: o envio segue pronto, com o aviso ao lado
  const aviso = e.itens.find(i => i.estado === "aviso");
  const falta = e.itens.find(i => i.estado === "falta");
  if (!falta && aviso) return { situacao: "pronto", selo: "Pronto", nivel: "selo--ok", motivo: "", tom: "atencao" };
  if (falta) {
    const rotulo = /^[A-ZÀ-Ý]{2}/.test(falta.rotulo) ? falta.rotulo : falta.rotulo.charAt(0).toLowerCase() + falta.rotulo.slice(1);
    return { situacao: "pendencia", selo: falta.estado === "falta" ? `Falta ${rotulo}` : falta.rotulo, nivel: "selo--atencao",
      motivo: "", tom: "atencao" };
  }
  return { situacao: "pronto", selo: "Pronto", nivel: "selo--ok", motivo: "", tom: "neutro" };
}

/** O que vai junto, so' para ler: cada item com o estado e, onde falta algo, o link para resolver. */
function ItensLeitura({ e, certidoes }: { e: Envio; certidoes: ItemCertidao[] | null }) {
  const [erroBaixar, setErroBaixar] = useState("");
  // issue #169: a FRC desatualizada e' recusada pelo servidor; a mensagem aparece aqui em vez do JSON do erro
  async function baixar(caminho: string) {
    setErroBaixar("");
    try { await baixarArquivo(caminho, "FRC.pdf"); } catch (x) { setErroBaixar(mensagem(x)); }
  }
  const aqui = { tela: "medicao" as const, obra: e.contrato_id, id: e.medicao_ids[0] };
  const itens = certidoes && certidoes.length > 0 ? e.itens.filter(i => !i.chave.startsWith("certidoes")) : e.itens;
  return (
    <ul className="nota-itens">
      {itens.map(it => (
        <li key={it.chave}>
          <EstadoItem estado={it.estado} />
          <span className="nota-item">
            <span className="nota-item__texto">
              <span>{it.rotulo}</span>
              {it.detalhe && <span className={`nota-item__detalhe nota-item__detalhe--${it.estado}`}>{it.detalhe}</span>}
              {it.acao === "anexar_frc" && it.estado !== "ok" && it.frc_gerada && it.medicao_id && (
                <span className="nota-item__detalhe">
                  <a className="link forte" href={`/api/medicoes/${it.medicao_id}/frc/pdf`}
                    onClick={ev => { ev.preventDefault(); void baixar(`/api/medicoes/${it.medicao_id}/frc/pdf`); }}>Baixar a FRC gerada (nº {it.frc_gerada})</a>
                </span>
              )}
              {it.acao === "anexar_frc" && it.estado !== "ok" && (
                <span className="nota-item__detalhe"><Link className="link forte" para={aqui} secao="etapa-4">Anexar na etapa 4</Link></span>
              )}
              {it.acao === "anexar_regularidade" && (
                <span className="nota-item__detalhe"><Link className="link forte" para={{ tela: "documentos" }}>Anexar em Documentos</Link></span>
              )}
            </span>
          </span>
        </li>
      ))}
      {erroBaixar && <li><p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erroBaixar}</p></li>}
    </ul>
  );
}

function Painel({ e, podeEditar }: { e: Envio; podeEditar: boolean }) {
  const r = resumoDe(e);
  const certidoes = useCertidoes(e.contrato_id, naturezaDoEnvio(e));
  const aqui = { tela: "medicao" as const, obra: e.contrato_id, id: e.medicao_ids[0] };
  return (
    <section className="nota-painel" id="painel-nota" aria-labelledby="titulo-envio">
      <div className="nota-painel__bloco">
        <h2 className="nota-painel__titulo" id="titulo-envio">{e.obra} · {e.descricao}
          {e.a_pedido && <>{" "}<Selo>A pedido do órgão</Selo></>}</h2>
        <p className="nota-painel__meta">{[e.orgao, e.orgao_sub, e.emitida_em ? fmtDataPura(e.emitida_em) : ""].filter(Boolean).join(" · ")}</p>
      </div>
      <div className="nota-painel__bloco">
        <p className="nota-painel__valor nota-mono">{brl(e.valor_centavos)}</p>
      </div>
      <div className="nota-painel__junto">
        <span className="nota-painel__sub">O que vai junto</span>
        <ItensLeitura e={e} certidoes={certidoes} />
        {certidoes && certidoes.length > 0 && <ListaCertidoes itens={certidoes} />}
      </div>
      {/* issue #188: a medicao e o reajuste vao no mesmo e-mail; sem as notas da outra metade, nao ha' o que iniciar */}
      {e.situacao === "esperando" && (
        <CaixaAviso nivel="atencao">
          {r.motivo.replace(/\.$/, "")}; para enviar sem {e.espera?.tipo === "execucao" ? "ela" : "ele"}, abra a{" "}
          <Link para={aqui} secao="etapa-4">etapa 4 da medição</Link>.
        </CaixaAviso>
      )}
      <div className="en-rodape">
        {r.motivo && e.situacao !== "esperando" && <p className={`en-motivo en-motivo--${r.tom}`}>{r.motivo}</p>}
        <Link className="en-abrir" para={aqui}>Abrir a medição</Link>
        {/* B-09 (10/10/2026): quem so' consulta ve o que vai no envio, sem o botao */}
        {podeEditar && e.situacao !== "esperando" && (e.situacao === "bloqueado"
          ? <button type="button" className="btn btn--primario" disabled>Enviar a nota →</button>
          : <Link className="btn btn--primario" para={aqui} secao="etapa-4">Enviar a nota →</Link>)}
      </div>
    </section>
  );
}

export default function NotasAEnviar({ busca, podeEditar }: { busca: Busca; podeEditar: boolean }) {
  const [dados, setDados] = useState<ListaEnvios | null>(null);
  const [erro, setErro] = useState("");
  const [sel, setSel] = useState<string | null>(null);

  const carregar = useCallback(async () => {
    try { setDados(await api<ListaEnvios>("/api/notas/a-enviar")); setErro(""); } catch (e) { setErro(mensagem(e)); }
  }, []);
  useEffect(() => { void carregar(); }, [carregar]);

  const grupo = busca.grupo ?? "";
  const q = busca.q ?? "";
  const filtro = (FILTROS.find(f => f.id === busca.situacao)?.id ?? "todas") as FiltroId;
  const termo = q.trim().toLocaleLowerCase("pt-BR");
  const envios = dados?.envios ?? [];
  const doFiltro = (e: Envio, f: FiltroId) => f === "todas" || (f === "prontas" ? resumoDe(e).situacao === "pronto" : resumoDe(e).situacao === "pendencia");
  const filtrados = envios.filter(e => (!grupo || e.grupo === grupo) && doFiltro(e, filtro)
    && (!termo || [e.obra, e.descricao, e.orgao, ...e.notas.map(n => n.numero)].join(" ").toLocaleLowerCase("pt-BR").includes(termo)));
  const atual = filtrados.find(e => e.chave === sel) ?? filtrados[0] ?? null;
  const grupos = [...GRUPOS, ...[...new Set(envios.map(e => e.grupo))].filter(g => !GRUPOS.includes(g))];
  const comFiltro = (mudanca: Record<string, string>): Busca => {
    const novo: Busca = { ...(q ? { q } : {}), ...(grupo ? { grupo } : {}), ...(filtro !== "todas" ? { situacao: filtro } : {}), ...mudanca };
    for (const k of Object.keys(novo)) if (novo[k] === "" || novo[k] === "todas") delete novo[k];
    return novo;
  };

  if (!dados) {
    return erro
      ? <div className="form-inline"><p className="erro" role="alert"><IconeAlerta className="icone icone--p" />Não foi possível ler as notas a enviar: {erro}</p>
          <button type="button" className="btn btn--pequeno" onClick={() => void carregar()}>Tentar de novo</button></div>
      : <p className="campo__nota">Carregando as notas…</p>;
  }

  if (envios.length === 0) {
    return (
      <section className="cartao nota-vazia notas-v3" aria-label="Notas a enviar">
        <div className="vazio">
          <span className="nota-vazia__icone" aria-hidden="true">
            <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"
              strokeLinecap="round" strokeLinejoin="round"><path d="M20 6L9 17l-5-5" /></svg>
          </span>
          <p className="vazio__titulo">Nenhuma nota a enviar.</p>
        </div>
      </section>
    );
  }

  return (
    <div className="pilha notas-v3 en">
      <div className="nota-colunas">
        <div className="pilha">
          <div className="en-lista">
            <div className="nota-busca-caixa">
              <svg className="nota-busca__lupa" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                strokeWidth="2" strokeLinecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="M21 21l-4.3-4.3" /></svg>
              <input type="search" className="nota-busca" placeholder="Buscar nota ou obra…" aria-label="Buscar nota ou obra"
                autoComplete="off" value={q} onChange={ev => trocarBusca({ q: ev.target.value || null })} />
            </div>
            <div className="en-filtros">
              <div className="nota-pilulas" role="group" aria-label="Situação">
                {FILTROS.map(f => (
                  <Link key={f.id} className="nota-pilula" para={{ tela: "medicoes", aba: "enviar-nota" }} busca={comFiltro({ situacao: f.id })}
                    aria-current={filtro === f.id ? "true" : undefined}>
                    {f.rotulo}
                  </Link>
                ))}
              </div>
              <select className="en-orgao" aria-label="Órgão" value={grupo} onChange={ev => trocarBusca({ grupo: ev.target.value || null })}>
                <option value="">Todos os órgãos</option>
                {grupos.filter(g => envios.some(e => e.grupo === g)).map(g => <option key={g} value={g}>{g}</option>)}
              </select>
            </div>
            {filtrados.length === 0 && (
              <div className="vazio vazio--curto">
                <p className="vazio__titulo">Nenhuma nota com esses filtros.</p>
                <p><Link para={{ tela: "medicoes", aba: "enviar-nota" }}>Limpar os filtros</Link></p>
              </div>
            )}
            {grupos.map(g => {
              const itens = filtrados.filter(e => e.grupo === g);
              if (itens.length === 0) return null;
              return (
                <section key={g} className="pilha nota-grupo" aria-label={g}>
                  <h2 className="nota-grupo__titulo">{g}{itens.some(e => e.a_pedido) && <>{" "}<Selo>A pedido do órgão</Selo></>}</h2>
                  {itens.map(e => {
                    const r = resumoDe(e);
                    return (
                      <button key={e.chave} type="button" className="nota-cartao" aria-pressed={atual?.chave === e.chave}
                        onClick={() => {
                          setSel(e.chave);
                          if (window.matchMedia?.("(max-width: 1100px)").matches) document.getElementById("painel-nota")?.scrollIntoView?.({ behavior: "smooth", block: "start" });
                        }}>
                        <span className="nota-cartao__texto">
                          <span className="nota-cartao__obra">{e.obra}</span>
                          <span className="nota-cartao__desc">{[e.descricao, notasDe(e)].filter(Boolean).join(" · ")}</span>
                        </span>
                        <span className="en-direita">
                          <span className={`nota-cartao__valor nota-mono${e.a_pedido ? " nota-cartao__valor--espera" : ""}`}>{brl(e.valor_centavos)}</span>
                          <Selo classe={r.nivel}>{r.selo}</Selo>
                        </span>
                      </button>
                    );
                  })}
                </section>
              );
            })}
          </div>
        </div>
        <aside className="nota-lateral" aria-label="Envio selecionado">
          {atual && <Painel key={atual.chave} e={atual} podeEditar={podeEditar} />}
        </aside>
      </div>
    </div>
  );
}
