import { useCallback, useEffect, useRef, useState } from "react";
import CaixaAviso from "./CaixaAviso";
import ComporEmail, { type Mensagem } from "./ComporEmail";
import ConfirmarFaltas from "./ConfirmarFaltas";
import ConfirmarRemocao from "./ConfirmarRemocao";
import { api, apiForm, ApiErro } from "./api";
import { brl } from "./formato";
import { IconeAlerta } from "./icones";
import { IconeCheck, iniciarEnvio, ItensEnvio, mensagem, notasDe, type Envio, type ListaEnvios } from "./NotasAEnviar";
import "./notas.css";
import LiberarEnvio, { envioReservado, type Reserva } from "./LiberarEnvio";
import { fmtHora } from "./tempo";

// Enviar a nota (2026-10-09): o protocolo da etapa `nota` (SINFRA) ou `unico` (demais) de um envio. Sem carta
// (SINFRA, prefeituras): o que vai no e-mail e para quem vai. Com carta (MTPAR, SES): oficio, assinar e enviar
// ao protocolo. O servidor monta a previa do e-mail e diz o que bloqueia (GET /api/notas/envio/{id}).
// Desde 16/10/2026 so' mora na etapa 4 da pagina da medicao: nao ha' mais pagina avulsa (o endereco antigo
// /notas/envio/:id abre a etapa 4 da medicao).

type Det = {
  envio: Envio; familia: string; etapa: string; situacao_protocolo: string;
  carta: { oficio: string | null; paginas: string[] } | null;
  previa: { para: string[]; copia: string[]; assunto: string; corpo: string; anexos: { nome: string; origem?: string; tamanho: number }[];
    links?: Link[] };
  bloqueio: string | null; pendencias: (string | { mensagem: string })[];
  extras: Extra[];
};
type Extra = { id: number; nome: string; tamanho: number };
type Link = { id: number; nome: string; url: string };

// issue #100 (gate Sol S3, PR #141): a lista de anexos sem depender da ordem, como a conferencia do servidor; repetidos
// contam. A mesma lista em outra ordem nao refaz a previa.
function assinaturaAnexos(anexos: { nome: string; tamanho: number }[]): string {
  const pares = anexos.map(a => [a.nome, a.tamanho] as const)
    .sort((x, y) => (x[0] < y[0] ? -1 : x[0] > y[0] ? 1 : x[1] - y[1]));
  return JSON.stringify(pares);
}

