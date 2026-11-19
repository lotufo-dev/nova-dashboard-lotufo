// Tela SIGA (issue #329): o que o servidor devolve em GET /api/siga e as contas da tela (ordem, tempo no setor,
// nivel de atraso, textos da linha). Funcoes puras; o SigaPagina so' desenha o que sai daqui.

import type { Situacao } from "./situacao";
import { fmtData, fmtHora } from "./tempo";

export type TipoMovimentacao = "transferencia" | "recebimento" | "juntada" | "marcacao" | "outras";

export type Movimentacao = {
  data: string; evento: string | null; tipo: TipoMovimentacao; cad_lotacao: string; cad_pessoa: string; at_lotacao: string; at_pessoa: string;
};

// #663: quatro categorias fechadas. "medicoes" e' automatica (processo ligado a medicao ou a protocolo de medicao).
export type Categoria = "medicoes" | "aditivos" | "indenizatorios" | "outros";
export const CATEGORIAS: { categoria: Categoria; rotulo: string }[] = [
  { categoria: "medicoes", rotulo: "Medições" }, { categoria: "aditivos", rotulo: "Aditivos" },
  { categoria: "indenizatorios", rotulo: "Indenizatórios" }, { categoria: "outros", rotulo: "Outros" },
];

export type ProcessoSiga = {
  id: number; codigo: string | null; link: string | null; numero: string | null; nome: string | null;
  // o_que_e: a segunda parte do nome montado pelo servidor ("7ª Medição", "Aditivo de prazo")
  categoria: Categoria; complemento: string | null; o_que_e: string;
  // a categoria veio do nome que o robo mandou (ninguem escolheu ainda): a tela oferece confirmar
  categoria_sugerida?: boolean;
  // #805: o nome mostrado indica outra categoria que a escolhida por quem cadastrou (so' aviso; nada muda sozinho)
  categoria_a_conferir: Categoria | null;
  contrato_id: number | null; obra: string | null; medicao_id: number | null; medicao_titulo: string | null;
  // #805: o contratante da obra ("SINFRA", "SUEF II"); processo sem obra nao tem
  contratante: string | null; orgao_sub: string | null;
  // #805/#840: a leitura de "parado" do servidor (`siga.parado`: a regua do tempo parado sobre os dias sem
  // movimentacao); nula no encerrado e sem movimentacao nenhuma
  situacao_tempo: Situacao | null;
  protocolo_id: number | null; situacao: string | null; setor: string; caixa_entrada: boolean; com_quem: string;
  // #657: medicao recebida ou processo arquivado; derivado pelo servidor a cada leitura. null = vivo
  encerrado: "recebida" | "arquivado" | null;
  // desde/dias_uteis: a entrada no setor e o tempo nele (so' informacao). #840: dias_sem_movimentacao conta da `ultima`
  // (fora Marcacao e Anotacao), e `hoje` sao as movimentacoes de hoje fora Marcacao e Anotacao
  desde: string | null; dias_uteis: number | null; dias_sem_movimentacao: number | null; hoje: number; ultima: Movimentacao | null;
  protocolado_em: string | null; movimentacoes: Movimentacao[];
};

// Bloco `robo` (issue #342): rodada em andamento, pedidos em aberto (processo_id null = todos) e os avisos ja' com
// o texto da tela. O aviso com processo_id e' o "nao lido" daquele processo.
export type AvisoRobo = { tipo: string; processo_id: number | null; texto: string };
export type Robo = {
  estado: "lendo" | "na_fila" | "parado";
  rodada: { id: number; tipo: "automatica" | "pedido"; iniciada_em: string; processos: number[] } | null;
  // travado: o Windows recusou o disparo dele ou o robo nao comecou; o clique de novo dispara outra vez
  pedidos: { id: number; processo_id: number | null; usuario: string; pedido_em: string; travado: boolean }[];
  avisos: AvisoRobo[];
};

