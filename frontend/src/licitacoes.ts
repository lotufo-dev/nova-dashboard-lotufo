// Licitacoes (#908 e fatia 2 da #906, docs/adr/0018): o que GET /api/licitacoes/triagem, /favoritas e /calendario
// devolvem, o texto que as paginas escrevem com isso e o pedido de cada decisao. Tudo vem pronto do servidor
// (`backend/app/licitacoes.py`): os dias uteis ate' cada prazo, a situacao do prazo, a etapa com o rotulo, a ordem das
// linhas, as contagens, as etapas, os motivos de descarte e as semanas do calendario. Aqui nao ha' limite nem conta: so'
// formato.

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiErro, mensagemDeErro } from "./api";
import type { Situacao } from "./situacao";
import { fmtData, fmtDataPura, fmtDiaNoAno, fmtHora } from "./tempo";

/** A situacao de um prazo, como o servidor a leu: critico, vence em breve ou nenhuma. */
export type SituacaoDoPrazo = Extract<Situacao, "critico" | "breve"> | null;

/** A ultima leitura do radar (o programa de fora que le as fontes). `atrasada`: e' de antes do dia esperado. */
export type LeituraDoRadar = { lido_em: string | null; atrasada: boolean; fontes_com_problema: number };

/** Um prazo da favorita. `passado` e `hoje` sao do servidor, pela data (na hora de Cuiaba): de sexta para sabado nao
 *  ha' dia util, e tanto o prazo que ja' passou quanto o de sabado podem vir com `dias_uteis: 0`. A tela nunca le
 *  "passou" nem "hoje" no numero de dias, nem compara a data com o relogio do computador. */
export type PrazoDaFavorita = {
  codigo: string; rotulo: string; data: string; hora: string | null; aviso: string; dias_uteis: number; passado: boolean;
  hoje: boolean; situacao: SituacaoDoPrazo;
};
/** Uma mudanca da favorita. `chave`: a identidade dela, que a tela devolve ao marcar como vista; `vista`: alguem ja'
 *  a marcou (so' depois do corte). A mais recente pode estar vista e uma anterior nao: o radar traz mudanca com a
 *  data de outra que ja' foi vista. */
export type MudancaDaFavorita = { chave: string; data: string; texto: string; rotulo: string; vista: boolean };

/** A favorita: a licitacao que se decidiu acompanhar. A etapa vem do dossie quando ha' dossie (`etapa_do_dossie`). */
export type Favorita = {
  desde: string; etapa: string; etapa_rotulo: string; etapa_do_dossie: boolean; dossie: string | null;
  /** o que o dossie diz alem da etapa ("Diretoria: interesse", "Suspensa"); pode vir vazia */
  selos: string[];
  prazos: PrazoDaFavorita[]; proximo_prazo: PrazoDaFavorita | null; mudancas: MudancaDaFavorita[];
  /** quantas das mudancas ninguem marcou como vistas */
  mudancas_novas: number;
};

/** A recomendacao: a nota, o motivo e o local da obra pelo radar (`cidade`, que pode vir vazia, e `km`). */
export type Recomendada = {
  nota: number; pontos: { valor: number; distancia: number; acervo: number }; motivo: string;
  km: number | null; cidade: string;
};

/** Uma licitacao, com a mesma forma nas duas rotas. `orgao_de_interesse`: um dos orgaos que o dono acompanha de perto
 *  (as novas deles ja' vem contadas em `contagens.por_orgao`). */
export type LinhaLicitacao = {
  /** o numero pelo qual as decisoes enderecam a licitacao */
  id: number;
  chave: string; orgao: string; sigla_orgao: string; grupo_orgao: string; orgao_de_interesse: boolean; esfera: string | null;
  municipio: string; uf: string;
  cidade: string; km: number | null; edital: string; modalidade: string; objeto: string; tipo_obra: string;
  valor_centavos: number | null; valor_rotulo: string; situacao: string; data_publicacao: string | null;
  data_sessao: string | null; hora_sessao: string | null; primeira_vez: string | null; link: string; portal: string; fontes: string[];
  recomendada: Recomendada | null;
  /** dias uteis ate' a sessao; nulo e' sem data. Sessao passada e' `encerrada`, nunca o sinal dos dias */
  dias_uteis: number | null;
  /** a sessao e' hoje, pelo servidor */
  sessao_hoje: boolean;
  prazo: SituacaoDoPrazo; encerrada: boolean; favorita: Favorita | null;
};

