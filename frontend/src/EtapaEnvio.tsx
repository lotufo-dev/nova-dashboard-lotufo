import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import CaixaAviso from "./CaixaAviso";
import EnviarNota from "./EnviarNota";
import { brl } from "./formato";
import { IconeAlerta } from "./icones";
import Janela from "./Janela";
import type { Metade } from "./medicao";
import { IconeCheck, iniciarEnvio, ListaCertidoes, mensagem, naturezaDoEnvio, pedeOficio, resumoDe, useCertidoes,
         type Envio, type ItemCertidao, type ListaEnvios } from "./NotasAEnviar";
import RegistrarFora from "./RegistrarFora";
import Selo from "./Selo";

// Etapa 4 da pagina da medicao (#152, opcao B): o envio ao orgao numa tabela de uma linha por envio -- um so' na
// SINFRA e na Pref. VG (medicao e reajuste no mesmo e-mail), dois lado a lado na MTPAR e na SES --, com o motivo ao
// lado do botao ("Enviar a nota" fica ativo; so' bloqueio desabilita). O envio aberto (o e-mail montado, o oficio, a
// FRC assinada) desce sob a tabela; as certidoes com a validade de cada uma e o "Registrar envio feito fora do
// sistema" ficam no fim. #514 (passo 5 da pagina da obra): em cima, a faixa verde/vermelha e os cartoes Notas
// fiscais, Certidoes e Documentos; a tabela dos envios vira o cartao "E-mail ao órgão", com o "Já enviei por fora".

/** Os envios da lista de Notas a enviar que contem alguma destas medicoes, relidos a cada acao da pagina. */
export function useEnvios(ids: number[]) {
  const [envios, setEnvios] = useState<Envio[] | null>(null);
  const [erro, setErro] = useState("");
  const chave = ids.join(",");
  const alvo = useMemo(() => chave.split(",").filter(Boolean).map(Number), [chave]);
  const leitura = useRef(0);   // so' a leitura mais nova vale: uma resposta atrasada nao desfaz o que a acao acabou de mudar
  const carregar = useCallback(async () => {
    if (alvo.length === 0) return;
    const minha = ++leitura.current;
    try {
      const l = await api<ListaEnvios>("/api/notas/a-enviar");
      if (minha !== leitura.current) return;
      setEnvios(l.envios.filter(e => e.medicao_ids.some(id => alvo.includes(id))));
      setErro("");
    } catch (x) { if (minha === leitura.current) { setErro(mensagem(x)); setEnvios([]); } }
  }, [alvo]);
  useEffect(() => { void carregar(); }, [carregar]);
  return { envios, erro, carregar };
}

function SeloDocs({ e }: { e: Envio }) {
  const r = resumoDe(e);
  if (r.situacao === "pronto" && notasDivergentes(e).length > 0) return <Selo classe="selo--acao">Nota divergente</Selo>;
  return <Selo classe={r.nivel}>{r.situacao === "pronto" ? "Completo" : r.selo}</Selo>;
}

// Issue #562: o nome do campo conferido, o mesmo de notas.NOME_CAMPO no servidor
const CAMPO_NOTA: Record<string, string> = {
  valor: "Valor", iss: "ISS", inss: "INSS", irrf: "IRRF", ibs: "IBS", cbs: "CBS", liquido: "Líquido", municipio: "Município",
  tomador: "Tomador",
};

/** #562: as divergencias de grau "divergente" (as que pedem o motivo no envio). */
const notasDivergentes = (e: Envio) => (e.divergencias ?? []).filter(d => d.grau === "divergente");

const valorConferido = (v: number | string | null) => (typeof v === "number" ? brl(v) : v ?? "—");

/** #562: a nota que diverge do espelho, campo a campo (espelho x nota), e a nota maior que a medicao. A diferenca so'
 *  de arredondamento (1 centavo num tributo) aparece em atencao; o resto, em critico. */