// #805: a faixa de numeros (so' os vivos; parados = os criticos) e os limites do tempo parado, do servidor
export type NumerosSiga = { acompanhados: number; parados: number; andaram_hoje: number; nao_lidos: number };
export type LimitesSiga = { dias_atencao: number; dias_critico: number };

export type PainelSiga = {
  lido_em: string | null; atrasado: boolean; processos: ProcessoSiga[]; pode_atualizar: boolean; robo: Robo;
  numeros: NumerosSiga; limites: LimitesSiga;
};

/** Ha' pedido que o robo ainda vai atender sozinho? O travado nao conta: a tela nao rele a cada 5 s por ele. */
export function roboAtivo(robo: Robo): boolean {
  return robo.rodada !== null || robo.pedidos.some(p => !p.travado);
}

/** O botao de atualizar um processo (`processoId`) ou todos (null) enquanto o pedido nao foi atendido: "lendo" com a
 *  rodada em andamento que o inclui (no "todos", qualquer rodada), "na_fila" com pedido em aberto que o cobre. Pedido
 *  travado nao segura o botao: o clique de novo dispara outra vez (o servidor reaproveita o pedido). */
export function situacaoDoBotao(robo: Robo, processoId: number | null): "lendo" | "na_fila" | null {
  if (robo.rodada && (processoId === null || robo.rodada.processos.includes(processoId))) return "lendo";
  if (robo.pedidos.some(p => !p.travado && (p.processo_id === null || p.processo_id === processoId))) return "na_fila";
  return null;
}

/** O atraso do processo como o quadro de Medicoes o marca, a partir da leitura do SERVIDOR (#840: dias sem
 *  movimentacao): andou hoje = feito; breve e critico ficam; dentro do prazo ("andamento"), nenhuma, porque ali so' o
 *  atraso leva marca. */
export function situacaoDoAtraso(p: { situacao_tempo: Situacao | null }): Situacao | undefined {
  return p.situacao_tempo === "andamento" || p.situacao_tempo === null ? undefined : p.situacao_tempo;
}

const instante = (iso: string | null, vazio: number): number => {
  const t = iso === null ? NaN : Date.parse(iso);
  return Number.isNaN(t) ? vazio : t;
};

/** Do mais parado ao menos, na ordem do servidor (`siga._mais_parado`, #840): mais dias sem movimentacao, empate
 *  pela ultima movimentacao mais antiga; sem movimentacao nenhuma vai para o fim. */
export function ordenar(processos: ProcessoSiga[]): ProcessoSiga[] {
  return [...processos].sort((a, b) => {
    return (b.dias_sem_movimentacao ?? -1) - (a.dias_sem_movimentacao ?? -1)
      || instante(a.ultima?.data ?? null, Infinity) - instante(b.ultima?.data ?? null, Infinity) || a.id - b.id;
  });
}

/** As secoes da tabela principal (#663): uma por categoria, na ordem fixa, cada uma do mais parado ao menos; a
 *  categoria sem processo nao aparece. */
export function porCategoria(processos: ProcessoSiga[]): { categoria: Categoria; rotulo: string; processos: ProcessoSiga[] }[] {
  return CATEGORIAS
    .map(c => ({ ...c, processos: ordenar(processos.filter(p => p.categoria === c.categoria)) }))
    .filter(s => s.processos.length > 0);
}

/** A categoria escolhida na URL (`?categoria=aditivos`); sem ela, ou com valor que nao e' categoria, todas (null). */
export function categoriaDaBusca(busca: Record<string, string>): Categoria | null {
  return CATEGORIAS.find(c => c.categoria === busca.categoria)?.categoria ?? null;
}

/** O "nao lido" do processo (#657): o aviso do robo para ele, sem as palavras que viram a etiqueta ("às 11:02: A
 *  página não abriu"). Sem aviso, null. */
export function naoLidoDe(robo: Robo, processoId: number): string | null {
  const aviso = robo.avisos.find(a => a.tipo === "nao_lido" && a.processo_id === processoId);
  return aviso ? aviso.texto.replace(/^não lido\s*/i, "") : null;
}

