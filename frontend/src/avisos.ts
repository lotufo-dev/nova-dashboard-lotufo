// Regras de APRESENTACAO da tela de Avisos (NAVEGACAO.md › Avisos): funcoes puras sobre o aviso que o servidor
// manda pronto (`app/avisos.py`). Nada aqui decide nivel, prazo ou atraso: so' agrupa, filtra e ordena.
import { porAtraso, type Aviso, type Nivel } from "./Alertas";
import { hojeLocal } from "./tempo";

export type Familia = "prazo" | "reajuste" | "nota" | "siga" | "documentos" | "outros";

// A ordem dos grupos e' a do mapa; "Outros" guarda o aviso de lar desconhecido, para nada sumir. A familia
// Dinheiro saiu com o aviso de pagamento atrasado (issue #255), que era o unico dela. A pagina Avisos nao usa mais a
// familia: as abas dela sao os ASSUNTOS (abaixo, #805), pelo tipo do aviso.
export const FAMILIAS: { id: Familia; rotulo: string }[] = [
  { id: "prazo", rotulo: "Prazo" }, { id: "reajuste", rotulo: "Reajuste" }, { id: "nota", rotulo: "Nota" },
  { id: "siga", rotulo: "SIGA" }, { id: "documentos", rotulo: "Documentos" }, { id: "outros", rotulo: "Outros" },
];

/** A familia e' o lar do aviso: o `destino` que o servidor manda (a aba da obra, ou Documentos). */
export function familiaDoAviso(a: Aviso): Familia {
  const d = a.destino;
  if (d?.tela === "documentos") return "documentos";
  if (d?.tela === "siga") return "siga";
  if (d?.tela === "contrato") {
    if (d.aba === "prazos") return "prazo";
    if (d.aba === "reajuste") return "reajuste";
    if (d.aba === "notas") return "nota";
  }
  return "outros";
}

// ---- Assunto (#805): as abas da pagina Avisos, o resumo dos Vencidos por obra e a coluna da Agenda ----
//
// O assunto sai do `tipo` do aviso, e nao do destino: pelo destino, a garantia caia com a certidao (as duas abrem
// Documentos) e o aviso de medicao caia em "Outros" (o destino padrao e' a aba Medicoes da obra). Sao os assuntos da
// proposta aprovada pelo dono em 18/11/2026, mais o SIGA: o processo parado no orgao pode ser de aditivo ou de
// indenizatorio, e o monitor sem leitura nao e' de medicao nenhuma. A familia (acima, pelo destino) nao muda.

export type Assunto = "prazos" | "reajustes" | "garantias" | "certidoes" | "medicoes" | "siga" | "outros";

/** Na ordem das abas. "Outros" so' aparece se o servidor mandar um tipo que o mapa nao conhece. */
export const ASSUNTOS: { id: Assunto; rotulo: string }[] = [
  { id: "prazos", rotulo: "Prazos" }, { id: "reajustes", rotulo: "Reajustes" }, { id: "garantias", rotulo: "Garantias" },
  { id: "certidoes", rotulo: "Certidões" }, { id: "medicoes", rotulo: "Medições" }, { id: "siga", rotulo: "SIGA" },
  { id: "outros", rotulo: "Outros" },
];

/** O assunto de CADA tipo de aviso que o servidor emite (`backend/app`: prazos.py, reajuste.py, garantias.py,
 *  documentos.py, notas.py, avisos_medicao.py, capa_smo.py, siga.py e os dois do espelho em avisos.py). Tipo novo no
 *  servidor entra AQUI: `avisos.test.ts` le os tipos do codigo do servidor e reprova o que faltar, para ele nao cair
 *  calado em "Outros". */
