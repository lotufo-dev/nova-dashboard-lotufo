import { useRef, useState } from "react";
import CaixaAviso from "./CaixaAviso";
import CampoValor from "./CampoValor";
import ErroCampo from "./ErroCampo";
import { apiForm, mensagemDeErro } from "./api";
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
  // os campos que vieram da capa e ninguem mexeu: so' com os tres assim o boletim grava como aceito
  const [lidos, setLidos] = useState<Set<Campo>>(new Set());
  const [tentou, setTentou] = useState(false);
  const leitura = useRef(0);
  const hoje = hojeLocal();

  async function escolher(f: File | null) {
    if (!f) return;
    const n = ++leitura.current;
    setArquivo(f); setErroLeitura(""); setAvisos([]); setLidos(new Set());
    setNumero(""); setData(""); setValor("");
    setLendo(true);
    const fd = new FormData();
    fd.append("arquivo", f);
    try {
      const r = await apiForm<Leitura>(`/api/medicoes/${m.id}/boletim/leitura`, fd);
      if (n !== leitura.current) return;     // outro PDF chegou enquanto este era lido
      const c = r.campos ?? {};
      const novos = new Set<Campo>();
      if (c.numero_orgao) { setNumero(c.numero_orgao); novos.add("numero"); }
      if (c.data) { setData(c.data); novos.add("data"); }
      if (typeof c.valor_centavos === "number") { setValor(brlCampo(c.valor_centavos)); novos.add("valor"); }
      if (novos.size > 0 && !meio) setMeio("smo");
      setLidos(novos);
      setAvisos(r.avisos ?? []);
    } catch (e) {
      if (n === leitura.current) setErroLeitura(mensagemDeErro(e));
    } finally {
      if (n === leitura.current) setLendo(false);
    }
  }

  const mexeu = (c: Campo) => setLidos(s => { if (!s.has(c)) return s; const t = new Set(s); t.delete(c); return t; });
  const pedido = m.valor_protocolado_centavos;
  const aprovado = centavos(valor);
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
    fd.append("lido", String(lidos.size === 3));
    fd.append("arquivo", arquivo);
    const ok = await agir(() => apiForm(`/api/medicoes/${m.id}/boletim`, fd), "Boletim registrado.");
    if (ok) aoFechar();
  }

  const lido = (c: Campo) => lidos.has(c) ? <> <Selo>Lido da capa</Selo></> : null;

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
          <label className="campo__rotulo" htmlFor="bol-numero">Nº no órgão{lido("numero")}</label>
          <input id="bol-numero" name="numero_orgao" autoComplete="off" spellCheck={false} className="entrada--media" maxLength={100}
            value={numero} onChange={ev => { setNumero(ev.target.value); mexeu("numero"); }} />
        </div>
        <div className="campo">
          <label className="campo__rotulo" htmlFor="bol-data">Data do boletim{lido("data")}</label>
          <input id="bol-data" name="data" type="date" autoComplete="off" className="entrada--media" max={hoje}
            value={data} onChange={ev => { setData(ev.target.value); mexeu("data"); }} />
        </div>
        <div className="campo">
          <label className="campo__rotulo" htmlFor="bol-valor">Valor aprovado{lido("valor")}</label>
          <CampoValor id="bol-valor" name="valor" value={valor} onChange={v => { setValor(v); mexeu("valor"); }} />
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