export function ConferenciaNotas({ envios }: { envios: Envio[] }) {
  const graves = envios.flatMap(notasDivergentes);
  const leves = envios.flatMap(e => (e.divergencias ?? []).filter(d => d.grau === "arredondamento"));
  const acima = envios.flatMap(e => e.acima_da_medicao ?? []);
  if (graves.length === 0 && leves.length === 0 && acima.length === 0) return null;
  const numeros = [...new Set(graves.map(d => String(d.numero)))];
  return (
    <div className="pilha" aria-label="Conferência das notas com o espelho">
      {numeros.length > 0 && (
        <CaixaAviso nivel="critico" role="status">
          NF {numeros.join(", ")} diverge{numeros.length > 1 ? "m" : ""} do espelho
        </CaixaAviso>
      )}
      {graves.length > 0 && (
        <div className="med-caixa">
          <table className="tabela">
            <thead><tr><th scope="col">Nota</th><th scope="col">Campo</th><th scope="col" className="col-num">Espelho</th><th scope="col" className="col-num">Nota</th></tr></thead>
            <tbody>
              {graves.map(d => (
                <tr key={`${d.nota_id}-${d.campo}`}>
                  <td data-rotulo="Nota">NF {d.numero}</td>
                  <td data-rotulo="Campo">{CAMPO_NOTA[d.campo] ?? d.campo}</td>
                  <td data-rotulo="Espelho" className="col-num num">{valorConferido(d.espelho)}</td>
                  <td data-rotulo="Nota" className="col-num num">{valorConferido(d.nota)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {acima.map(x => (
        <CaixaAviso key={`acima-${x.nota_id}`} nivel="critico" role="status">
          NF {x.numero} de {brl(x.alocado_centavos)} é maior que a medição ({brl(x.medicao_centavos)})
        </CaixaAviso>
      ))}
      {leves.map(d => (
        <CaixaAviso key={`leve-${d.nota_id}-${d.campo}`} nivel="atencao" role="status">
          NF {d.numero}: {CAMPO_NOTA[d.campo] ?? d.campo} com diferença de arredondamento ({valorConferido(d.espelho)} no espelho, {valorConferido(d.nota)} na nota)
        </CaixaAviso>
      ))}
    </div>
  );
}

/** A natureza ao lado da NF so' quando o envio mistura medicao e reajuste: e' o que diz qual nota e' qual. */
function CelulaNotas({ e }: { e: Envio }) {
  const mistura = new Set(e.notas.map(n => n.natureza === "reajuste")).size > 1;
  return (
    <div className="envios__nfs">
      {e.notas.map(n => (
        <span key={`${n.numero}-${n.natureza}`}>NF {n.numero}{mistura && <> <small>· {n.natureza === "reajuste" ? "reajuste" : "medição"}</small></>}</span>
      ))}
    </div>
  );
}

/** #514: o que trava ou falta no envio, numa frase so' por envio (vazio = pronto). */
export function faltasDo(e: Envio): string[] {
  if (e.situacao === "pronto" || e.situacao === "a_pedido") return [];
  const r = resumoDe(e);
  if (e.situacao === "esperando") return [r.motivo.replace(/\.$/, "")];
  // a certidao que so' esta' para vencer avisa, nao falta (resumoDe a trata como pronta): fica fora da faixa
  const itens = (e.aviso ?? "").split(" · ").map(x => x.trim()).filter(x => x && !/vence (hoje|em \d+ dias?)$/.test(x));
  // "Falta a regularidade" vira "a regularidade" (a faixa ja' diz "Falta"); nome de empresa e sigla ficam como estao
  const minuscula = (x: string) => /^(A|O|As|Os|Sem|Pacote|Esperando|Envio)\b/.test(x) ? x.charAt(0).toLowerCase() + x.slice(1) : x;
  if (itens.length > 0) return itens.map(x => minuscula(x.replace(/^Falta\s+/, "")));
  return [r.selo.charAt(0).toLowerCase() + r.selo.slice(1)];
}

/** #514: a faixa do passo Envio da nota: verde "Tudo pronto para enviar" ou vermelha com o que falta (a certidao
 *  vencida e' o que desliga o botao; o motivo vem aqui). */
export function FaixaEnvio({ envios }: { envios: Envio[] }) {
  const faltas = envios.map(e => ({ e, f: faltasDo(e) })).filter(x => x.f.length > 0);
  // #562: com nota divergente nada esta' "pronto": a caixa da conferencia (logo abaixo) diz qual nota diverge
  if (faltas.length === 0 && envios.some(e => notasDivergentes(e).length > 0)) return null;
  if (faltas.length === 0) {
    return <div className="envio-faixa envio-faixa--ok" role="status"><span className="envio-faixa__marca" aria-hidden="true"><IconeCheck /></span>Tudo pronto para enviar</div>;
  }
  const total = faltas.reduce((t, x) => t + x.f.length, 0);
  const lista = faltas.map(x => `${envios.length > 1 ? `${x.e.descricao}: ` : ""}${x.f.join(", ")}`).join("; ");
  return (
    <div className="envio-faixa envio-faixa--falta" role="status">
      <IconeAlerta className="icone" />
      <span>Falta{total === 1 ? "" : "m"} {total} {total === 1 ? "item" : "itens"} para enviar: {lista}</span>
    </div>
  );
}

type Linha = { chave: string; texto: React.ReactNode; ok: boolean; detalhe?: string | null; valor?: number | null };

function Cartao({ titulo, linhas, children }: { titulo: string; linhas: Linha[]; children?: React.ReactNode }) {
  const ok = linhas.filter(l => l.ok).length;
  return (
    <section className="cartao med-painel envio-cartao" aria-label={titulo}>
      <h3 className="med-painel__titulo">{titulo}
        {linhas.length > 0 && <Selo classe={ok === linhas.length ? "selo--ok" : "selo--acao"}>{`${ok} de ${linhas.length}`}</Selo>}</h3>
      {children ?? (linhas.length === 0 ? <p>—</p> : (
        <ul className="envio-itens">
          {linhas.map(l => (
            <li key={l.chave} className={l.ok ? "envio-item--ok" : "envio-item--falta"}>
              <span className="envio-item__marca" aria-hidden="true">{l.ok ? <IconeCheck /> : "!"}</span>
              <span className="envio-item__texto">{l.texto}{!l.ok && l.detalhe && <small>{l.detalhe}</small>}</span>
              {l.valor !== undefined && l.valor !== null && <span className="num">{brl(l.valor)}</span>}
            </li>
          ))}
        </ul>
      ))}
    </section>
  );
}

/** #514: os tres cartoes do que vai junto: Notas fiscais (as NFs, a FRC assinada e as notas das consorciadas),
 *  Certidoes (por empresa no consorcio, com a validade de cada uma) e Documentos (a regularidade e o resto). */
export function CartoesEnvio({ envios, certidoes }: { envios: Envio[]; certidoes: ItemCertidao[] | null }) {
  const itens = envios.flatMap(e => e.itens.map(i => ({ ...i, chave: `${e.chave}|${i.chave}` })));
  const base = (c: string) => c.split("|")[1];
  const mistura = new Set(envios.flatMap(e => e.notas.map(n => n.natureza === "reajuste"))).size > 1;
  const notas: Linha[] = [
    ...envios.flatMap(e => e.notas.map(n => ({ chave: `${e.chave}|nf-${n.numero}-${n.natureza}`, ok: true, valor: n.valor_centavos,
      texto: <>NF {n.numero}{mistura ? ` · ${n.natureza === "reajuste" ? "reajuste" : "medição"}` : ""}{n.municipio ? ` · ${n.municipio}` : ""}</> }))),
    // sem o detalhe do servidor: ele fala em etapa antiga e "anexe aqui", e a acao mora no e-mail aberto (revisor, PR #555)
    ...itens.filter(i => (base(i.chave) === "notas" && i.estado !== "ok") || base(i.chave).startsWith("frc:") || base(i.chave) === "consorcio")
      .map(i => ({ chave: i.chave, ok: i.estado === "ok", texto: base(i.chave) === "notas" ? "Falta a nota fiscal" : i.rotulo })),
  ];
  const certs = itens.filter(i => base(i.chave).startsWith("certidoes:"));
  const certLinhas: Linha[] = certs.map(i => ({ chave: i.chave, ok: i.estado === "ok" || i.estado === "aviso", texto: i.rotulo, detalhe: i.detalhe }));
  const docs = itens.filter(i => !["notas", "consorcio"].includes(base(i.chave)) && !base(i.chave).startsWith("frc:") && !base(i.chave).startsWith("certidoes:"))
    .map(i => ({ chave: i.chave, ok: i.estado === "ok" || i.estado === "aviso", texto: <>{i.rotulo}{i.estado === "ok" && i.detalhe ? ` de ${i.detalhe}` : ""}</>, detalhe: i.detalhe }));
  const varias = new Set(certs.map(i => i.entidade_id)).size > 1 || new Set((certidoes ?? []).map(i => i.entidade_id)).size > 1;
  return (
    <div className="envio-cartoes">
      <Cartao titulo="Notas fiscais" linhas={notas} />
      <Cartao titulo={varias ? "Certidões por empresa" : "Certidões"} linhas={certLinhas}>
        {certidoes && certidoes.length > 0 ? <ListaCertidoes itens={certidoes} semTitulo /> : undefined}
      </Cartao>
      <Cartao titulo="Documentos" linhas={docs} />
    </div>
  );
}

export function EtapaEnvio({ medicaoId, envios, erro, recarregarEnvios, podeEditar, versaoDocs, aoAnexarItem, aoMudar, pronta, aoSemAOutra }: {
  medicaoId: number; envios: Envio[] | null; erro: string; recarregarEnvios: () => Promise<void>;
  podeEditar: boolean; versaoDocs: number; aoAnexarItem: () => void;
  /** depois de enviar ou registrar por fora: a pagina le tudo de novo e mostra o aviso */
  aoMudar: (aviso?: string) => void;
  pronta: Metade | null; aoSemAOutra: () => void;
}) {
  const [aberto, setAberto] = useState<number | null>(null);        // protocolo do envio aberto
  const [oficioDe, setOficioDe] = useState<Envio | null>(null);
  const [oficio, setOficio] = useState("");
  const [fora, setFora] = useState(false);
  const [ocupado, setOcupado] = useState(false);
  const [erroAcao, setErroAcao] = useState("");
  const certidoes = useCertidoes(envios?.[0]?.contrato_id ?? 0, envios?.[0] ? naturezaDoEnvio(envios[0]) : "execucao");

  if (envios === null) return <p className="campo__nota">Conferindo o envio…</p>;
  if (erro) return <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />Não foi possível ler o envio: {erro}</p>;
  if (envios.length === 0) {
    return <p className="campo__nota">Esta medição não aparece em Notas a enviar: confira se a obra tem o órgão no cadastro.</p>;
  }

  async function iniciar(e: Envio, numeroOficio?: string) {
    setOcupado(true); setErroAcao("");
    try {
      const pid = await iniciarEnvio(e.contrato_id, e.medicao_ids, numeroOficio);
      await recarregarEnvios();
      setAberto(pid); setOficioDe(null); setOficio("");
    } catch (x) { setErroAcao(mensagem(x)); } finally { setOcupado(false); }
  }
  function enviar(e: Envio) {
    if (e.protocolo_id) { setAberto(aberto === e.protocolo_id ? null : e.protocolo_id); return; }
    // orgao com carta e envio ainda nao comecado: o numero do oficio se pede uma vez so'
    if (pedeOficio(e.familia)) { setOficio(""); setOficioDe(e); return; }
    void iniciar(e);
  }

  const registraveis = envios.filter(e => e.situacao !== "bloqueado" && e.situacao !== "esperando");
  const envioAberto = envios.find(e => e.protocolo_id !== null && e.protocolo_id === aberto) ?? null;
  const pidAberto = envioAberto?.protocolo_id ?? null;

  return (
    <div className="pilha">
      <FaixaEnvio envios={envios} />
      <ConferenciaNotas envios={envios} />
      <CartoesEnvio envios={envios} certidoes={certidoes} />
      <section className="cartao med-painel" aria-labelledby="email-orgao-titulo">
      <h3 className="med-painel__titulo" id="email-orgao-titulo">E-mail ao órgão</h3>
      {erroAcao && <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erroAcao}</p>}
      <div className="med-caixa">
        <table className="tabela envios">
          <thead>
            <tr><th>Envio</th><th>Nota fiscal</th><th className="col-num">Valor</th><th>Documentos</th><th><span className="sr-only">Ação</span></th></tr>
          </thead>
          <tbody>
            {envios.map(e => {
              const r = resumoDe(e);
              const aberta = e.protocolo_id !== null && e.protocolo_id === pidAberto;
              const esperando = e.situacao === "esperando";
              return (
                <tr key={e.chave} className={aberta ? "envios--aberto" : ""}>
                  <td data-rotulo="Envio"><strong>{e.descricao}</strong></td>
                  <td data-rotulo="Nota fiscal"><CelulaNotas e={e} /></td>
                  <td data-rotulo="Valor" className="col-num">{brl(e.valor_centavos)}</td>
                  <td data-rotulo="Documentos"><SeloDocs e={e} /></td>
                  <td>
                    <div className="envios__acao">
                      {r.motivo && <span className={`envios__motivo envios__motivo--${r.tom}`}>{r.motivo}</span>}
                      {podeEditar && (esperando
                        ? (pronta && <button type="button" className="btn btn--pequeno" onClick={aoSemAOutra}>
                            {pronta.tipo === "execucao" ? "Enviar a medição sem o reajuste…" : "Enviar o reajuste sem a medição…"}</button>)
                        : <button type="button" className="btn btn--primario btn--envio" disabled={e.situacao === "bloqueado" || ocupado}
                            aria-expanded={aberta} onClick={() => enviar(e)}>
                            {aberta ? "Fechar o envio" : ocupado ? "Abrindo…" : "Enviar a nota"}</button>)}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {envioAberto && pidAberto && (
        <div className="notas-v3 med-envio" id="envio-aberto" aria-label="Envio aberto">
          <div className="med-envio__cabeca">
            <h3>{envioAberto.descricao} · <span className="nota-mono">{brl(envioAberto.valor_centavos)}</span></h3>
            <button type="button" className="btn btn--pequeno" onClick={() => setAberto(null)}>Fechar</button>
          </div>
          <EnviarNota key={pidAberto} protocoloId={pidAberto} podeEditar={podeEditar} versao={versaoDocs}
            embutido={{ aoConcluir: aoMudar, aoTrocar: pid => { void recarregarEnvios().then(() => setAberto(pid)); }, aoAnexarItem, aoDescartar: () => setAberto(null) }} />
        </div>
      )}

      {podeEditar && registraveis.length > 0 && (
        <div className="nota-porfora">
          <button type="button" className="botao-link" onClick={() => setFora(true)}>Já enviei por fora</button>
        </div>
      )}
      </section>
      {fora && <RegistrarFora envios={registraveis} medicaoId={medicaoId} aoRecarregar={() => aoMudar()} aoFechar={() => setFora(false)}
        aoFeito={aviso => { setFora(false); aoMudar(aviso); }} />}
      {oficioDe && (
        <Janela titulo="Número do ofício desta nota" aoFechar={() => setOficioDe(null)}>
          <form className="pilha" onSubmit={ev => { ev.preventDefault(); if (oficio.trim()) void iniciar(oficioDe, oficio); }}>
            <div className="campo">
              <label className="campo__rotulo" htmlFor="oficio-numero">Nº do ofício</label>
              <input id="oficio-numero" name="numero_oficio" type="text" autoFocus autoComplete="off" spellCheck={false} maxLength={40} className="entrada--media entrada--num" placeholder="Ex.: 361…"
                value={oficio} onChange={ev => setOficio(ev.target.value)} />
            </div>
            <div className="iniciar__rodape">
              <button type="submit" className="btn btn--primario" disabled={ocupado || !oficio.trim()}>{ocupado ? "Abrindo…" : "Começar o envio"}</button>
              <button type="button" className="btn" onClick={() => setOficioDe(null)}>Cancelar</button>
            </div>
          </form>
        </Janela>
      )}
    </div>
  );
}
