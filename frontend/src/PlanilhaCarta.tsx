import { useEffect, useId, useRef, useState } from "react";
import { api, apiForm, ApiErro, mensagemDeErro } from "./api";
import CaixaAviso from "./CaixaAviso";
import CampoCompetencia from "./CampoCompetencia";
import CampoReajuste, { type ValorReajuste } from "./CampoReajuste";
import CampoValor from "./CampoValor";
import Checklist, { type ItemChecklist } from "./Checklist";
import ComporEmail, { type Mensagem } from "./ComporEmail";
import ErroCampo from "./ErroCampo";
import { brl, digitosParaBrl, fmtTamanho } from "./formato";
import { IconeAlerta, IconeSeta } from "./icones";
import { IconeCheck } from "./NotasAEnviar";
import LiberarEnvio, { envioReservado, type Reserva } from "./LiberarEnvio";
import Pendencias from "./Pendencias";
import Selo from "./Selo";
import { fmtData, fmtDataPura, fmtHora, hojeLocal } from "./tempo";
import "./planilhaCarta.css";

// Planilha/carta da medicao (issue #289; spec 2026-10-20 §2.1, "Quem clica", passos 1 e 2). O cartao "Nova
// planilha/carta" e' o primeiro passo da medicao: nº e periodo sugeridos, valor pedido, oficio e planilha arrastados,
// acumulado anterior e saldo, e os avisos de periodo enquanto a pessoa digita. Registrada, a medicao mostra o cartao
// da planilha/carta: as versoes, "Enviar para protocolo" (o mesmo compositor de e-mail da nota), "Registrar envio por
// fora", o nº do SIGA e a revisao (Rev01, Rev02...) com motivo. Toda regra mora no servidor (`medicao_planilhas`,
// `planilha_envio`); a tela so' mostra o que ele devolve.

export type TipoPlanilha = "execucao" | "projeto";
type Sugestao = {
  tipo: TipoPlanilha; numero: number; numero_orgao: number | null; competencia: string;
  periodo_inicio: string; periodo_fim: string; vigente_centavos: number;
  acumulado_anterior_centavos: number; saldo_centavos: number | null;
};
export type Registrada = { medicao_id: number; versao: number; estado: string; avisos: string[] };

/** "12.345,67" -> 1234567 (centavos inteiros, sem conta em ponto flutuante); vazio -> null. */
export function centavosDoTexto(valor: string): number | null {
  const d = valor.replace(/\D/g, "");
  return d ? Number(d) : null;
}

/** O mes civil da competencia "AAAA-MM": ["AAAA-MM-01", "AAAA-MM-<ultimo dia>"]. */
export function mesCivil(comp: string): [string, string] {
  const m = /^(\d{4})-(\d{2})$/.exec(comp);
  if (!m) return ["", ""];
  const ultimo = new Date(Date.UTC(Number(m[1]), Number(m[2]), 0)).getUTCDate();
  return [`${comp}-01`, `${comp}-${String(ultimo).padStart(2, "0")}`];
}

/** "Original" na 1a versao; Rev01, Rev02... nas seguintes (o mesmo sufixo que o servidor poe no nome do arquivo). */
export function rotuloVersao(versao: number): string {
  return versao <= 1 ? "Original" : `Rev${String(versao - 1).padStart(2, "0")}`;
}

/** Arquivo arrastado ou escolhido: uma area de soltar com o botao de escolher. */
function CampoArquivo({ id, rotulo, aceita, arquivo, aoEscolher, erro }: {
  id: string; rotulo: string; aceita: string; arquivo: File | null; aoEscolher: (f: File | null) => void; erro?: string;
}) {
  const [sobre, setSobre] = useState(false);
  return (
    <div className="campo">
      <span className="campo__rotulo" id={`${id}-rotulo`}>{rotulo}</span>
      <div className={`planilha__soltar${sobre ? " planilha__soltar--sobre" : ""}`}
        onDragOver={ev => { ev.preventDefault(); if (!sobre) setSobre(true); }}
        onDragLeave={() => setSobre(false)}
        onDrop={ev => { ev.preventDefault(); setSobre(false); aoEscolher(ev.dataTransfer.files?.[0] ?? null); }}>
        {arquivo
          ? <span className="planilha__arquivo" title={arquivo.name}>{arquivo.name} <span className="num">{fmtTamanho(arquivo.size)}</span></span>
          : <span className="planilha__arquivo planilha__arquivo--vazio">—</span>}
        <label className="btn btn--pequeno espelho__anexar">
          {arquivo ? "Trocar" : "Escolher"}
          <input id={id} type="file" accept={aceita} className="espelho__arquivo" aria-label={rotulo}
            aria-invalid={erro ? true : undefined} aria-describedby={erro ? `${id}-erro` : undefined}
            onChange={ev => { aoEscolher(ev.currentTarget.files?.[0] ?? null); ev.currentTarget.value = ""; }} />
        </label>
      </div>
      <ErroCampo id={`${id}-erro`} erro={erro} />
    </div>
  );
}

type FormPedido = { competencia: string; inicio: string; fim: string; valor: string; oficio: File | null; planilha: File | null };

