import { useCallback, useEffect, useState } from "react";
import { api, mensagemDeErro } from "./api";
import { CartaoPleito, NovoPleito, cadeiaDoPleito, type Pleito, type TipoPleito } from "./FluxoOficio";
import CaixaAviso from "./CaixaAviso";
import { IconeAlerta } from "./icones";
import { focarPorId } from "./foco";
import { desfechoDoPedido, type InstrumentoPrazo } from "./obra";
import { Link } from "./Link";
import { fmtDataPura } from "./tempo";
import Selo from "./Selo";

// Aba Prazos da obra (bloco 7; spec §7.3 e §7.4; NAVEGACAO.md › Obra): a situacao do prazo (execucao, vigencia,
// folga, endosso e o pedido de prorrogacao em curso, com as linhas que levam aos instrumentos em Contrato), os
// pedidos e cartas (cada oficio com o desfecho, e o historico que entra na carta) e o encerramento. A regra mora
// em `app/prazos.py`; a lista dos instrumentos, o cadastro e os fiscais moram na aba Contrato.

type Instrumento = InstrumentoPrazo & { nova_execucao_fim: string | null; nova_vigencia_fim: string | null };
type Situacao = {
  execucao_fim: string | null; dias_execucao: number | null; vigencia_fim: string | null; dias_vigencia: number | null;
  vigencia_automatica: boolean; folga: { exigida: number | null; real: number | null; quebrada: boolean };
  paralisacao: { desde: string; numero: string | null } | null;
  // o pedido de prorrogacao enviado que nenhum instrumento atendeu ainda (o servidor decide)
  pedido?: { id: number; numero_oficio: string | null; enviado_em: string } | null;
  endosso: { instrumento: string | null; assinado_em: string | null; dias: number | null; entregue: boolean } | null;
  encerramento: { desde: string; marcos: Record<string, string>; conclusao_comunicada: boolean } | null;
  instrumentos: Instrumento[];
};

const MARCOS: [string, string][] = [["conclusao", "Conclusão"], ["provisorio", "Recebimento provisório"],
  ["definitivo", "Recebimento definitivo"], ["baixa_garantia", "Baixa da garantia"]];

function data(iso: string | null | undefined): string {
  return iso ? fmtDataPura(iso.slice(0, 10)) : "—";
}
// espaco nao separavel: "3 dias" nao quebra no meio da coluna do resumo
function dias(n: number): string {
  return `${n}\u00a0${n === 1 ? "dia" : "dias"}`;
}
// prazo vencido pede acao: vira selo so' quando acontece (quanto falta nao se escreve)
function SeloVencida({ d }: { d: number | null }) {
  return d !== null && d < 0 ? <Selo classe="selo--acao">vencida</Selo> : null;
}

/** O desfecho de um ofício enviado (F-71): o selo diz o que aconteceu (atendido ou sem instrumento); a data do
 *  envio e o resto vão para o texto de apoio. */
export type DesfechoPleito = { classe: string; texto: string; forte?: boolean; partes: string[] };

/** Ofício que vira linha dentro do cartão (F-74): o que já foi enviado e o que veio do cadastro. O que ainda se
 *  trabalha (ou foi descartado, com a carta) segue no CartaoPleito, que traz o formulário. */
export function pleitoEmLinha(p: Pleito): boolean {
  return p.situacao === "enviado" || p.origem === "cadastro";
}

/** A data do envio, que identifica o oficio: "enviado em DD/MM/AAAA". */
export function partesDoEnvio(p: Pleito): string[] {
  if (p.situacao !== "enviado" || !p.enviado_em) return [];
  return [`enviado em ${fmtDataPura(p.enviado_em.slice(0, 10))}`];
}

/** Um ofício como seção do cartão pai: título, o selo do desfecho e o apoio. Sem formulário, sem cartão irmão. */
export function LinhaPleito({ p, desfecho, contexto }: { p: Pleito; desfecho: DesfechoPleito; contexto?: string }) {
  return (
    <section className="pleito-linha" aria-labelledby={`pleito-${p.id}`} id={`oficio-${p.id}`}>
      <div className="pleito-linha__cabeca">
        <h3 className="cartao__titulo" id={`pleito-${p.id}`}>
          {p.rotulo}{contexto ? ` (${contexto})` : ""}{p.numero_oficio ? ` · ${p.numero_oficio}` : ""}
        </h3>
        <Selo classe={desfecho.classe} forte={desfecho.forte}>{desfecho.texto}</Selo>
      </div>
      {desfecho.partes.length > 0 && <p className="campo__nota">{desfecho.partes.join(" · ")}</p>}
      {/* issue #277: a cadeia do pleito de reajuste (o que ele reitera e quem o reiterou) */}
      {cadeiaDoPleito(p).map((t, i) => <p key={i} className="campo__nota">{t}</p>)}
      {p.situacao === "enviado" && p.envio_justificativa && (
        <CaixaAviso nivel="atencao">Enviado com ressalva: {p.envio_justificativa}</CaixaAviso>
      )}
    </section>
  );
}