export const ROTULO_ENCERRADO = { recebida: "Medição recebida", arquivado: "Arquivado" } as const;

/** "N dias uteis" a partir de um dia util; antes disso, minutos ou horas; passado um dia corrido sem dia util
 *  completo (fim de semana, feriado), "menos de 1 dia util". */
export function tempoNoSetor(p: Pick<ProcessoSiga, "desde" | "dias_uteis">, agora: Date): string {
  if (p.desde === null || p.dias_uteis === null) return "—";
  if (p.dias_uteis >= 1) return p.dias_uteis === 1 ? "1 dia útil" : `${p.dias_uteis} dias úteis`;
  const desde = instante(p.desde, NaN);
  if (Number.isNaN(desde)) return "—";
  const minutos = Math.max(1, Math.floor((agora.getTime() - desde) / 60_000));
  if (minutos < 60) return `${minutos} min`;
  if (minutos < 24 * 60) return `${Math.floor(minutos / 60)} h`;
  return "menos de 1 dia útil";
}

/** "Dias sem movimentação" (#840): "andou hoje", "N dias úteis" ou, com a ultima movimentacao num fim de semana ou
 *  feriado depois do ultimo dia util, "menos de 1 dia útil". Sem movimentacao, "—". O numero vem do servidor. */
export function textoSemMovimentacao(p: Pick<ProcessoSiga, "dias_sem_movimentacao" | "hoje">): string {
  if (p.hoje > 0) return "andou hoje";
  const dias = p.dias_sem_movimentacao;
  if (dias === null) return "—";
  if (dias === 0) return "menos de 1 dia útil";
  return dias === 1 ? "1 dia útil" : `${dias} dias úteis`;
}

/** A data e a hora da movimentacao (#840): "dd/mm hh:mm", com o ano quando nao e' o de hoje ("dd/mm/aaaa hh:mm"). */
export function dataHoraCurta(iso: string, agora: Date): string {
  const [dia, hora] = [fmtData(iso), fmtHora(iso)];
  const ano = fmtData(agora.toISOString()).slice(6);
  return `${dia.slice(6) === ano ? dia.slice(0, 5) : dia} ${hora}`;
}

/** "(2º Volume)" quando o processo ja' esta' num volume depois do primeiro; o ultimo volume e' o da situacao. */
export function volumeDe(situacao: string | null): string {
  const ultimo = (situacao ?? "").split(" | ").pop() ?? "";
  const n = /(\d+)º\s*Volume/i.exec(ultimo);
  return n && Number(n[1]) > 1 ? `(${n[1]}º Volume)` : "";
}

/** O evento sem o texto que o SIGA poe depois de " |". */
export function tituloDoEvento(evento: string | null): string {
  return (evento ?? "").split("|")[0].trim();
}

/** "COFIN/ORGAO" -> "COFIN". */
export function sigla(lotacao: string | null): string {
  return (lotacao ?? "").split("/")[0].trim();
}

const ehTransferencia = (m: Movimentacao) => /transfer/i.test(m.evento ?? "");

/** Quem fez / quem tem: na transferencia, quem passou (cadastro); nas demais, a pessoa e o setor atribuidos. */
export function quemDaMovimentacao(m: Movimentacao): string {
  const t = ehTransferencia(m);
  const pessoa = (t ? m.cad_pessoa || m.at_pessoa : m.at_pessoa || m.cad_pessoa).trim();
  const setor = t ? sigla(m.cad_lotacao) || sigla(m.at_lotacao) : sigla(m.at_lotacao) || sigla(m.cad_lotacao);
  return [pessoa, setor].filter(Boolean).join(", ");
}

/** Para onde foi, na transferencia: o setor de destino. */
export function destinoDaMovimentacao(m: Movimentacao): string {
  return ehTransferencia(m) && sigla(m.at_lotacao) ? `→ ${sigla(m.at_lotacao)}` : "";
}

