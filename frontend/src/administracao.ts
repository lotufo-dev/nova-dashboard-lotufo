// Administracao (NAVEGACAO.md › Administracao): as abas, os grupos da reconciliacao RM × dashboard e os filtros da
// auditoria, no front, sobre o que a API ja' manda (`/api/rm/reconciliacao`, `/api/admin/auditoria`).
import type { AbaAdmin, Rota } from "./rota";
import { diaLocal } from "./tempo";

/** As abas da Administracao, na ordem do mapa (a Saude e' a padrao). */
export const ABAS_ADMIN: { id: AbaAdmin; rotulo: string }[] = [
  { id: "saude", rotulo: "Saúde" }, { id: "reconciliacao", rotulo: "Reconciliação" },
  { id: "usuarios", rotulo: "Usuários" }, { id: "auditoria", rotulo: "Auditoria" },
];

/* ------------------------------------------------------------ reconciliacao */

export type NfSolta = { id: number; coligada: number; numero: string; serie: string | null; emissao: string | null;
                        valor_centavos: number; campo_livre1: string | null };
export type MedSemNf = { medicao_id: number; contrato_id: number; numero_instrumento: string; numero: number; tipo: string;
                         competencia: string; estado: string; valor_centavos: number | null };
export type Divergencia = { medicao_id: number; contrato_id: number; numero_instrumento: string; numero: number; tipo: string;
                            competencia: string | null; valor_centavos: number; alocado_centavos: number };
// A API nao manda o id da obra na alocacao desfeita, so' o instrumento.
// `id` e' o da alocacao (o cursor da pagina seguinte).
export type Desfeita = { id: number; medicao_id: number; desfeita_em: string; motivo_desfazer: string; numero: string; serie: string | null;
                         numero_instrumento: string; numero_medicao: number; estado: string };
// Issue #203: medicao recebida a mao com a NF ligada e o titulo ainda aberto no RM (uma linha por NF); `falta_centavos`
// e' o que o RM mostra em aberto, cheio. O recebimento manual vale; a linha e' o aviso de que o RM nao tem a baixa.
export type RecebidaSemBaixa = { medicao_id: number; contrato_id: number; numero_instrumento: string; numero: number; tipo: string;
                                 competencia: string | null; recebida_em: string | null; nota_id: number; numero_nf: string;
                                 serie: string | null; falta_centavos: number };
// #22: as NFs sem medicao e as alocacoes desfeitas chegam em paginas; `totais` e' o numero exato de cada uma e
// `ha_mais` diz se existe pagina seguinte
type PorPaginado<T> = { nfs_sem_medicao: T; alocacoes_desfeitas: T };
export type Reconciliacao = { nfs_sem_medicao: NfSolta[]; medicoes_sem_nf: MedSemNf[]; divergencias: Divergencia[];
                              alocacoes_desfeitas: Desfeita[]; recebidas_sem_baixa: RecebidaSemBaixa[];
                              totais: PorPaginado<number>; ha_mais: PorPaginado<boolean> };
type CampoPaginado = keyof PorPaginado<unknown>;

export type CategoriaRec = "nfs" | "medicoes" | "divergencias" | "desfeitas" | "recebidas";
/** Os grupos, na ordem da tela (`?categoria=` na URL). */
export const CATEGORIAS_REC: { id: CategoriaRec; campo: Exclude<keyof Reconciliacao, "totais" | "ha_mais">; titulo: string }[] = [
  { id: "nfs", campo: "nfs_sem_medicao", titulo: "NFs sem medição" },
  { id: "medicoes", campo: "medicoes_sem_nf", titulo: "Medições sem NF do RM" },
  { id: "divergencias", campo: "divergencias", titulo: "Divergências de valor" },
  { id: "desfeitas", campo: "alocacoes_desfeitas", titulo: "Alocações desfeitas" },
  { id: "recebidas", campo: "recebidas_sem_baixa", titulo: "Notas de recebimentos à mão sem baixa no RM" },
];

// #22: a API (`sincronizacao_rm.reconciliacao`) manda duas listas em paginas (200 NFs sem medicao, 50 alocacoes
// desfeitas, das mais recentes), depois da linha de id `?<parametro>=` (a ultima que a tela ja' tem: o cursor nao
// repete nem pula linha se a sincronizacao mudar a lista no meio), com o total exato em `totais`.
const PAGINADOS: Partial<Record<CategoriaRec, { campo: CampoPaginado; parametro: string }>> = {
  nfs: { campo: "nfs_sem_medicao", parametro: "nfs_apos" },
  desfeitas: { campo: "alocacoes_desfeitas", parametro: "desfeitas_apos" },
};