/** De que lado estao as decisoes (`docs/adr/0018`): ate' o corte sao espelho do radar e a tela nao tem botao.
 *  `pode_decidir`: depois do corte, e so' para quem decide; e' o que acende os botoes. */
type Poder = { decisoes: "radar" | "dashboard"; pode_decidir: boolean };
export type MotivoDeDescarte = { motivo: string; rotulo: string };
export type EtapaDaFavorita = { etapa: string; rotulo: string };

export type RespostaTriagem = Poder & {
  leitura: LeituraDoRadar;
  contagens: {
    recomendadas: number; favoritas: number; novas: number;
    novas_desde: { desde: string; quantas: number } | null;
    por_orgao: { orgao: string; novas: number }[];
  };
  favoritas: LinhaLicitacao[]; recomendadas: LinhaLicitacao[];
  /** os motivos que a janela do descarte oferece, na ordem */
  motivos_descarte: MotivoDeDescarte[];
};
/** `etapas`: as colunas do quadro e as opcoes do controle de etapa, na ordem. */
export type RespostaFavoritas = Poder & { leitura: LeituraDoRadar; etapas: EtapaDaFavorita[]; favoritas: LinhaLicitacao[] };

/** Um prazo no calendario: o da lista, com a licitacao a que pertence. */
export type PrazoNoCalendario = PrazoDaFavorita & {
  licitacao: Pick<LinhaLicitacao, "id" | "chave" | "orgao" | "sigla_orgao" | "edital" | "modalidade" | "objeto" | "link" | "encerrada">;
};
export type DiaDoCalendario = { data: string; do_mes: boolean; hoje: boolean; prazos: PrazoNoCalendario[] };
/** O mes das favoritas, em semanas de domingo a sabado. `prazos`: quantos ha' no mes. */
export type RespostaCalendario = Poder & {
  leitura: LeituraDoRadar; mes: string; anterior: string; proximo: string; mes_atual: boolean; prazos: number;
  semanas: DiaDoCalendario[][];
};

/** O que POST /api/licitacoes/{id}/analise devolve: o comando para colar na sessao de analise e, sem link de edital, o
 *  aviso. */
export type AnaliseDoEdital = { id: number; favoritou: boolean; comando: string; aviso: string | null };

/** Le uma rota de Licitacoes ao abrir a pagina; `tentar` le de novo (depois da falha, ou depois de uma decisao) e
 *  termina quando a leitura chega. So' a resposta do ultimo pedido vale. */
export function useLicitacoes<T>(caminho: string) {
  const [dados, setDados] = useState<T | null>(null);
  const [erro, setErro] = useState("");
  const pedido = useRef(0);
  const tentar = useCallback((): Promise<void> => {
    const n = ++pedido.current;
    return api<T>(caminho).then(
      d => { if (n === pedido.current) { setDados(d); setErro(""); } },
      e => { if (n === pedido.current) setErro(mensagemDeErro(e)); });
  }, [caminho]);
  useEffect(() => {
    void tentar();
    return () => { pedido.current += 1; };
  }, [tentar]);
  return { dados, erro, tentar };
}

/** A recusa de uma decisao, junto da licitacao a que se refere. `nome`: para dizer de qual e' quando a linha dela ja'
 *  saiu da lista. */
export type FalhaDaDecisao = { id: number; nome: string; texto: string };

/** As decisoes da pagina (favoritar, descartar, etapa...): POST /api/licitacoes/{id}/{decisao} e, aceito, a leitura de
 *  novo, para a linha sair pelo que o servidor diz (a tela nao mexe na lista). Uma decisao por vez na pagina: `ocupada`
 *  diz que ha' pedido em curso, e os botoes de decisao ficam desligados ate' a leitura nova chegar. `falha`: a recusa
 *  do servidor, nas palavras dele. Recusa 409 ou 404 quer dizer que a pagina esta' atrasada (outra aba, outra pessoa,
 *  resposta perdida na rede): a pagina le de novo, e a recusa continua dita. */
