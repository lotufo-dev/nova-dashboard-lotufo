import { useRef, useState } from "react";
import CaixaAviso from "./CaixaAviso";
import CampoValor from "./CampoValor";
import ErroCampo from "./ErroCampo";
import { api, apiForm, mensagemDeErro } from "./api";
import { brl } from "./formato";
import { IconeAlerta } from "./icones";
import { brlCampo, type Agir } from "./MedicaoAtos";
import type { Medicao } from "./Medicoes";
import Selo from "./Selo";
import { hojeLocal } from "./tempo";
import "./planilhaCarta.css";

// Issue #290 (spec 2026-10-20 §2.1 passo 3 e §2.3): "Registrar boletim". A pessoa arrasta o PDF do orgao, o leitor
// da capa do SMO (#285) propoe nº, data e valor, marcados como lidos; ela confere e aceita (origem `aceito`). Sem
// leitura, os tres campos ficam vazios para digitar (origem `manual`). A diferenca pedido x aprovado aparece na hora.

type Leitura = { lido: boolean; fonte: string | null; avisos: string[];
  campos: { numero_orgao?: string; data?: string; valor_centavos?: number } };
type Campo = "numero" | "data" | "valor";

const MEIOS_BOLETIM: [string, string][] = [
  ["smo", "SMO"], ["oficio", "Ofício"], ["email", "E-mail"], ["carimbo", "Carimbo"], ["ci", "CI"], ["outro", "Outro"]];

const MIN_JUSTIFICATIVA_DIFERENCA = 10;     // medicoes.MIN_JUSTIFICATIVA_DIFERENCA

/** Issue #288: aprovado do boletim vigente abaixo do pedido. Ja' aceita: o selo. Senao, quem edita (operacao e
 *  engenharia) aceita com justificativa; a diretoria so' le. Sem diferenca abaixo do pedido, nada. */
export function AceiteDiferenca({ m, podeEditar, salvando, agir, aoFechar, erro }: {
  m: Medicao; podeEditar: boolean; salvando: boolean; agir: Agir;
  /** Em janela (Mais acoes): o formulario ja' abre e fechar fecha a janela. */
  aoFechar?: () => void; erro?: string;
}) {
  const [abertoAqui, setAbertoAqui] = useState(false);
  const aberto = abertoAqui || !!aoFechar;
  const fechar = () => { setAbertoAqui(false); aoFechar?.(); };
  const [justificativa, setJustificativa] = useState("");
  const [tentou, setTentou] = useState(false);
  const comBoletim = (m.boletins ?? []).some(b => b.tem_arquivo);
  const pedido = m.valor_protocolado_centavos, aprovado = m.valor_atestado_centavos;
  // #286: a capa do SMO divergente do cadastro tambem se aceita aqui, mesmo com o aprovado igual ao pedido
  const capaDiverge = (m.capa_divergencias ?? []).length > 0;
  if (!comBoletim || ["cancelada", "desistida"].includes(m.estado) || pedido === null || aprovado === null
    || (aprovado >= pedido && !capaDiverge && !m.diferenca_aceita)) return null;
  if (m.diferenca_aceita) return <Selo classe="selo--ok">Diferença aceita</Selo>;
  if (!podeEditar) return null;
  if (!aberto) {
    return <div><button type="button" className="btn btn--pequeno" onClick={() => setAbertoAqui(true)}>Aceitar a diferença</button></div>;
  }
  const falta = justificativa.trim().length < MIN_JUSTIFICATIVA_DIFERENCA
    ? `Informe a justificativa (ao menos ${MIN_JUSTIFICATIVA_DIFERENCA} caracteres).` : undefined;
  async function salvar(ev: React.FormEvent) {
    ev.preventDefault();
    setTentou(true);
    if (falta) return;
    const ok = await agir(() => api(`/api/medicoes/${m.id}/diferenca-aceita`, {
      method: "POST", body: JSON.stringify({ justificativa: justificativa.trim() }),
    }), "Diferença aceita.");
    if (ok) fechar();
  }
  return (
    <form className="pilha" onSubmit={salvar} noValidate aria-label="Aceitar a diferença"
      onKeyDown={ev => ev.key === "Escape" && fechar()}>
      {erro && <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erro}</p>}
      <div className="campo">
        <label className="campo__rotulo" htmlFor="dif-justificativa">Justificativa</label>
        <textarea id="dif-justificativa" name="justificativa" className="entrada--larga" rows={2} maxLength={1000} autoFocus
          value={justificativa} onChange={ev => setJustificativa(ev.target.value)}
          {...(tentou && falta ? { "aria-invalid": true as const, "aria-describedby": "dif-erro" } : {})} />
        <ErroCampo id="dif-erro" erro={tentou ? falta : undefined} />
      </div>
      <div className="form-inline">
        <button type="submit" className="btn btn--primario" disabled={salvando}>{salvando ? "Aceitando…" : "Aceitar a diferença"}</button>
        <button type="button" className="btn" onClick={fechar}>Cancelar</button>
      </div>
    </form>
  );
}

