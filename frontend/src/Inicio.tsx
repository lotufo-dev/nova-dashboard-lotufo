import { useEffect, useState } from "react";
import { api, mensagemDeErro } from "./api";
import { brl, contar, fmtPercentual } from "./formato";
import type { Usuario } from "./Login";
import { type Ir } from "./rota";
import { Link } from "./Link";
import { fmtCompetencia, fmtMesExtenso } from "./tempo";
import "./inicio.css";

// Inicio do redesenho de 11/2026 (imagem aprovada pelo Leonardo em 06/11/2026): informacao geral para a diretoria.
// Tudo vem de GET /api/inicio/painel; as regras de cada numero moram em `backend/app/inicio.py`. A tela so' desenha.
// Acao operacional (nota a enviar, espelho a conferir) saiu daqui: vive nas telas dela e na tela Avisos.

type Certidao = { tipo: string; entidade: string; validade: string | null; dias: number | null; vencida: boolean };
type Reajuste = { contrato_id: number; obra: string; data_base_mes: string; aniversario: string; dias: number };
type Prazo = { contrato_id: number; obra: string; contratante: string; tipo: "execucao" | "vigencia" | "data_base"; data: string; dias: number };
type Contratante = { contratante: string; atual_centavos: number; anterior_centavos: number };
type Acumulado = { mes: string; ate_dia: number; valor_centavos: number; quantidade: number; acumulado_centavos: number[] };
type SecaoAvisos<T> = { total: number; itens: T[] };
export type PainelInicio = {
  hoje: string;
  notas_a_enviar: number;
  certidoes: { vencidas: number; vencendo: number; itens: Certidao[] };
  reajustes: Reajuste[];
  protocoladas: { obras_protocoladas: number; obras_ativas: number; ultima: string | null };
  medido: { competencia: string; anterior_competencia: string; valor_centavos: number;
            anterior_centavos: number; quantidade: number; ultimo_lancamento: string | null; variacao_pct: number | null };
  por_contratante: Contratante[];
  recebido_ano: { valor_centavos: number | null; mes_centavos: number; sem_data: number; real_centavos?: number };
  a_receber: { liberado: boolean; valor_centavos: number | null; mais_60_centavos: number | null };
  prazos: Prazo[];
  espelhos: EspelhoAConferir[];
  protocolado_mes: { dia: number; atual: Acumulado; anterior: Acumulado; variacao_pct: number | null };
  notas_mes: { mes: string; valor_centavos: number; notas: number; obras: number; acumulado_centavos: number[] };
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

/** Variacao com sinal: "+38,2%" / "-14,6%" (hifen simples, como o resto da tela). */
function fmtVariacao(pct: number): string {
  return `${pct > 0 ? "+" : ""}${fmtPercentual(pct / 100, 1, true)}`;
}

/** Selo da variacao: subiu = verde, caiu = ambar (regra de cor da informacao), igual ou sem base = nada. */
function SeloVariacao({ pct, sufixo = "" }: { pct: number | null; sufixo?: string }) {
  if (pct === null) return null;
  const tom = pct > 0 ? "ok" : pct < 0 ? "atencao" : "neutro";
  return <span className={`ini-variacao ini-variacao--${tom}`}>{fmtVariacao(pct)}{sufixo}</span>;
}

/** Teto "redondo" do eixo e o passo entre os rotulos, em reais inteiros (1, 2, 5 x 10^n). */
function escalaDoEixo(maxCentavos: number): { topo: number; passo: number } {
  const reais = Math.max(5, maxCentavos / 100);    // eixo vazio: 0 a 5, passos inteiros
  const bruto = reais / 5;
  const pot = 10 ** Math.floor(Math.log10(bruto));
  const f = bruto / pot;
  const passo = (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * pot;
  return { topo: Math.ceil(reais / passo) * passo, passo };
}

const L = 720, A = 250, MESQ = 92, MDIR = 16, MTOP = 12, MBAIXO = 30;

/** Acumulado por dia do mes de hoje (cheia) contra o do mes anterior no mesmo periodo (tracejada). */
function GraficoAcumulado({ p, nomeAtual, nomeAnterior }: { p: PainelInicio["protocolado_mes"]; nomeAtual: string; nomeAnterior: string }) {
  const atual = p.atual.acumulado_centavos, ant = p.anterior.acumulado_centavos;
  const { topo, passo } = escalaDoEixo(Math.max(0, ...atual, ...ant));
  const dias = Math.max(atual.length, ant.length, 2);
  const x = (dia: number) => MESQ + ((dia - 1) / (dias - 1)) * (L - MESQ - MDIR);
  const y = (centavos: number) => MTOP + (1 - centavos / 100 / topo) * (A - MTOP - MBAIXO);
  const pontos = (v: number[]) => v.map((c, i) => `${x(i + 1).toFixed(1)},${y(c).toFixed(1)}`);
  const linhaAtual = pontos(atual);
  const base = A - MBAIXO;
  const area = linhaAtual.length > 0 ? `${x(1)},${base} ${linhaAtual.join(" ")} ${x(atual.length)},${base}` : "";
  const rotulos = Array.from({ length: Math.round(topo / passo) + 1 }, (_, i) => i * passo);
  const passoDias = dias > 16 ? 5 : 1;
  const marcas = Array.from({ length: dias }, (_, i) => i + 1).filter(d => d === 1 || d === dias || d % passoDias === 0);
  return (
    <figure className="ini-grafico">
      <svg viewBox={`0 0 ${L} ${A}`} role="img"
        aria-label={`Protocolado acumulado por dia, ${nomeAtual}: ${brl(p.atual.valor_centavos)}; ${nomeAnterior}: ${brl(p.anterior.valor_centavos)}`}>
        {rotulos.map(v => (
          <g key={v}>
            <line className="ini-grafico__grade" x1={MESQ} x2={L - MDIR} y1={y(v * 100)} y2={y(v * 100)} />
            <text className="ini-grafico__eixo" x={MESQ - 8} y={y(v * 100) + 5} textAnchor="end">{v.toLocaleString("pt-BR")}</text>
          </g>
        ))}
        {marcas.map(d => <text key={d} className="ini-grafico__eixo" x={x(d)} y={A - 8} textAnchor="middle">{d}</text>)}
        {area && <polygon className="ini-grafico__area" points={area} />}
        {ant.length > 0 && <polyline className="ini-grafico__linha ini-grafico__linha--anterior" points={pontos(ant).join(" ")} />}
        {linhaAtual.length > 0 && <polyline className="ini-grafico__linha ini-grafico__linha--atual" points={linhaAtual.join(" ")} />}
        {atual.length > 0 && <circle className="ini-grafico__ponto" cx={x(atual.length)} cy={y(atual[atual.length - 1])} r="5" />}
      </svg>
      <figcaption className="ini-legenda">
        <span><i className="ini-traco ini-traco--atual" />{nomeAtual}</span>
        <span><i className="ini-traco ini-traco--anterior" />{nomeAnterior}</span>
      </figcaption>
    </figure>
  );
}

/** Minigrafico do acumulado do mes (sem eixo): so' a forma da subida. */
function Minigrafico({ v }: { v: number[] }) {
  const max = Math.max(1, ...v), n = Math.max(v.length, 2);
  const pts = v.map((c, i) => `${(2 + (i / (n - 1)) * 196).toFixed(1)},${(36 - (c / max) * 32).toFixed(1)}`);
  return (
    <svg className="ini-mini" viewBox="0 0 200 40" preserveAspectRatio="none" aria-hidden="true">
      {pts.length > 0 && <polygon className="ini-grafico__area" points={`2,38 ${pts.join(" ")} ${pts.length > 1 ? 2 + ((pts.length - 1) / (n - 1)) * 196 : 2},38`} />}
      {pts.length > 0 && <polyline className="ini-grafico__linha ini-grafico__linha--atual" points={pts.join(" ")} />}
    </svg>
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
  return bs.length > 1 ? ` (${bs.length} data-bases)` : "";
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
  const nomeMes = fmtMesExtenso(m.competencia);
  const nomeAnterior = fmtMesExtenso(m.anterior_competencia);
  const pm = p.protocolado_mes;
  const mesHoje = fmtMesExtenso(p.hoje.slice(0, 7)), mesAntes = fmtMesExtenso(pm.anterior.mes);
  const nm = p.notas_mes;
  const av = p.avisos_importantes;
  const ano = p.hoje.slice(0, 4);
  const recebido = p.recebido_ano.real_centavos ?? p.recebido_ano.valor_centavos;
  // barra do recebido: o que ja' entrou no ano sobre o que entrou + o que falta receber (so' com o total liberado)
  const aReceber = p.a_receber.liberado ? p.a_receber.valor_centavos : null;
  const pctRecebido = recebido !== null && aReceber !== null && recebido + aReceber > 0
    ? Math.round(100 * recebido / (recebido + aReceber)) : null;
  const maior = Math.max(1, ...p.por_contratante.map(x => Math.max(x.atual_centavos, x.anterior_centavos)));
  const ateDia = (a: Acumulado) => `até dia ${a.ate_dia}`;

  return (
    <div className="ini">
      {titulo}
      <div className="ini-grade">
        <div className="ini-coluna">
          <section aria-labelledby="ini-protocoladas" className="ini-painel ini-destaque">
            <div>
              <h2 id="ini-protocoladas">Medições protocoladas</h2>
              <p className="ini-sub">{mesHoje} × {mesAntes}, mesmo período (dias 1 a {pm.atual.ate_dia})</p>
            </div>
            <div className="ini-destaque__valores">
              <div className="ini-destaque__valor">
                <span className="ini-numero__rotulo">{`${mesHoje[0].toUpperCase()}${mesHoje.slice(1)} (${ateDia(pm.atual)})`}</span>
                <span className="ini-destaque__numero ini-destaque__numero--atual">{brl(pm.atual.valor_centavos)}</span>
                <span className="ini-numero__rotulo">{contar(pm.atual.quantidade, "medição", "medições")}</span>
              </div>
              <SeloVariacao pct={pm.variacao_pct} />
              <div className="ini-destaque__valor ini-destaque__valor--anterior">
                <span className="ini-numero__rotulo">{`${mesAntes[0].toUpperCase()}${mesAntes.slice(1)} (${ateDia(pm.anterior)})`}</span>
                <span className="ini-destaque__numero ini-destaque__numero--anterior">{brl(pm.anterior.valor_centavos)}</span>
                <span className="ini-numero__rotulo">{contar(pm.anterior.quantidade, "medição", "medições")}</span>
              </div>
            </div>
            <GraficoAcumulado p={pm} nomeAtual={mesHoje} nomeAnterior={mesAntes} />
          </section>

          <section aria-label="Números do mês" className="ini-numeros">
            <div className="ini-numero">
              <span className="ini-numero__rotulo">Notas fiscais protocoladas em {mesHoje}</span>
              <span className="ini-numero__valor ini-numero__valor--acento">{brl(nm.valor_centavos)}</span>
              <span className="ini-numero__rotulo">{contar(nm.notas, "nota", "notas")} · {contar(nm.obras, "obra", "obras")}</span>
              <Minigrafico v={nm.acumulado_centavos} />
            </div>
            <div className="ini-numero">
              <span className="ini-numero__rotulo">Medido em {nomeMes}</span>
              <span className="ini-numero__valor">{brl(m.valor_centavos)}</span>
              <span className="ini-numero__rotulo">mês fechado</span>
              <span><SeloVariacao pct={m.variacao_pct} sufixo={` vs. ${nomeAnterior}`} /></span>
            </div>
            <div className="ini-numero">
              <span className="ini-numero__rotulo">Recebido em {ano}</span>
              <span className="ini-numero__valor">{brl(recebido)}</span>
              {pctRecebido !== null && (
                <span className="ini-barra ini-barra--ok" role="img" aria-label={`${pctRecebido}% do recebido e a receber`}>
                  <span style={{ width: `${pctRecebido}%` }} /></span>)}
            </div>
          </section>

          <section aria-labelledby="ini-medido" className="ini-painel ini-painel--grafico">
            <div className="ini-painel__topo">
              <h2 id="ini-medido">Medido por contratante</h2>
              <span className="ini-legenda">
                <span><i className="ini-chave ini-chave--anterior" />{nomeAnterior}</span>
                <span><i className="ini-chave ini-chave--atual" />{nomeMes}</span>
              </span>
            </div>
            {m.quantidade === 0 && (
              <div className="ini-sem-medicao" role="status">
                <strong>Nenhuma medição da competência de {nomeMes}.</strong>
                <Link para={{ tela: "medicoes" }} ir={ir} className="ini-sem-medicao__botao">Lançar medição →</Link>
              </div>
            )}
            {p.por_contratante.length > 0 && (
              <ul className="ini-barras">
                {p.por_contratante.map(x => (
                  <li key={x.contratante} className="ini-barras__linha">
                    <span className="ini-barras__nome">{x.contratante}</span>
                    <svg className="ini-barras__svg" viewBox="0 0 100 23" preserveAspectRatio="none" role="img"
                      aria-label={`${nomeAnterior}: ${brl(x.anterior_centavos)}; ${nomeMes}: ${brl(x.atual_centavos)}`}>
                      <rect className="ini-barras__anterior" x="0" y="0" height="10" rx="1.5" width={100 * x.anterior_centavos / maior} />
                      <rect className="ini-barras__atual" x="0" y="13" height="10" rx="1.5" width={100 * x.atual_centavos / maior} />
                    </svg>
                    <span className="ini-barras__valor">{brl(x.atual_centavos)}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>

        <aside aria-labelledby="ini-avisos" className="ini-painel ini-avisos">
          <h2 id="ini-avisos">Avisos importantes</h2>
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
        </aside>
      </div>
    </div>
  );
}
