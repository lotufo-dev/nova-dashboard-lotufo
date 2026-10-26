import { useRascunho } from "./rascunho";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import CaixaAviso from "./CaixaAviso";
import Checklist, { CartaRecolhivel, type ItemChecklist } from "./Checklist";
import ComporEmail, { type Mensagem } from "./ComporEmail";
import ConfirmarFaltas from "./ConfirmarFaltas";
import { api, apiForm, ApiErro, mensagemDeErro } from "./api";
import { IconeAlerta, IconeSeta } from "./icones";
import { FormMotivo } from "./MedicaoAtos";
import { fmtTamanho as mb } from "./formato";
import { protocolosDa } from "./medicao";
import { Link } from "./Link";
import { fmtCompetencia, fmtDataHora } from "./tempo";
import Selo from "./Selo";
import Pendencias from "./Pendencias";

// Protocolo de medicao feito pelo sistema (bloco 5; spec §3 passos 4 a 7). A tela desenha o que o
// servidor responde (etapas da familia, pecas do orgao, pendencias, conferencia do assinado): as
// regras moram em `app/protocolo.py`, nao aqui.

type Etapa = { chave: string; rotulo: string; carta: boolean };
type PecaCfg = { tipo: string; rotulo: string; exigida: boolean; solto: boolean; naturezas?: string[] };
type Medicao = { id: number; numero: number; tipo: string; titulo: string; estado: string;
  competencia: string; valor_protocolado_centavos: number | null };
type Peca = { id: number; tipo: string; nome: string; tamanho: number; ext: string };
type Pendencia = { codigo: string; mensagem: string; protocolo_id?: number | null };
type Conferencia = { ok: boolean; avisos: { codigo: string; mensagem: string }[]; envelope: string | null;
  paginas_montado: number; paginas_assinado: number; certificado: number };
export type ProtocoloDet = {
  id: number; etapa: string; etapa_rotulo: string; tem_carta: boolean; natureza: string;
  numero_oficio: string | null; situacao: string; corpo_carta: string | null; corpo_padrao?: string | null;
  erro_carta?: string; montado_paginas: number | null; nome_arquivo: string | null; assinado_arquivo: string | null;
  conferencia: Conferencia | null; medicoes: Medicao[]; pecas: Peca[]; pendencias: Pendencia[];
  envio_id: number | null; numero_orgao: string | null; comprovante_arquivo?: string | null; justificativa: string | null; criado_em: string;
  enviado_em?: string | null; enviado_por?: string | null;   // A6: quando saiu e quem mandou
};
export type Lista = { familia: string; etapas: Etapa[]; pecas: PecaCfg[]; medicoes: Medicao[]; protocolos: ProtocoloDet[] };
type Previa = { para: string[]; copia: string[]; assunto: string; corpo: string;
  anexos: { nome: string; tamanho: number }[]; total: number; limite: number; pendencias: Pendencia[] };

const SITUACAO: Record<string, string> = {
  rascunho: "rascunho", montado: "pacote montado", assinado: "assinado", enviado: "enviado", descartado: "descartado",
};

function mensagem(e: unknown): string {
  return mensagemDeErro(e);
}

// As pecas do orgao como checklist (F-67). "Falta" e' Atencao: peca exigida sem anexo e' pendencia que se envia
// com justificativa (app/protocolo.py), nao bloqueio. Peca anexada de um tipo que a etapa nao pede aparece em
// "Outras pecas", so' para remover. Sem nota por item: a situacao (falta/opcional) ja' diz se e' exigida.
function itensDoProtocolo(p: ProtocoloDet, pecasCfg: PecaCfg[]): ItemChecklist[] {
  const arquivosDe = (tipo: string) => p.pecas.filter(x => x.tipo === tipo).map(x => ({ id: x.id, nome: x.nome, tamanho: x.tamanho }));
  const itens: ItemChecklist[] = pecasCfg.map((cfg): ItemChecklist => {
    const arquivos = arquivosDe(cfg.tipo);
    return { chave: cfg.tipo, rotulo: cfg.rotulo, arquivos,
      situacao: arquivos.length > 0 ? "anexada" : cfg.exigida ? "falta" : "opcional",
      aceita: cfg.tipo === "planilha" ? ".xlsx" : "application/pdf" };
  });
  const conhecidos = new Set(pecasCfg.map(c => c.tipo));
  const outras = p.pecas.filter(x => !conhecidos.has(x.tipo)).map(x => ({ id: x.id, nome: x.nome, tamanho: x.tamanho }));
  if (outras.length > 0) itens.push({ chave: "outras", rotulo: "Outras peças", situacao: "anexada", arquivos: outras, semAnexar: true });
  return itens;
}