export default function Prazos({ contratoId, podeEditar }: { contratoId: number; podeEditar: boolean }) {
  const [dados, setDados] = useState<{ situacao: Situacao; historico: string; pleitos: Pleito[] } | null>(null);
  // "sem instrumento ha N dias": o numero vem do servidor (a lista de obras, mudanca A9), nao de uma conta da tela
  const [diasPedido, setDiasPedido] = useState<number | null>(null);
  const [erro, setErro] = useState("");
  const [novo, setNovo] = useState<TipoPleito | null>(null);
  // para onde o foco vai quando o formulario fecha: o botao que o abriu (cancelar) ou o oficio criado
  const [foco, setFoco] = useState<string | null>(null);

  const carregar = useCallback(async () => {
    try {
      const d = await api<{ situacao: Situacao; historico: string; pleitos: Pleito[] }>(`/api/contratos/${contratoId}/prazos`);
      setDados(d);
      if (d.situacao.pedido) {
        const obras = await api<{ id: number; pedido_prorrogacao?: { dias: number | null } | null }[]>("/api/contratos")
          .catch(() => []);
        setDiasPedido(obras.find(o => o.id === contratoId)?.pedido_prorrogacao?.dias ?? null);
      } else setDiasPedido(null);
    } catch (e) { setErro(mensagemDeErro(e)); }
  }, [contratoId]);
  useEffect(() => { void carregar(); }, [carregar]);
  // o oficio criado so' existe depois que a lista recarrega: tenta de novo a cada leitura
  useEffect(() => { if (foco && focarPorId(foco)) setFoco(null); }, [foco, dados]);

  if (erro) return <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erro}</p>;
  if (!dados) return <section className="cartao"><div className="vazio"><p>Carregando…</p></div></section>;
  const s = dados.situacao;
  const contrato = { tela: "obra" as const, id: contratoId, aba: "contrato" as const };
  const semInstrumento = diasPedido === null ? "sem instrumento ainda" : `sem instrumento há ${dias(diasPedido)}`;

  // o desfecho de cada pedido de prorrogacao enviado: o instrumento que o atendeu (Em dia) ou nenhum ainda
  // (Atencao, com os dias que o servidor conta); embaixo, so' a data do envio (F-71)
  const desfecho = (p: Pleito): DesfechoPleito => {
    const envio = partesDoEnvio(p);
    if (p.tipo !== "prazo" || p.situacao !== "enviado") return { classe: "", texto: p.situacao, partes: envio };
    const inst = desfechoDoPedido(p.enviado_em, s.instrumentos);
    if (!inst) {
      return s.pedido?.id === p.id
        ? { classe: "selo--atencao", texto: semInstrumento, partes: envio }
        : { classe: "", texto: "sem instrumento ainda", partes: envio };
    }
    const nome = inst.numero ?? (inst.forma === "apostilamento" ? "apostilamento" : "termo aditivo");
    return { classe: "selo--ok", texto: `atendido pelo ${nome}`, partes: envio };
  };
  const oficios = dados.pleitos.length;
  // pedido que ainda se trabalha (feito no sistema, nem enviado nem descartado): o caminho e' continuar nele
  const aberto = dados.pleitos.find(p => p.tipo === "prazo" && p.origem === "sistema" && p.situacao !== "enviado" && p.situacao !== "descartado");

  return (
    <div className="pilha">
      <section className="cartao" aria-labelledby="titulo-situacao-prazo">
        <div className="cartao__cabeca"><h2 className="cartao__titulo" id="titulo-situacao-prazo">Situação do prazo</h2></div>
        {/* a grade de 4 colunas do resumo da obra (.resumo-grade): as colunas nao mudam de lugar entre obras */}
        <div className="cartao__corpo resumo-grade">
          <div className="dado">
            <span className="resumo__rotulo">Execução até</span>
            <span className="dado__valor num">{data(s.execucao_fim)}</span>
            {s.execucao_fim && <SeloVencida d={s.dias_execucao} />}
            {s.paralisacao && <Selo classe="selo--atencao">paralisada desde {data(s.paralisacao.desde)}</Selo>}
          </div>
          <div className="dado">
            <span className="resumo__rotulo">Vigência até</span>
            <span className="dado__valor num">{data(s.vigencia_fim)}</span>
            {s.vigencia_fim && <SeloVencida d={s.dias_vigencia} />}
          </div>
          <div className="dado">
            <span className="resumo__rotulo">Folga entre execução e vigência</span>
            <span className="dado__valor num">{s.folga.real === null ? "—" : dias(s.folga.real)}</span>
            {s.folga.quebrada && <Selo classe="selo--acao">folga quebrada</Selo>}
          </div>
          {s.endosso && (
            <div className="dado">
              <span className="resumo__rotulo">Endosso do seguro-garantia</span>
              <span className="dado__valor">{s.endosso.instrumento ?? "último instrumento"}</span>
              <Selo classe={s.endosso.entregue ? "selo--ok" : "selo--atencao"}>
                {s.endosso.entregue ? "endosso registrado" : "endosso não registrado"}
              </Selo>
            </div>
          )}
          <div className="dado">
            <span className="resumo__rotulo">Pedido de prorrogação</span>
            {s.pedido ? (
              <>
                <span className="dado__valor"><Link para={{ tela: "obra", id: contratoId, aba: "prazos" }} secao={`oficio-${s.pedido.id}`}>
                  {s.pedido.numero_oficio ?? "Ofício"}</Link></span>
                <Selo classe="selo--atencao">{semInstrumento}</Selo>
              </>
            ) : <span className="dado__valor">—</span>}
          </div>
        </div>
        {/* a lista dos instrumentos (aditivos, paralisacoes, endossos) mora em Contrato › Instrumentos */}
        <div className="cartao__corpo">
          <Link para={contrato} secao="instrumentos">Abrir os instrumentos</Link>
        </div>
      </section>

      {/* um cartao so': a cabeca (contagem, pedir, historico) e, embaixo, cada oficio como secao, com o desfecho */}
      <section className="cartao" aria-labelledby="titulo-pedidos">
        <div className="cartao__cabeca">
          <h2 className="cartao__titulo" id="titulo-pedidos">Pedidos e cartas</h2>
          {podeEditar && aberto && (
            <div className="cartao__acoes">
              <Link className="btn btn--pequeno" para={{ tela: "obra", id: contratoId, aba: "prazos" }} secao={`oficio-${aberto.id}`}>
                Continuar o pedido{aberto.numero_oficio ? ` ${aberto.numero_oficio}` : ""}
              </Link>
            </div>
          )}
          {podeEditar && !aberto && !s.encerramento && novo !== "prazo" && (
            <div className="cartao__acoes">
              <button type="button" className="btn btn--primario" id="pedir-prorrogacao" onClick={() => setNovo("prazo")}>Pedir prorrogação</button>
            </div>
          )}
        </div>
        {/* o historico entra na secao 1 da carta de prazo: aberto enquanto se pede a prorrogacao */}
        <details className="detalhes cartao__corpo" key={novo ?? "-"} open={novo === "prazo"}>
          <summary>Histórico do contrato</summary>
          {dados.historico ? dados.historico.split("\n\n").map((p, i) => <p key={i}>{p}</p>) : <p>—</p>}
        </details>
        {(novo === "prazo" || oficios > 0) && (
          <div className="secoes-pleito">
            {novo === "prazo" && (
              <section className="cartao" aria-labelledby="titulo-novo-pedido">
                <div className="cartao__cabeca"><h3 className="cartao__titulo" id="titulo-novo-pedido">Novo pedido de prorrogação</h3></div>
                <NovoPleito contratoId={contratoId} tipo="prazo"
                  aoCriar={p => { setNovo(null); setFoco(`oficio-${p.id}`); void carregar(); }}
                  aoCancelar={() => { setNovo(null); setFoco("pedir-prorrogacao"); }} />
              </section>
            )}
            {dados.pleitos.map(p => pleitoEmLinha(p)
              ? <LinhaPleito key={p.id} p={p} desfecho={desfecho(p)} />
              : <CartaoPleito key={p.id} p={p} podeEditar={podeEditar} aoMudar={() => void carregar()} />)}
          </div>
        )}
      </section>

      {s.encerramento && (
        <section className="cartao" aria-labelledby="titulo-encerramento">
          <div className="cartao__cabeca">
            <h2 className="cartao__titulo" id="titulo-encerramento">Encerramento</h2>
          </div>
          <ul className="lista-simples cartao__corpo">
            {MARCOS.map(([k, rotulo]) => <li key={k}>{rotulo}: <span className="num">{data(s.encerramento!.marcos[k])}</span></li>)}
            <li>Comunicação de conclusão: {s.encerramento.conclusao_comunicada ? "enviada" : "não enviada"}</li>
          </ul>
          {podeEditar && !s.encerramento.conclusao_comunicada && novo !== "conclusao" && (
            <div className="cartao__corpo"><button type="button" className="btn btn--primario" id="comunicar-conclusao" onClick={() => setNovo("conclusao")}>Comunicar conclusão</button></div>
          )}
        </section>
      )}
      {novo === "conclusao" && (
        <section className="cartao" aria-labelledby="titulo-nova-conclusao">
          <div className="cartao__cabeca"><h3 className="cartao__titulo" id="titulo-nova-conclusao">Nova comunicação de conclusão</h3></div>
          <NovoPleito contratoId={contratoId} tipo="conclusao"
            aoCriar={p => { setNovo(null); setFoco(`oficio-${p.id}`); void carregar(); }}
            aoCancelar={() => { setNovo(null); setFoco("comunicar-conclusao"); }} />
        </section>
      )}
    </div>
  );
}