// Documentos complementares (09/10/2026): PDF a mais no envio (ex.: justificativa tecnica). Vai SEMPRE separado no
// e-mail, fora do PDF da carta; por isso anexar ou remover nao desfaz o montado/assinado. Botao ou arrastar e soltar.
// `emailMexido` (issue #28): remover remonta o e-mail com o texto montado de novo; a confirmacao avisa que o
// texto editado se perde.
function Complementares({ protocoloId, extras, links, ocupado, agir, aoMudar, emailMexido }: {
  protocoloId: number; extras: Extra[]; links: Link[]; ocupado: boolean; agir: (f: () => Promise<void>) => Promise<void>;
  aoMudar: () => Promise<void>; emailMexido: boolean;
}) {
  const aviso = emailMexido ? "O texto do e-mail que você editou será montado de novo." : undefined;
  const [sobre, setSobre] = useState(false);
  const [linkNome, setLinkNome] = useState("");
  const [linkUrl, setLinkUrl] = useState("");

  // Arquivo grande por link do OneDrive (opcao A, 09/10/2026): como a Maria fazia no Outlook ("anexar como link").
  // O link entra no corpo do e-mail e nao conta no limite de 25 MB dos anexos.
  function adicionarLink() {
    void agir(async () => {
      await api(`/api/protocolos/${protocoloId}/links`, { method: "POST",
        body: JSON.stringify({ nome: linkNome.trim(), url: linkUrl.trim() }) });
      setLinkNome(""); setLinkUrl("");
      await aoMudar();
    });
  }

  // PDF ou .zip (o zip do DocuSign com os relatorios assinados vai como veio, 09/10/2026). Outro formato nao
  // some calado: avisa.
  function anexar(arquivos: FileList | null) {
    const todos = Array.from(arquivos ?? []);
    const aceitos = todos.filter(f => /\.(pdf|zip)$/i.test(f.name));
    const recusados = todos.filter(f => !aceitos.includes(f));
    if (todos.length === 0) return;
    void agir(async () => {
      if (recusados.length > 0) throw new Error(`Só PDF ou .zip: ${recusados.map(f => f.name).join(", ")}`);
      for (const f of aceitos) {
        const fd = new FormData();
        fd.append("tipo", "anexo");
        fd.append("arquivo", f);
        await apiForm(`/api/protocolos/${protocoloId}/pecas`, fd);
      }
      await aoMudar();
    });
  }

  return (
    <div className="nota-complementares">
      <span className="campo__rotulo">Documentos complementares</span>
      {extras.length > 0 && (
        <ul className="nota-complementares__lista">
          {extras.map(x => (
            <li key={x.id}>
              <span className="nota-complementares__nome" title={x.nome}>{x.nome}</span>
              <span className="campo__nota">{Math.max(1, Math.round(x.tamanho / 1024))} KB</span>
              <ConfirmarRemocao alvo={x.nome} ocupado={ocupado} aviso={aviso}
                aoConfirmar={() => void agir(async () => {
                  await api(`/api/protocolos/${protocoloId}/pecas/${x.id}/remover`, { method: "POST", body: "{}" });
                  await aoMudar();
                })} />
            </li>
          ))}
        </ul>
      )}
      <div className={`nota-complementares__soltar${sobre ? " nota-complementares__soltar--sobre" : ""}`}
        onDragOver={ev => { ev.preventDefault(); if (!sobre) setSobre(true); }}
        onDragLeave={() => setSobre(false)}
        onDrop={ev => { ev.preventDefault(); setSobre(false); if (!ocupado) anexar(ev.dataTransfer.files); }}>
        <span>Arraste o PDF ou .zip aqui ou</span>
        <label className="btn btn--pequeno espelho__anexar">
          Anexar outro documento
          <input type="file" accept=".pdf,.zip,application/pdf,application/zip" multiple className="espelho__arquivo" disabled={ocupado}
            aria-label="Anexar outro documento em PDF ou .zip" onChange={ev => { const fs = ev.currentTarget.files; anexar(fs); ev.currentTarget.value = ""; }} />
        </label>
      </div>
      <span className="campo__nota">Vai como anexo separado no e-mail, por exemplo uma justificativa técnica ou o .zip do DocuSign com os relatórios assinados.</span>

      <span className="campo__rotulo nota-complementares__subtitulo">Arquivo grande por link do OneDrive</span>
      {links.length > 0 && (
        <ul className="nota-complementares__lista">
          {links.map(x => (
            <li key={x.id}>
              <a className="nota-complementares__nome" href={x.url} target="_blank" rel="noreferrer" title={x.url}>{x.nome}</a>
              <span className="campo__nota">link</span>
              <ConfirmarRemocao alvo={`o link ${x.nome}`} ocupado={ocupado} aviso={aviso}
                aoConfirmar={() => void agir(async () => {
                  await api(`/api/protocolos/${protocoloId}/links/${x.id}/remover`, { method: "POST", body: "{}" });
                  await aoMudar();
                })} />
            </li>
          ))}
        </ul>
      )}
      <form className="nota-complementares__link" onSubmit={ev => { ev.preventDefault(); adicionarLink(); }}>
        <label className="campo">
          <span className="campo__nota">Nome do arquivo</span>
          <input type="text" value={linkNome} maxLength={200} placeholder="Ex.: Documento juntado - 15ª Medição…"
            disabled={ocupado} onChange={ev => setLinkNome(ev.target.value)} />
        </label>
        <label className="campo nota-complementares__url">
          <span className="campo__nota">Link do OneDrive</span>
          <input type="url" name="link_url" autoComplete="off" spellCheck={false} value={linkUrl} maxLength={2100} placeholder="https://…sharepoint.com/…"
            disabled={ocupado} onChange={ev => setLinkUrl(ev.target.value)} />
        </label>
        <button type="submit" className="btn btn--pequeno" disabled={ocupado || !linkNome.trim() || !linkUrl.trim()}>Adicionar link</button>
      </form>
      <span className="campo__nota">Para arquivo que passa do limite do e-mail (25 MB somados): suba no seu OneDrive, copie o link de compartilhamento e cole aqui. O link entra no texto do e-mail. Cole um link do OneDrive ou SharePoint da Lotufo; link de outro endereço é recusado.</span>
    </div>
  );
}
type Conferencia = { ok: boolean; avisos: { codigo: string; mensagem: string }[] } | null;

type Passo = "atual" | "feito" | "futuro";

