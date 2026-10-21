import { useRascunho } from "./rascunho";
import { useEffect, useState } from "react";
import CaixaAviso from "./CaixaAviso";
import Checklist, { CartaRecolhivel, type ItemChecklist } from "./Checklist";
import ComporEmail, { type Mensagem } from "./ComporEmail";
import ErroCampo from "./ErroCampo";
import { api, apiForm, mensagemDeErro } from "./api";
import { IconeAlerta } from "./icones";
import { FormMotivo } from "./MedicaoAtos";
import { fmtTamanho as mb } from "./formato";
import { fmtCompetencia, fmtDataPura } from "./tempo";
import Selo from "./Selo";
import Pendencias from "./Pendencias";
import PleitoPrevisao from "./PleitoPrevisao";
import LiberarEnvio, { envioReservado, type Reserva } from "./LiberarEnvio";

// Fluxo do oficio (bloco 7): pleito de reajuste, pedido de prorrogacao e comunicacao de conclusao. Mesmo caminho
// do protocolo (bloco 5), com um documento so': numero do oficio -> anexos -> carta -> assinado -> previa -> envio.
// As regras (anexos exigidos, "chuva" sem paralisacao, conferencia do assinado) moram em `app/pleitos.py`.

export type TipoPleito = "reajuste" | "prazo" | "conclusao";
type Pendencia = { codigo: string; mensagem: string };
type Conferencia = { ok: boolean; avisos: { codigo: string; mensagem: string }[]; paginas_montado: number;
  certificado: number };
export type Pleito = {
  id: number; tipo: TipoPleito; rotulo: string; origem: "sistema" | "cadastro"; numero_oficio: string | null;
  data_base_mes: string | null; ciclo: number | null; dias: number | null; justificativa: string | null;
  situacao: string; corpo_carta: string | null; corpo_padrao?: string | null; erro_carta?: string;
  montado_paginas: number | null; assinado_arquivo: string | null; nome_documento: string | null;
  conferencia: Conferencia | null; pendencias: Pendencia[]; enviado_em: string | null; envio_justificativa: string | null;
  anexos: { id: number; tipo: string; nome: string; tamanho: number }[];
  exigidos: { tipo: string; rotulo: string }[];
};
type Previa = { para: string[]; copia: string[]; assunto: string; corpo: string;
  anexos: { nome: string; tamanho: number }[]; total: number; limite: number; pendencias: Pendencia[] };

const MIN_JUSTIFICATIVA = 10;        // o servidor recusa menos que isso (pleitos.MIN_JUSTIFICATIVA)

function mensagem(e: unknown): string {
  return mensagemDeErro(e);
}

// Os anexos do oficio como checklist (F-67). Tudo o que o servidor lista em `exigidos` e' exigido, entao sem
// arquivo e' "Falta" (Atencao: se envia com justificativa, como no protocolo). Anexo de um tipo que nao esta'
// entre os exigidos aparece em "Outros anexos", so' para remover.
function itensDoPleito(p: Pleito): ItemChecklist[] {
  const arquivosDe = (tipo: string) => p.anexos.filter(a => a.tipo === tipo).map(a => ({ id: a.id, nome: a.nome, tamanho: a.tamanho }));
  const itens: ItemChecklist[] = p.exigidos.map((x): ItemChecklist => {
    const arquivos = arquivosDe(x.tipo);
    return { chave: x.tipo, rotulo: x.rotulo, nota: "Exigida", arquivos, situacao: arquivos.length > 0 ? "anexada" : "falta",
      aceita: ".xlsx,application/pdf" };
  });
  const conhecidos = new Set(p.exigidos.map(x => x.tipo));
  const outros = p.anexos.filter(a => !conhecidos.has(a.tipo)).map(a => ({ id: a.id, nome: a.nome, tamanho: a.tamanho }));
  if (outros.length > 0) itens.push({ chave: "outros", rotulo: "Outros anexos", situacao: "anexada", arquivos: outros, semAnexar: true });
  return itens;
}

