import { Fragment, useEffect, useState } from "react";
import { destinoDoAviso, semEmpresa, semObra, type Aviso } from "./Alertas";
import { api, mensagemDeErro } from "./api";
import { daAgenda, diasAteOAviso, porSecao, semRSOrfao, type Secao } from "./avisos";
import { brl, contar } from "./formato";
import LegendaCor from "./LegendaCor";
import type { Usuario } from "./Login";
import { type Ir } from "./rota";
import { Link } from "./Link";
import { fmtCompetencia, fmtMesCurto, fmtMesExtenso } from "./tempo";
import "./inicio.css";

// Inicio do redesenho de 11/2026: informacao geral para a diretoria. Issue #642 (decisao do dono de 10/11/2026): a
// faixa do ciclo da medicao entrou no lugar do destaque de protocoladas e das barras por contratante.
// Tudo vem de GET /api/inicio/painel; as regras de cada numero moram em `backend/app/inicio.py`. A tela so' desenha.
// Acao operacional (nota a enviar, espelho a conferir) saiu daqui: vive nas telas dela e na tela Avisos.
// #666: a caixa "Avisos importantes" le GET /api/inicio, a MESMA fila da tela Avisos (com o recorte do perfil), e usa a
// mesma regra de secao (`avisos.ts`): a contagem dela e' a soma de Vencido, Esta semana e Este mes daquela tela.

type Certidao = { tipo: string; entidade: string; validade: string | null; dias: number | null; vencida: boolean };
type Reajuste = { contrato_id: number; obra: string; data_base_mes: string; aniversario: string; dias: number };
type Prazo = { contrato_id: number; obra: string; contratante: string; tipo: "execucao" | "vigencia" | "data_base"; data: string; dias: number };
type ChaveEtapa = "em_analise" | "boletim" | "nota" | "protocolado" | "recebido_mes";
// #642: uma etapa da faixa do ciclo, na cota da Lotufo; `mais_antigo_dias` nulo = etapa vazia ou sem idade (recebido)
type EtapaCiclo = { etapa: ChaveEtapa; valor_centavos: number; quantidade: number; mais_antigo_dias: number | null };
// #652: o recebido de um mes (baixas do RM, na cota) e uma linha da previsao de entrada
type MesRecebido = { mes: string; valor_centavos: number };
type GrupoPrevisao = { valor_centavos: number; quantidade: number };
// #659: a etapa da medicao de uma competencia; `atrasado` = protocolada alem do prazo do contratante (a regra da
// previsao de entrada). Celula nula = sem medicao na competencia
type EtapaMatriz = "em_analise" | "boletim" | "nota" | "protocolado" | "atrasado" | "recebida";
type CelulaMatriz = { etapa: EtapaMatriz; medicao_id: number } | null;
type ObraMatriz = { contrato_id: number; obra: string; celulas: CelulaMatriz[] };
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
  recebido_12m: MesRecebido[];
  // #652: `depois` = data esperada alem do proximo mes
  previsao: Record<"neste_mes" | "proximo_mes" | "atrasado" | "sem_previsao" | "depois", GrupoPrevisao>;
  matriz: { competencias: string[]; grupos: { contratante: string; obras: ObraMatriz[] }[] };
  notas_mes: { mes: string; valor_centavos: number; notas: number; obras: number };
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

/** Faixa do ciclo (#642): um trecho por etapa. O minimo de cada trecho e' o proprio conteudo (`min-content`: o valor
 *  inteiro numa linha, #659); a proporcao pelo valor vale para o espaco que sobra. Em container estreito a faixa vira
 *  lista vertical (inicio.css). A faixa e' desenho; quem usa leitor de tela le a tabela equivalente. */
