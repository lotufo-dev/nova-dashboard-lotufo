import { useRascunho } from "./rascunho";
import { useEffect, useRef, useState } from "react";
import CaixaAviso from "./CaixaAviso";
import CampoCompetencia from "./CampoCompetencia";
import CampoValor from "./CampoValor";
import ComporEmail, { type Mensagem } from "./ComporEmail";
import { api, apiForm, ApiErro, mensagemDeErro } from "./api";
import { IconeAlerta, IconeBaixar, IconeMais } from "./icones";
import { larDoEspelho, tituloMedicao } from "./medicao";
import { brl } from "./Medicoes";
import { Link } from "./Link";
// data-hora no fuso de Cuiaba (tempo.ts), e nao no do navegador; competencia em MM/AAAA
import { fmtCompetencia as competenciaBR, fmtDataHora as dataHoraBR, fmtDataPura as dataBR } from "./tempo";
import Rolagem from "./Rolagem";
import Selo from "./Selo";
import LiberarEnvio, { envioReservado, type Reserva } from "./LiberarEnvio";

// Espelho de NF (bloco 2, spec §3 passos 1-2): a medicao nasce aqui. A pessoa digita numero,
// competencia e os valores da regra da obra; o sistema calcula uma linha por nota, gera os
// .docx e manda o e-mail ao faturamento pela conta de quem clicou.

type Entrada = { chave: string; rotulo: string; natureza: string };
type Regra = { situacao: "prova" | "ativa"; entradas: Entrada[]; saidas: number };
type Saida = {
  chave: string; natureza: string; rotulo: string; emissor: string; municipio: string;
  valor: number; mo: number | null; material: number | null; inss: number | null; iss: number | null;
  irrf: number | null; ibs: number | null; cbs: number | null; liquido: number; nome_arquivo?: string;
};
type Previa = { saidas: Saida[]; medicoes: { tipo: string; valor_centavos: number; existente: string | null }[]; avisos: string[];
  periodo: string };
type Arquivo = { documento_id: number; saida: string; nome: string; tamanho: number };
type Envio = { id: number; remetente: string; para: string[]; copia: string[]; assunto: string; enviado_em: string };
type EspelhoDetalhe = {
  id: number; numero: number; competencia: string; versao: number; situacao: "vigente" | "substituido";
  entradas: Record<string, number>; periodo_inicio: string | null; periodo_fim: string | null;
  criado_em: string; criado_por_nome: string | null; motivo: string | null; saidas: Saida[];
  medicoes: { id: number; tipo: string; estado: string; superado?: boolean }[]; arquivos: Arquivo[]; envio: Envio | null;
};
type PreviaEnvio = { para: string[]; copia: string[]; assunto: string; corpo: string;
  anexos: { nome: string; tamanho: number }[]; total: number; limite: number; avisos: string[] };

const TIPO: Record<string, string> = { execucao: "execução", reajuste: "reajuste", projeto: "projeto" };

function paraCompetencia(mmaaaa: string): string {
  // "05/2026" -> "2026-05"; o input type=month ja entrega "2026-05"
  const m = mmaaaa.match(/^(\d{2})\/(\d{4})$/);
  return m ? `${m[2]}-${m[1]}` : mmaaaa;
}
// primeiro e ultimo dia do mes da competencia ("2026-02" -> ["2026-02-01", "2026-02-28"])
function mesCivil(comp: string): [string, string] {
  const m = comp.match(/^(\d{4})-(\d{2})$/);
  if (!m) return ["", ""];
  const ultimo = new Date(Number(m[1]), Number(m[2]), 0).getDate();
  return [`${m[1]}-${m[2]}-01`, `${m[1]}-${m[2]}-${String(ultimo).padStart(2, "0")}`];
}
function mensagem(e: unknown): string {
  return mensagemDeErro(e);
}
const col = (v: number | null) => (v === null ? "—" : brl(v));

type Passo = { tipo: "lista" } | { tipo: "form" } | { tipo: "previa"; previa: Previa }
  | { tipo: "envio"; espelho: EspelhoDetalhe; previa: PreviaEnvio };