/** Passo 1: numero do oficio e os campos do tipo. */
export function NovoPleito({ contratoId, tipo, dataBase, aoCriar, aoCancelar }: {
  contratoId: number; tipo: TipoPleito; dataBase?: string; aoCriar: (p: Pleito) => void; aoCancelar: () => void;
}) {
  const [oficio, setOficio] = useState("");
  const [dias, setDias] = useState("");
  const [justificativa, setJustificativa] = useState("");
  const [erro, setErro] = useState("");
  const [ocupado, setOcupado] = useState(false);

  async function criar(ev: React.FormEvent) {
    ev.preventDefault();
    setOcupado(true); setErro("");
    try {
      aoCriar(await api<Pleito>(`/api/contratos/${contratoId}/pleitos`, { method: "POST", body: JSON.stringify({
        tipo, numero_oficio: oficio, data_base_mes: dataBase ?? null,
        dias: tipo === "prazo" ? Number(dias) || null : null, justificativa: tipo === "prazo" ? justificativa : null }) }));
    } catch (e) { setErro(mensagem(e)); } finally { setOcupado(false); }
  }

  return (
    <form className="cartao__corpo pilha" onSubmit={criar} aria-label="Novo ofício">
      {erro && <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erro}</p>}
      {dataBase && <p>Data-base <span className="num">{fmtCompetencia(dataBase)}</span></p>}
      <div className="campo">
        <label className="campo__rotulo" htmlFor={`oficio-${tipo}`}>Nº do ofício (CT)</label>
        {/* o formulario so' aparece depois do clique que o pediu: o foco vem para o primeiro campo */}
        <input id={`oficio-${tipo}`} name="numero_oficio" autoComplete="off" spellCheck={false} className="entrada--16ch" required maxLength={40} autoFocus
          placeholder="Ex.: 301…" value={oficio} onChange={e => setOficio(e.target.value)} />
      </div>
      {tipo === "prazo" && (
        <>
          <div className="campo">
            <label className="campo__rotulo" htmlFor="prazo-dias">Dias de prorrogação</label>
            <input id="prazo-dias" name="dias" autoComplete="off" spellCheck={false} className="entrada--16ch" type="number" min={1} required
              placeholder="Ex.: 60…" value={dias} onChange={e => setDias(e.target.value)} />
          </div>
          <div className="campo">
            <label className="campo__rotulo" htmlFor="prazo-just">Justificativa (vai na seção “2. DO PEDIDO”)</label>
            <textarea id="prazo-just" name="justificativa" autoComplete="off" rows={5} required value={justificativa}
              onChange={e => setJustificativa(e.target.value)} />
          </div>
        </>
      )}
      <div className="form-inline">
        <button type="submit" className="btn btn--primario" disabled={ocupado}>{ocupado ? "Criando…" : "Criar ofício"}</button>
        <button type="button" className="btn" onClick={aoCancelar}>Cancelar</button>
      </div>
    </form>
  );
}