function Cartao({ p, pecasCfg, podeEditar, aoMudar, marcado, aoMarcar }: {
  p: ProtocoloDet; pecasCfg: PecaCfg[]; podeEditar: boolean; aoMudar: (p?: ProtocoloDet) => void;
  marcado: boolean; aoMarcar: (v: boolean) => void;
}) {
  const [corpo, setCorpo] = useState(p.corpo_carta || p.corpo_padrao || "");
  const [erro, setErro] = useState(p.erro_carta ?? "");
  const [ocupado, setOcupado] = useState(false);
  const [descartando, setDescartando] = useState(false);
  useEffect(() => { setCorpo(p.corpo_carta || p.corpo_padrao || ""); }, [p.id, p.corpo_carta, p.corpo_padrao]);
  useRascunho(podeEditar && !["enviado", "descartado"].includes(p.situacao)
    && corpo.trim() !== (p.corpo_carta || p.corpo_padrao || "").trim());   // carta editada e ainda nao montada

  async function agir(f: () => Promise<ProtocoloDet | void>) {
    setOcupado(true); setErro("");
    try { aoMudar((await f()) || undefined); } catch (e) { setErro(mensagem(e)); } finally { setOcupado(false); }
  }
  function arquivo(caminho: string, extras: Record<string, string>, input: HTMLInputElement) {
    const f = input.files?.[0];
    input.value = "";
    if (!f) return;
    const fd = new FormData();
    fd.append("arquivo", f);
    for (const [k, v] of Object.entries(extras)) fd.append(k, v);
    agir(() => apiForm<ProtocoloDet>(caminho, fd));
  }
  const itens = itensDoProtocolo(p, pecasCfg);
  const editavel = podeEditar && p.situacao !== "enviado";

  return (
    <section className="cartao" aria-labelledby={`prot-${p.id}`}>
      <div className="cartao__cabeca">
        <h3 className="cartao__titulo" id={`prot-${p.id}`}>
          {p.etapa_rotulo}: {p.medicoes.map(m => m.titulo).join(" e ")}{p.numero_oficio ? ` · ${p.numero_oficio}` : ""}
        </h3>
        <Selo classe={p.situacao === "enviado" ? "selo--ok" : ""}>{SITUACAO[p.situacao] ?? p.situacao}</Selo>
        {p.situacao !== "enviado" && (
          <label className="campo--linha">
            <input type="checkbox" name={`incluir-${p.id}`} checked={marcado} onChange={e => aoMarcar(e.target.checked)} /> Incluir neste e-mail
          </label>
        )}
      </div>
      <div className="cartao__corpo pilha">
        {erro && <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erro}</p>}

        {itens.length > 0 && (
          <div>
            <span className="painel__titulo">Peças técnicas</span>
            <Checklist itens={itens} legenda={`Peças técnicas de ${p.etapa_rotulo}`} editavel={editavel} ocupado={ocupado}
              aoAnexar={(tipo, input) => arquivo(`/api/protocolos/${p.id}/pecas`, { tipo }, input)}
              aoRemover={id => agir(() => api<ProtocoloDet>(`/api/protocolos/${p.id}/pecas/${id}/remover`, { method: "POST" }))} />
          </div>
        )}

        {p.tem_carta && (
          <div className="pilha">
            {/* montado o pacote, a carta recolhe; montar e baixar ficam fora dela, sempre a' vista */}
            <CartaRecolhivel id={`carta-${p.id}`} linhas={9} valor={corpo} desabilitado={!editavel} aoMudar={setCorpo}
              montada={!!p.nome_arquivo} />
            {editavel && (
              <div className="form-inline">
                {/* primario so' enquanto o pacote nao foi montado: depois dele, montar de novo nao e' o passo */}
                <button type="button" className={`btn${p.situacao === "rascunho" ? " btn--primario" : ""}`} disabled={ocupado}
                  onClick={() => agir(() => api<ProtocoloDet>(`/api/protocolos/${p.id}/montar`, { method: "POST", body: JSON.stringify({ corpo }) }))}>
                  {ocupado ? "Montando…" : "Montar pacote"}
                </button>
                {p.nome_arquivo && (
                  <a className="btn" href={`/api/protocolos/${p.id}/pacote`}>
                    Baixar pacote{p.montado_paginas ? ` (${p.montado_paginas} páginas)` : ""}
                  </a>
                )}
              </div>
            )}
          </div>
        )}

        {p.tem_carta && p.nome_arquivo && editavel && (
          <div className="campo">
            <span className="campo__rotulo">PDF assinado no DocuSign</span>
            <label className="btn espelho__anexar">
              {p.assinado_arquivo ? "Trocar o assinado" : "Anexar o assinado"}
              <input type="file" accept="application/pdf" className="espelho__arquivo" aria-label="Anexar o PDF assinado"
                onChange={ev => arquivo(`/api/protocolos/${p.id}/assinado`, {}, ev.currentTarget)} />
            </label>
          </div>
        )}
        {/* so' a divergencia do assinado aparece; conferido, o selo "assinado" do cabecalho basta */}
        {p.conferencia && !p.conferencia.ok && (
          <ul className="lista-simples">{p.conferencia.avisos.map(a => <li key={a.codigo} className="notas__diverge">{a.mensagem}</li>)}</ul>
        )}

        {p.pendencias.length > 0 && p.situacao !== "enviado" && (
          <div>
            {/* "O que falta" e' o da medicao, que junta tudo; aqui sao so' as deste protocolo */}
            <span className="painel__titulo">Pendências deste protocolo</span>
            <Pendencias itens={p.pendencias} />
          </div>
        )}

        {p.situacao === "enviado" && (
          <NumeroOrgao p={p} podeEditar={podeEditar} aoMudar={aoMudar} />
        )}
        {editavel && p.situacao !== "enviado" && (descartando
          ? <FormMotivo id={`descartar-${p.id}`} titulo="Descartar este protocolo" rotulo="Motivo (obrigatório)"
              acao="Descartar o protocolo" acaoOcupada="Descartando…" ocupado={ocupado}
              aoFechar={() => setDescartando(false)}
              aoConfirmar={motivo => agir(async () => { await api(`/api/protocolos/${p.id}/descartar`, { method: "POST", body: JSON.stringify({ motivo }) }); })} />
          : <button type="button" className="btn btn--pequeno" disabled={ocupado} onClick={() => setDescartando(true)}>Descartar</button>)}
      </div>
    </section>
  );
}