// Dois lugares (NAVEGACAO.md): na obra, o cartao "Nova medicao", que so' gera o espelho e aponta para a
// medicao que nasceu dele (na obra do fluxo antigo, mostra `semRegra`, o formulario a mao); com `medicao`,
// a secao Espelho da pagina da medicao, com os espelhos dela e o envio ao faturamento. O espelho que atende
// execucao e reajuste mora na medicao de execucao; a de reajuste mostra um resumo com o link.
export default function Espelho({ contratoId, podeEditar, aoMudar, aoSaberRegra, medicao, semRegra, aoGerar, abrirForm: abrirLogo, parte, inicial }: {
  contratoId: number; podeEditar: boolean; aoMudar: () => void; aoSaberRegra?: (ativa: boolean) => void;
  medicao?: { id: number; tipo: string }; semRegra?: React.ReactNode;
  /** Nova medicao (2026-10-09): recebe a medicao que nasceu do espelho, para abrir a pagina dela. */
  aoGerar?: (medicaoId: number) => void;
  /** Abre ja' no formulario (a pagina Nova medicao nao tem outra coisa a mostrar). */
  abrirForm?: boolean;
  /** Pagina da medicao (#152): `espelho` e' a etapa 1 (os valores, os arquivos, "Gerar de novo"; sem moldura) e
   *  `faturamento` a etapa 2 (o que foi ao faturamento e o envio). Sem `parte`, o cartao inteiro de antes. */
  parte?: "espelho" | "faturamento";
  /** Numero e competencia (AAAA-MM) da medicao prevista ou escolhida na janela "Iniciar processo" (#151): o
   *  formulario abre com eles. `tipo: "projeto"` mostra so' os valores de Projeto. */
  inicial?: { numero: string | number; competencia: string; tipo?: "projeto" };
}) {
  const [regra, setRegra] = useState<Regra | null | undefined>(undefined);
  const [espelhos, setEspelhos] = useState<EspelhoDetalhe[]>([]);
  const [passo, setPasso] = useState<Passo>({ tipo: "lista" });
  const [form, setForm] = useState<{ numero: string; competencia: string; entradas: Record<string, string>; motivo: string;
    periodoInicio: string; periodoFim: string }>(
    { numero: inicial ? String(inicial.numero) : "", competencia: inicial?.competencia ?? "", entradas: {}, motivo: "",
      periodoInicio: mesCivil(inicial?.competencia ?? "")[0], periodoFim: mesCivil(inicial?.competencia ?? "")[1] });
  const [erro, setErro] = useState("");
  const [reservado, setReservado] = useState<{ id: number; reserva: Reserva } | null>(null);   // envio preso (409)
  // Versao ja' enviada: so' manda de novo com a confirmacao marcada (S8, 10/10/2026). `jaEnviado`: o 409
  // ESPELHO_JA_ENVIADO de quem tinha a tela aberta quando outro acabou de enviar.
  const [reenviar, setReenviar] = useState(false);
  const [jaEnviado, setJaEnviado] = useState(false);
  const [ocupado, setOcupado] = useState(false);
  const [feito, setFeito] = useState("");
  // o espelho que acabou de ser gerado na obra: a mensagem aponta para a medicao dele
  const [gerado, setGerado] = useState<number | null>(null);
  const geracao = useRef(0);
  const baseForm = useRef(JSON.stringify(form));   // o formulario como abriu: so' conta como rascunho o que mudou
  useRascunho(passo.tipo !== "lista" && passo.tipo !== "envio" && JSON.stringify(form) !== baseForm.current);

  const carregar = async () => {
    const g = geracao.current;
    const r = await api<{ regra: Regra | null; espelhos: EspelhoDetalhe[] }>(`/api/contratos/${contratoId}/espelho`);
    if (g !== geracao.current) return;
    setRegra(r.regra); setEspelhos(r.espelhos);
    aoSaberRegra?.(r.regra?.situacao === "ativa");
    return r;
  };

  useEffect(() => {
    geracao.current += 1;
    const g = geracao.current;
    setRegra(undefined); setEspelhos([]); setPasso({ tipo: "lista" }); setErro(""); setFeito(""); setGerado(null);
    carregar()
      .then(r => {
        if (!abrirLogo || r?.regra?.situacao !== "ativa" || g !== geracao.current) return;
        // medicao prevista (do cronograma): o formulario abre com o numero e a competencia dela
        if (inicial) {
          const [pi, pf] = mesCivil(inicial.competencia);
          const novo = { numero: String(inicial.numero), competencia: inicial.competencia, entradas: {}, motivo: "", periodoInicio: pi, periodoFim: pf };
          baseForm.current = JSON.stringify(novo);
          setForm(novo);
        }
        setPasso({ tipo: "form" });
      })
      .catch(e => { if (g === geracao.current) setErro(mensagem(e)); });
    return () => { geracao.current += 1; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [contratoId]);

  // #151: "Projeto" escolhido na janela Iniciar processo mostra so' os valores de Projeto (se a regra os tem)
  const soProjeto = inicial?.tipo === "projeto" && regra?.entradas.some(en => en.natureza === "projeto") === true;
  const titulo = medicao ? "Espelho" : "Nova medição";
  // a secao da medicao tem ancora (#espelho): quem chega pela fila no passo "enviar ao faturamento" cai nela
  // e na obra (#nova-medicao), onde a fila manda quem precisa gerar o espelho de uma obra sem medicao aberta
  const idSecao = medicao ? "espelho" : "nova-medicao";
  if (regra === undefined && !erro) {
    return medicao || parte ? <section className={parte ? "espelho-etapa" : "cartao"} id={idSecao}><div className="vazio"><p>Carregando o espelho…</p></div></section> : null;
  }
  if (!regra || regra.situacao !== "ativa") {
    // `undefined` aqui e' a carga que falhou: sem saber a regra, a tela nao oferece a medicao manual (o servidor a
    // recusa numa obra com regra ativa, issue #12, mas a tela nao deve oferece-la)
    const falhou = regra === undefined;
    if (parte) {
      return (
        <section className="espelho-etapa pilha" id={idSecao}>
          {erro && <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erro}{falhou ? " Recarregue a página para tentar de novo." : ""}</p>}
          {!falhou && (medicao ? <div className="vazio"><p>Nenhum espelho.</p></div> : semRegra)}
        </section>
      );
    }
    return (
      <section className="cartao" aria-labelledby="titulo-espelho" id={idSecao}>
        <div className="cartao__cabeca">
          <h2 className="cartao__titulo" id="titulo-espelho">{titulo}</h2>
        </div>
        {erro && <div className="cartao__corpo"><p className="erro" role="alert"><IconeAlerta className="icone icone--p" />
          {erro}{falhou ? " Recarregue a página para tentar de novo." : ""}</p></div>}
        {!falhou && (medicao ? <div className="vazio"><p>Nenhum espelho.</p></div> : semRegra)}
      </section>
    );
  }

  // "Gerar de novo" parte dos valores da versao vigente (centavos -> "1.234,56"): quem corrige um
  // campo nao redigita os outros nem zera uma natureza sem querer.
  const brlPuro = (c: number) => brl(c).replace(/^R\$\s?/, "");
  const abrirForm = (base?: EspelhoDetalhe) => {
    setErro(""); setFeito(""); setGerado(null);
    const [pi, pf] = base?.periodo_inicio && base.periodo_fim ? [base.periodo_inicio, base.periodo_fim]
      : mesCivil(base ? base.competencia : "");
    const novo = { numero: base ? String(base.numero) : "", competencia: base ? base.competencia : "",
      entradas: Object.fromEntries(regra.entradas.map(e => {
        const c = base?.entradas?.[e.chave];
        return [e.chave, c ? brlPuro(c) : ""];
      })), motivo: "", periodoInicio: pi, periodoFim: pf };
    baseForm.current = JSON.stringify(novo);
    setForm(novo);
    setPasso({ tipo: "form" });
  };

  const corpoEspelho = () => {
    const comp = paraCompetencia(form.competencia);
    const [mi, mf] = mesCivil(comp);
    // so' manda o periodo quando ele nao e' o mes inteiro da competencia
    const proprio = (form.periodoInicio || form.periodoFim) && (form.periodoInicio !== mi || form.periodoFim !== mf);
    return {
      numero: Number(form.numero), competencia: comp, entradas: form.entradas,
      ...(form.motivo.trim() ? { motivo: form.motivo.trim() } : {}),
      ...(proprio ? { periodo_inicio: form.periodoInicio, periodo_fim: form.periodoFim } : {}),
    };
  };

  const conferir = async (ev: React.FormEvent) => {
    ev.preventDefault(); setErro(""); setOcupado(true);
    try {
      const p = await api<Previa>(`/api/contratos/${contratoId}/espelho/previa`, {
        method: "POST", body: JSON.stringify(corpoEspelho()) });
      setPasso({ tipo: "previa", previa: p });
    } catch (e) { setErro(mensagem(e)); } finally { setOcupado(false); }
  };

  const gerar = async () => {
    setErro(""); setOcupado(true);
    try {
      const r = await api<{ espelho_id: number }>(`/api/contratos/${contratoId}/espelho`, {
        method: "POST", body: JSON.stringify(corpoEspelho()) });
      const novos = await carregar();
      const esp = novos?.espelhos.find(e => e.id === r.espelho_id);
      const lar = esp ? larDoEspelho(esp) : undefined;
      if (aoGerar && lar) { aoGerar(lar); return; }
      setPasso({ tipo: "lista" });
      setFeito(`Espelho nº ${form.numero} gerado. Confira os arquivos e envie ao faturamento`);
      setGerado(r.espelho_id);
      aoMudar();
    } catch (e) { setErro(mensagem(e)); } finally { setOcupado(false); }
  };

  const abrirEnvio = async (esp: EspelhoDetalhe) => {
    setErro(""); setFeito(""); setReservado(null); setReenviar(false); setJaEnviado(false); setOcupado(true);
    try {
      const p = await api<PreviaEnvio>(`/api/espelhos/${esp.id}/envio`);
      setPasso({ tipo: "envio", espelho: esp, previa: p });
    } catch (e) { setErro(mensagem(e)); } finally { setOcupado(false); }
  };

  const enviar = async (m: Mensagem) => {
    if (passo.tipo !== "envio") return;
    setErro(""); setReservado(null); setOcupado(true);
    try {
      await api(`/api/espelhos/${passo.espelho.id}/enviar`, { method: "POST",
        body: JSON.stringify(reenviar ? { ...m, reenviar: true } : m) });
      await carregar();
      setPasso({ tipo: "lista" });
      setFeito("Enviado ao faturamento. A medição passou a Espelho enviado.");
      aoMudar();
    } catch (e) {
      setErro(mensagem(e));
      if (envioReservado(e)) setReservado({ id: passo.espelho.id, reserva: e.corpo });
      if (e instanceof ApiErro && e.status === 409 && e.corpo?.codigo === "ESPELHO_JA_ENVIADO") setJaEnviado(true);
    } finally { setOcupado(false); }
  };

  // Evidencia do orgao (spec §3 passo 1, opcional): o PDF que o orgao mandou vai para a medicao
  // da pagina; fora dela, para a casa do espelho (execucao viva). Nunca para uma medicao superada (#212).
  const anexarEvidencia = async (esp: EspelhoDetalhe, input: HTMLInputElement) => {
    const arquivo = input.files?.[0];
    if (!arquivo) return;
    const alvo = medicao && esp.medicoes.some(m => m.id === medicao.id && !m.superado) ? medicao.id : larDoEspelho(esp);
    const med = esp.medicoes.find(m => m.id === alvo);
    if (!med) { setFeito(""); setErro("Este espelho não tem medição em vigor para receber o anexo."); input.value = ""; return; }
    setErro(""); setFeito(""); setOcupado(true);
    try {
      const fd = new FormData();
      fd.append("arquivo", arquivo);
      const r = await apiForm<{ documento_id: number; repetido: boolean }>(`/api/medicoes/${med.id}/documentos`, fd);
      // sem ponto final: a mensagem de `feito` ganha o ponto na hora de mostrar
      setFeito(r.repetido ? `${arquivo.name} já estava anexado a esta medição`
        : `${arquivo.name} anexado como evidência do órgão em: ${tituloMedicao({ numero: esp.numero, tipo: med.tipo })}`);
      aoMudar();
    } catch (e) { setErro(mensagem(e)); } finally { setOcupado(false); input.value = ""; }
  };

  // #208: espelho com versao mais nova para esta medicao (superado) nao aparece nela
  const daMedicao = medicao ? espelhos.filter(e => e.medicoes.some(x => x.id === medicao.id && !x.superado)) : espelhos;
  // na medicao, o espelho mora na de execucao da competencia: as outras mostram o resumo com o link
  const deOutra = medicao ? daMedicao.filter(e => e.situacao === "vigente" && larDoEspelho(e) !== medicao.id) : [];
  const vigentes = daMedicao.filter(e => e.situacao === "vigente" && !deOutra.includes(e));
  const substituidos = daMedicao.filter(e => e.situacao === "substituido" && (!medicao || larDoEspelho(e) === medicao.id));
  const temIbsCbs = (s: Saida[]) => s.some(x => x.ibs !== null || x.cbs !== null);

  const tabelaNotas = (saidas: Saida[]) => (
    <Rolagem rotulo="Notas do espelho">
      <table className="tabela espelho__notas">
        <thead>
          <tr>
            <th scope="col">Saída</th><th scope="col" className="col-num num">Valor</th><th scope="col" className="col-num num">Mão de obra</th><th scope="col" className="col-num num">Material</th>
            <th scope="col" className="col-num num">INSS</th><th scope="col" className="col-num num">ISS</th><th scope="col" className="col-num num">IRRF</th>
            {temIbsCbs(saidas) && <><th scope="col" className="col-num num">IBS</th><th scope="col" className="col-num num">CBS</th></>}
            <th scope="col" className="col-num col-fixa num">Líquido</th>
          </tr>
        </thead>
        <tbody>
          {saidas.map(s => (
            <tr key={s.chave}>
              <td>{s.rotulo} · {s.emissor.charAt(0).toUpperCase() + s.emissor.slice(1)} · {s.municipio}</td>
              <td className="col-num dinheiro num">{brl(s.valor)}</td><td className="col-num dinheiro num">{col(s.mo)}</td><td className="col-num dinheiro num">{col(s.material)}</td>
              <td className="col-num dinheiro num">{col(s.inss)}</td><td className="col-num dinheiro num">{col(s.iss)}</td><td className="col-num dinheiro num">{col(s.irrf)}</td>
              {temIbsCbs(saidas) && <><td className="col-num dinheiro num">{col(s.ibs)}</td><td className="col-num dinheiro num">{col(s.cbs)}</td></>}
              <td className="col-num col-fixa dinheiro num">{brl(s.liquido)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Rolagem>
  );

  // a etapa da pagina da medicao (`parte`) vai sem moldura propria: a moldura e' a da etapa
  const Raiz = parte ? "div" : "section";
  const so = (p: "espelho" | "faturamento") => !parte || parte === p;   // este pedaco aparece nesta parte?
  return (
    <Raiz className={parte ? "espelho-etapa pilha" : "cartao"} {...(parte ? {} : { "aria-labelledby": "titulo-espelho" })} id={idSecao}>
      {!parte && (
      <div className="cartao__cabeca">
        <h2 className="cartao__titulo" id="titulo-espelho">{titulo}</h2>
        {podeEditar && passo.tipo === "lista" && !medicao && (
          <div className="cartao__acoes">
            <button type="button" className="btn btn--primario" onClick={() => abrirForm()}>
              <IconeMais className="icone icone--p" /> Gerar espelho
            </button>
          </div>
        )}
      </div>
      )}

      {parte && !medicao && podeEditar && passo.tipo === "lista" && (
        <div><button type="button" className="btn btn--primario" onClick={() => abrirForm()}><IconeMais className="icone icone--p" /> Gerar espelho</button></div>
      )}
      {erro && <div className="cartao__corpo"><p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erro}</p></div>}
      {passo.tipo === "envio" && reservado?.id === passo.espelho.id && (
        <div className="cartao__corpo"><LiberarEnvio tabela="espelhos" id={reservado.id} reserva={reservado.reserva}
          aoLiberar={() => { setErro(""); void carregar(); }} /></div>
      )}
      {/* regiao viva sempre montada; a confirmacao e' sucesso (.feito), nao atencao */}
      <div className={feito && passo.tipo === "lista" ? "cartao__corpo" : "sr-only"} role="status">
      {feito && passo.tipo === "lista" && (
        <p className="feito">{feito}{(() => {
          // na obra, a mensagem leva a medicao que nasceu do espelho (e onde ele mora e se envia)
          const esp = !medicao && gerado ? espelhos.find(e => e.id === gerado) : undefined;
          const lar = esp ? esp.medicoes.find(x => x.id === larDoEspelho(esp)) : undefined;
          return esp && lar
            ? <> na <Link para={{ tela: "medicao", obra: contratoId, id: lar.id }} secao="espelho">{tituloMedicao({ numero: esp.numero, tipo: lar.tipo })}</Link>.</>
            : ".";
        })()}</p>
      )}
      </div>

      {passo.tipo === "form" && so("espelho") && (
        <form className="cartao__corpo" onSubmit={conferir} aria-label="Gerar espelho">
          <p className="painel__titulo">Gerar espelho</p>
          <div className="form-inline">
            <div className="campo">
              <label className="campo__rotulo" htmlFor="esp-numero">Nº da medição{soProjeto ? " de Projeto" : ""}</label>
              <input id="esp-numero" name="numero" autoComplete="off" spellCheck={false} className="entrada--curta entrada--num num" required inputMode="numeric"
                pattern="[0-9]{1,3}" value={form.numero}
                onChange={e => setForm({ ...form, numero: e.target.value })} />
            </div>
            <div className="campo">
              <label className="campo__rotulo" htmlFor="esp-competencia">Competência</label>
              <CampoCompetencia id="esp-competencia" name="competencia" className="entrada--media" value={form.competencia}
                onChange={v => {
                  // trocar a competencia volta o periodo ao mes inteiro dela: um periodo proprio da
                  // competencia anterior nao pode seguir calado para a nova
                  const [ni, nf] = mesCivil(v);
                  setForm({ ...form, competencia: v, periodoInicio: ni, periodoFim: nf });
                }} />
            </div>
            <div className="campo">
              <label className="campo__rotulo" htmlFor="esp-periodo-ini">Período: de</label>
              <input id="esp-periodo-ini" name="periodo_inicio" autoComplete="off" type="date" className="entrada--media" value={form.periodoInicio}
                onChange={e => setForm({ ...form, periodoInicio: e.target.value })} />
            </div>
            <div className="campo">
              <label className="campo__rotulo" htmlFor="esp-periodo-fim">até</label>
              <input id="esp-periodo-fim" name="periodo_fim" autoComplete="off" type="date" className="entrada--media" value={form.periodoFim}
                onChange={e => setForm({ ...form, periodoFim: e.target.value })} />
            </div>
            {regra.entradas.filter(en => !soProjeto || en.natureza === "projeto").map(en => (
              <div className="campo" key={en.chave}>
                <label className="campo__rotulo" htmlFor={`esp-${en.chave}`}>{en.rotulo}</label>
                <CampoValor id={`esp-${en.chave}`} name={en.chave} className="entrada--media num"
                  value={form.entradas[en.chave] ?? ""}
                  onChange={v => setForm({ ...form, entradas: { ...form.entradas, [en.chave]: v } })} />
              </div>
            ))}
          </div>
          <div className="painel__rodape form-inline">
            <button type="submit" className="btn btn--primario" disabled={ocupado}>{ocupado ? "Conferindo…" : "Conferir"}</button>
            <button type="button" className="btn" onClick={() => setPasso({ tipo: "lista" })}>Voltar</button>
          </div>
        </form>
      )}

      {passo.tipo === "previa" && so("espelho") && (
        <div className="cartao__corpo">
          <p className="painel__titulo">Conferir antes de gerar</p>
          <p className="campo__nota">Período no espelho: <span className="num">{passo.previa.periodo}</span></p>
          {tabelaNotas(passo.previa.saidas)}
          <ul className="lista-simples espelho__medicoes">
            {passo.previa.medicoes.map(m => (
              <li key={m.tipo}>Medição {form.numero} de {TIPO[m.tipo] ?? m.tipo}: {brl(m.valor_centavos)}
                {m.existente && <> <Selo classe="selo--atencao">Versão nova</Selo></>}</li>
            ))}
          </ul>
          {passo.previa.avisos.map(a => <CaixaAviso nivel="atencao" key={a}>{a}</CaixaAviso>)}
          {passo.previa.medicoes.some(m => m.existente) && (
            <div className="campo">
              <label className="campo__rotulo" htmlFor="esp-motivo">Motivo da nova versão (opcional)</label>
              <input id="esp-motivo" name="motivo" autoComplete="off" className="entrada--media" maxLength={500} value={form.motivo}
                onChange={e => setForm({ ...form, motivo: e.target.value })} />
            </div>
          )}
          <div className="painel__rodape form-inline">
            <button type="button" className="btn btn--primario" disabled={ocupado} onClick={gerar}>{ocupado ? "Gerando…" : "Gerar"}</button>
            <button type="button" className="btn" onClick={() => setPasso({ tipo: "form" })}>Voltar</button>
          </div>
        </div>
      )}

      {passo.tipo === "envio" && so("faturamento") && (
        <div className="cartao__corpo">
          <p className="painel__titulo">Enviar ao faturamento</p>
          {passo.previa.avisos.map(a => <CaixaAviso nivel="atencao" key={a}>{a}</CaixaAviso>)}
          {(passo.espelho.envio || jaEnviado) && (
            <label>
              <input type="checkbox" checked={reenviar} onChange={ev => setReenviar(ev.target.checked)} />{" "}
              Confirmo o reenvio desta versão (substitui o envio anterior)
            </label>
          )}
          <ComporEmail key={passo.espelho.id} ocupado={ocupado} anexos={passo.previa.anexos}
            inicial={{ para: passo.previa.para, copia: passo.previa.copia, cco: [], assunto: passo.previa.assunto, corpo: passo.previa.corpo }}
            aoEnviar={enviar} aoDescartar={() => setPasso({ tipo: "lista" })} />
        </div>
      )}

      {medicao && passo.tipo === "lista" && deOutra.map(esp => {
        const lar = esp.medicoes.find(x => x.id === larDoEspelho(esp));
        return (
          <div className="cartao__corpo" key={esp.id}>
            {lar && (
              <p><Link para={{ tela: "medicao", obra: contratoId, id: lar.id }} secao="espelho">
                Abrir o espelho na {tituloMedicao({ numero: esp.numero, tipo: lar.tipo })}
              </Link></p>
            )}
          </div>
        );
      })}

      {medicao && passo.tipo === "lista" && vigentes.length === 0 && deOutra.length === 0 && (
        <div className="vazio"><p>Nenhum espelho.</p></div>
      )}

      {medicao && passo.tipo === "lista" && vigentes.map(esp => {
        // #212: com uma das medicoes ja' em espelho mais novo, este fica so' para leitura (o servidor recusa
        // o envio, e gerar de novo partiria dos valores antigos da superada)
        const superadas = esp.medicoes.filter(m => m.superado);
        const soLeitura = superadas.length > 0;
        return (
        <article className={parte ? "pilha espelho__item" : "cartao__corpo espelho__item"} key={esp.id} aria-label={`Espelho nº ${esp.numero}`}>
          {!parte && (
          <div className="espelho__cabeca">
            <strong>Nº {esp.numero} · {competenciaBR(esp.competencia)}</strong>
            {/* o estado do envio e' SELO (nao texto de apoio): e' o que diz se falta um passo */}
            {esp.envio
              ? <Selo classe="selo--ok">Enviado em {dataHoraBR(esp.envio.enviado_em)}</Selo>
              : <Selo classe="selo--atencao" forte>Não enviado ao faturamento</Selo>}
          </div>
          )}
          {so("espelho") && (
            <div className={parte ? "med-caixa" : undefined}>{tabelaNotas(esp.saidas)}</div>
          )}
          {parte === "espelho" && (
            <ul className="med-linhas med-linhas--caixa">
              {regra.entradas.filter(en => esp.entradas?.[en.chave] !== undefined).map(en => (
                <li key={en.chave}><span>{en.rotulo.replace(/\s*\(R\$\)\s*$/, "")}</span><span className="num">{brl(esp.entradas[en.chave])}</span></li>
              ))}
              {esp.periodo_inicio && esp.periodo_fim && (
                <li><span>Período no espelho</span><span className="num">{dataBR(esp.periodo_inicio)} a {dataBR(esp.periodo_fim)}</span></li>
              )}
            </ul>
          )}
          <div>
            {parte && <p className="med-sub">Arquivos</p>}
            <ul className="lista-simples lista-simples--arquivos">
              {esp.arquivos.map(a => (
                <li key={a.documento_id}>
                  <a href={`/api/espelhos/${esp.id}/arquivos/${a.documento_id}`}><IconeBaixar className="icone icone--p" /> {a.nome}</a>
                </li>
              ))}
            </ul>
          </div>
          {superadas.map(m => (
            <p className="campo__nota" key={m.id}>
              {/* sem artigo antes do titulo: "Reajuste da 10ª Medicao" e' masculino, as outras femininas */}
              Este espelho fica só para leitura: já existe espelho mais novo para{" "}
              <Link para={{ tela: "medicao", obra: contratoId, id: m.id }} secao="espelho">{tituloMedicao({ numero: esp.numero, tipo: m.tipo })}</Link>.
            </p>
          ))}
          {podeEditar && (
            <div className={parte ? "med-acoes" : "form-inline"}>
              {/* primario so' enquanto nao foi enviado: "Enviar de novo" nao e' o proximo passo */}
              {so("faturamento") && !soLeitura && (
                <button type="button" className={`btn btn--pequeno${esp.envio ? "" : " btn--primario"}`} disabled={ocupado} onClick={() => abrirEnvio(esp)}>
                  {esp.envio ? "Enviar de novo" : "Enviar ao faturamento"}
                </button>
              )}
              {so("espelho") && !soLeitura && <button type="button" className="btn btn--pequeno" onClick={() => abrirForm(esp)}>Gerar de novo</button>}
              {so("espelho") && (
                <label className="btn btn--pequeno espelho__anexar">
                  Anexar o que o órgão mandou (PDF)
                  <input type="file" name="evidencia" accept="application/pdf" className="espelho__arquivo" disabled={ocupado}
                    aria-label={`Anexar evidência do órgão à medição ${esp.numero}`}
                    onChange={ev => anexarEvidencia(esp, ev.currentTarget)} />
                </label>
              )}
            </div>
          )}
        </article>
        );
      })}

      {medicao && passo.tipo === "lista" && so("espelho") && substituidos.length > 0 && (
        <details className={parte ? "detalhes" : "detalhes cartao__corpo"}>
          <summary>Versões anteriores</summary>
          <ul className="lista-simples">
            {substituidos.map(e => (
              <li key={e.id}>Nº {e.numero} · {competenciaBR(e.competencia)} · versão {e.versao}{e.motivo ? ` · ${e.motivo}` : ""}</li>
            ))}
          </ul>
        </details>
      )}
    </Raiz>
  );
}
