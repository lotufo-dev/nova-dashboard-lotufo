import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import EnviarNota from "./EnviarNota";
import { brl } from "./formato";
import { IconeAlerta } from "./icones";
import Janela from "./Janela";
import type { Metade } from "./medicao";
import { iniciarEnvio, ListaCertidoes, mensagem, naturezaDoEnvio, pedeOficio, resumoDe, useCertidoes,
         type Envio, type ListaEnvios } from "./NotasAEnviar";
import RegistrarFora from "./RegistrarFora";
import Selo from "./Selo";

// Etapa 4 da pagina da medicao (#152, opcao B): o envio ao orgao numa tabela de uma linha por envio -- um so' na
// SINFRA e na Pref. VG (medicao e reajuste no mesmo e-mail), dois lado a lado na MTPAR e na SES --, com o motivo ao
// lado do botao ("Enviar a nota" fica ativo; so' bloqueio desabilita). O envio aberto (o e-mail montado, o oficio, a
// FRC assinada) desce sob a tabela; as certidoes com a validade de cada uma e o "Registrar envio feito fora do
// sistema" ficam no fim.

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
  return <Selo classe={r.nivel}>{r.situacao === "pronto" ? "Completo" : r.selo}</Selo>;
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

      {certidoes && certidoes.length > 0 && <div className="med-bloco"><ListaCertidoes itens={certidoes} /></div>}

      {podeEditar && registraveis.length > 0 && (
        <div className="med-bloco notas-v3">
          <div className="nota-porfora">
            <button type="button" className="botao-link" onClick={() => setFora(true)}>Registrar envio feito fora do sistema</button>
          </div>
        </div>
      )}
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