/** Passos 2 a 6: anexos, carta, assinado, previa e envio. Pleito do cadastro (enviado antes do sistema) so' aparece. */
export function CartaoPleito({ p, podeEditar, aoMudar, desfecho, contexto }: {
  // `desfecho`: o que aconteceu depois do envio (na aba Prazos, o instrumento que atendeu o pedido);
  // `contexto`: o que o rotulo do servidor nao diz e a tela precisa (no Reajuste, o ciclo do pleito)
  p: Pleito; podeEditar: boolean; aoMudar: () => void; desfecho?: string; contexto?: string;
}) {
  const [corpo, setCorpo] = useState(p.corpo_carta || p.corpo_padrao || "");
  const [erro, setErro] = useState(p.erro_carta ?? "");
  const [reserva, setReserva] = useState<Reserva | null>(null);   // envio preso (409): oferece a liberacao
  const [ocupado, setOcupado] = useState(false);
  const [previa, setPrevia] = useState<Previa | null>(null);
  const [justificativa, setJustificativa] = useState("");
  const [tentou, setTentou] = useState(false);   // clicou em Enviar: so' ai' o campo mostra o que falta
  const [descartando, setDescartando] = useState(false);
  useEffect(() => { setCorpo(p.corpo_carta || p.corpo_padrao || ""); }, [p.id, p.corpo_carta, p.corpo_padrao]);
  const editavel = podeEditar && p.origem === "sistema" && !["enviado", "descartado"].includes(p.situacao);
  useRascunho(editavel && corpo.trim() !== (p.corpo_carta || p.corpo_padrao || "").trim());   // carta editada e ainda nao montada

  async function agir(f: () => Promise<unknown>) {
    setOcupado(true); setErro(""); setReserva(null);
    try { await f(); aoMudar(); } catch (e) { setErro(mensagem(e)); setReserva(envioReservado(e) ? e.corpo : null); } finally { setOcupado(false); }
  }
  function arquivo(caminho: string, extras: Record<string, string>, input: HTMLInputElement) {
    const f = input.files?.[0];
    input.value = "";
    if (!f) return;
    const fd = new FormData();
    fd.append("arquivo", f);
    for (const [k, v] of Object.entries(extras)) fd.append(k, v);
    void agir(() => apiForm(caminho, fd));
  }
  async function abrirPrevia() {
    setOcupado(true); setErro("");
    try {
      const pv = await api<Previa>(`/api/pleitos/${p.id}/previa`, { method: "POST" });
      setPrevia(pv);
      setJustificativa("");
      setTentou(false);
    } catch (e) { setErro(mensagem(e)); } finally { setOcupado(false); }
  }
  async function enviar(m: Mensagem) {
    await agir(async () => {
      await api(`/api/pleitos/${p.id}/enviar`, { method: "POST", body: JSON.stringify({
        ...m, justificativa: justificativa || null }) });
      setPrevia(null);
    });
  }
  const precisaJustificativa = (previa?.pendencias.length ?? 0) > 0;
  const faltaJustificativa = precisaJustificativa && justificativa.trim().length < MIN_JUSTIFICATIVA;
  const erroJustificativa = tentou && faltaJustificativa
    ? `Escreva a justificativa, com pelo menos ${MIN_JUSTIFICATIVA} caracteres.` : undefined;
  // o clique em Enviar chega aqui antes do envio: a justificativa que falta aparece junto do campo, com o foco nele
  function validarAntes(): boolean {
    setTentou(true);
    if (faltaJustificativa) document.getElementById(`pl-just-${p.id}`)?.focus();
    return !faltaJustificativa;
  }
  const itens = itensDoPleito(p);

  return (
    <section className="cartao" aria-labelledby={`pleito-${p.id}`} id={`oficio-${p.id}`}>
      <div className="cartao__cabeca">
        <h3 className="cartao__titulo" id={`pleito-${p.id}`}>
          {p.rotulo}{contexto ? ` (${contexto})` : ""}{p.numero_oficio ? ` · ${p.numero_oficio}` : ""}
        </h3>
        <Selo classe={p.situacao === "enviado" ? "selo--ok" : ""}>
          {p.situacao === "enviado" ? `enviado ${p.enviado_em ? fmtDataPura(p.enviado_em.slice(0, 10)) : ""}` : p.situacao}
        </Selo>
        {p.origem === "cadastro" && <span className="cartao__dica">enviado antes do sistema (cadastro)</span>}
      </div>
      {desfecho && <p className="cartao__corpo campo__nota">{desfecho}</p>}
      {p.origem === "sistema" && p.situacao !== "enviado" && (
        <div className="cartao__corpo pilha">
          {erro && <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erro}</p>}
          {reserva && <LiberarEnvio tabela="pleitos" id={p.id} reserva={reserva} aoLiberar={() => { setErro(""); aoMudar(); }} />}

          {itens.length > 0 && (
            <div>
              <span className="painel__titulo">Anexos</span>
              <Checklist itens={itens} legenda={`Anexos de ${p.rotulo}`} editavel={editavel} ocupado={ocupado}
                aoAnexar={(tipo, input) => arquivo(`/api/pleitos/${p.id}/anexos`, { tipo }, input)}
                aoRemover={id => agir(() => api(`/api/pleitos/${p.id}/anexos/${id}/remover`, { method: "POST" }))} />
            </div>
          )}

          {/* issue #272: a previsao por competencia se confere antes de montar a carta */}
          {editavel && p.tipo === "reajuste" && <PleitoPrevisao pleitoId={p.id} dataBase={p.data_base_mes} ciclo={p.ciclo} aoGravar={aoMudar} />}

          <div className="pilha">
            {/* montada a carta, o texto recolhe; montar e baixar ficam fora dele, sempre a' vista */}
            <CartaRecolhivel id={`carta-pleito-${p.id}`} linhas={12} valor={corpo} desabilitado={!editavel} aoMudar={setCorpo}
              montada={!!p.nome_documento} dicaMontada="carta montada; abra para editar"
              nota="Linha em branco separa parágrafos; “# ” abre título." />
            {editavel && (
              <div className="form-inline">
                {/* primario so' enquanto a carta nao foi montada: depois dela o passo e' assinar e enviar */}
                <button type="button" className={`btn${p.nome_documento ? "" : " btn--primario"}`} disabled={ocupado}
                  onClick={() => agir(() => api(`/api/pleitos/${p.id}/montar`, { method: "POST", body: JSON.stringify({ corpo }) }))}>
                  {ocupado ? "Montando…" : "Montar carta"}
                </button>
                {p.nome_documento && (
                  <a className="btn" href={`/api/pleitos/${p.id}/documento`}>
                    Baixar{p.montado_paginas ? ` (${p.montado_paginas} páginas)` : ""}
                  </a>
                )}
              </div>
            )}
          </div>

          {p.nome_documento && editavel && (
            <div className="campo">
              <span className="campo__rotulo">PDF assinado no DocuSign</span>
              <label className="btn espelho__anexar">
                {p.assinado_arquivo ? "Trocar o assinado" : "Anexar o assinado"}
                <input type="file" accept="application/pdf" className="espelho__arquivo" aria-label="Anexar o PDF assinado"
                  onChange={ev => arquivo(`/api/pleitos/${p.id}/assinado`, {}, ev.currentTarget)} />
              </label>
            </div>
          )}
          {p.conferencia && (
            p.conferencia.ok
              ? <p className="notas__ok">Assinado conferido: {p.conferencia.paginas_montado} páginas com o carimbo do envelope.</p>
              : <ul className="lista-simples">{p.conferencia.avisos.map(a => <li key={a.codigo} className="notas__diverge">{a.mensagem}</li>)}</ul>
          )}

          {p.pendencias.length > 0 && (
            <div>
              <span className="painel__titulo">O que falta</span>
              <Pendencias itens={p.pendencias} />
            </div>
          )}

          {editavel && p.nome_documento && !previa && (
            <div className="form-inline">
              <button type="button" className="btn btn--primario" disabled={ocupado} onClick={abrirPrevia}>Prévia do e-mail</button>
            </div>
          )}
          {editavel && (descartando
            ? <FormMotivo id={`descartar-pleito-${p.id}`} titulo="Descartar este ofício" rotulo="Motivo (obrigatório)"
                placeholder="Ex.: número do ofício errado…" acao="Descartar o ofício" acaoOcupada="Descartando…" ocupado={ocupado}
                aoFechar={() => setDescartando(false)}
                aoConfirmar={motivo => void agir(() => api(`/api/pleitos/${p.id}/descartar`, { method: "POST", body: JSON.stringify({ motivo }) }))} />
            : <button type="button" className="btn btn--pequeno" disabled={ocupado} onClick={() => setDescartando(true)}>Descartar</button>)}

          {previa && (
            <div aria-label="Prévia do e-mail">
              <ComporEmail key={p.id} ocupado={ocupado} anexos={previa.anexos}
                validarAntes={validarAntes}
                inicial={{ para: previa.para, copia: previa.copia, cco: [], assunto: previa.assunto, corpo: previa.corpo }}
                antes={precisaJustificativa && (
                  <div className="campo ol-pendencias">
                    <label className="campo__rotulo" htmlFor={`pl-just-${p.id}`}>
                      Justificativa (obrigatória para enviar com pendência)
                    </label>
                    <textarea id={`pl-just-${p.id}`} name="justificativa" autoComplete="off" rows={2} maxLength={2000} value={justificativa}
                      aria-invalid={erroJustificativa ? true : undefined} aria-describedby={erroJustificativa ? `pl-just-${p.id}-erro` : undefined}
                      onChange={e => setJustificativa(e.target.value)} />
                    <ErroCampo id={`pl-just-${p.id}-erro`} erro={erroJustificativa} />
                    {/* F-69: a condicao do Enviar, logo abaixo do campo que a cumpre */}
                    <span className="campo__nota">Para enviar com pendência, a justificativa precisa de {MIN_JUSTIFICATIVA} caracteres.</span>
                  </div>
                )}
                aoEnviar={enviar} aoDescartar={() => setPrevia(null)} />
              <p className="campo__nota">O e-mail sai da sua conta Microsoft. Anexos: {mb(previa.total)} de {mb(previa.limite)} permitidos.</p>
            </div>
          )}
        </div>
      )}
      {p.situacao === "enviado" && p.envio_justificativa && (
        <div className="cartao__corpo"><CaixaAviso nivel="atencao">Enviado com ressalva: {p.envio_justificativa}</CaixaAviso></div>
      )}
    </section>
  );
}