function NumeroOrgao({ p, podeEditar, aoMudar }: { p: ProtocoloDet; podeEditar: boolean; aoMudar: (p?: ProtocoloDet) => void }) {
  const [numero, setNumero] = useState(p.numero_orgao ?? "");
  const [comprovante, setComprovante] = useState<File | null>(null);
  const [erro, setErro] = useState("");
  const [ocupado, setOcupado] = useState(false);
  const entradaArquivo = useRef<HTMLInputElement>(null);
  async function salvar(ev: React.FormEvent) {
    ev.preventDefault();
    if (ocupado) return;
    const fd = new FormData();
    fd.append("numero", numero);
    if (comprovante) fd.append("comprovante", comprovante);
    setOcupado(true); setErro("");
    try {
      aoMudar(await apiForm<ProtocoloDet>(`/api/protocolos/${p.id}/numero-orgao`, fd));
      setComprovante(null);
      if (entradaArquivo.current) entradaArquivo.current.value = "";
    } catch (e) { setErro(mensagem(e)); } finally { setOcupado(false); }
  }
  return (
    <form className="form-inline" onSubmit={salvar}>
      {/* a justificativa do envio aparece uma vez so', como ressalva, em quem desenha o enviado */}
      <div className="campo">
        <label className="campo__rotulo" htmlFor={`orgao-${p.id}`}>Nº do protocolo no órgão</label>
        {/* gate Sol S1 (10/10/2026): vazio so' passa para anexar o comprovante de um numero ja' gravado; o erro do
            servidor explica na hora */}
        <input id={`orgao-${p.id}`} name="numero_orgao" autoComplete="off" spellCheck={false} className="entrada--media" maxLength={100} value={numero} disabled={!podeEditar} onChange={e => setNumero(e.target.value)} />
      </div>
      {(podeEditar || p.comprovante_arquivo) && (
        <div className="campo">
          <span className="campo__rotulo">Comprovante do órgão</span>
          <div className="form-inline">
            {podeEditar && (
              <label className="btn btn--pequeno espelho__anexar">
                {p.comprovante_arquivo ? "Trocar o comprovante" : "Anexar o comprovante"}
                <input ref={entradaArquivo} type="file" accept="application/pdf" className="espelho__arquivo" aria-label="Anexar o comprovante do órgão (PDF)"
                  onChange={ev => { setComprovante(ev.currentTarget.files?.[0] ?? null); setErro(""); }} />
              </label>
            )}
            {comprovante && <span className="campo__nota">{comprovante.name}</span>}
            {p.comprovante_arquivo && <a className="btn btn--pequeno" href={`/api/protocolos/${p.id}/comprovante`}>Baixar o comprovante</a>}
          </div>
        </div>
      )}
      {podeEditar && <button type="submit" className="btn btn--pequeno" disabled={ocupado}>{ocupado ? "Salvando…" : "Salvar"}</button>}
      {erro && <span className="notas__diverge">{erro}</span>}
    </form>
  );
}