/** Nome montado pelo sistema (#663): "<obra> · <o que e'>". O numero do SIGA nao entra. Sem obra, o complemento
 *  e, na falta dele, o nome que o robo mandou. */
export function nomeDoProcesso(p: ProcessoSiga): string {
  if (p.obra) return `${p.obra} · ${p.o_que_e}`;
  return p.complemento || p.nome || p.numero || p.codigo || "Processo sem nome";
}

const semAcento = (s: string) => s.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();

/** Filtro por obra: obra, nome do robo, numero e medicao, sem maiuscula nem acento. */
export function casaComBusca(p: ProcessoSiga, texto: string): boolean {
  const q = semAcento(texto.trim());
  if (!q) return true;
  return [p.obra, p.nome, p.numero, p.medicao_titulo].some(c => c && semAcento(c).includes(q));
}

/* ------------------------------------------------------------ historico do processo (#512) */

export const TIPOS: { tipo: TipoMovimentacao; rotulo: string }[] = [
  { tipo: "transferencia", rotulo: "Transferências" }, { tipo: "recebimento", rotulo: "Recebimentos" },
  { tipo: "juntada", rotulo: "Juntadas" }, { tipo: "marcacao", rotulo: "Marcações" }, { tipo: "outras", rotulo: "Outras" },
];

/** Quantas movimentacoes ha' de cada tipo (os chips do historico). */
export function contagemPorTipo(movs: Movimentacao[]): Record<TipoMovimentacao, number> {
  const c: Record<TipoMovimentacao, number> = { transferencia: 0, recebimento: 0, juntada: 0, marcacao: 0, outras: 0 };
  for (const m of movs) c[m.tipo] += 1;
  return c;
}

/** A mais recente primeiro; por tipo (null = todas) e por texto em setor, pessoa ou documento, sem maiuscula nem acento. */
export function filtrarMovimentacoes(movs: Movimentacao[], tipo: TipoMovimentacao | null, texto: string): Movimentacao[] {
  const q = semAcento(texto.trim());
  return [...movs]
    .sort((a, b) => Date.parse(b.data) - Date.parse(a.data))
    .filter(m => (tipo === null || m.tipo === tipo)
      && (!q || [m.evento, m.cad_lotacao, m.cad_pessoa, m.at_lotacao, m.at_pessoa].some(c => c && semAcento(c).includes(q))));
}

/** O que o SIGA poe depois de " |" no evento (na juntada, o documento). */
export function detalheDoEvento(evento: string | null): string {
  const i = (evento ?? "").indexOf("|");
  return i < 0 ? "" : (evento as string).slice(i + 1).trim();
}

/** "COFIN · Ana": setor (sigla) e pessoa; so' o que houver. */
export function setorPessoa(lotacao: string | null, pessoa: string | null): string {
  return [sigla(lotacao), (pessoa ?? "").trim()].filter(Boolean).join(" · ");
}

/** A movimentacao que colocou o processo no setor atual (a que a linha destaca): a transferencia ou o recebimento
 *  da data de entrada no setor (#650). */
export function ehEntradaNoSetorAtual(p: ProcessoSiga, m: Movimentacao): boolean {
  return !p.caixa_entrada && (m.tipo === "recebimento" || m.tipo === "transferencia")
    && p.desde !== null && Date.parse(m.data) === Date.parse(p.desde);
}

/** "02/10/2026 a 23/10/2026" (primeira e ultima movimentacao); vazio sem movimentacao. */
export function periodoDe(movs: Movimentacao[], fmt: (iso: string) => string): string {
  if (movs.length === 0) return "";
  const tempos = movs.map(m => Date.parse(m.data));
  const menor = movs[tempos.indexOf(Math.min(...tempos))], maior = movs[tempos.indexOf(Math.max(...tempos))];
  return fmt(menor.data) === fmt(maior.data) ? fmt(menor.data) : `${fmt(menor.data)} a ${fmt(maior.data)}`;
}
