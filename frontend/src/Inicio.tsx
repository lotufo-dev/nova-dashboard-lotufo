import { useEffect, useState } from "react";
import { api, mensagemDeErro } from "./api";
import { brl, contar } from "./formato";
import LegendaCor from "./LegendaCor";
import type { Usuario } from "./Login";
import { type Ir } from "./rota";
import { Link } from "./Link";
import { fmtCompetencia, fmtMesExtenso } from "./tempo";
import "./inicio.css";

// Inicio do redesenho de 11/2026: informacao geral para a diretoria. Issue #642 (decisao do dono de 10/11/2026): a
// faixa do ciclo da medicao entrou no lugar do destaque de protocoladas e das barras por contratante.
// Tudo vem de GET /api/inicio/painel; as regras de cada numero moram em `backend/app/inicio.py`. A tela so' desenha.
// Acao operacional (nota a enviar, espelho a conferir) saiu daqui: vive nas telas dela e na tela Avisos.

type Certidao = { tipo: string; entidade: string; validade: string | null; dias: number | null; vencida: boolean };
type Reajuste = { contrato_id: number; obra: string; data_base_mes: string; aniversario: string; dias: number };
type Prazo = { contrato_id: number; obra: string; contratante: string; tipo: "execucao" | "vigencia" | "data_base"; data: string; dias: number };
type SecaoAvisos<T> = { total: number; itens: T[] };
type ChaveEtapa = "em_analise" | "boletim" | "nota" | "protocolado" | "recebido_mes";
// #642: uma etapa da faixa do ciclo, na cota da Lotufo; `mais_antigo_dias` nulo = etapa vazia ou sem idade (recebido)
type EtapaCiclo = { etapa: ChaveEtapa; valor_centavos: number; quantidade: number; mais_antigo_dias: number | null };
export type PainelInicio = {
  hoje: string;
  notas_a_enviar: number;
  certidoes: { vencidas: number; vencendo: number; itens: Certidao[] };
  reajustes: Reajuste[];
  protocoladas: { obras_protocoladas: number; obras_ativas: number; ultima: string | null };
  medido: { competencia: string; valor_centavos: number; quantidade: number; ultimo_lancamento: string | null };
  recebido_ano: { valor_centavos: number | null; mes_centavos: number; sem_data: number; real_centavos?: number };
  a_receber: { liberado: boolean; valor_centavos: number | null; mais_60_centavos: number | null };
  prazos: Prazo[];
  espelhos: EspelhoAConferir[];
  ciclo: EtapaCiclo[];
  notas_mes: { mes: string; valor_centavos: number; notas: number; obras: number };
  avisos_importantes: {
    // issue #274: o pleito a pedir e os avisos do motor de apostilamento, o mais grave primeiro
    reajustes: SecaoAvisos<{ contrato_id: number; obra: string; dias: number | null; tipo?: string;
      nivel?: "critico" | "acao" | "atencao"; competencias?: string[]; datas_base?: string[] }>;
    prazos: SecaoAvisos<{ contrato_id: number; obra: string; tipo: "execucao" | "vigencia"; dias: number }>;
    certidoes: SecaoAvisos<Certidao>;
  };
};
// #359: o aprovado mudou depois do espelho (ou o espelho antigo nao se confere): a mesma fonte do aviso
type EspelhoAConferir = { espelho_id: number; contrato_id: number; medicao_id: number; obra: string | null; titulo: string;
  situacao: "aprovado_mudou" | "nota_emitida" | "nao_conferido" };

/** "Bom dia" / "Boa tarde" / "Boa noite" pela hora de Cuiaba. */
export function saudacao(agora: Date = new Date()): string {
  const h = Number(new Intl.DateTimeFormat("pt-BR", { hour: "numeric", hourCycle: "h23", timeZone: "America/Cuiaba" }).format(agora));
  return h >= 5 && h < 12 ? "Bom dia" : h >= 12 && h < 18 ? "Boa tarde" : "Boa noite";
}