/** Leitura dos protocolos da obra (etapas da familia, pecas do orgao, medicoes elegiveis e protocolos), a
 *  mesma para a obra e para a pagina de uma medicao, com guarda de geracao: resposta de outra obra nao
 *  escreve no estado. */
export function useProtocolos(contratoId: number, versao = 0) {
  const [dados, setDados] = useState<Lista | null>(null);
  const [erro, setErro] = useState("");
  const geracao = useRef(0);
  const carregar = useCallback(async () => {
    const g = geracao.current;
    try {
      const d = await api<Lista>(`/api/contratos/${contratoId}/protocolos`);
      if (g === geracao.current) { setDados(d); setErro(""); }
    } catch (e) { if (g === geracao.current) setErro(mensagem(e)); }
  }, [contratoId]);
  useEffect(() => {
    geracao.current += 1;
    setDados(null); setErro("");
    void carregar();
    return () => { geracao.current += 1; };
  }, [carregar]);
  // `versao` subiu: outro cartao da pagina mudou o que esta leitura mostra. Le de novo sem zerar `dados`
  // (zerar fecharia o formulario aberto); trocar de obra ja' le pelo efeito acima.
  const versaoLida = useRef(versao);
  useEffect(() => {
    if (versaoLida.current === versao) return;
    versaoLida.current = versao;
    void carregar();
  }, [versao, carregar]);
  return { dados, erro, carregar };
}

const pecasDe = (dados: Lista, p: ProtocoloDet) =>
  p.etapa === "nota" ? [] : dados.pecas.filter(c => !c.naturezas || c.naturezas.includes(p.natureza));