export const ASSUNTO_DO_TIPO: Readonly<Record<string, Exclude<Assunto, "outros">>> = {
  // o prazo da obra: execucao, vigencia, o instrumento de prazo pendente, a folga, a paralisacao e o encerramento
  execucao_vencendo: "prazos", vigencia_vencendo: "prazos", instrumento_pendente: "prazos", execucao_sem_prazo: "prazos",
  folga_quebrada: "prazos", obra_paralisada: "prazos", conclusao_nao_comunicada: "prazos",
  reajuste_pleito: "reajustes", reajuste_sem_resposta: "reajustes", reajuste_apostilamento: "reajustes",
  reajuste_sem_apostilamento: "reajustes", reajuste_nota_antes_do_apostilamento: "reajustes", reajuste_reemitir: "reajustes",
  // a garantia do contrato: a que vence, a que nao cobre o fim da execucao e o endosso depois de um aditivo
  garantia_vencendo: "garantias", garantia_aquem_execucao: "garantias", endosso_garantia: "garantias",
  // os documentos da empresa: as certidoes e a regularidade do mes
  documentos_empresa: "certidoes", regularidade_mes: "certidoes",
  // o ciclo da medicao: a planilha, o boletim (e a capa dele), o espelho e a nota
  planilha_nao_enviada: "medicoes", pedido_sem_boletim: "medicoes", aprovado_abaixo_do_pedido: "medicoes",
  medicao_fora_de_ordem: "medicoes",
  capa_prazo_divergente: "medicoes", capa_instrumento_ausente: "medicoes", capa_valor_contrato_divergente: "medicoes",
  capa_acumulado_divergente: "medicoes",
  espelho_desatualizado: "medicoes", espelho_nao_conferido: "medicoes",
  nota_divergente: "medicoes", nota_acima_da_medicao: "medicoes", notas_pagas_nao_cobrem: "medicoes",
  recebida_notas_nao_cobrem: "medicoes", nota_ausente_rm: "medicoes", nota_cancelada_rm: "medicoes",
  siga_parado: "siga", siga_sem_leitura: "siga",
};

/** O assunto do aviso, pelo `tipo`; o tipo que o mapa nao conhece fica em "Outros", para nada sumir. */
export function assuntoDoAviso(a: Aviso): Assunto {
  return Object.prototype.hasOwnProperty.call(ASSUNTO_DO_TIPO, a.tipo) ? ASSUNTO_DO_TIPO[a.tipo] : "outros";
}

/** O nome do assunto, como a aba, o resumo dos vencidos e a coluna da Agenda o escrevem. */
export const rotuloDoAssunto = (id: Assunto) => ASSUNTOS.find(x => x.id === id)?.rotulo ?? id;

// O `?familia=` dos links de antes. Os plurais que o Inicio mandava (prazos, reajustes, certidoes) sao hoje os ids
// dos assuntos; aqui ficam os ids da familia (pelo destino). A familia "Documentos" juntava certidao e garantia: abre
// Certidoes, como o `?familia=certidoes` de antes abria ela. A familia "Nota" eram avisos de medicao. "siga" e
// "outros" tem o mesmo id nos dois.
const ASSUNTO_DE_ANTES: Readonly<Record<string, Assunto>> = {
  prazo: "prazos", reajuste: "reajustes", documentos: "certidoes", nota: "medicoes",
};

/** A aba da rota (`?familia=`): o id do assunto, ou o valor dos links de antes. Valor desconhecido: sem filtro. */
export function assuntoDaBusca(v: string | undefined): Assunto | null {
  const id = v !== undefined && Object.prototype.hasOwnProperty.call(ASSUNTO_DE_ANTES, v) ? ASSUNTO_DE_ANTES[v] : v;
  return ASSUNTOS.find(x => x.id === id)?.id ?? null;
}

export type FiltroAvisos = { familia?: Familia | null; nivel?: Nivel | null; obra?: number | null };

export function filtrarAvisos(avisos: Aviso[], f: FiltroAvisos): Aviso[] {
  return avisos.filter(a => (!f.familia || familiaDoAviso(a) === f.familia)
    && (!f.nivel || a.nivel === f.nivel) && (!f.obra || a.contrato_id === f.obra));
}

export type Grupo = { chave: string; rotulo: string; contratoId: number | null; entidadeId?: number | null; itens: Aviso[] };

/** Por familia, na ordem do mapa; dentro, do mais grave ao mais atrasado. So' os grupos com aviso. */
export function porFamilia(avisos: Aviso[]): Grupo[] {
  return FAMILIAS.map(f => ({ chave: f.id, rotulo: f.rotulo, contratoId: null,
    itens: porAtraso(avisos.filter(a => familiaDoAviso(a) === f.id)) })).filter(g => g.itens.length > 0);
}

/** Por obra (o `contrato_id` do aviso), a do aviso mais grave primeiro; os avisos de empresa sem obra, por empresa
 *  (A11: o nome vem do servidor); o resto sem obra num grupo so'. Cada grupo na posicao do aviso mais grave dele. */