export function useDecisoes(recarregar: () => Promise<void>) {
  const [ocupada, setOcupada] = useState(false);
  const emCurso = useRef(false);
  const [falha, setFalha] = useState<FalhaDaDecisao | null>(null);
  const decidir = async <R = unknown>(
    l: Pick<LinhaLicitacao, "id" | "orgao" | "sigla_orgao" | "edital" | "modalidade">, decisao: string,
    corpo: Record<string, string | string[]> = {},
  ): Promise<R | null> => {
    if (emCurso.current) return null;
    emCurso.current = true;
    setOcupada(true);
    setFalha(null);
    try {
      const resposta = await api<R>(`/api/licitacoes/${l.id}/${decisao}`, { method: "POST", body: JSON.stringify(corpo) });
      await recarregar();
      return resposta;
    } catch (e) {
      setFalha({ id: l.id, nome: nomeDaLicitacao(l), texto: mensagemDeErro(e) });
      if (e instanceof ApiErro && (e.status === 409 || e.status === 404)) await recarregar();
      return null;
    } finally {
      emCurso.current = false;
      setOcupada(false);
    }
  };
  return { ocupada, falha, decidir, limparFalha: () => setFalha(null) };
}

/** O que GET /api/licitacoes/resumo devolve para a linha da Inicio: os numeros da Triagem, pela mesma funcao do
 *  servidor (`licitacoes.resumo`). A rota e' de quem tem `ver_licitacoes`. */
export type ResumoDasLicitacoes = { leitura: LeituraDoRadar; recomendadas: number; favoritas: number };

/** O nome curto da licitacao, para o titulo da janela e o nome dos botoes: "SEOBRAS-EX · CE 012/2026". */
export function nomeDaLicitacao(l: Pick<LinhaLicitacao, "orgao" | "sigla_orgao" | "edital" | "modalidade">): string {
  const edital = l.edital || l.modalidade;
  return `${orgaoDaLinha(l)}${edital ? ` · ${edital}` : ""}`;
}

/** Copia o texto de um campo. `navigator.clipboard` so' existe em contexto seguro, e a producao roda em http: sem ele,
 *  a copia antiga (selecionar e execCommand), feita no proprio campo. O campo esta' dentro da janela: com um <dialog>
 *  modal aberto, o que fica fora dele e' inerte, nao recebe foco nem selecao, e o execCommand responde que copiou sem
 *  ter copiado nada. Por isso so' devolve que copiou quando o campo ficou mesmo com o foco e o texto todo selecionado. */
export async function copiarTexto(campo: HTMLInputElement): Promise<boolean> {
  const texto = campo.value;
  try {
    if (navigator.clipboard) { await navigator.clipboard.writeText(texto); return true; }
  } catch { /* cai na copia antiga */ }
  campo.focus();
  campo.select();
  if (document.activeElement !== campo || campo.selectionStart !== 0 || campo.selectionEnd !== texto.length) return false;
  try { return document.execCommand("copy"); } catch { return false; }
}

/** O endereco do edital, so' quando e' http ou https: o servidor ja' valida, e a tela nao confia. */
export function linkExterno(link: string | null | undefined): string | null {
  return /^https?:\/\//i.test(link ?? "") ? (link as string) : null;
}

/** Quando o radar leu: "24/11 às 09:05", na hora de Cuiaba. */
export function quandoLeu(lidoEm: string): string {
  return `${fmtData(lidoEm).slice(0, 5)} às ${fmtHora(lidoEm)}`;
}

/** O aviso da leitura atrasada; sem leitura nenhuma, que o radar ainda nao entregou. */
export function avisoDaLeitura(leitura: LeituraDoRadar): string {
  return leitura.lido_em ? `O radar não lê desde ${quandoLeu(leitura.lido_em)}.` : "O radar ainda não entregou leitura.";
}

/** Os dias uteis que o servidor contou ate' um prazo que ainda nao passou, por extenso: "em 1 dia útil", "em 12 dias
 *  úteis". No dia do prazo (`hoje`, que o servidor manda), "hoje". Sem dia util ate' la' e noutro dia (o prazo de sabado
 *  visto na sexta), "antes do próximo dia útil": zero dias uteis nao quer dizer hoje. Sem a contagem, nada. Se o prazo
 *  passou quem diz e' o servidor (`passado`, `encerrada`), e ai' esta funcao nem e' chamada. */
export function emDiasUteis(dias: number | null, hoje: boolean): string | null {
  if (dias === null) return null;
  if (hoje) return "hoje";
  return dias <= 0 ? "antes do próximo dia útil" : dias === 1 ? "em 1 dia útil" : `em ${dias.toLocaleString("pt-BR")} dias úteis`;
}