/** Prévia do e-mail e envio dos protocolos marcados (o mesmo fluxo na obra e na medicao). */
function EnvioProtocolos({ marcados, protocolos, podeEditar, aoEnviado, nivel = "h2", temAbertos, proximo }: {
  marcados: number[]; protocolos: ProtocoloDet[]; podeEditar: boolean; aoEnviado: () => Promise<void> | void; nivel?: "h2" | "h3";
  temAbertos: boolean; proximo: boolean;
}) {
  const Titulo = nivel;
  const idNota = useId();
  // a previa guarda os protocolos com que foi montada: o Enviar manda esses, nao os marcados na hora do clique
  const [previa, setPrevia] = useState<(Previa & { ids: number[]; marca: string }) | null>(null);
  // issue #213: o aviso "ATENÇÃO" aberto pelo Enviar, com o e-mail que espera a confirmacao e a lista do que falta
  const [confirmar, setConfirmar] = useState<{ m: Mensagem; itens: string[]; mudou: boolean } | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const [erro, setErro] = useState("");
  const [feito, setFeito] = useState("");

  // issue #10: mudar a selecao com a previa aberta fecha a previa, para nao sair um conjunto diferente do conferido
  // revisor R1 (PR #92): fecha tambem quando um protocolo dela muda no recarregamento (peca, pacote, assinado)
  const marcaDe = (ids: number[]) => JSON.stringify(ids.map(id => protocolos.find(p => p.id === id) ?? null));
  if (previa && (previa.ids.length !== marcados.length || previa.ids.some(id => !marcados.includes(id))
    || previa.marca !== marcaDe(previa.ids))) setPrevia(null);

  async function abrirPrevia() {
    setOcupado(true); setErro(""); setFeito("");
    const ids = marcados, marca = marcaDe(ids);
    try {
      const p = await api<Previa>("/api/protocolos/envio/previa", { method: "POST", body: JSON.stringify({ protocolo_ids: ids }) });
      setPrevia({ ...p, ids, marca });
      setConfirmar(null);
    } catch (e) { setErro(mensagem(e)); } finally { setOcupado(false); }
  }

  // issue #213: com pendencia na previa, o clique em Enviar so' abre o aviso; nada sai antes do "Continuar"
  const faltam = (previa?.pendencias ?? []).map(p => p.mensagem);
  function enviar(m: Mensagem) {
    if (faltam.length > 0) setConfirmar({ m, itens: faltam, mudou: false });
    else void enviarConfirmado(m, []);
  }

  async function enviarConfirmado(m: Mensagem, confirmadas: string[]) {
    setConfirmar(null);
    setOcupado(true); setErro("");
    try {
      await api("/api/protocolos/envio", { method: "POST", body: JSON.stringify({
        protocolo_ids: previa!.ids, ...m, confirmadas: confirmadas.length > 0 ? confirmadas : null,
        // revisor R3 (PR #92): os anexos vistos; documento anexado depois da previa faz o servidor recusar
        anexos: previa!.anexos.map(a => ({ nome: a.nome, tamanho: a.tamanho })) }) });
      setPrevia(null);
      setFeito("Enviado. O e-mail saiu da sua conta Microsoft e ficou registrado.");
      await aoEnviado();
    } catch (e) {
      // o que falta mudou depois do aviso: a previa passa a mostrar a lista de agora e o aviso abre de novo com ela
      if (e instanceof ApiErro && e.status === 422 && e.corpo?.codigo === "CONFIRMAR_PENDENCIAS") {
        const itens: Pendencia[] = e.corpo.itens ?? [];
        setPrevia(p => p && { ...p, pendencias: itens });
        setConfirmar({ m, itens: itens.map(x => x.mensagem), mudou: confirmadas.length > 0 });
      } else setErro(mensagem(e));
    } finally { setOcupado(false); }
  }

  return (
    <>
      {erro && <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erro}</p>}
      <p className={feito ? "notas__ok" : "sr-only"} role="status">{feito}</p>
      {/* F-68: a acao esta' sempre a' vista enquanto ha protocolo aberto; primaria quando protocolar e' o proximo
          passo, e desabilitada, com a razao ao lado, enquanto nada foi marcado */}
      {podeEditar && temAbertos && !previa && (
        <div className="acao-nota">
          <button type="button" className={`btn${proximo ? " btn--primario" : ""}`} disabled={ocupado || marcados.length === 0}
            aria-describedby={marcados.length === 0 ? idNota : undefined} onClick={abrirPrevia}>
            Prévia do e-mail{marcados.length > 0 ? ` (${marcados.length} ${marcados.length === 1 ? "protocolo" : "protocolos"})` : ""}
          </button>
          {marcados.length === 0 && <span className="campo__nota" id={idNota}>Marque os protocolos que vão no e-mail.</span>}
        </div>
      )}
      {previa && (
        <section className="cartao" aria-labelledby="titulo-previa-protocolo">
          <div className="cartao__cabeca">
            <Titulo className="cartao__titulo" id="titulo-previa-protocolo">Prévia do e-mail de protocolo</Titulo>
          </div>
          <div className="cartao__corpo">
            <ComporEmail ocupado={ocupado} anexos={previa.anexos}
              inicial={{ para: previa.para, copia: previa.copia, cco: [], assunto: previa.assunto, corpo: previa.corpo }}
              antes={faltam.length > 0 && (
                <div className="campo ol-pendencias">
                  <span className="campo__rotulo">O que falta</span>
                  <Pendencias itens={previa.pendencias} />
                </div>
              )}
              aoEnviar={enviar} aoDescartar={() => setPrevia(null)} />
            {confirmar && <ConfirmarFaltas itens={confirmar.itens} mudou={confirmar.mudou} aoCancelar={() => setConfirmar(null)}
              aoContinuar={() => void enviarConfirmado(confirmar.m, confirmar.itens)} />}
            {previa.total > previa.limite && (
              <p className="notas__diverge">Anexos passam do limite: {mb(previa.total)} de {mb(previa.limite)} permitidos.</p>
            )}
          </div>
        </section>
      )}
    </>
  );
}