export function porObra(avisos: Aviso[]): Grupo[] {
  const grupos = new Map<string, Grupo>();
  for (const a of porAtraso(avisos)) {
    const chave = a.contrato_id !== null ? `obra-${a.contrato_id}` : a.entidade_id != null ? `empresa-${a.entidade_id}` : "sem-obra";
    const g = grupos.get(chave) ?? (a.contrato_id !== null
      ? { chave, rotulo: a.obra ?? `Obra ${a.contrato_id}`, contratoId: a.contrato_id, itens: [] }
      : a.entidade_id != null
        // "Documentos · Oriundi": o nome da empresa pode ser o mesmo de uma obra (o consorcio e a obra dele)
        ? { chave, rotulo: `Documentos · ${a.entidade ?? `empresa ${a.entidade_id}`}`, contratoId: null, entidadeId: a.entidade_id, itens: [] }
        : { chave, rotulo: "Avisos sem obra", contratoId: null, itens: [] });
    g.itens.push(a);
    grupos.set(chave, g);
  }
  // o Map guarda a ordem de insercao: a da primeira aparicao na lista por atraso, que e' a do aviso mais grave
  return [...grupos.values()];
}

/** Quando, pelos dias do servidor e o sentido deles (A8): o prazo que vence ou venceu, ou o fato parado ha' N dias. */
export function quandoDoAviso(a: Aviso): string {
  if (a.dias === null) return "—";
  const n = Math.abs(a.dias), d = `${n}\u00a0${n === 1 ? "dia" : "dias"}`;
  if (a.sentido === "desde") return `há ${d}`;
  if (a.sentido === "prazo") return a.dias > 0 ? `vence em ${d}` : a.dias === 0 ? "vence hoje" : `venceu há ${d}`;
  return a.dias >= 0 ? `${d}` : `há ${d}`;
}

/** O "R$" nao fica orfao no fim da linha: o espaco depois dele nao separa (N04-09). A mensagem vem pronta do servidor. */
export const semRSOrfao = (t: string) => t.replace(/R\$ /g, "R$\u00a0");

// ---- Avisos pelo tempo (#511): Vencido \u00b7 Esta semana \u00b7 Este m\u00eas \u00b7 Depois, e "Sem data" ----

// Agenda (#656): so' o aviso com data entra, do que ja' venceu ate' HORIZONTE_DIAS a frente; a secao "Sem data" saiu.
export type Secao = "vencido" | "semana" | "mes" | "depois";

export const SECOES: { id: Secao; rotulo: string }[] = [
  { id: "vencido", rotulo: "Vencido" }, { id: "semana", rotulo: "Esta semana" }, { id: "mes", rotulo: "Este m\u00eas" },
  { id: "depois", rotulo: "Depois" },
];

/** Ate' onde a agenda olha: o que vence depois disso nao aparece (#656). O vencido nao tem limite de idade. */
export const HORIZONTE_DIAS = 90;

const diaUTC = (iso: string) => Date.UTC(Number(iso.slice(0, 4)), Number(iso.slice(5, 7)) - 1, Number(iso.slice(8, 10)));

/** Dias ate' o fato, com sinal: negativo = ja' passou. O fato parado "desde" N dias (sentido do servidor) e' passado;
 *  o prazo ("prazo") vem com o sinal certo; sem sentido, o sinal dos dias manda. Aviso com `data` e sem `dias` (#656)
 *  e' posicionado pela data, contra `hoje` (AAAA-MM-DD, o dia de Cuiaba). `null` = sem data: fora da agenda. */
export function diasAteOAviso(a: Aviso, hoje: string = hojeLocal()): number | null {
  if (a.dias === null || a.dias === undefined) {
    return a.data && /^\d{4}-\d{2}-\d{2}/.test(a.data) ? Math.round((diaUTC(a.data) - diaUTC(hoje)) / 86_400_000) : null;
  }
  return a.sentido === "desde" ? -Math.abs(a.dias) : a.dias;
}

/** A secao do aviso pelos dias e pelo sentido: passado = Vencido; 0 a 7 dias = Esta semana; 8 a 30 = Este mes;
 *  31 a 90, Depois. `null` = fora da agenda: sem data, ou alem de 90 dias. Cada aviso cai em uma secao so'. */
export function secaoDoAviso(a: Aviso, hoje?: string): Secao | null {
  const d = diasAteOAviso(a, hoje);
  if (d === null || d > HORIZONTE_DIAS) return null;
  if (d < 0) return "vencido";
  if (d <= 7) return "semana";
  if (d <= 30) return "mes";
  return "depois";
}

/** So' os avisos da agenda: com data, do que ja' venceu ate' 90 dias a frente. */
export function daAgenda(avisos: Aviso[], hoje?: string): Aviso[] {
  return avisos.filter(a => secaoDoAviso(a, hoje) !== null);
}