/** Os campos comuns ao registro e a' revisao: periodo, valor pedido, oficio e planilha. */
function CamposDoPedido({ prefixo, form, setForm, comCompetencia, tentou }: {
  prefixo: string; form: FormPedido; setForm: (f: FormPedido) => void; comCompetencia: boolean; tentou: boolean;
}) {
  return (
    <>
      <div className="form-inline">
        {comCompetencia && (
          <div className="campo">
            <label className="campo__rotulo" htmlFor={`${prefixo}-competencia`}>Competência</label>
            <CampoCompetencia id={`${prefixo}-competencia`} name="competencia" className="entrada--media" value={form.competencia}
              onChange={v => {
                // trocar a competencia volta o periodo ao mes inteiro dela, como no espelho
                const [ini, fim] = mesCivil(v);
                setForm({ ...form, competencia: v, inicio: ini || form.inicio, fim: fim || form.fim });
              }} />
          </div>
        )}
        <div className="campo">
          <label className="campo__rotulo" htmlFor={`${prefixo}-inicio`}>Período: de</label>
          <input id={`${prefixo}-inicio`} name="periodo_inicio" type="date" className="entrada--media" required autoComplete="off"
            value={form.inicio} onChange={e => setForm({ ...form, inicio: e.target.value })} />
        </div>
        <div className="campo">
          <label className="campo__rotulo" htmlFor={`${prefixo}-fim`}>até</label>
          <input id={`${prefixo}-fim`} name="periodo_fim" type="date" className="entrada--media" required autoComplete="off"
            value={form.fim} onChange={e => setForm({ ...form, fim: e.target.value })} />
        </div>
        <div className="campo">
          <label className="campo__rotulo" htmlFor={`${prefixo}-valor`}>Valor pedido</label>
          <CampoValor id={`${prefixo}-valor`} name="valor" value={form.valor} required onChange={v => setForm({ ...form, valor: v })} />
        </div>
      </div>
      <div className="planilha__arquivos">
        <CampoArquivo id={`${prefixo}-oficio`} rotulo="Ofício assinado (PDF)" aceita="application/pdf,.pdf" arquivo={form.oficio}
          aoEscolher={f => setForm({ ...form, oficio: f })} erro={tentou && !form.oficio ? "Anexe o ofício assinado." : undefined} />
        <CampoArquivo id={`${prefixo}-planilha`} rotulo="Planilha (.xlsx ou PDF)" aceita=".xlsx,.pdf,application/pdf" arquivo={form.planilha}
          aoEscolher={f => setForm({ ...form, planilha: f })} erro={tentou && !form.planilha ? "Anexe a planilha." : undefined} />
      </div>
    </>
  );
}

/** O que o servidor confere enquanto a pessoa digita: os avisos de periodo (sobreposto, pulando dias, competencia
 *  anterior) e o acumulado anterior e o saldo DO Nº digitado. `numero` diz de qual nº e' a leitura. */
type Conferencia = { numero: string; avisos: string[]; acumulado_anterior_centavos: number | null; saldo_centavos: number | null };

function useConferencia(contratoId: number, tipo: string, numero: string, competencia: string, inicio: string): Conferencia | null {
  const [conf, setConf] = useState<Conferencia | null>(null);
  useEffect(() => {
    if (!/^\d{1,3}$/.test(numero) || !/^\d{4}-\d{2}$/.test(competencia) || !/^\d{4}-\d{2}-\d{2}$/.test(inicio)) {
      setConf(null);
      return;
    }
    let vivo = true;
    const t = setTimeout(() => {
      const q = new URLSearchParams({ tipo, numero, competencia, periodo_inicio: inicio });
      api<Omit<Conferencia, "numero">>(`/api/contratos/${contratoId}/planilhas/avisos?${q}`)
        .then(r => { if (vivo) setConf({ numero, avisos: r.avisos ?? [], acumulado_anterior_centavos: r.acumulado_anterior_centavos ?? null,
          saldo_centavos: r.saldo_centavos ?? null }); })
        .catch(() => { if (vivo) setConf(null); });       // aviso nao impede: sem a leitura, nada aparece
    }, 300);
    return () => { vivo = false; clearTimeout(t); };
  }, [contratoId, tipo, numero, competencia, inicio]);
  return conf;
}

/** Acumulado anterior e saldo do nº que esta' no formulario: o da conferencia desse nº, senao o da sugestao quando o nº
 *  e' o sugerido; de outro nº, "—" (o acumulado depende do nº). */
export function saldoDoNumero(numero: string, sug: { numero: number; acumulado_anterior_centavos: number; saldo_centavos: number | null },
  conf: Conferencia | null): { acumulado: number | null; saldo: number | null } {
  if (conf && conf.numero === numero) return { acumulado: conf.acumulado_anterior_centavos, saldo: conf.saldo_centavos };
  if (String(sug.numero) === numero) return { acumulado: sug.acumulado_anterior_centavos, saldo: sug.saldo_centavos };
  return { acumulado: null, saldo: null };
}