/** A contagem de um grupo: `n` linhas (exato, ou piso quando `piso`) e se ha' pagina seguinte na API.
 *  `rec` e' o que chegou; `d`, o recorte da obra (ou o proprio `rec`). Com a obra escolhida, as desfeitas da obra
 *  so' se contam no que ja' chegou: enquanto houver pagina, o numero e' piso. */
export function contaRec(rec: Reconciliacao, d: Reconciliacao, c: CategoriaRec, daObra: boolean): { n: number; piso: boolean; haMais: boolean } {
  const pag = PAGINADOS[c];
  const campo = CATEGORIAS_REC.find(x => x.id === c)!.campo;
  if (!pag) return { n: d[campo].length, piso: false, haMais: false };
  const haMais = rec.ha_mais[pag.campo];
  if (!daObra) return { n: rec.totais[pag.campo], piso: false, haMais };
  // as NFs sem medicao nao tem obra: com o filtro, o grupo fica vazio e nao ha' o que carregar
  if (c === "nfs") return { n: 0, piso: false, haMais: false };
  return { n: d[pag.campo].length, piso: haMais, haMais };
}

/** O endereco da pagina seguinte de um grupo paginado: depois do id da ultima linha que ja' chegou (as NFs vem da
 *  API pelo id, que nao muda; a tela as reordena pela emissao com `nfsPorEmissao`). */
export function urlPaginaRec(rec: Reconciliacao, c: CategoriaRec): string {
  const pag = PAGINADOS[c]!;
  const lista = rec[pag.campo];
  return `/api/rm/reconciliacao?${pag.parametro}=${lista[lista.length - 1].id}`;
}

/** Junta a pagina seguinte de um grupo ao que ja' chegou, descartando o id que ja' esta' na tela; o total e o
 *  `ha_mais` passam a ser os da pagina nova. As outras listas ficam como estavam. */
export function juntarPaginaRec(rec: Reconciliacao, c: CategoriaRec, pagina: Reconciliacao): Reconciliacao {
  const pag = PAGINADOS[c]!;
  const totais = { ...rec.totais, [pag.campo]: pagina.totais[pag.campo] };
  const ha_mais = { ...rec.ha_mais, [pag.campo]: pagina.ha_mais[pag.campo] };
  const novas = <T extends { id: number }>(ja: T[], vindas: T[]) => {
    const ids = new Set(ja.map(x => x.id));
    return [...ja, ...vindas.filter(x => !ids.has(x.id))];
  };
  return pag.campo === "nfs_sem_medicao"
    ? { ...rec, totais, ha_mais, nfs_sem_medicao: novas(rec.nfs_sem_medicao, pagina.nfs_sem_medicao) }
    : { ...rec, totais, ha_mais, alocacoes_desfeitas: novas(rec.alocacoes_desfeitas, pagina.alocacoes_desfeitas) };
}

/** As NFs sem medicao na ordem da tela: da emissao mais recente a mais antiga, as sem data por ultimo (empate: a que
 *  chegou depois primeiro). */
export function nfsPorEmissao(nfs: NfSolta[]): NfSolta[] {
  const cmp = (x: string, y: string) => (x < y ? -1 : x > y ? 1 : 0);
  return [...nfs].sort((a, b) => cmp(b.emissao ?? "", a.emissao ?? "") || b.id - a.id);
}

/** A quantidade de um grupo: "37", ou "3 ou mais" quando o numero e' piso. */
export function quantidadeRec(n: number, piso = false): string {
  return piso ? `${n} ou mais` : String(n);
}

/** O rotulo de um grupo sem o numero ("divergências de valor"), no singular quando n vale 1. */
export function rotuloRec(c: CategoriaRec, n: number): string {
  switch (c) {
    case "nfs": return n === 1 ? "NF sem medição" : "NFs sem medição";
    case "medicoes": return n === 1 ? "medição sem NF do RM" : "medições sem NF do RM";
    case "divergencias": return n === 1 ? "divergência de valor" : "divergências de valor";
    case "desfeitas": return n === 1 ? "alocação desfeita" : "alocações desfeitas";
    case "recebidas": return n === 1 ? "nota de recebimento à mão sem baixa no RM" : "notas de recebimentos à mão sem baixa no RM";
  }
}

/** A contagem de um grupo, em palavras ("37 divergências de valor"; "3 ou mais alocações desfeitas" quando piso). */
export function contagemRec(c: CategoriaRec, n: number, piso = false): string {
  return `${quantidadeRec(n, piso)} ${rotuloRec(c, n)}`;
}

/** A reconciliacao de uma obra: as medicoes sem NF e as divergencias pelo id da obra; as alocacoes desfeitas pelo
 *  instrumento; as NFs sem medicao nao tem obra e saem. Sem obra, tudo. */