// Passo numerado: indigo no passo da vez, verde com check quando concluido, cinza quando vem depois.
function Secao({ n, titulo, passo, acoes, children }: {
  n: number; titulo: string; passo: Passo; acoes?: React.ReactNode; children: React.ReactNode;
}) {
  return (
    <section className={`nota-secao nota-secao--${passo}`} aria-labelledby={`secao-${n}`}>
      <span className={`nota-passo nota-passo--${passo}`} aria-hidden="true">{passo === "feito" ? <IconeCheck /> : n}</span>
      <div className="nota-secao__corpo">
        <div className="nota-secao__cabeca">
          <h2 className="nota-secao__titulo" id={`secao-${n}`}>{titulo}</h2>
          {acoes && <span className="nota-secao__acoes">{acoes}</span>}
        </div>
        {children}
      </div>
    </section>
  );
}

/** A etapa 4 da pagina da medicao mostra este envio; depois de enviar ela recarrega. */
export type Embutido = { aoConcluir: (aviso?: string) => void; aoTrocar: (protocoloId: number) => void;
  /** issue #148: um documento anexado num item (a FRC assinada, p. ex.) muda o que as outras etapas mostram */
  aoAnexarItem?: () => void;
  /** a lixeira do e-mail (sem texto editado) fecha o envio aberto */
  aoDescartar?: () => void };

/** `versao` (issue #100): a pagina da medicao a incrementa quando um documento da medicao muda em outra etapa; o envio
 *  e' lido de novo e, se os anexos mudaram, a previa e' refeita com o aviso. */