/** As secoes na ordem da tela: vencido = o mais antigo primeiro; a vencer = o mais proximo primeiro. */
export function porSecao(avisos: Aviso[], hoje?: string): { id: Secao; rotulo: string; itens: Aviso[] }[] {
  const ordem = (x: Aviso, y: Aviso) => (diasAteOAviso(x, hoje) ?? 0) - (diasAteOAviso(y, hoje) ?? 0)
    || (x.data ?? "").localeCompare(y.data ?? "");
  return SECOES.map(s => ({ ...s, itens: avisos.filter(a => secaoDoAviso(a, hoje) === s.id).sort(ordem) }));
}

/** Os dias com sinal, por extenso, como o selo os escreve: "há 3 dias" no que passou, "hoje", "em 5 dias". */
export function diasPorExtenso(d: number): string {
  const n = Math.abs(d), txt = `${n.toLocaleString("pt-BR")} ${n === 1 ? "dia" : "dias"}`;
  return d < 0 ? `há ${txt}` : d === 0 ? "hoje" : `em ${txt}`;
}

// ---- Vencidos por obra (#805): o vencido deixa de ser lista corrida; a decisao da #656 (todos, sem limite de idade) fica ----

/** Uma obra (ou uma empresa, no aviso sem obra) com os vencidos dela: `itens` do mais antigo ao mais novo,
 *  `assuntos` na ordem das abas (o resumo da linha) e `maisAntigo` em dias, positivo. */
export type GrupoVencido = {
  chave: string; nome: string; contratoId: number | null; entidadeId: number | null;
  assuntos: Assunto[]; itens: Aviso[]; maisAntigo: number;
};

/** Os vencidos agrupados pela obra (`contrato_id`); o aviso sem obra, pela empresa (`entidade_id`); o resto, num
 *  grupo so'. Do grupo com o vencido mais antigo ao mais novo; no empate, o de mais avisos e depois o nome. O que nao
 *  venceu (ou nao tem data) fica de fora. */
export function vencidosPorObra(avisos: Aviso[], hoje?: string): GrupoVencido[] {
  const vencidos = porSecao(avisos, hoje)[0].itens;
  const grupos = new Map<string, GrupoVencido>();
  for (const a of vencidos) {
    const chave = a.contrato_id !== null ? `obra-${a.contrato_id}` : a.entidade_id != null ? `empresa-${a.entidade_id}` : "sem-obra";
    const g = grupos.get(chave) ?? { chave, contratoId: a.contrato_id, entidadeId: a.contrato_id === null ? a.entidade_id ?? null : null,
      nome: a.contrato_id !== null ? a.obra ?? `Obra ${a.contrato_id}` : a.entidade_id != null ? a.entidade ?? `Empresa ${a.entidade_id}` : "Sem obra",
      assuntos: [], itens: [], maisAntigo: 0 };
    g.itens.push(a);
    g.maisAntigo = Math.max(g.maisAntigo, -(diasAteOAviso(a, hoje) ?? 0));
    grupos.set(chave, g);
  }
  for (const g of grupos.values()) {
    const tem = new Set(g.itens.map(assuntoDoAviso));
    g.assuntos = ASSUNTOS.map(x => x.id).filter(x => tem.has(x));
  }
  return [...grupos.values()].sort((x, y) => y.maisAntigo - x.maisAntigo || y.itens.length - x.itens.length
    || x.nome.localeCompare(y.nome, "pt-BR"));
}

/** Em quantas obras e empresas os vencidos estao: "em 14 obras", "em 3 obras e 1 empresa"; sem nenhuma das duas, "". */
export function ondeEstao(grupos: GrupoVencido[]): string {
  const obras = grupos.filter(g => g.contratoId !== null).length, empresas = grupos.filter(g => g.entidadeId !== null).length;
  const partes = [obras > 0 && `${obras.toLocaleString("pt-BR")} ${obras === 1 ? "obra" : "obras"}`,
    empresas > 0 && `${empresas.toLocaleString("pt-BR")} ${empresas === 1 ? "empresa" : "empresas"}`].filter(Boolean);
  return partes.length ? `em ${partes.join(" e ")}` : "";
}

/** O filtro por categoria da rota (?familia=reajustes|prazos|certidoes, do "Ver todos" do Inicio); os ids das
 *  familias (?familia=prazo) continuam valendo. */
export function familiaDaBusca(v: string | undefined): Familia | null {
  const alias: Record<string, Familia> = { reajustes: "reajuste", prazos: "prazo", certidoes: "documentos" };
  const id = alias[v ?? ""] ?? v;
  return FAMILIAS.find(f => f.id === id)?.id ?? null;
}