/** Quando saiu e quem mandou (A6), e o numero que o orgao deu. */
function Enviado({ p, podeEditar, aoMudar, comMedicoes = true }: {
  p: ProtocoloDet; podeEditar: boolean; aoMudar: () => void; comMedicoes?: boolean;
}) {
  return (
    <div>
      <p>
        <strong>{p.etapa_rotulo}</strong>{comMedicoes ? `: ${p.medicoes.map(m => m.titulo).join(" e ")}` : ""}
        {p.numero_oficio ? ` · ${p.numero_oficio}` : ""}
        {p.enviado_em && <> · enviado em <span className="num">{fmtDataHora(p.enviado_em)}</span>{p.enviado_por ? ` por ${p.enviado_por}` : ""}</>}
      </p>
      {p.justificativa && <CaixaAviso nivel="atencao">Enviado com ressalva: {p.justificativa}</CaixaAviso>}
      <NumeroOrgao p={p} podeEditar={podeEditar} aoMudar={aoMudar} />
    </div>
  );
}

/** "Novo protocolo com várias medições" (NAVEGACAO.md › Obra › aba Medicoes): so' em orgao que junta medicoes
 *  num protocolo (SES), recolhido. O protocolo criado mora na primeira medicao dele, e a mensagem leva ate' la';
 *  nos outros orgaos o protocolo nasce dentro de cada medicao ("Criar protocolo" no O que falta). */
export function NovoProtocolo({ contratoId, versao = 0, aoMudar }: { contratoId: number; versao?: number; aoMudar?: () => void }) {
  const { dados, carregar } = useProtocolos(contratoId, versao);
  const [erro, setErro] = useState("");
  const [novo, setNovo] = useState<{ etapa: string; medicoes: number[]; oficio: string }>({ etapa: "", medicoes: [], oficio: "" });
  const [ocupado, setOcupado] = useState(false);
  const [criado, setCriado] = useState<{ id: number; titulo: string } | null>(null);

  if (!dados || dados.familia !== "ses") return null;
  const etapaAtual = novo.etapa || dados.etapas[0]?.chave || "";
  const etapa = dados.etapas.find(e => e.chave === etapaAtual);
  // so' as marcadas que continuam elegiveis: a lista se refaz quando outro cartao muda uma medicao
  const marcadas = novo.medicoes.filter(id => dados.medicoes.some(m => m.id === id));

  async function criar(ev: React.FormEvent) {
    ev.preventDefault();
    setOcupado(true); setErro(""); setCriado(null);
    try {
      await api(`/api/contratos/${contratoId}/protocolos`, { method: "POST",
        body: JSON.stringify({ etapa: etapaAtual, medicao_ids: marcadas, numero_oficio: etapa?.carta ? novo.oficio : null }) });
      // o lar e' a primeira medicao do protocolo, na ordem em que o servidor as devolve (a da lista abaixo)
      const primeira = dados!.medicoes.find(m => marcadas.includes(m.id));
      if (primeira) setCriado({ id: primeira.id, titulo: primeira.titulo });
      setNovo({ ...novo, medicoes: [], oficio: "" });
      // com `aoMudar`, a pagina sobe a versao e esta leitura se refaz sozinha (uma leitura so')
      if (aoMudar) aoMudar(); else await carregar();
    } catch (e) { setErro(mensagem(e)); } finally { setOcupado(false); }
  }

  return (
    <details className="cartao">
      <summary className="cartao__cabeca">
        <IconeSeta className="icone icone--p seta" />
        <span className="cartao__titulo">Novo protocolo com várias medições</span>
      </summary>
      <form className="cartao__corpo pilha" onSubmit={criar} aria-label="Novo protocolo com várias medições">
        <fieldset className="opcoes">
          <legend className="campo__rotulo">Etapa</legend>
          {dados.etapas.map(e => (
            <label key={e.chave} className="campo--linha">
              <input type="radio" name="etapa" checked={etapaAtual === e.chave}
                onChange={() => setNovo({ ...novo, etapa: e.chave })} /> {e.rotulo}
            </label>
          ))}
        </fieldset>
        {dados.medicoes.length === 0 ? <p className="campo__nota">Nenhuma medição em andamento.</p> : (
          <fieldset className="opcoes">
            <legend className="campo__rotulo">Medições</legend>
            {dados.medicoes.map(m => (
              <label key={m.id} className="campo--linha">
                <input type="checkbox" checked={novo.medicoes.includes(m.id)}
                  onChange={ev => setNovo({ ...novo, medicoes: ev.target.checked ? [...novo.medicoes, m.id] : novo.medicoes.filter(x => x !== m.id) })} />
                {m.titulo} ({fmtCompetencia(m.competencia)})
              </label>
            ))}
          </fieldset>
        )}
        <div className="form-inline">
          {etapa?.carta && (
            <div className="campo">
              <label className="campo__rotulo" htmlFor="novo-oficio">Nº do ofício (CT)</label>
              <input id="novo-oficio" name="numero_oficio" autoComplete="off" spellCheck={false} className="entrada--16ch" required placeholder="Ex.: 301…" maxLength={40} value={novo.oficio}
                onChange={e => setNovo({ ...novo, oficio: e.target.value })} />
            </div>
          )}
          <button type="submit" className="btn" disabled={ocupado || marcadas.length === 0}>{ocupado ? "Criando…" : "Criar protocolo"}</button>
        </div>
        {erro && <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erro}</p>}
        <p className={criado ? "notas__ok" : "sr-only"} role="status">
          {criado && <>Protocolo criado. Monte e envie na{" "}
            <Link para={{ tela: "medicao", obra: contratoId, id: criado.id }} secao="protocolo">{criado.titulo}</Link>.</>}
        </p>
      </form>
    </details>
  );
}