/** Passo 1: "Nova planilha/carta". `inicial`: a medicao prevista que este registro promove (nº e competencia dela). */
export function NovaPlanilhaCarta({ contratoId, tipo = "execucao", inicial, aoRegistrar }: {
  contratoId: number; tipo?: TipoPlanilha; inicial?: { numero?: number; competencia?: string };
  aoRegistrar: (r: Registrada) => void;
}) {
  const [sug, setSug] = useState<Sugestao | null>(null);
  const [erroSug, setErroSug] = useState("");
  const [numero, setNumero] = useState("");
  const [numeroOrgao, setNumeroOrgao] = useState("");
  const [form, setForm] = useState<FormPedido>({ competencia: "", inicio: "", fim: "", valor: "", oficio: null, planilha: null });
  const [tentou, setTentou] = useState(false);
  const [ocupado, setOcupado] = useState(false);
  const [erro, setErro] = useState("");
  // issue #276: o reajuste da mesma competencia, opcional, so' na planilha/carta de execucao
  const [reaj, setReaj] = useState<ValorReajuste>({ valor: "", dataBase: "" });
  const inicialNumero = inicial?.numero, inicialCompetencia = inicial?.competencia;

  useEffect(() => {
    let vivo = true;
    api<Sugestao>(`/api/contratos/${contratoId}/planilhas/sugestao?tipo=${tipo}`)
      .then(s => {
        if (!vivo) return;
        setSug(s);
        const competencia = inicialCompetencia ?? s.competencia;
        // o periodo sugerido vale para a competencia sugerida; a prevista de outra competencia abre no mes dela
        const [ini, fim] = competencia === s.competencia ? [s.periodo_inicio, s.periodo_fim] : mesCivil(competencia);
        setNumero(String(inicialNumero ?? s.numero));
        // o nº do orgao sugerido e' o do nº sugerido; na prevista fica vazio e o servidor mantem o que ela ja' tem
        setNumeroOrgao(s.numero_orgao !== null && (inicialNumero ?? s.numero) === s.numero ? String(s.numero_orgao) : "");
        setForm(f => ({ ...f, competencia, inicio: ini, fim }));
      })
      .catch(e => { if (vivo) setErroSug(mensagemDeErro(e)); });
    return () => { vivo = false; };
  }, [contratoId, tipo, inicialNumero, inicialCompetencia]);

  const conf = useConferencia(contratoId, tipo, numero, form.competencia, form.inicio);
  const avisos = conf?.avisos ?? [];
  const pedido = centavosDoTexto(form.valor);

  async function registrar(ev: React.FormEvent) {
    ev.preventDefault();
    setTentou(true);
    if (!form.oficio || !form.planilha) return;
    setOcupado(true); setErro("");
    const fd = new FormData();
    fd.append("numero", numero);
    fd.append("tipo", tipo);
    fd.append("competencia", form.competencia);
    fd.append("periodo_inicio", form.inicio);
    fd.append("periodo_fim", form.fim);
    fd.append("valor", form.valor);
    if (numeroOrgao.trim()) fd.append("numero_orgao", numeroOrgao.trim());
    if (tipo === "execucao" && reaj.valor) {
      fd.append("reajuste_valor", reaj.valor);
      if (reaj.dataBase) fd.append("reajuste_data_base", reaj.dataBase);
    }
    fd.append("oficio", form.oficio);
    fd.append("planilha", form.planilha);
    try {
      aoRegistrar(await apiForm<Registrada>(`/api/contratos/${contratoId}/planilhas`, fd));
    } catch (e) { setErro(mensagemDeErro(e)); } finally { setOcupado(false); }
  }

  if (erroSug) return <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />Não foi possível abrir a planilha/carta: {erroSug}</p>;
  if (!sug) return <p role="status">Carregando…</p>;
  const saldo = saldoDoNumero(numero, sug, conf);

  return (
    <form className="cartao__corpo pilha" onSubmit={registrar} aria-label="Nova planilha/carta">
      <p className="painel__titulo">Nova planilha/carta</p>
      {erro && <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erro}</p>}
      <div className="form-inline">
        <div className="campo">
          <label className="campo__rotulo" htmlFor="pl-numero">Nº da medição</label>
          <input id="pl-numero" name="numero" autoComplete="off" spellCheck={false} className="entrada--curta entrada--num num" required
            inputMode="numeric" pattern="[0-9]{1,3}" value={numero} onChange={e => setNumero(e.target.value)} />
        </div>
        <div className="campo">
          <label className="campo__rotulo" htmlFor="pl-numero-orgao">Nº no órgão</label>
          <input id="pl-numero-orgao" name="numero_orgao" autoComplete="off" spellCheck={false} className="entrada--curta entrada--num num"
            inputMode="numeric" pattern="[0-9]{1,4}" value={numeroOrgao} onChange={e => setNumeroOrgao(e.target.value)} />
        </div>
      </div>
      <CamposDoPedido prefixo="pl" form={form} setForm={setForm} comCompetencia tentou={tentou} />
      {tipo === "execucao" && (
        <CampoReajuste contratoId={contratoId} competencia={form.competencia} numero={numero} prefixo="pl" valor={reaj} aoMudar={setReaj} />
      )}
      <dl className="planilha__saldo">
        <div><dt>Acumulado anterior</dt><dd className="num">{brl(saldo.acumulado)}</dd></div>
        <div><dt>Saldo</dt><dd className="num">{brl(saldo.saldo)}</dd></div>
        {saldo.saldo !== null && pedido !== null && (
          <div><dt>Saldo depois do pedido</dt>
            <dd className={`num${saldo.saldo - pedido < 0 ? " planilha__negativo" : ""}`}>{brl(saldo.saldo - pedido)}</dd></div>
        )}
      </dl>
      {avisos.length > 0 && (
        <div role="status">{avisos.map(a => <CaixaAviso nivel="atencao" key={a}>{a}</CaixaAviso>)}</div>
      )}
      <div className="painel__rodape form-inline">
        <button type="submit" className="btn btn--primario" disabled={ocupado}>{ocupado ? "Registrando…" : "Registrar planilha/carta"}</button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------------------------------- cartao da medicao

export type Versao = { id: number; versao: number; periodo_inicio: string; periodo_fim: string; valor_pedido_centavos: number;
  acumulado_anterior_centavos: number; motivo: string | null; criado_em: string; usuario: string | null };
type Peca = { id: number; tipo: string; nome: string; tamanho: number };
/** Um envio da planilha/carta: pelo sistema (`enviado_em` instante UTC) ou por fora (a data informada, sem hora). */
export type EnvioPlanilha = { planilha_id: number | null; versao: number; numero_oficio: string | null; enviado_em: string;
  usuario: string | null; origem?: "sistema" | "externo" };

/** O dia do envio em Cuiaba: o instante do sistema vira o dia local (21h em Cuiaba nao e' o dia seguinte). */
export function dataDoEnvio(e: EnvioPlanilha): string {
  return /^\d{4}-\d{2}-\d{2}$/.test(e.enviado_em) ? fmtDataPura(e.enviado_em) : fmtData(e.enviado_em);
}

type SituacaoEnvio = {
  disponivel: boolean; motivo: string | null;
  envios: EnvioPlanilha[];
  reserva: { id: number; envio_reservado_em: string | null; reservado_por: string | null } | null;
  pecas: Peca[]; pecas_do_orgao: { tipo: string; rotulo: string; exigida: boolean; no_oficio: boolean }[];
};
export type DetalhePlanilha = {
  id: number; contrato_id: number; numero: number; tipo: string; competencia: string; estado: string; planilha_enviada_em: string | null;
  planilha_envio_origem: string | null; planilhas: Versao[]; envio_planilha: SituacaoEnvio;
  planilha_siga: { data: string | null; numero: string | null } | null;
  /** issue #490: a leitura por grupo mais nova da planilha; `aviso` so' quando ela foi recusada */
  leitura_planilha?: { situacao: string; aviso: string | null } | null;
  /** issue #508: o medidor do pacote do envio (bytes) e o limite do e-mail */
  pacote_planilha?: { carta: number | null; planilha: number | null; pecas: number; total: number; limite: number } | null;
  dias_uteis_no_orgao?: number | null;
};
type Previa = { numero_oficio: string; versao: number; para: string[]; copia: string[]; assunto: string; corpo: string;
  anexos: { nome: string; tamanho: number; sha256: string }[]; total: number; limite: number;
  pendencias: { codigo: string; mensagem: string }[] };

const ESTADOS_COM_ACAO = ["planilha_gerada", "planilha_enviada"];
const MIN_JUSTIFICATIVA = 10;        // o servidor recusa menos que isso (planilha_envio.MIN_JUSTIFICATIVA)

type Painel = null | "oficio" | "fora" | "revisao";

/** "Enviada em dd/mm" no selo do cartao: o dia do primeiro envio (pelo sistema ou por fora). */
export function seloDoEnvio(enviadaEm: string | null): string | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(enviadaEm ?? "");
  return m ? `Enviada em ${m[3]}/${m[2]}` : null;
}