// #642: rotulo de cada etapa e a cor da informacao (em andamento = azul; recebido = feito, verde)
const ETAPAS: Record<ChaveEtapa, { rotulo: string; tom: "andamento" | "feito" }> = {
  em_analise: { rotulo: "Em análise", tom: "andamento" },
  boletim: { rotulo: "Boletim", tom: "andamento" },
  nota: { rotulo: "Nota", tom: "andamento" },
  protocolado: { rotulo: "Protocolado", tom: "andamento" },
  recebido_mes: { rotulo: "Recebido no mês", tom: "feito" },
};

const dias = (n: number) => contar(n, "dia", "dias");
/** A quantidade da etapa: medicoes; no recebido, as notas com baixa no mes. */
const quantos = (e: EtapaCiclo) => e.etapa === "recebido_mes" ? contar(e.quantidade, "nota", "notas") : contar(e.quantidade, "medição", "medições");

/** Faixa do ciclo (#642): um trecho por etapa, com a largura proporcional ao valor (o minimo de cada trecho, que mantem
 *  o texto legivel, e' `--ini-faixa-min` no CSS). Em container estreito a faixa vira lista vertical (inicio.css). A
 *  faixa e' desenho; quem usa leitor de tela le a tabela equivalente. */
function FaixaCiclo({ etapas }: { etapas: EtapaCiclo[] }) {
  const total = etapas.reduce((s, e) => s + Math.max(0, e.valor_centavos), 0);
  const colunas = etapas.map(e =>
    `minmax(var(--ini-faixa-min), ${total > 0 ? Math.round(100 * Math.max(0, e.valor_centavos) / total) : 1}fr)`).join(" ");
  return (
    <section aria-labelledby="ini-ciclo" className="ini-painel ini-ciclo">
      <h2 id="ini-ciclo">Ciclo da medição (cota da Lotufo)</h2>
      <ol className="ini-faixa" aria-hidden="true" style={{ "--ini-faixa-colunas": colunas } as React.CSSProperties}>
        {etapas.map(e => (
          <li key={e.etapa} className={`ini-faixa__etapa ini-faixa__etapa--${ETAPAS[e.etapa].tom}`}>
            <span className="ini-faixa__rotulo">{ETAPAS[e.etapa].rotulo}</span>
            <span className="ini-faixa__valor">{brl(e.valor_centavos)}</span>
            <span className="ini-faixa__conta">{quantos(e)}</span>
            {e.mais_antigo_dias !== null && (
              <span className="ini-faixa__conta">
                {e.mais_antigo_dias === 0 ? "mais antiga de hoje" : `mais antiga há ${dias(e.mais_antigo_dias)}`}</span>)}
          </li>
        ))}
      </ol>
      {/* `sr-only` no div, nao na <table>: tabela ignora largura e overflow e alargava a pagina no celular (PR #676) */}
      <div className="sr-only"><table>
        <caption>Ciclo da medição por etapa, na cota da Lotufo</caption>
        <thead><tr><th scope="col">Etapa</th><th scope="col">Valor</th><th scope="col">Quantidade</th><th scope="col">Mais antiga</th></tr></thead>
        <tbody>
          {etapas.map(e => (
            <tr key={e.etapa}>
              <th scope="row">{ETAPAS[e.etapa].rotulo}</th>
              <td>{brl(e.valor_centavos)}</td>
              <td>{quantos(e)}</td>
              <td>{e.mais_antigo_dias === null ? "—" : dias(e.mais_antigo_dias)}</td>
            </tr>
          ))}
        </tbody>
      </table></div>
    </section>
  );
}

const IconeReajuste = () => (
  <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M12 3 3 8l9 5 9-5-9-5Z" /><path d="m3 13 9 5 9-5" /><path d="m3 17.5 9 5 9-5" />
  </svg>);
const IconePrazo = () => (
  <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <rect x="3" y="5" width="18" height="16" rx="2" /><path d="M3 10h18M8 3v4M16 3v4" />
  </svg>);