function FaixaCiclo({ etapas }: { etapas: EtapaCiclo[] }) {
  const total = etapas.reduce((s, e) => s + Math.max(0, e.valor_centavos), 0);
  const colunas = etapas.map(e =>
    `minmax(min-content, ${total > 0 ? Math.round(100 * Math.max(0, e.valor_centavos) / total) : 1}fr)`).join(" ");
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

/** Valor de eixo, curto: "1,2 mi", "350 mil"; mes sem recebimento, tracinho. O valor inteiro esta' na tabela. */
function curto(centavos: number): string {
  return centavos > 0 ? (centavos / 100).toLocaleString("pt-BR", { notation: "compact", maximumFractionDigits: 1 }) : "—";
}

/** Recebido em 12 meses (#652): uma barra por mes, a ultima e' o mes corrente; o tamanho de cada uma e' a fracao do
 *  maior mes (`--ini-rec-tamanho`). Em container estreito as barras deitam, um mes por linha (inicio.css). */
function Recebido12Meses({ meses }: { meses: MesRecebido[] }) {
  const maior = Math.max(0, ...meses.map(m => m.valor_centavos));
  return (
    <section aria-labelledby="ini-recebido" className="ini-painel ini-recebido">
      <h2 id="ini-recebido">Recebido em 12 meses (cota da Lotufo)</h2>
      <ol className="ini-rec" aria-hidden="true">
        {meses.map(m => (
          <li key={m.mes} className="ini-rec__mes"
            style={{ "--ini-rec-tamanho": `${maior > 0 ? Math.round(100 * Math.max(0, m.valor_centavos) / maior) : 0}%` } as React.CSSProperties}>
            <span className="ini-rec__valor">{curto(m.valor_centavos)}</span>
            <span className="ini-rec__trilho"><span className="ini-rec__coluna" /></span>
            <span className="ini-rec__rotulo">{fmtMesCurto(m.mes)}</span>
          </li>
        ))}
      </ol>
      <div className="sr-only"><table>
        <caption>Recebido por mês, na cota da Lotufo</caption>
        <thead><tr><th scope="col">Mês</th><th scope="col">Recebido</th></tr></thead>
        <tbody>
          {meses.map(m => <tr key={m.mes}><th scope="row">{fmtCompetencia(m.mes)}</th><td>{brl(m.valor_centavos)}</td></tr>)}
        </tbody>
      </table></div>
    </section>
  );
}

// #652: as cinco linhas da previsao, na ordem da tela. Juntas somam a etapa "Protocolado" da faixa do ciclo: "Depois"
// (data esperada alem do proximo mes) entrou para o numero fechar na tela
const LINHAS_PREVISAO: { chave: keyof PainelInicio["previsao"]; rotulo: string }[] = [
  { chave: "neste_mes", rotulo: "Neste mês" },
  { chave: "proximo_mes", rotulo: "No próximo mês" },
  { chave: "depois", rotulo: "Depois" },
  { chave: "atrasado", rotulo: "Atrasado" },
  { chave: "sem_previsao", rotulo: "Sem previsão" },
];

/** Previsao de entrada (#652): o protocolado pela data esperada (protocolo + prazo do orgao). Cor da informacao: so' o
 *  atrasado, quando existe, e' critico (vermelho); o resto fica preto. */
function PrevisaoEntrada({ previsao }: { previsao: PainelInicio["previsao"] }) {
  return (
    <section aria-labelledby="ini-previsao" className="ini-painel ini-previsao">
      <h2 id="ini-previsao">Previsão de entrada (cota da Lotufo)</h2>
      <ul className="ini-previsao__linhas">
        {LINHAS_PREVISAO.map(({ chave, rotulo }) => {
          const g = previsao[chave];
          const critico = chave === "atrasado" && g.quantidade > 0;
          return (
            <li key={chave} className={`ini-previsao__linha${critico ? " ini-previsao__linha--critico" : ""}`}>
              <span className="ini-previsao__rotulo">{rotulo}</span>
              <span className="ini-previsao__valor">{brl(g.valor_centavos)}</span>
              <span className="ini-previsao__conta">{contar(g.quantidade, "medição", "medições")}</span>
            </li>);
        })}
      </ul>
    </section>
  );
}

// #659: as etapas da matriz na ordem da legenda: do azul mais claro ao mais escuro, o verde do recebido e o vermelho
// da protocolada alem do prazo
const ETAPAS_MATRIZ: { chave: EtapaMatriz; rotulo: string }[] = [
  { chave: "em_analise", rotulo: "Em análise" },
  { chave: "boletim", rotulo: "Boletim" },
  { chave: "nota", rotulo: "Nota" },
  { chave: "protocolado", rotulo: "Protocolado" },
  { chave: "recebida", rotulo: "Recebido" },
  { chave: "atrasado", rotulo: "Atrasado" },
];
const ROTULO_MATRIZ = Object.fromEntries(ETAPAS_MATRIZ.map(e => [e.chave, e.rotulo])) as Record<EtapaMatriz, string>;

/** Matriz obra por competencia (#659): uma linha por obra ativa, agrupada por contratante, e uma celula por competencia
 *  com a cor da etapa da medicao. A celula pintada e' o link para a medicao, com o nome (obra, competencia, etapa) no
 *  `aria-label` e na dica; a tabela equivalente fica para o leitor de tela. */
function MatrizObras({ matriz }: { matriz: PainelInicio["matriz"] }) {
  const { competencias, grupos } = matriz;
  return (
    <section aria-labelledby="ini-matriz" className="ini-painel ini-matriz">
      <div className="ini-matriz__topo">
        <h2 id="ini-matriz">Medições por obra e competência</h2>
        <ul className="ini-matriz__legenda" aria-label="Legenda das etapas">
          {ETAPAS_MATRIZ.map(e => <li key={e.chave}><span className={`ini-matriz__cor ini-matriz__cor--${e.chave}`} />{e.rotulo}</li>)}
        </ul>
      </div>
      {grupos.length === 0 ? <p className="ini-vazio">Nenhuma obra ativa.</p> : <>
        <div className="ini-matriz__grade">
          <div className="ini-matriz__linha ini-matriz__linha--meses" aria-hidden="true">
            {competencias.map((c, i) => {
              const [mes, ano] = fmtMesCurto(c).split("/");
              return (
                <span key={c} className="ini-matriz__mes">
                  <span>{mes}</span>{(i === 0 || c.endsWith("-01")) && <span className="ini-matriz__ano">{ano}</span>}
                </span>);
            })}
          </div>
          {grupos.map(g => (
            <Fragment key={g.contratante}>
              <h3 className="ini-matriz__grupo">{g.contratante}</h3>
              {g.obras.map(o => (
                <div key={o.contrato_id} className="ini-matriz__linha ini-matriz__linha--obra">
                  <span className="ini-matriz__obra">{o.obra}</span>
                  {competencias.map((c, i) => {
                    const cel = o.celulas[i];
                    if (!cel) return <span key={c} className="ini-matriz__celula" aria-hidden="true" />;
                    const nome = `${o.obra}, ${fmtCompetencia(c)}: ${ROTULO_MATRIZ[cel.etapa]}`;
                    return <Link key={c} para={{ tela: "medicao", obra: o.contrato_id, id: cel.medicao_id }}
                      className={`ini-matriz__celula ini-matriz__celula--${cel.etapa}`} aria-label={nome} title={nome}>{null}</Link>;
                  })}
                </div>))}
            </Fragment>))}
        </div>
        <div className="sr-only"><table>
          <caption>Etapa da medição de cada obra por competência</caption>
          <thead><tr><th scope="col">Obra</th><th scope="col">Contratante</th>
            {competencias.map(c => <th key={c} scope="col">{fmtCompetencia(c)}</th>)}</tr></thead>
          <tbody>
            {grupos.flatMap(g => g.obras.map(o => (
              <tr key={o.contrato_id}>
                <th scope="row">{o.obra}</th><td>{g.contratante}</td>
                {competencias.map((c, i) => { const cel = o.celulas[i]; return <td key={c}>{cel ? ROTULO_MATRIZ[cel.etapa] : "—"}</td>; })}
              </tr>)))}
          </tbody>
        </table></div>
      </>}
    </section>
  );
}

// #666: as secoes da caixa, na ordem da tela Avisos; "Depois" (31 a 90 dias) fica so' la'. O tom e' a cor da
// informacao: vencido = critico (vermelho); o que vence na semana ou no mes = vence em breve (ambar)
const SECOES_DA_CAIXA: Partial<Record<Secao, "acao" | "atencao">> = { vencido: "acao", semana: "atencao", mes: "atencao" };
const AVISOS_VISIVEIS = 3;

/** O selo de dias do item: "há N dias" no vencido; "hoje" ou "em N dias" no que vence. */
function seloDeDias(a: Aviso, secao: Secao): string {
  const n = Math.abs(diasAteOAviso(a) ?? 0), d = `${n.toLocaleString("pt-BR")} ${n === 1 ? "dia" : "dias"}`;
  return secao === "vencido" ? `há ${d}` : n === 0 ? "hoje" : `em ${d}`;
}

function ItemAviso({ a, secao, tom, ir }: { a: Aviso; secao: Secao; tom: "acao" | "atencao"; ir: Ir }) {
  const d = destinoDoAviso(a);
  // a obra (ou a empresa) abre a linha: a mensagem perde o "Nome: " do comeco, como na tela Avisos
  const quem = a.obra ?? a.entidade ?? "";
  const texto = semRSOrfao((a.obra ? semObra(a) : semEmpresa(a)).mensagem);
  const corpo = <>
    <span className="ini-aviso__nome">{quem ? `${quem} · ${texto}` : texto}</span>
    <span className={`ini-pilula ini-pilula--${tom}`}>{seloDeDias(a, secao)}</span>
  </>;
  return <li>{d ? <Link para={d.para} busca={d.busca} secao={d.secao} ir={ir} className="ini-aviso__linha">{corpo}</Link>
    : <span className="ini-aviso__linha">{corpo}</span>}</li>;
}

/** Caixa "Avisos importantes" (#666): so' o que esta' na agenda da tela Avisos, em tres secoes pelo tempo, cada uma
 *  com a contagem e os primeiros itens. `avisos`: `undefined` carregando, `null` falhou (como em AvisosPagina). */
function CaixaAvisos({ avisos, ir }: { avisos: Aviso[] | null | undefined; ir: Ir }) {
  const secoes = porSecao(daAgenda(avisos ?? [])).filter(s => SECOES_DA_CAIXA[s.id]);
  const total = secoes.reduce((n, s) => n + s.itens.length, 0);
  return (
    <aside aria-labelledby="ini-avisos" className="ini-painel ini-avisos">
      <header className="ini-avisos__topo">
        <h2 id="ini-avisos">Avisos importantes</h2>
        {avisos && <span className="ini-aviso__conta ini-avisos__total" aria-label={contar(total, "aviso", "avisos")}>{total.toLocaleString("pt-BR")}</span>}
        <Link para={{ tela: "avisos" }} ir={ir} className="ini-ver-todos" aria-label="Ver todos os avisos">Ver todos</Link>
      </header>
      {avisos === undefined && <p className="ini-carregando">Carregando…</p>}
      {avisos === null && <p className="erro" role="alert">Não foi possível verificar os avisos. Recarregue a página para tentar de novo.</p>}
      {avisos && total === 0 && <p className="ini-vazio">Nenhum aviso.</p>}
      {avisos && total > 0 && (
        <div className="ini-avisos__secoes">
          {secoes.map(s => {
            const tom = SECOES_DA_CAIXA[s.id] ?? "atencao", id = `ini-av-${s.id}`;
            return (
              <section key={s.id} aria-labelledby={id} className={`ini-aviso ini-aviso--${s.itens.length > 0 ? tom : "neutro"}`}>
                <header className="ini-aviso__topo">
                  <h3 id={id}>{s.rotulo}</h3>
                  <span className="ini-aviso__conta">{s.itens.length.toLocaleString("pt-BR")}</span>
                </header>
                {s.itens.length > 0 && (
                  <ul className="ini-aviso__lista">
                    {s.itens.slice(0, AVISOS_VISIVEIS).map((a, i) =>
                      <ItemAviso key={`${a.tipo}-${a.contrato_id}-${a.entidade_id ?? ""}-${a.medicao_id ?? ""}-${i}`} a={a} secao={s.id} tom={tom} ir={ir} />)}
                  </ul>)}
              </section>);
          })}
        </div>)}
    </aside>
  );
}

export default function Inicio({ usuario, ir }: { usuario: Usuario; ir: Ir }) {
  const [p, setP] = useState<PainelInicio | null>(null);
  const [erro, setErro] = useState("");
  const [avisos, setAvisos] = useState<Aviso[] | null | undefined>(undefined);

  useEffect(() => {
    let vivo = true;
    api<PainelInicio>("/api/inicio/painel")
      .then(d => { if (vivo) setP(d); })
      .catch(e => { if (vivo) setErro(mensagemDeErro(e)); });
    // a fila da tela Avisos; se falhar, so' a caixa mostra o erro
    api<{ avisos: Aviso[] }>("/api/inicio")
      .then(d => { if (vivo) setAvisos(d.avisos); })
      .catch(() => { if (vivo) setAvisos(null); });
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

  return (
    <div className="ini">
      <div className="ini-topo">
        {titulo}
        <LegendaCor />
      </div>
      <FaixaCiclo etapas={p.ciclo} />
      <Recebido12Meses meses={p.recebido_12m} />
      <PrevisaoEntrada previsao={p.previsao} />
      <MatrizObras matriz={p.matriz} />

      <section aria-label="Números do mês" className="ini-numeros">
        <div className="ini-numero">
          <span className="ini-numero__rotulo">Notas fiscais protocoladas em {fmtMesExtenso(p.hoje.slice(0, 7))}</span>
          <span className="ini-numero__valor">{brl(p.notas_mes.valor_centavos)}</span>
        </div>
        <div className="ini-numero">
          <span className="ini-numero__rotulo">Medido em {fmtMesExtenso(m.competencia)}</span>
          <span className="ini-numero__valor">{brl(m.valor_centavos)}</span>
        </div>
      </section>

      <CaixaAvisos avisos={avisos} ir={ir} />
    </div>
  );
}