/** "Criar protocolo" de UMA medicao, no "O que falta" da pagina dela: etapa e, quando a etapa tem carta, o
 *  numero do oficio. Primario so' quando protocolar e' o proximo passo (um primario por pagina). */
export function CriarProtocolo({ contratoId, medicaoId, dados, carregar, primario }: {
  contratoId: number; medicaoId: number; dados: Lista; carregar: () => Promise<void>; primario: boolean;
}) {
  const [etapaEscolhida, setEtapa] = useState("");
  const [oficio, setOficio] = useState("");
  const [ocupado, setOcupado] = useState(false);
  const [erro, setErro] = useState("");
  // Aberto so' quando protocolar e' o proximo passo; antes disso fica num botao, sem empurrar a secao do
  // passo que vem antes (o espelho, as notas) para baixo.
  const [aberto, setAberto] = useState(primario);
  const etapaAtual = etapaEscolhida || dados.etapas[0]?.chave || "";
  const etapa = dados.etapas.find(e => e.chave === etapaAtual);

  if (!aberto) {
    return <div><button type="button" className="btn btn--pequeno" onClick={() => setAberto(true)}>Criar protocolo</button></div>;
  }

  async function criar(ev: React.FormEvent) {
    ev.preventDefault();
    setOcupado(true); setErro("");
    try {
      await api(`/api/contratos/${contratoId}/protocolos`, { method: "POST",
        body: JSON.stringify({ etapa: etapaAtual, medicao_ids: [medicaoId], numero_oficio: etapa?.carta ? oficio : null }) });
      setOficio("");
      await carregar();
    } catch (e) { setErro(mensagem(e)); } finally { setOcupado(false); }
  }

  return (
    <form className="pilha" onSubmit={criar}>
      {dados.etapas.length > 1 && (
        <fieldset className="opcoes">
          <legend className="campo__rotulo">Etapa do protocolo</legend>
          {dados.etapas.map((e, i) => (
            <label key={e.chave} className="campo--linha">
              {/* aberto por clique: o foco vai ao primeiro campo, e nao se perde no <body> */}
              <input type="radio" name="etapa-medicao" checked={etapaAtual === e.chave} autoFocus={!primario && i === 0}
                onChange={() => setEtapa(e.chave)} /> {e.rotulo}
            </label>
          ))}
        </fieldset>
      )}
      <div className="form-inline">
        {etapa?.carta && (
          <div className="campo">
            <label className="campo__rotulo" htmlFor="medicao-oficio">Nº do ofício (CT)</label>
            <input id="medicao-oficio" name="numero_oficio" autoComplete="off" spellCheck={false} className="entrada--16ch" required placeholder="Ex.: 301…" maxLength={40} value={oficio}
              autoFocus={!primario && dados.etapas.length <= 1} onChange={e => setOficio(e.target.value)} />
          </div>
        )}
        <button type="submit" className={`btn${primario ? " btn--primario" : ""}`} disabled={ocupado}>
          {ocupado ? "Criando…" : "Criar protocolo"}
        </button>
      </div>
      {erro && <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erro}</p>}
    </form>
  );
}