const IconeCertidao = () => (
  <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M12 3 5 6v5c0 4.5 3 8 7 10 4-2 7-5.5 7-10V6l-7-3Z" />
  </svg>);

// issue #274: o que cada aviso de reajuste diz na linha da secao Reajustes (o tipo vem de `app/reajuste.py`)
const AVISO_REAJUSTE: Record<string, string> = {
  reajuste_pleito: "reajuste a pedir",
  reajuste_fora_da_previsao: "reajuste fora da previsão",
  reajuste_sem_apostilamento: "reajuste sem apostilamento",
  reajuste_nota_antes_do_apostilamento: "nota antes do apostilamento",
  reajuste_reemitir: "cronograma de reajuste a reemitir",
  reajuste_sem_resposta: "pedido de reajuste sem resposta",
};

/** O que o item juntou (rodada 2 da PR #579: um item por obra e tipo): a competencia, ou quantas; sem competencia,
 *  quantas datas-base quando ha' mais de uma. */
function detalheDoReajuste(x: { competencias?: string[]; datas_base?: string[] }): string {
  const cs = x.competencias ?? [], bs = x.datas_base ?? [];
  if (cs.length === 1) return ` (${fmtCompetencia(cs[0])})`;
  if (cs.length > 1) return ` (${cs.length} competências)`;
  return bs.length > 1 ? ` (${bs.length} datas-base)` : "";
}

/** "vencido há 450 dias" / "vence hoje" / "vence em 5 dias" (dias < 0 = vencido). */
function quando(dias: number | null, vencida: boolean): string {
  if (dias === null) return vencida ? "vencida" : "—";
  if (dias < 0) return `vencido há ${(-dias).toLocaleString("pt-BR")} ${-dias === 1 ? "dia" : "dias"}`;
  if (dias === 0) return "vence hoje";
  return `vence em ${dias.toLocaleString("pt-BR")} ${dias === 1 ? "dia" : "dias"}`;
}

function SecaoAviso({ id, titulo, icone, total, tom, familia, ir, vazio, children }:
    { id: string; titulo: string; icone: React.ReactNode; total: number; tom: "neutro" | "acao" | "atencao"; familia: string; ir: Ir;
      vazio: string; children: React.ReactNode }) {
  return (
    <section aria-labelledby={id} className={`ini-aviso ini-aviso--${tom}`}>
      <header className="ini-aviso__topo">
        <span className="ini-aviso__icone">{icone}</span>
        <h3 id={id}>{titulo}</h3>
        <span className="ini-aviso__conta" aria-label={`${total} ${titulo.toLowerCase()}`}>{total.toLocaleString("pt-BR")}</span>
        <Link para={{ tela: "avisos" }} busca={{ familia }} ir={ir} className="ini-ver-todos" aria-label={`Ver todos: ${titulo}`}>Ver todos</Link>
      </header>
      {total === 0 ? <p className="ini-vazio">{vazio}</p> : <ul className="ini-aviso__lista">{children}</ul>}
    </section>
  );
}