export function reconciliacaoDaObra(rec: Reconciliacao, obra: { id: number; numero_instrumento: string | null } | null): Reconciliacao {
  if (obra === null) return rec;
  return {
    nfs_sem_medicao: [],
    medicoes_sem_nf: rec.medicoes_sem_nf.filter(m => m.contrato_id === obra.id),
    divergencias: rec.divergencias.filter(d => d.contrato_id === obra.id),
    alocacoes_desfeitas: obra.numero_instrumento === null ? [] : rec.alocacoes_desfeitas.filter(d => d.numero_instrumento === obra.numero_instrumento),
    recebidas_sem_baixa: rec.recebidas_sem_baixa.filter(x => x.contrato_id === obra.id),
    // os totais sao os da API, sem obra; a contagem da obra sai de `contaRec`
    totais: rec.totais, ha_mais: rec.ha_mais,
  };
}

/* ---------------------------------------------------------------- auditoria */

export type Evento = { id: number; acao: string; entidade: string | null; entidade_id?: string | null; criado_em: string;
                       usuario_id: number | null;
                       /** A obra da medicao ou do protocolo (a API resolve); nulo quando o objeto sumiu. */
                       contrato_id?: number | null };
export type FiltroAuditoria = { acao?: string | null; pessoa?: string | null; desde?: string | null };

// F-85: a acao e o objeto do evento em portugues. B-11 (10/10/2026): o mapa cobre toda acao que backend/app grava
// (grep de auditoria.registrar) e as que scripts gravaram no banco; a desconhecida cai no codigo legivel.
const ROTULO_ACAO: Record<string, string> = {
  "auth.login": "Entrada no sistema", "usuario.login": "Entrada no sistema",
  "auth.login_falha": "Tentativa de entrada recusada", "auth.logout": "Saída do sistema",
  "usuario.criar": "Usuário criado", "usuario.atualizar": "Usuário alterado", "usuario.desbloquear": "Usuário desbloqueado",
  "usuario.senha_redefinida": "Senha redefinida pelo admin", "usuario.senha_trocada": "Senha trocada",
  "medicao.criar": "Medição criada", "medicao.estado": "Mudança de estado da medição",
  "medicao.protocolo": "Protocolo da medição", "medicao.final": "Medição final marcada",
  "medicao.valor_protocolado": "Valor protocolado alterado", "medicao.valor_atestado": "Atestado alterado",
  "medicao.numero_orgao": "Número do órgão registrado na medição", "medicao.remover_teste": "Medição de teste removida",
  "medicao.documento": "Documento da medição", "medicao.faturada_legado": "Faturamento carregado do legado",
  "medicao.recebida_com_diferenca": "Recebida com diferença dentro da tolerância",
  "espelho.gerar": "Espelho gerado", "espelho.enviar": "Espelho enviado",
  "protocolo.criar": "Protocolo criado", "protocolo.peca": "Peça do protocolo anexada",
  "protocolo.peca_removida": "Peça do protocolo removida", "protocolo.montar": "Protocolo montado",
  "protocolo.assinado": "Protocolo assinado", "protocolo.enviar": "Protocolo enviado",
  "protocolo.numero_orgao": "Número do órgão registrado", "protocolo.descartar": "Protocolo descartado",
  "protocolo.link": "Link adicionado ao protocolo", "protocolo.link_removido": "Link removido do protocolo",
  "envio.liberar": "Envio liberado à mão", "notas.envio_externo": "Envio feito por fora registrado", "frc.gerar": "FRC gerada",
  "pleito.criar": "Pleito criado", "pleito.anexo": "Anexo do pleito", "pleito.anexo_removido": "Anexo do pleito removido",
  "pleito.montar": "Pleito montado", "pleito.assinado": "Pleito assinado", "pleito.enviar": "Pleito enviado",
  "pleito.descartar": "Pleito descartado",
  "nf.alocar": "NF alocada à medição", "nf.desalocar": "Alocação de NF desfeita",
  "nota.confirmacao": "Nota confirmada pelo RM", "nota.conferencia": "Nota conferida", "nota.justificar": "Nota justificada",
  "nota.manual": "Nota lançada à mão", "rm.sincronizacao": "Sincronização com o RM",
  "siga.vinculo": "Processo do SIGA ligado à medição",
  "aditivo.criar": "Aditivo criado", "aditivo.atualizar": "Aditivo alterado", "aditivo.cancelar": "Aditivo cancelado",
  "aditivo.assinar": "Aditivo assinado", "aditivo.carga": "Aditivos carregados do legado",
  "contrato.criar": "Obra criada", "contrato.atualizar": "Obra alterada", "contrato.mudar_estado": "Mudança de estado da obra",
  "contrato.encerramento": "Obra em encerramento", "cronograma.nova_versao": "Nova versão do cronograma",
  "certidao.marcar_estado": "Estado da certidão alterado", "certidao_tipo.criar": "Tipo de certidão criado",
  "certidao.registrar": "Certidão registrada", "certidao.nao_se_aplica": "Certidão marcada como não se aplica",
  "regularidade.registrar": "Regularidade registrada", "regularidade.competencia_corrigida": "Competência da regularidade corrigida",
  "entidade.criar": "Entidade criada", "entidade.coligada_rm": "Coligada do RM da entidade", "entidade.desativar": "Entidade desativada",
  "correio.envio": "E-mail enviado", "correio.assinatura": "Assinatura de e-mail gravada",
  "cadastro.aplicar": "Cadastro aplicado", "cadastro.orgao": "Cadastro: órgão", "cadastro.entidade": "Cadastro: entidade",
  "cadastro.consorciadas": "Cadastro: consorciadas", "cadastro.contrato": "Cadastro: obra", "cadastro.datas_base": "Cadastro: datas-base",
  "cadastro.fiscal": "Cadastro: fiscal", "cadastro.pleito": "Cadastro: pleito", "cadastro.instrumento": "Cadastro: instrumento",
  "cadastro.geral": "Cadastro: geral", "cadastro.espelho": "Cadastro: espelho", "cadastro.cronograma": "Cadastro: cronograma",
};
const ROTULO_ENTIDADE: Record<string, string> = {
  medicao: "Medição", contrato: "Obra", usuario: "Usuário", entidade: "Entidade", orgao: "Órgão", instrumento: "Instrumento",
  aditivo: "Aditivo", cadastro: "Cadastro", cadastro_geral: "Cadastro geral", certidao: "Certidão", certidao_tipo: "Tipo de certidão",
  regularidade: "Regularidade", protocolo: "Protocolo", pleito: "Pleito", envio: "E-mail", nota: "Nota", nf: "NF",
};