/** "12.345,67" -> 1234567 (centavos inteiros, sem ponto flutuante); vazio -> null. */
function centavos(valor: string): number | null {
  const d = valor.replace(/\D/g, "");
  return d ? Number(d) : null;
}

export function FormBoletim({ m, salvando, agir, aoFechar, erro }: {
  m: Medicao; salvando: boolean; agir: Agir; aoFechar: () => void; erro?: string;
}) {
  const [arquivo, setArquivo] = useState<File | null>(null);
  const [sobre, setSobre] = useState(false);
  const [lendo, setLendo] = useState(false);
  const [erroLeitura, setErroLeitura] = useState("");
  const [avisos, setAvisos] = useState<string[]>([]);
  const [numero, setNumero] = useState("");
  const [data, setData] = useState("");
  const [valor, setValor] = useState("");
  const [meio, setMeio] = useState("");
  // o que a capa trouxe (gate Sol, rodada 1): o campo e' "lido" enquanto o valor atual for o lido, mesmo depois de
  // mexer e voltar. Quem decide a origem (`aceito`) e' o servidor, contra a leitura que ele guardou.
  const [lido, setLido] = useState<{ numero?: string; data?: string; valor?: number }>({});
  const [tentou, setTentou] = useState(false);
  const leitura = useRef(0);
  const hoje = hojeLocal();

  async function escolher(f: File | null) {
    if (!f) return;
    const n = ++leitura.current;
    // o que veio da leitura do PDF anterior sai; o que a pessoa digitou fica (code-review)
    if (lidos.has("numero")) setNumero("");
    if (lidos.has("data")) setData("");
    if (lidos.has("valor")) setValor("");
    setArquivo(f); setErroLeitura(""); setAvisos([]); setLido({});
    setLendo(true);
    const fd = new FormData();
    fd.append("arquivo", f);
    try {
      const r = await apiForm<Leitura>(`/api/medicoes/${m.id}/boletim/leitura`, fd);
      if (n !== leitura.current) return;     // outro PDF chegou enquanto este era lido
      const c = r.campos ?? {};
      const novo: typeof lido = {};
      if (c.numero_orgao) { setNumero(c.numero_orgao); novo.numero = c.numero_orgao; }
      if (c.data) { setData(c.data); novo.data = c.data; }
      // aprovado negativo nao se propoe (o servidor tambem nao): o campo fica para digitar
      if (typeof c.valor_centavos === "number" && c.valor_centavos >= 0) {
        setValor(brlCampo(c.valor_centavos)); novo.valor = c.valor_centavos;
      }
      if (Object.keys(novo).length > 0 && !meio) setMeio("smo");
      setLido(novo);
      setAvisos(r.avisos ?? []);
    } catch (e) {
      if (n === leitura.current) setErroLeitura(mensagemDeErro(e));
    } finally {
      if (n === leitura.current) setLendo(false);
    }
  }

  const pedido = m.valor_protocolado_centavos;
  const aprovado = centavos(valor);
  const lidos = new Set<Campo>([
    ...(lido.numero !== undefined && numero.trim() === lido.numero ? ["numero" as const] : []),
    ...(lido.data !== undefined && data === lido.data ? ["data" as const] : []),
    ...(lido.valor !== undefined && aprovado === lido.valor ? ["valor" as const] : []),
  ]);
  const falta = !arquivo ? "Arraste ou escolha o PDF do boletim."
    : !numero.trim() ? "Informe o nº do boletim no órgão."
    : !data ? "Informe a data do boletim."
    : data > hoje ? "A data do boletim não pode ser futura."
    : aprovado === null ? "Informe o valor aprovado." : undefined;

  async function salvar(ev: React.FormEvent) {
    ev.preventDefault();
    setTentou(true);
    if (falta || !arquivo || lendo) return;
    const fd = new FormData();
    fd.append("valor", valor);
    fd.append("data", data);
    fd.append("numero_orgao", numero.trim());
    if (meio) fd.append("meio", meio);
    fd.append("arquivo", arquivo);
    const ok = await agir(() => apiForm(`/api/medicoes/${m.id}/boletim`, fd), "Boletim registrado.");
    if (ok) aoFechar();
  }

  const seloLido = (c: Campo) => lidos.has(c) ? <> <Selo>Lido da capa</Selo></> : null;

  return (
    <form className="pilha" onSubmit={salvar} noValidate aria-label="Registrar boletim" onKeyDown={ev => ev.key === "Escape" && aoFechar()}>
      <p className="painel__titulo">Registrar o boletim da {m.numero}ª medição</p>
      {erro && <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erro}</p>}
      <div className="campo">
        <span className="campo__rotulo" id="bol-arquivo-rotulo">PDF do boletim</span>
        <div className={`planilha__soltar${sobre ? " planilha__soltar--sobre" : ""}`} data-testid="soltar-boletim"
          onDragOver={ev => { ev.preventDefault(); if (!sobre) setSobre(true); }}
          onDragLeave={() => setSobre(false)}
          onDrop={ev => { ev.preventDefault(); setSobre(false); void escolher(ev.dataTransfer.files?.[0] ?? null); }}>
          {arquivo
            ? <span className="planilha__arquivo" title={arquivo.name}>{arquivo.name}</span>
            : <span className="planilha__arquivo planilha__arquivo--vazio">—</span>}
          <label className="btn btn--pequeno espelho__anexar">
            {arquivo ? "Trocar" : "Escolher"}
            <input id="bol-arquivo" type="file" accept="application/pdf,.pdf" className="espelho__arquivo" aria-label="PDF do boletim"
              onChange={ev => { void escolher(ev.currentTarget.files?.[0] ?? null); ev.currentTarget.value = ""; }} />
          </label>
        </div>
      </div>
      <p className={lendo ? "" : "sr-only"} role="status">{lendo ? "Lendo a capa…" : ""}</p>
      {erroLeitura && <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />Não foi possível ler o PDF: {erroLeitura}</p>}
      {avisos.map(a => <CaixaAviso nivel="atencao" key={a}>{a}</CaixaAviso>)}
      <div className="form-inline">
        <div className="campo">
          <label className="campo__rotulo" htmlFor="bol-numero">Nº no órgão{seloLido("numero")}</label>
          <input id="bol-numero" name="numero_orgao" autoComplete="off" spellCheck={false} className="entrada--media" maxLength={100}
            value={numero} onChange={ev => setNumero(ev.target.value)} />
        </div>
        <div className="campo">
          <label className="campo__rotulo" htmlFor="bol-data">Data do boletim{seloLido("data")}</label>
          <input id="bol-data" name="data" type="date" autoComplete="off" className="entrada--media" max={hoje}
            value={data} onChange={ev => setData(ev.target.value)} />
        </div>
        <div className="campo">
          <label className="campo__rotulo" htmlFor="bol-valor">Valor aprovado{seloLido("valor")}</label>
          <CampoValor id="bol-valor" name="valor" value={valor} onChange={setValor} />
        </div>
        <div className="campo">
          <label className="campo__rotulo" htmlFor="bol-meio">Meio</label>
          <select id="bol-meio" name="meio" className="entrada--media" value={meio} onChange={ev => setMeio(ev.target.value)}>
            <option value="">—</option>
            {MEIOS_BOLETIM.map(([v, r]) => <option key={v} value={v}>{r}</option>)}
          </select>
        </div>
      </div>
      <dl className="planilha__saldo" aria-label="Pedido e aprovado">
        <div><dt>Pedido</dt><dd className="num">{brl(pedido)}</dd></div>
        <div><dt>Aprovado</dt><dd className="num">{brl(aprovado)}</dd></div>
        <div><dt>Diferença</dt>
          <dd className={`num${pedido !== null && aprovado !== null && aprovado < pedido ? " planilha__negativo" : ""}`}>
            {pedido !== null && aprovado !== null ? brl(aprovado - pedido) : "—"}</dd></div>
      </dl>
      <ErroCampo id="bol-erro" erro={tentou ? falta : undefined} />
      <div className="painel__rodape form-inline">
        <button type="submit" className="btn btn--primario" disabled={salvando || lendo}>
          {salvando ? "Registrando…" : lidos.size > 0 ? "Aceitar e registrar o boletim" : "Registrar boletim"}</button>
        <button type="button" className="btn" onClick={aoFechar}>Cancelar</button>
      </div>
    </form>
  );
}