export default function Inicio({ usuario, ir }: { usuario: Usuario; ir: Ir }) {
  const [p, setP] = useState<PainelInicio | null>(null);
  const [erro, setErro] = useState("");

  useEffect(() => {
    let vivo = true;
    api<PainelInicio>("/api/inicio/painel")
      .then(d => { if (vivo) setP(d); })
      .catch(e => { if (vivo) setErro(mensagemDeErro(e)); });
    return () => { vivo = false; };
  }, []);

  const nome = usuario.nome.trim().split(/\s+/)[0] ?? "";
  const titulo = <h1 className="ini-titulo">{saudacao()}{nome ? `, ${nome}` : ""}</h1>;
  if (!p) {
    return (
      <div className="ini">
        {titulo}
        {erro ? <p className="erro" role="alert">Não foi possível carregar o início: {erro}</p>
          : <p className="ini-carregando">Carregando…</p>}
      </div>
    );
  }

  const m = p.medido;
  const av = p.avisos_importantes;
  const recebido = p.recebido_ano.real_centavos ?? p.recebido_ano.valor_centavos;

  return (
    <div className="ini">
      <div className="ini-topo">
        {titulo}
        <LegendaCor />
      </div>
      <FaixaCiclo etapas={p.ciclo} />

      <section aria-label="Números do mês" className="ini-numeros">
        <div className="ini-numero">
          <span className="ini-numero__rotulo">Notas fiscais protocoladas em {fmtMesExtenso(p.hoje.slice(0, 7))}</span>
          <span className="ini-numero__valor">{brl(p.notas_mes.valor_centavos)}</span>
        </div>
        <div className="ini-numero">
          <span className="ini-numero__rotulo">Medido em {fmtMesExtenso(m.competencia)}</span>
          <span className="ini-numero__valor">{brl(m.valor_centavos)}</span>
        </div>
        <div className="ini-numero">
          <span className="ini-numero__rotulo">Recebido em {p.hoje.slice(0, 4)}</span>
          <span className="ini-numero__valor">{brl(recebido)}</span>
        </div>
      </section>

      <aside aria-labelledby="ini-avisos" className="ini-painel ini-avisos">
        <h2 id="ini-avisos">Avisos importantes</h2>
        <div className="ini-avisos__secoes">
          <SecaoAviso id="ini-av-reajustes" titulo="Reajustes" icone={<IconeReajuste />} total={av.reajustes.total} tom="neutro"
            familia="reajustes" ir={ir} vazio="Nenhum aviso de reajuste.">
            {av.reajustes.itens.map((x, i) => (
              <li key={`${x.contrato_id}-${i}`}>
                <Link para={{ tela: "obra", id: x.contrato_id, aba: "reajuste" }} ir={ir} className="ini-aviso__linha">
                  <span className="ini-aviso__nome">{x.obra} · {AVISO_REAJUSTE[x.tipo ?? "reajuste_pleito"] ?? "reajuste"}{detalheDoReajuste(x)}</span>
                </Link>
              </li>))}
          </SecaoAviso>
          <SecaoAviso id="ini-av-prazos" titulo="Prazos" icone={<IconePrazo />} total={av.prazos.total} tom="acao"
            familia="prazos" ir={ir} vazio="Nenhum prazo vencido ou chegando.">
            {av.prazos.itens.map(x => (
              <li key={`${x.contrato_id}-${x.tipo}`}>
                <Link para={{ tela: "obra", id: x.contrato_id, aba: "prazos" }} ir={ir} className="ini-aviso__linha">
                  <span className="ini-aviso__nome">{x.obra}</span>
                  <span className={`ini-pilula ini-pilula--${x.dias <= 15 ? "acao" : "atencao"}`}>
                    {x.dias < 0 ? `vencido há ${(-x.dias).toLocaleString("pt-BR")} ${-x.dias === 1 ? "dia" : "dias"}`
                      : `faltam ${x.dias.toLocaleString("pt-BR")} ${x.dias === 1 ? "dia" : "dias"}`}</span>
                </Link>
              </li>))}
          </SecaoAviso>
          <SecaoAviso id="ini-av-certidoes" titulo="Certidões" icone={<IconeCertidao />} total={av.certidoes.total} tom="atencao"
            familia="certidoes" ir={ir} vazio="Nenhuma certidão vencendo.">
            {av.certidoes.itens.map((x, i) => (
              <li key={`${x.tipo}-${x.entidade}-${i}`}>
                <Link para={{ tela: "documentos" }} ir={ir} className="ini-aviso__linha">
                  <span className="ini-aviso__nome">{x.tipo} · {x.entidade}</span>
                  <span className={`ini-pilula ini-pilula--${x.vencida ? "acao" : "atencao"}`}>{quando(x.dias, x.vencida)}</span>
                </Link>
              </li>))}
          </SecaoAviso>
        </div>
      </aside>
    </div>
  );
}