/** A acao de um evento em portugues ("medicao.protocolo" vira "Protocolo da medição"); sem rotulo, o codigo legivel
 *  ("algo.novo_aqui" vira "Algo novo aqui"). */
export function rotuloAcao(acao: string): string {
  if (ROTULO_ACAO[acao]) return ROTULO_ACAO[acao];
  const texto = acao.replace(/[._]+/g, " ").trim();
  return texto.charAt(0).toUpperCase() + texto.slice(1);
}

/** O objeto de um evento em portugues ("medicao 700" vira "Medição 700"); sem entidade, "—". */
export function rotuloObjeto(entidade: string | null, id?: string | null): string {
  if (!entidade) return "—";
  const nome = ROTULO_ENTIDADE[entidade] ?? entidade.charAt(0).toUpperCase() + entidade.slice(1).replace(/_/g, " ");
  return id ? `${nome} ${id}` : nome;
}

/** A tela do objeto de um evento, ou null quando ele nao tem tela (fica como texto): a obra, a medicao (na obra dela),
 *  o protocolo (que mora na aba Medicoes da obra dele) e o usuario (aba Usuarios da Administracao). */
export function rotaDoObjeto(ev: Pick<Evento, "entidade" | "entidade_id" | "contrato_id">): Rota | null {
  const id = ev.entidade_id && /^[0-9]+$/.test(ev.entidade_id) ? Number(ev.entidade_id) : null;
  if (id === null || id < 1) return null;
  switch (ev.entidade) {
    case "contrato": return { tela: "obra", id, aba: "medicoes" };
    case "medicao": return ev.contrato_id ? { tela: "medicao", obra: ev.contrato_id, id } : null;
    case "protocolo": return ev.contrato_id ? { tela: "obra", id: ev.contrato_id, aba: "medicoes" } : null;
    case "usuario": return { tela: "admin", aba: "usuarios" };
    default: return null;
  }
}

/** O campo do formulario de Novo usuario a que a mensagem de erro da API se refere (para o aria-invalid), se der para saber. */
export function campoDoErroDeUsuario(msg: string): "nome" | "email" | "senha" | "perfil" | null {
  if (/senha/i.test(msg)) return "senha";
  if (/e-?mail/i.test(msg)) return "email";
  if (/perfil/i.test(msg)) return "perfil";
  if (/nome/i.test(msg)) return "nome";
  return null;
}

/** A pessoa de um evento, como o filtro a guarda na URL: o id do usuario, ou "sistema" quando nao ha usuario. */
export function pessoaDoEvento(e: Evento): string {
  return e.usuario_id === null ? "sistema" : String(e.usuario_id);
}

/** Os eventos que passam nos filtros: a acao exata, a pessoa, e `desde` (AAAA-MM-DD) pelo dia de Cuiaba do evento. */
export function filtrarEventos(eventos: Evento[], f: FiltroAuditoria): Evento[] {
  return eventos.filter(e => (!f.acao || e.acao === f.acao)
    && (!f.pessoa || pessoaDoEvento(e) === f.pessoa)
    && (!f.desde || (diaLocal(e.criado_em) ?? "") >= f.desde));
}