/** A secao Protocolo da pagina da medicao: os protocolos que moram nela (em montagem, com o envio, e os
 *  enviados, com quando e quem), o resumo dos que moram em outra medicao, e o que a pagina acrescenta no
 *  fim (os protocolos registrados fora e o "Registrar protocolo feito fora"). */
export function ProtocolosDaMedicao({ contratoId, medicaoId, dados, erro, carregar, podeEditar, aoMudar, vazio, semCartao, children }: {
  contratoId: number; medicaoId: number; dados: Lista | null; erro?: string; carregar: () => Promise<void>; podeEditar: boolean;
  aoMudar: () => void; vazio?: React.ReactNode; children?: React.ReactNode;
  /** Na etapa 4 da pagina da medicao a moldura e' a da etapa: sem o cartao nem o titulo "Protocolo". */
  semCartao?: boolean;
}) {
  const [marcados, setMarcados] = useState<number[]>([]);
  const { daqui, deOutra } = dados ? protocolosDa(dados.protocolos, medicaoId) : { daqui: [], deOutra: [] };
  const abertos = daqui.filter(p => p.situacao !== "enviado");
  const enviados = daqui.filter(p => p.situacao === "enviado");
  const recarregar = async () => { await carregar(); aoMudar(); };
  // protocolar e' o proximo passo quando algum protocolo aberto ja esta' pronto para sair: o assinado, ou o que
  // nao tem carta (a etapa da nota) e so' espera o envio
  const protocolarEProximo = abertos.some(p => p.situacao === "assinado" || !p.tem_carta);

  const Raiz = semCartao ? "div" : "section";
  return (
    <Raiz className={semCartao ? undefined : "cartao"} id="protocolo" {...(semCartao ? {} : { "aria-labelledby": "titulo-protocolo-medicao" })}>
      {!semCartao && (
      <div className="cartao__cabeca">
        <h2 className="cartao__titulo" id="titulo-protocolo-medicao">Protocolo</h2>
      </div>
      )}
      <div className={semCartao ? "pilha" : "cartao__corpo pilha"}>
        {!dados && !erro && <p className="campo__nota">Carregando os protocolos…</p>}
        {!dados && erro && (
          <div className="form-inline">
            <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />Não foi possível ler os protocolos desta obra: {erro}</p>
            <button type="button" className="btn btn--pequeno" onClick={() => void carregar()}>Tentar de novo</button>
          </div>
        )}
        {dados && abertos.map(p => (
          <Cartao key={p.id} p={p} pecasCfg={pecasDe(dados, p)} podeEditar={podeEditar}
            aoMudar={() => void recarregar()} marcado={marcados.includes(p.id)}
            aoMarcar={v => setMarcados(v ? [...marcados, p.id] : marcados.filter(x => x !== p.id))} />
        ))}
        <EnvioProtocolos marcados={marcados} protocolos={abertos} podeEditar={podeEditar} nivel="h3" temAbertos={abertos.length > 0} proximo={protocolarEProximo}
          aoEnviado={async () => { setMarcados([]); await recarregar(); }} />
        {deOutra.map(p => (
          <p key={p.id}>
            {p.etapa_rotulo}{p.numero_oficio ? ` · ${p.numero_oficio}` : ""} ({SITUACAO[p.situacao] ?? p.situacao}):{" "}
            <Link para={{ tela: "medicao", obra: contratoId, id: p.medicoes[0].id }} secao="protocolo">{p.medicoes[0].titulo}</Link>
          </p>
        ))}
        {enviados.map(p => <Enviado key={p.id} p={p} podeEditar={podeEditar} aoMudar={() => void recarregar()} comMedicoes={p.medicoes.length > 1} />)}
        {dados && daqui.length === 0 && deOutra.length === 0 && <p className="campo__nota">{vazio ?? "Nenhum protocolo desta medição."}</p>}
        {children}
      </div>
    </Raiz>
  );
}