/** Revisao registrada e ainda nao enviada: em `planilha_enviada`, a vigente acima da ultima enviada (pelo sistema ou
 *  por fora; sem envio listado, a 1a conta como enviada, como em planilha_envio._ultima_enviada). */
export function revisaoPendente(d: DetalhePlanilha): boolean {
  if (d.estado !== "planilha_enviada" || d.planilhas.length === 0) return false;
  const vigente = Math.max(...d.planilhas.map(v => v.versao));
  const enviada = Math.max(1, ...d.envio_planilha.envios.map(e => e.versao));
  return vigente > enviada;
}

function itensDasPecas(s: SituacaoEnvio): ItemChecklist[] {
  return s.pecas_do_orgao.map(p => {
    const arquivos = s.pecas.filter(x => x.tipo === p.tipo).map(x => ({ id: x.id, nome: x.nome, tamanho: x.tamanho }));
    // a peca que vai no oficio assinado nao se anexa (o servidor recusa); a anexada antes da marca nao vai no e-mail,
    // mas ainda se remove
    return { chave: p.tipo, rotulo: p.rotulo, arquivos, aceita: ".xlsx,application/pdf", semAnexar: p.no_oficio,
      situacao: p.no_oficio ? "no_oficio" : arquivos.length > 0 ? "anexada" : p.exigida ? "falta" : "opcional" };
  });
}