export default function EnviarNota({ protocoloId, embutido, podeEditar, versao = 0 }: {
  protocoloId: number; embutido: Embutido; podeEditar: boolean; versao?: number;
}) {
  const [det, setDet] = useState<Det | null>(null);
  const [erro, setErro] = useState("");
  const [erroAcao, setErroAcao] = useState("");
  const [reserva, setReserva] = useState<Reserva | null>(null);   // envio preso (409): oferece a liberacao
  const [ocupado, setOcupado] = useState(false);
  // issue #213: o aviso "ATENÇÃO" aberto pelo Enviar, com o e-mail que espera a confirmacao e a lista do que falta
  const [confirmar, setConfirmar] = useState<{ m: Mensagem; itens: string[]; mudou: boolean } | null>(null);
  const [outros, setOutros] = useState<Envio[] | null>(null);
  const [juntar, setJuntar] = useState<string[]>([]);
  const [conferencia, setConferencia] = useState<Conferencia>(null);
  const [emailMexido, setEmailMexido] = useState(false);

  // issue #100 (revisor na PR #141): os anexos mudaram depois da primeira leitura, entao o e-mail foi refeito e o
  // texto editado voltou ao padrao; a tela diz isso em vez de trocar o e-mail calada
  const [refeita, setRefeita] = useState(false);
  const anexosLidos = useRef<string | null>(null);

  const carregar = useCallback(async () => {
    try {
      const novo = await api<Det>(`/api/notas/envio/${protocoloId}`);
      const assinatura = assinaturaAnexos(novo.previa.anexos);
      if (anexosLidos.current !== null && anexosLidos.current !== assinatura) setRefeita(true);
      anexosLidos.current = assinatura;
      setDet(novo); setErro("");
    } catch (e) { setErro(mensagem(e)); }
  }, [protocoloId]);
  useEffect(() => { void carregar(); }, [carregar, versao]);   // versao: documento da medicao mudou em outra etapa

  async function agir(f: () => Promise<void>) {
    setOcupado(true); setErroAcao(""); setReserva(null);
    try { await f(); } catch (e) { setErroAcao(mensagem(e)); setReserva(envioReservado(e) ? e.corpo : null); } finally { setOcupado(false); }
  }

  if (!det) {
    return (
      <div className="pagina">
        {erro ? (
          <div className="form-inline">
            <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />Não foi possível abrir o envio: {erro}</p>
            <button type="button" className="btn btn--pequeno" onClick={() => void carregar()}>Tentar de novo</button>
          </div>
        ) : <p className="campo__nota">Carregando o envio…</p>}
      </div>
    );
  }

  const e = det.envio;
  const comCarta = det.carta !== null;
  const assinado = det.situacao_protocolo === "assinado";
  const montado = det.situacao_protocolo === "montado" || assinado;
  // issue #213: o que falta nao trava o envio; o Enviar abre o aviso "ATENÇÃO" com esta lista
  const faltam = det.pendencias.map(p => typeof p === "string" ? p : p.mensagem);
  const motivo = det.bloqueio ? det.bloqueio
    : comCarta && !assinado ? "Libera depois de anexar o assinado."
    : faltam.length > 0 ? "Falta documento: o envio pede a sua confirmação." : "";
  // so' o que trava o envio de fato (bloqueio do servidor, carta sem o assinado) apaga o botao
  const travado = !!det.bloqueio || (comCarta && !assinado);
  const paginas = det.carta?.paginas ?? [];
  // so' o desenho dos passos (com carta): montar -> assinar -> enviar
  const passoOficio: Passo = montado ? "feito" : "atual";
  const passoAssinar: Passo = assinado ? "feito" : montado ? "atual" : "futuro";
  const passoEnviar: Passo = assinado ? "atual" : "futuro";

  // issue #100 (como o protocolo na PR #92): os anexos que a previa mostrou; documento anexado depois dela (na
  // medicao, em outra aba) faz o servidor recusar o envio em vez de mandar o que ninguem conferiu
  const anexosVistos = det.previa.anexos.map(a => ({ nome: a.nome, tamanho: a.tamanho }));
  const itemMudou = () => { void carregar(); embutido.aoAnexarItem?.(); };

  // issue #213: com documento faltando, o clique em Enviar so' abre o aviso; nada sai antes do "Continuar"
  function enviar(m: Mensagem) {
    if (faltam.length > 0) setConfirmar({ m, itens: faltam, mudou: false });
    else void enviarConfirmado(m, []);
  }

  async function enviarConfirmado(m: Mensagem, confirmadas: string[]) {
    setConfirmar(null);
    setRefeita(false);
    await agir(async () => {
      try {
        await api(`/api/notas/envio/${protocoloId}/enviar`, { method: "POST", body: JSON.stringify({
          para: m.para, copia: m.copia, cco: m.cco, assunto: m.assunto, corpo: m.corpo,
          confirmadas: confirmadas.length > 0 ? confirmadas : null, anexos: anexosVistos }) });
      } catch (erro) {
        // o que falta mudou depois do aviso (ou da leitura da tela): o servidor manda a lista de agora e o aviso
        // abre de novo com ela, sem enviar nada. So' a lista da tela e' trocada: recarregar o envio inteiro podia
        // remontar o e-mail e perder o texto editado que o aviso ainda vai mandar
        if (erro instanceof ApiErro && erro.status === 422 && erro.corpo?.codigo === "CONFIRMAR_PENDENCIAS") {
          const itens: string[] = erro.corpo.pendencias ?? [];
          setDet(d => d && { ...d, pendencias: itens });
          setConfirmar({ m, itens, mudou: confirmadas.length > 0 });
          return;
        }
        // so' a recusa por anexos mudados (em outra aba, p. ex.) recarrega: a previa com os anexos de agora toma o
        // lugar. Outro erro (409 de envio em andamento, falha do Outlook) mantem o e-mail como esta' (gate Sol S2).
        // `carregar` guarda o proprio erro, entao o que sobe e' sempre o do envio.
        if (erro instanceof ApiErro && erro.status === 422 && erro.corpo?.codigo === "ANEXOS_MUDARAM") await carregar();
        throw erro;
      }
      // B-06 (10/10/2026): a pagina da medicao troca o aviso anterior ("Valor protocolado gravado.") por este
      embutido.aoConcluir(`Nota enviada às ${fmtHora(new Date().toISOString())}.`);
    });
  }

  const reiniciar = (ids: number[]) => agir(async () => {
    const pid = await iniciarEnvio(e.contrato_id, [...new Set(ids)].sort((a, b) => a - b));
    setOutros(null); setJuntar([]);
    if (pid === protocoloId) await carregar();
    else embutido.aoTrocar(pid);
  });

  const abrirJuntar = () => agir(async () => {
    const l = await api<ListaEnvios>("/api/notas/a-enviar");
    setOutros(l.envios.filter(x => x.contrato_id === e.contrato_id && x.chave !== e.chave));
  });

  function anexarAssinado(input: HTMLInputElement) {
    const f = input.files?.[0];
    input.value = "";
    if (!f) return;
    const fd = new FormData();
    fd.append("arquivo", f);
    void agir(async () => {
      const r = await apiForm<{ conferencia: Conferencia }>(`/api/protocolos/${protocoloId}/assinado`, fd);
      setConferencia(r.conferencia ?? null);
      await carregar();
    });
  }

  // issue #213: a justificativa escrita deu lugar ao aviso "ATENÇÃO" do Enviar; aqui fica so' a lista do que falta
  const faltamBloco = faltam.length > 0 && (
    <div className="campo nota-justificativa">
      <span className="campo__rotulo">O que falta</span>
      <ul className="lista-simples">
        {faltam.map((p, i) => <li key={i} className="notas__diverge">{p}</li>)}
      </ul>
      <span className="campo__nota">Dá para enviar assim: o Enviar pede a sua confirmação antes de o e-mail sair.</span>
    </div>
  );

  const complementares = (
    <Complementares protocoloId={protocoloId} extras={det.extras ?? []} links={det.previa.links ?? []} ocupado={ocupado}
      agir={agir} aoMudar={carregar} emailMexido={emailMexido} />
  );

  const email = (
    <>
      {/* a chave inclui os complementares: anexar ou remover refaz o texto ("... e documento complementar.") */}
      {/* issue #100: e os anexos da previa: NF ou FRC anexada, juntar ou separar fecham a previa e abrem a nova */}
      <ComporEmail key={`${protocoloId}-${det.situacao_protocolo}-${(det.extras ?? []).map(x => x.id).join(".")}-${(det.previa.links ?? []).map(x => x.id).join(".")}-${assinaturaAnexos(anexosVistos)}`} ocupado={ocupado} rotuloEnviar="Enviar o e-mail"
        bloqueado={travado} anexos={det.previa.anexos}
        inicial={{ para: det.previa.para, copia: det.previa.copia, cco: [], assunto: det.previa.assunto, corpo: det.previa.corpo }}
        aoMexer={setEmailMexido} aoEnviar={enviar} aoDescartar={() => embutido.aoDescartar?.()} />
      {refeita && <CaixaAviso nivel="atencao" role="status">A prévia foi refeita com os anexos de agora e o texto voltou ao padrão; confira antes de enviar.</CaixaAviso>}
      <p className="campo__nota">Texto montado com os anexos prontos; você pode editar. O e-mail sai da sua conta Microsoft.</p>
    </>
  );

  const classe = "nota-envio notas-v3 nota-envio--embutido";

  // B-09 (10/10/2026): a diretoria chegava ao e-mail com "Enviar a nota" habilitado e recebia 403; quem so'
  // consulta ve o que vai no envio, sem as acoes
  if (!podeEditar) {
    return (
      <div className={classe}>
        {det.bloqueio && <CaixaAviso nivel="critico" role="alert">Envio bloqueado: {det.bloqueio}</CaixaAviso>}
        <Secao n={1} titulo="O que vai no e-mail" passo="atual">
          <ItensEnvio itens={e.itens} aoMudar={() => void carregar()} podeEditar={false} />
        </Secao>
        <p className="campo__nota">Seu perfil só consulta esta tela: o envio é da engenharia ou da administração.</p>
      </div>
    );
  }

  return (
    <>
      <div className={classe}>
        {det.bloqueio && <CaixaAviso nivel="critico" role="alert">Envio bloqueado: {det.bloqueio}</CaixaAviso>}
        {erroAcao && <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erroAcao}</p>}
        {confirmar && <ConfirmarFaltas itens={confirmar.itens} mudou={confirmar.mudou} aoCancelar={() => setConfirmar(null)}
          aoContinuar={() => void enviarConfirmado(confirmar.m, confirmar.itens)} />}
        {reserva && <LiberarEnvio tabela="protocolos" id={protocoloId} reserva={reserva}
          aoLiberar={() => { setErroAcao(""); void carregar(); }} />}

        {!comCarta ? (
          <>
            <Secao n={1} titulo="O que vai no e-mail" passo="atual" acoes={<>
              <button type="button" className="btn btn--pequeno" disabled={ocupado} onClick={() => void abrirJuntar()}>Juntar outra nota desta obra</button>
              {e.medicao_ids.length > 1 && (
                <button type="button" className="btn btn--pequeno" disabled={ocupado} title="Este envio fica só com a primeira medição; as outras voltam para a lista"
                  onClick={() => void reiniciar([e.medicao_ids[0]])}>Separar</button>
              )}
            </>}>
              {outros && (
                <fieldset className="opcoes">
                  <legend className="campo__rotulo">Notas desta obra que ainda não foram enviadas</legend>
                  {outros.length === 0 ? <p className="campo__nota">Não há outra nota emitida desta obra para juntar.</p> : outros.map(o => (
                    <label key={o.chave} className="campo--linha">
                      <input type="checkbox" checked={juntar.includes(o.chave)}
                        onChange={ev => setJuntar(ev.target.checked ? [...juntar, o.chave] : juntar.filter(c => c !== o.chave))} />
                      {o.descricao} · {notasDe(o)} · <span className="num">{brl(o.valor_centavos)}</span>
                    </label>
                  ))}
                  <div className="form-inline">
                    {outros.length > 0 && (
                      <button type="button" className="btn btn--pequeno btn--primario" disabled={ocupado || juntar.length === 0}
                        onClick={() => void reiniciar([...e.medicao_ids, ...outros.filter(o => juntar.includes(o.chave)).flatMap(o => o.medicao_ids)])}>
                        Juntar neste e-mail
                      </button>
                    )}
                    <button type="button" className="btn btn--pequeno" onClick={() => { setOutros(null); setJuntar([]); }}>Cancelar</button>
                  </div>
                </fieldset>
              )}
              <ItensEnvio itens={e.itens} aoMudar={itemMudou} />
              {complementares}
              {faltamBloco}
            </Secao>
            <Secao n={2} titulo="Para quem vai" passo="futuro">{email}</Secao>
          </>
        ) : (
          <>
            <Secao n={1} titulo="Ofício" passo={passoOficio}>
              {det.carta?.oficio && <p>Ofício <span className="nota-mono">{det.carta.oficio}</span></p>}
              {paginas.length > 0 && (
                <div>
                  <p className="campo__nota">PDF único, {paginas.length} {paginas.length === 1 ? "página" : "páginas"}, nesta ordem:</p>
                  <ol className="lista-simples nota-paginas">{paginas.map((p, i) => <li key={i}>{p}</li>)}</ol>
                </div>
              )}
              <ItensEnvio itens={e.itens} aoMudar={itemMudou} />
              {complementares}
              {faltamBloco}
              {det.situacao_protocolo === "rascunho" && (
                <div className="form-inline">
                  <button type="button" className="btn btn--primario" disabled={ocupado || !!det.bloqueio}
                    onClick={() => void agir(async () => {
                      await api(`/api/protocolos/${protocoloId}/montar`, { method: "POST", body: JSON.stringify({}) });
                      await carregar();
                    })}>{ocupado ? "Montando…" : "Montar"}</button>
                </div>
              )}
            </Secao>
            <Secao n={2} titulo="Assinar a carta" passo={passoAssinar}>
              <p>O sistema monta o PDF{paginas.length ? ` de ${paginas.length} páginas` : ""}. Baixe, assine no DocuSign e anexe o PDF assinado.</p>
              <div className="form-inline nota-assinar">
                {montado ? <a className="btn" href={`/api/protocolos/${protocoloId}/pacote`}>Baixar para assinar</a>
                  : <span className="campo__nota">Monte o ofício para baixar.</span>}
                {montado && (
                  <label className={`btn espelho__anexar${assinado ? "" : " btn--primario"}`}>
                    {assinado ? "Trocar o assinado" : "Anexar o assinado"}
                    <input type="file" accept="application/pdf" className="espelho__arquivo" disabled={ocupado}
                      aria-label="Anexar o PDF assinado" onChange={ev => anexarAssinado(ev.currentTarget)} />
                  </label>
                )}
              </div>
              {conferencia && !conferencia.ok && (
                <ul className="lista-simples">{conferencia.avisos.map(a => <li key={a.codigo} className="notas__diverge">{a.mensagem}</li>)}</ul>
              )}
              {assinado ? <p className="notas__ok">Assinado conferido.</p>
                : <p className="campo__nota">O sistema confere se o assinado tem as mesmas {paginas.length || ""} páginas.</p>}
            </Secao>
            <Secao n={3} titulo={`Enviar ao protocolo${e.grupo ? ` da ${e.grupo}` : ""}`} passo={passoEnviar}>{email}</Secao>
          </>
        )}

        <div className="nota-rodape">
          {motivo && <p className={`nota-rodape__motivo nota-rodape__motivo--${det.bloqueio ? "bloqueio" : faltam.length > 0 ? "atencao" : "neutro"}`}>{motivo}</p>}
        </div>
        {e.familia === "mtpar" && (
          <p className="nota-porfora__dica">Depois do envio a nota vai para Aguardando pagamento sem o nº do protocolo do órgão; o número e o comprovante se registram aqui, na etapa 4, depois do envio.</p>
        )}
      </div>
    </>
  );
}