/** Data pura e hora de um prazo: "27/11" no ano de hoje, "01/03/2027" em outro, com a hora quando ha'. */
export function dataDoPrazo(data: string, hora: string | null, hoje?: string): string {
  return `${fmtDiaNoAno(data, hoje) ?? fmtDataPura(data)}${hora ? ` ${hora}` : ""}`;
}

/** O orgao como a linha o escreve: a sigla, quando o radar a manda; senao o nome. */
export function orgaoDaLinha(l: Pick<LinhaLicitacao, "orgao" | "sigla_orgao">): string {
  return l.sigla_orgao || l.orgao;
}

/** A distancia ate' a obra: "1.250 km", com o espaco que nao separa o numero da unidade; nulo sem distancia. */
export function fmtKm(km: number | null): string | null {
  return km === null ? null : `${km.toLocaleString("pt-BR")}\u00a0km`;
}

/* ------------------------------------------------------------------ Todas e Grande vulto (fatia 3 da #906) */

/** Uma opcao de filtro: o valor que vai no endereco, o rotulo e quantas licitacoes a lista teria escolhendo-a (com os
 *  outros filtros como estao). A conta e' do servidor. */
export type OpcaoDoFiltro = { valor: string; rotulo: string; n: number };
/** Um filtro de escolha, com as opcoes na ordem do servidor. `escolhido`: o valor do endereco, mesmo que nao ache nada. */
export type FiltroDeTodas = { filtro: string; rotulo: string; escolhido: string | null; opcoes: OpcaoDoFiltro[] };
/** O descarte em vigor de uma licitacao: o motivo, com o rotulo, e quando. */
export type DescarteEmVigor = { motivo: string; rotulo: string; quando: string };
export type LinhaDeTodas = LinhaLicitacao & { descarte: DescarteEmVigor | null };
export type OrdemDeTodas = "padrao" | "prazo" | "publicacao" | "valor";
/** O que GET /api/licitacoes/todas devolve: as linhas ja' filtradas e na ordem, `total` (quantas a vista tem sem
 *  filtro), os filtros com as opcoes e as ordens. */
export type RespostaTodas = Poder & {
  leitura: LeituraDoRadar; vista: "novas" | "grande-vulto"; total: number; ordem: OrdemDeTodas;
  ordens: { ordem: OrdemDeTodas; rotulo: string }[]; filtros: FiltroDeTodas[]; linhas: LinhaDeTodas[];
};

/** Os filtros de Todas que vivem na busca do endereco, alem da ordem. */
export const FILTROS_DE_TODAS = ["q", "tipo", "modalidade", "orgao", "esfera", "valor", "km", "situacao", "decisao", "portal",
  "sessao_de", "sessao_ate"] as const;
const ORDENS: readonly string[] = ["padrao", "prazo", "publicacao", "valor"];
const DATA = /^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$/;
/** Data que existe no calendario (31/02 nao) e que o servidor aceita (o ano 0 nao). */
const dataValida = (v: string) => DATA.test(v) && v >= "0001" && new Date(`${v}T00:00:00Z`).toISOString().slice(0, 10) === v;

/** O pedido de Todas a partir da busca do endereco. O que nao cabe no que o servidor aceita fica de fora (data fora do
 *  formato, ordem desconhecida), para um link estragado abrir a lista em vez de uma falha; o texto vai cortado no
 *  tamanho que o servidor aceita. */
export function pedidoDeTodas(vista: "novas" | "grande-vulto", busca: Record<string, string>): string {
  const q = new URLSearchParams({ vista });
  for (const f of FILTROS_DE_TODAS) {
    const v = (busca[f] ?? "").trim();
    if (!v) continue;
    if (f === "sessao_de" || f === "sessao_ate") { if (dataValida(v)) q.set(f, v); continue; }
    q.set(f, v.slice(0, f === "q" ? 200 : 120));
  }
  if (ORDENS.includes(busca.ordem ?? "") && busca.ordem !== "padrao") q.set("ordem", busca.ordem);
  return `/api/licitacoes/todas?${q.toString()}`;
}

/** Ha' algum filtro (ou busca, ou ordem que nao e' a padrao) no endereco? */
export function temFiltro(busca: Record<string, string>): boolean {
  return FILTROS_DE_TODAS.some(f => (busca[f] ?? "").trim() !== "") || ((busca.ordem ?? "") !== "" && busca.ordem !== "padrao");
}