/** O cartao da planilha/carta na etapa 1 da medicao. `podeEditar` falso (diretoria): so' le, sem nenhum botao. */
// `estado`: o da medicao na pagina; quando ele muda por outra etapa (a pagina recarregou), o cartao le de novo
// `aoRevisaoPendente`: avisa a pagina se ha' revisao registrada e nao enviada (o espelho espera por ela, PR #382)
// `aoEnvioReservado`: avisa a pagina se o envio da planilha/carta esta' saindo pelo sistema (ou preso): o espelho da
// so' gerada espera por ele (gate Sol, PR #528)
export function CartaoPlanilha({ medicaoId, estado, podeEditar, aoMudar, aoRevisaoPendente, aoEnvioReservado }: {
  medicaoId: number; estado?: string; podeEditar: boolean; aoMudar: () => void;
  aoRevisaoPendente?: (pendente: boolean | null) => void;
  aoEnvioReservado?: (reservado: boolean) => void;
}) {
  const base = useId();
  const [d, setD] = useState<DetalhePlanilha | null>(null);
  const [erro, setErro] = useState("");
  const [feito, setFeito] = useState("");
  const [ocupado, setOcupado] = useState(false);
  const [painel, setPainel] = useState<Painel>(null);
  const [reserva, setReserva] = useState<Reserva | null>(null);
  const [numeroOficio, setNumeroOficio] = useState("");
  const [previa, setPrevia] = useState<Previa | null>(null);
  const [justificativa, setJustificativa] = useState("");
  const [tentouJust, setTentouJust] = useState(false);

  const avisarPendente = useRef(aoRevisaoPendente);
  const avisarReserva = useRef(aoEnvioReservado);
  useEffect(() => { avisarPendente.current = aoRevisaoPendente; avisarReserva.current = aoEnvioReservado; });
  function avisar(x: DetalhePlanilha) {
    avisarPendente.current?.(revisaoPendente(x));
    avisarReserva.current?.(!!x.envio_planilha?.reserva);
  }
  async function carregar() {
    const x = await api<DetalhePlanilha>(`/api/medicoes/${medicaoId}`);
    setD(x);
    // toda releitura certa avisa a pagina, para ela sair de uma falha anterior mesmo sem o pendente mudar
    avisar(x);
  }
  useEffect(() => {
    let vivo = true;
    api<DetalhePlanilha>(`/api/medicoes/${medicaoId}`).then(x => { if (vivo) { setD(x); avisar(x); } })
      .catch(e => { if (vivo) { setErro(mensagemDeErro(e)); avisarPendente.current?.(null); } });
    return () => { vivo = false; };
  }, [medicaoId, estado]);
  const pendente = d ? revisaoPendente(d) : null;
  useEffect(() => { if (pendente !== null) avisarPendente.current?.(pendente); }, [pendente]);

  /** Executa, recarrega o cartao e avisa a pagina. Devolve se gravou. */
  async function agir(f: () => Promise<unknown>, mensagemFeito: string): Promise<boolean> {
    setOcupado(true); setErro(""); setFeito(""); setReserva(null);
    try {
      await f();
      setFeito(mensagemFeito);
      await carregar().catch(() => avisarPendente.current?.(null));
      aoMudar();
      return true;
    } catch (e) {
      setErro(mensagemDeErro(e));
      if (envioReservado(e)) setReserva(e.corpo);
      return false;
    } finally { setOcupado(false); }
  }

  async function abrirPrevia(ev?: React.FormEvent) {
    ev?.preventDefault();
    setOcupado(true); setErro(""); setFeito("");
    try {
      const pv = await api<Previa>(`/api/medicoes/${medicaoId}/envio-planilha/previa`, { method: "POST",
        body: JSON.stringify({ numero_oficio: numeroOficio.trim() }) });
      setPrevia(pv); setJustificativa(""); setTentouJust(false);
    } catch (e) { setErro(mensagemDeErro(e)); } finally { setOcupado(false); }
  }

  async function enviar(m: Mensagem) {
    if (!previa) return;
    setOcupado(true); setErro(""); setFeito(""); setReserva(null);
    try {
      await api(`/api/medicoes/${medicaoId}/envio-planilha`, { method: "POST", body: JSON.stringify({
        numero_oficio: previa.numero_oficio, para: m.para, copia: m.copia, cco: m.cco, assunto: m.assunto, corpo: m.corpo,
        justificativa: justificativa.trim() || null,
        anexos_previa: previa.anexos.map(a => ({ nome: a.nome, tamanho: a.tamanho, sha256: a.sha256 })) }) });
      setPrevia(null); setPainel(null);
      setFeito(`Planilha/carta enviada às ${fmtHora(new Date().toISOString())}.`);
      await carregar().catch(() => avisarPendente.current?.(null));
      aoMudar();
    } catch (e) {
      setErro(mensagemDeErro(e));
      if (envioReservado(e)) setReserva(e.corpo);
      // os anexos mudaram desde a previa: ela abre de novo, com o que vai agora
      if (e instanceof ApiErro && e.status === 422 && e.corpo?.codigo === "ANEXOS_MUDARAM") {
        try {
          setPrevia(await api<Previa>(`/api/medicoes/${medicaoId}/envio-planilha/previa`, { method: "POST",
            body: JSON.stringify({ numero_oficio: previa.numero_oficio }) }));
        } catch { setPrevia(null); }
      }
    } finally { setOcupado(false); }
  }

  if (erro && !d) return <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />Não foi possível abrir a planilha/carta: {erro}</p>;
  if (!d) return null;
  // medicao que nao nasceu da planilha/carta (historico, espelho direto): o cartao nao aparece
  if (d.planilhas.length === 0) return null;

  const s = d.envio_planilha;
  const editavel = podeEditar && ESTADOS_COM_ACAO.includes(d.estado);
  const gerada = d.estado === "planilha_gerada";
  // depois do envio, so' a revisao ainda nao enviada sai (pelo sistema ou por fora)
  const podeEnviar = editavel && s.disponivel;
  const podeFora = editavel && (gerada || s.disponivel);
  const selo = seloDoEnvio(d.planilha_enviada_em);
  const precisaJustificativa = (previa?.pendencias.length ?? 0) > 0;
  const faltaJustificativa = precisaJustificativa && justificativa.trim().length < MIN_JUSTIFICATIVA;
  const erroJustificativa = tentouJust && faltaJustificativa
    ? `Escreva a justificativa, com pelo menos ${MIN_JUSTIFICATIVA} caracteres.` : undefined;
  const itens = itensDasPecas(s);
  const vigente = d.planilhas[d.planilhas.length - 1];

  function anexarPeca(tipo: string, input: HTMLInputElement) {
    const f = input.files?.[0];
    input.value = "";
    if (!f) return;
    const fd = new FormData();
    fd.append("tipo", tipo);
    fd.append("arquivo", f);
    void agir(() => apiForm(`/api/medicoes/${medicaoId}/envio-planilha/pecas`, fd), "Peça anexada.");
  }

  // issue #508: o pacote do envio (carta e planilha, documentos que o orgao exige, o que falta, medidor) a' esquerda
  // e o e-mail ao orgao a' direita; as versoes anteriores e os envios ficam no pacote, para nao perder historico
  const pacote = d.pacote_planilha ?? null;
  // "N de M": a carta, a planilha e as pecas que o orgao EXIGE (a opcional anexada nao muda a conta)
  const exigidas = new Set(s.pecas_do_orgao.filter(p => p.exigida).map(p => p.tipo));
  const pedidas = itens.filter(i => exigidas.has(i.chave));
  const prontas = pedidas.filter(i => i.situacao === "anexada" || i.situacao === "no_oficio");
  const ultimoOficio = s.envios.filter(e => e.numero_oficio).at(-1)?.numero_oficio ?? null;
  const acima = pacote ? pacote.total > pacote.limite : false;

  return (
    <div className="med-duas planilha-passo" id="planilha-carta">
      <section className="cartao med-painel pacote" aria-labelledby={`${base}-titulo`}>
        <h3 className="med-painel__titulo" id={`${base}-titulo`}>
          Pacote do envio
          {editavel && <span className="med-contagem">{2 + prontas.length} de {2 + pedidas.length}</span>}
          {selo ? <Selo classe="selo--ok">{selo}</Selo> : <Selo>Gerada</Selo>}
          {d.planilha_envio_origem === "externo" && <Selo>Fora do sistema</Selo>}
        </h3>
        {d.leitura_planilha?.aviso && <CaixaAviso nivel="atencao">{d.leitura_planilha.aviso}</CaixaAviso>}

        <div>
          <p className="med-grupo">Carta e planilha</p>
          {vigente && (
            <ul className="pacote-itens" aria-label="Carta e planilha">
              <li>
                <span className="pacote__ok" aria-hidden="true"><IconeCheck /></span>
                <a className="link pacote__nome" href={`/api/medicoes/${medicaoId}/planilhas/${vigente.id}/oficio`}>
                  Carta{ultimoOficio ? ` ${ultimoOficio}` : ""} assinada</a>
                {pacote?.carta != null && <span className="pacote__tam">{fmtTamanho(pacote.carta)}</span>}
              </li>
              <li>
                <span className="pacote__ok" aria-hidden="true"><IconeCheck /></span>
                <a className="link pacote__nome" href={`/api/medicoes/${medicaoId}/planilhas/${vigente.id}/planilha`}>
                  Planilha da {d.numero}ª medição · {rotuloVersao(vigente.versao).toLowerCase()}</a>
                {pacote?.planilha != null && <span className="pacote__tam">{fmtTamanho(pacote.planilha)}</span>}
              </li>
            </ul>
          )}
        </div>

        {itens.length > 0 && (editavel || itens.some(i => i.arquivos.length > 0)) && (
          <div>
            <p className="med-grupo">Documentos que o órgão exige</p>
            <Checklist itens={itens} legenda="Peças da planilha/carta" editavel={editavel && (podeEnviar || gerada)} ocupado={ocupado}
              aoAnexar={anexarPeca}
              aoRemover={id => void agir(() => api(`/api/medicoes/${medicaoId}/envio-planilha/pecas/${id}/remover`, { method: "POST", body: "{}" }), "Peça removida.")} />
          </div>
        )}

        {editavel && pacote && (
          <div className={`medidor${acima ? " medidor--acima" : ""}`}>
            <div className="medidor__barra" role="meter" aria-label="Tamanho dos anexos" aria-valuemin={0} aria-valuemax={pacote.limite}
              aria-valuenow={Math.min(pacote.total, pacote.limite)} aria-valuetext={`${fmtTamanho(pacote.total)} de ${fmtTamanho(pacote.limite)}`}>
              <div className="medidor__cheio" style={{ width: `${Math.min(100, (pacote.total / pacote.limite) * 100)}%` }} />
            </div>
            <span className="medidor__texto">{fmtTamanho(pacote.total)} de {fmtTamanho(pacote.limite)}</span>
          </div>
        )}

        {d.planilhas.length > 1 && (
          <table className="tabela tabela--densa" aria-label="Versões da planilha/carta">
            <thead><tr><th scope="col">Versão</th><th scope="col">Período</th><th scope="col" className="num">Pedido</th>
              <th scope="col">Motivo</th><th scope="col">Arquivos</th></tr></thead>
            <tbody>
              {d.planilhas.map(v => (
                <tr key={v.id}>
                  <td>{rotuloVersao(v.versao)}</td>
                  <td className="num">{fmtDataPura(v.periodo_inicio)} a {fmtDataPura(v.periodo_fim)}</td>
                  <td className="num">{brl(v.valor_pedido_centavos)}</td>
                  <td>{v.motivo ?? "—"}</td>
                  <td>
                    <a className="link" href={`/api/medicoes/${medicaoId}/planilhas/${v.id}/oficio`}>Ofício</a>{" "}
                    <a className="link" href={`/api/medicoes/${medicaoId}/planilhas/${v.id}/planilha`}>Planilha</a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="cartao med-painel email-orgao" aria-labelledby={`${base}-email`}>
        <h3 className="med-painel__titulo" id={`${base}-email`}>E-mail ao órgão</h3>
        {erro && <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erro}</p>}
        {feito && <p className="feito" role="status" aria-live="polite">{feito}</p>}
        {/* envio reservado e nao concluido (em andamento ou preso): a liberacao, como no protocolo e no pleito */}
        {podeEditar && s.reserva && (
          <div>
            <CaixaAviso nivel="atencao">Envio iniciado e não concluído{s.reserva.reservado_por ? ` por ${s.reserva.reservado_por}` : ""}.</CaixaAviso>
            <LiberarEnvio tabela="medicao_planilha_envios" id={s.reserva.id} reserva={reserva}
              aoLiberar={() => { setErro(""); setReserva(null); void carregar().catch(() => {}); }} />
          </div>
        )}

        {s.envios.length > 0 && (
          <ul className="lista-simples">
            {s.envios.map(e => (
              <li key={`${e.origem}-${e.versao}`}>{rotuloVersao(e.versao)} enviada em <span className="num">{dataDoEnvio(e)}</span>
                {e.numero_oficio ? ` · ofício ${e.numero_oficio}` : ""}{e.origem === "externo" && <> <Selo>Fora do sistema</Selo></>}</li>
            ))}
          </ul>
        )}

        {d.planilha_enviada_em && <NumeroSiga medicaoId={medicaoId} atual={d.planilha_siga?.numero ?? null}
          podeEditar={podeEditar} aoGravar={() => { void carregar().catch(() => {}); aoMudar(); }} />}

        {editavel && painel === null && (
          <>
            {podeEnviar && <button type="button" className="btn btn--primario btn--envio-orgao" disabled={ocupado} onClick={() => setPainel("oficio")}>Enviar ao órgão</button>}
            {/* o porque de nao enviar pelo sistema, so' antes do 1o envio (depois dele o selo ja' diz) */}
            {gerada && !s.disponivel && s.motivo && <p className="campo__nota">{s.motivo}</p>}
            <ul className="acoes-lista">
              {podeFora && <li><button type="button" disabled={ocupado} onClick={() => setPainel("fora")}>Já enviei por fora<IconeSeta className="icone" /></button></li>}
              <li><button type="button" disabled={ocupado} onClick={() => setPainel("revisao")}>Registrar revisão da planilha<IconeSeta className="icone" /></button></li>
            </ul>
          </>
        )}

        {editavel && painel === "oficio" && !previa && (
          <form className="painel-inline" onSubmit={abrirPrevia} aria-label="Enviar ao órgão">
            <div className="form-inline">
              <div className="campo">
                <label className="campo__rotulo" htmlFor={`${base}-oficio`}>Nº do ofício (CT)</label>
                <input id={`${base}-oficio`} name="numero_oficio" autoComplete="off" spellCheck={false} className="entrada--16ch" required
                  maxLength={40} autoFocus placeholder="Ex.: 301…" value={numeroOficio} onChange={e => setNumeroOficio(e.target.value)} />
              </div>
              <button type="submit" className="btn btn--primario" disabled={ocupado || !numeroOficio.trim()}>{ocupado ? "Abrindo…" : "Prévia do e-mail"}</button>
              <button type="button" className="btn" onClick={() => setPainel(null)}>Voltar</button>
            </div>
          </form>
        )}
        {editavel && painel === "oficio" && previa && (
          <div aria-label="Prévia do e-mail">
            {previa.pendencias.length > 0 && <Pendencias itens={previa.pendencias} />}
            <ComporEmail key={`${previa.versao}-${previa.numero_oficio}`} ocupado={ocupado} anexos={previa.anexos}
              rotuloEnviar="Enviar ao órgão"
              validarAntes={() => {
                setTentouJust(true);
                if (faltaJustificativa) document.getElementById(`${base}-just`)?.focus();
                return !faltaJustificativa;
              }}
              inicial={{ para: previa.para, copia: previa.copia, cco: [], assunto: previa.assunto, corpo: previa.corpo }}
              antes={precisaJustificativa && (
                <div className="campo ol-pendencias">
                  <label className="campo__rotulo" htmlFor={`${base}-just`}>Justificativa (obrigatória para enviar com pendência)</label>
                  <textarea id={`${base}-just`} name="justificativa" autoComplete="off" rows={2} maxLength={2000} value={justificativa}
                    aria-invalid={erroJustificativa ? true : undefined} aria-describedby={erroJustificativa ? `${base}-just-erro` : undefined}
                    onChange={e => setJustificativa(e.target.value)} />
                  <ErroCampo id={`${base}-just-erro`} erro={erroJustificativa} />
                </div>
              )}
              aoEnviar={m => void enviar(m)} aoDescartar={() => { setPrevia(null); setPainel(null); }} />
            {previa.total > previa.limite && (
              <p className="notas__diverge">Anexos passam do limite: {fmtTamanho(previa.total)} de {fmtTamanho(previa.limite)} permitidos.</p>
            )}
          </div>
        )}
        {editavel && painel === "fora" && (
          <EnvioPorFora medicaoId={medicaoId} ocupado={ocupado} aoFechar={() => setPainel(null)}
            aoRegistrar={async fd => {
              const ok = await agir(() => apiForm(`/api/medicoes/${medicaoId}/planilhas/envio-externo`, fd), "Envio por fora registrado.");
              if (ok) setPainel(null);
            }} />
        )}
        {editavel && painel === "revisao" && vigente && (
          <Revisao medicao={d} vigente={vigente} ocupado={ocupado} aoFechar={() => setPainel(null)}
            aoRegistrar={async fd => {
              const ok = await agir(() => apiForm(`/api/medicoes/${medicaoId}/planilhas`, fd), "Revisão registrada.");
              if (ok) setPainel(null);
            }} />
        )}
      </section>
    </div>
  );
}

/** "Registrar envio por fora": data, meio e nº do protocolo; o .eml e' opcional. */
function EnvioPorFora({ medicaoId, ocupado, aoFechar, aoRegistrar }: {
  medicaoId: number; ocupado: boolean; aoFechar: () => void; aoRegistrar: (fd: FormData) => Promise<void>;
}) {
  const [data, setData] = useState(hojeLocal());
  const [meio, setMeio] = useState("");
  const [protocolo, setProtocolo] = useState("");
  const [eml, setEml] = useState<File | null>(null);
  function registrar(ev: React.FormEvent) {
    ev.preventDefault();
    const fd = new FormData();
    fd.append("enviado_em", data);
    fd.append("meio", meio.trim());
    if (protocolo.trim()) fd.append("numero_protocolo", protocolo.trim());
    if (eml) fd.append("eml", eml);
    void aoRegistrar(fd);
  }
  return (
    <form className="painel-inline" onSubmit={registrar} aria-label="Registrar envio por fora"
      onKeyDown={ev => ev.key === "Escape" && aoFechar()}>
      <p className="painel__titulo">Registrar envio por fora</p>
      <div className="form-inline">
        <div className="campo">
          <label className="campo__rotulo" htmlFor={`fora-data-${medicaoId}`}>Data do envio</label>
          <input id={`fora-data-${medicaoId}`} type="date" name="enviado_em" className="entrada--media" required max={hojeLocal()}
            value={data} onChange={e => setData(e.target.value)} />
        </div>
        <div className="campo">
          <label className="campo__rotulo" htmlFor={`fora-meio-${medicaoId}`}>Meio</label>
          <input id={`fora-meio-${medicaoId}`} name="meio" autoComplete="off" className="entrada--media" required maxLength={200}
            placeholder="Ex.: Outlook, balcão…" value={meio} onChange={e => setMeio(e.target.value)} />
        </div>
        <div className="campo">
          <label className="campo__rotulo" htmlFor={`fora-protocolo-${medicaoId}`}>Nº do protocolo</label>
          <input id={`fora-protocolo-${medicaoId}`} name="numero_protocolo" autoComplete="off" spellCheck={false} className="entrada--media"
            maxLength={100} value={protocolo} onChange={e => setProtocolo(e.target.value)} />
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
      <div className="form-inline">
        <button type="submit" className="btn btn--primario" disabled={ocupado || !meio.trim() || !data}>{ocupado ? "Registrando…" : "Registrar envio"}</button>
        <button type="button" className="btn" onClick={aoFechar}>Voltar</button>
      </div>
    </form>
  );
}

/** Revisao da planilha/carta (Rev01, Rev02...): versao nova, com motivo obrigatorio. */
export function Revisao({ medicao, vigente, ocupado, aoFechar, aoRegistrar }: {
  medicao: DetalhePlanilha; vigente: Versao; ocupado: boolean; aoFechar: () => void; aoRegistrar: (fd: FormData) => Promise<void>;
}) {
  const [motivo, setMotivo] = useState("");
  const [form, setForm] = useState<FormPedido>({ competencia: "", inicio: vigente.periodo_inicio, fim: vigente.periodo_fim,
    valor: digitosParaBrl(String(vigente.valor_pedido_centavos)), oficio: null, planilha: null });
  const [tentou, setTentou] = useState(false);
  const proxima = rotuloVersao(vigente.versao + 1);
  // os mesmos avisos de periodo da 1a versao, enquanto a pessoa muda o periodo da revisao
  const avisos = useConferencia(medicao.contrato_id, medicao.tipo, String(medicao.numero), medicao.competencia, form.inicio)?.avisos ?? [];
  const erroMotivo = tentou && !motivo.trim() ? "Informe o motivo da revisão." : undefined;
  function registrar(ev: React.FormEvent) {
    ev.preventDefault();
    setTentou(true);
    if (!motivo.trim() || !form.oficio || !form.planilha) {
      if (!motivo.trim()) document.getElementById("rev-motivo")?.focus();
      return;
    }
    const fd = new FormData();
    fd.append("motivo", motivo.trim());
    fd.append("periodo_inicio", form.inicio);
    fd.append("periodo_fim", form.fim);
    fd.append("valor", form.valor);
    fd.append("oficio", form.oficio);
    fd.append("planilha", form.planilha);
    void aoRegistrar(fd);
  }
  return (
    <form className="painel-inline pilha" onSubmit={registrar} aria-label={`Registrar revisão ${proxima}`}
      onKeyDown={ev => ev.key === "Escape" && aoFechar()}>
      <p className="painel__titulo">Revisão {proxima}</p>
      <div className="campo">
        <label className="campo__rotulo" htmlFor="rev-motivo">Motivo (obrigatório)</label>
        <input id="rev-motivo" name="motivo" autoComplete="off" className="entrada--larga" maxLength={1000} autoFocus
          aria-invalid={erroMotivo ? true : undefined} aria-describedby={erroMotivo ? "rev-motivo-erro" : undefined}
          value={motivo} onChange={e => setMotivo(e.target.value)} />
        <ErroCampo id="rev-motivo-erro" erro={erroMotivo} />
      </div>
      <CamposDoPedido prefixo="rev" form={form} setForm={setForm} comCompetencia={false} tentou={tentou} />
      {avisos.length > 0 && <div role="status">{avisos.map(a => <CaixaAviso nivel="atencao" key={a}>{a}</CaixaAviso>)}</div>}
      <div className="form-inline">
        <button type="submit" className="btn btn--primario" disabled={ocupado}>{ocupado ? "Registrando…" : "Registrar revisão"}</button>
        <button type="button" className="btn" onClick={aoFechar}>Voltar</button>
      </div>
    </form>
  );
}

/** O nº do SIGA que o orgao devolve depois do envio (pelo sistema ou por fora). */
export function NumeroSiga({ medicaoId, atual, podeEditar, aoGravar }: {
  medicaoId: number; atual: string | null; podeEditar: boolean; aoGravar: () => void;
}) {
  const [numero, setNumero] = useState(atual ?? "");
  const [editando, setEditando] = useState(false);
  const [ocupado, setOcupado] = useState(false);
  const [erro, setErro] = useState("");
  const [feito, setFeito] = useState("");
  useEffect(() => { setNumero(atual ?? ""); }, [atual]);
  async function gravar(ev: React.FormEvent) {
    ev.preventDefault();
    setOcupado(true); setErro(""); setFeito("");
    try {
      await api(`/api/medicoes/${medicaoId}/planilhas/numero-siga`, { method: "POST", body: JSON.stringify({ numero: numero.trim() }) });
      setFeito("Número gravado."); setEditando(false);
      aoGravar();
    } catch (e) { setErro(mensagemDeErro(e)); } finally { setOcupado(false); }
  }
  const aberto = podeEditar && (editando || !atual);
  return (
    <div className="pilha">
      {!aberto && (
        <p>Nº do SIGA <span className="num">{atual ?? "—"}</span>
          {podeEditar && <> <button type="button" className="btn btn--pequeno" onClick={() => setEditando(true)}>Corrigir</button></>}</p>
      )}
      {aberto && (
        <form className="form-inline" onSubmit={gravar} aria-label="Nº do SIGA">
          <div className="campo">
            <label className="campo__rotulo" htmlFor={`siga-${medicaoId}`}>Nº do SIGA</label>
            <input id={`siga-${medicaoId}`} name="numero_siga" autoComplete="off" spellCheck={false} className="entrada--media" required
              maxLength={100} value={numero} onChange={e => setNumero(e.target.value)} />
          </div>
          <button type="submit" className="btn" disabled={ocupado || !numero.trim()}>{ocupado ? "Gravando…" : "Gravar"}</button>
          {editando && <button type="button" className="btn" onClick={() => { setEditando(false); setNumero(atual ?? ""); }}>Voltar</button>}
        </form>
      )}
      {erro && <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erro}</p>}
      {feito && <p className="feito" role="status" aria-live="polite">{feito}</p>}
    </div>
  );
}
