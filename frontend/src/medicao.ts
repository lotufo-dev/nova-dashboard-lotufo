// Regras de APRESENTACAO da pagina da medicao (NAVEGACAO.md › Medicao): funcoes puras sobre o que a API ja
// entrega. Nada aqui decide estado, valor ou prazo — isso mora no servidor.

export type MarcoProtocolo = { id: number; data: string; numero_oficio: string | null; numero_processo: string | null;
  origem: string; protocolo_id?: number | null };
export type Conferencia = { campo: string; espelho: number | string | null; nota: number | string | null; grau: string };
export type NotaDaMedicao = { nota_id: number; numero: string; serie: string | null; emissao: string | null;
  valor_centavos: number; conferencia?: Conferencia[]; justificativa?: string | null; confirmacao?: string };
export type MedicaoBase = {
  id: number; numero: number; tipo: string; competencia: string; estado: string;
  valor_protocolado_centavos: number | null; valor_atestado_centavos: number | null;
  atestado_em: string | null; recebida_em: string | null; nota_emitida_em?: string | null;
  final?: number; final_em?: string | null; protocolos: MarcoProtocolo[]; notas?: NotaDaMedicao[];
  edicoes_valor?: { data: string; texto: string }[];   // B-02 (10/10/2026): da auditoria, texto pronto do servidor
};
export type EspelhoResumo = { id: number; numero: number; versao: number; situacao: string; criado_em: string;
  criado_por_nome: string | null; medicoes: { id: number; tipo: string; superado?: boolean }[];
  envio: { enviado_em: string; remetente: string } | null };
export type ProtocoloResumo = { id: number; etapa_rotulo: string; numero_oficio: string | null; situacao: string;
  criado_em: string; enviado_em?: string | null; enviado_por?: string | null;
  medicoes: { id: number; titulo: string }[]; pendencias: { codigo: string; mensagem: string }[] };

// Encerramentos por excecao: nem o atestado muda mais neles (espelha a guarda de medicoes.definir_valor).
export const EXCECOES = ["cancelada", "desistida"];
export const FINAIS = ["recebida", "cancelada", "desistida"];
// Estados em que a medicao nasceu no espelho (bloco 2): o valor vem da regra da obra, nao se edita a mao.
export const DO_ESPELHO = ["espelho_gerado", "espelho_enviado"];

// Espelha medicoes.TRANSICOES do servidor, MENOS `protocolada` (exclusividade de POST /protocolo) e MENOS
// `nota_emitida` (fecha pela nota, em api_notas). `nf_emitida` e' legado; fica so' o caminho de saida dele.
export const PROXIMOS: Record<string, string[]> = {
  protocolada: ["recebida", "cancelada", "desistida"],
  nf_emitida: ["recebida", "cancelada", "desistida"],
  prevista: ["cancelada", "desistida"],
  espelho_gerado: ["cancelada"],
  espelho_enviado: ["cancelada"],
  nota_emitida: ["cancelada"],
};

const ORDEM_TIPO: Record<string, number> = { execucao: 0, projeto: 1, reajuste: 2 };

/** As medicoes da obra em duas listas (NAVEGACAO.md › Obra): as abertas, que pedem acao, e as anteriores
 *  (recebidas, canceladas e desistidas), cada uma da mais nova para a mais antiga; na mesma competencia, a
 *  de execucao antes da de reajuste. */
export function separarMedicoes<M extends { numero: number; tipo: string; estado: string }>(ms: M[]): { emAndamento: M[]; anteriores: M[] } {
  const ordem = (a: M, b: M) => b.numero - a.numero || (ORDEM_TIPO[a.tipo] ?? 9) - (ORDEM_TIPO[b.tipo] ?? 9);
  return { emAndamento: ms.filter(m => !FINAIS.includes(m.estado)).sort(ordem),
           anteriores: ms.filter(m => FINAIS.includes(m.estado)).sort(ordem) };
}

/** A coluna "Notas" das medicoes da obra: quantas, quantas o RM confirmou e quantas divergem do espelho. */
export function resumoNotas(m: MedicaoBase): string {
  const ns = m.notas ?? [];
  if (ns.length === 0) return "—";
  const confirmadas = ns.filter(n => n.confirmacao === "confirmada").length;
  const divergem = notasDivergentes(m).length;
  return [`${ns.length} ${ns.length === 1 ? "nota" : "notas"}`,
          confirmadas ? `${confirmadas} ${confirmadas === 1 ? "confirmada" : "confirmadas"} pelo RM` : "",
          divergem ? `${divergem} ${divergem === 1 ? "diverge" : "divergem"} do espelho` : ""].filter(Boolean).join(" · ");
}

/** "23ª Medição", "Reajuste da 23ª Medição", "3ª Medição de Projeto" (o mesmo nome do servidor). */
export function tituloMedicao(m: { numero: number; tipo: string }): string {
  if (m.tipo === "reajuste") return `Reajuste da ${m.numero}ª Medição`;
  return `${m.numero}ª Medição${m.tipo === "projeto" ? " de Projeto" : ""}`;
}

// Issue #188: a execucao e o reajuste da mesma competencia, lado a lado na pagina da medicao. O servidor diz se o
// orgao junta os dois no mesmo e-mail (SINFRA, Pref. VG) e qual metade espera a outra; aqui so' o texto.
export type Liberacao = { justificativa: string | null; em: string; por: string | null };
export type Espera = { medicao_id: number; titulo: string; tipo: string; texto: string };
export type Metade = { medicao_id: number; tipo: string; titulo: string; estado: string; faltam: number;
  esperadas: unknown[]; completa: boolean; espera: Espera | null; liberacao: Liberacao | null };
export type ParDaMedicao = { junta: boolean; orgao: string | null; metades: Metade[] };

/** Cabeca do bloco: "Execução · 14ª Medição" / "Reajuste da 14ª Medição". */
export function rotuloDoBloco(m: { numero: number; tipo: string }): string {
  return m.tipo === "execucao" ? `Execução · ${tituloMedicao(m)}` : tituloMedicao(m);
}

const faltamNotas = (n: number) => n === 1 ? "falta 1 nota" : n > 1 ? `faltam ${n} notas` : "sem notas";

/** O que falta, por bloco: "execução completa · reajuste: faltam 2 notas"; com as duas completas, "notas completas". */
export function resumoDoPar(metades: Metade[]): string {
  if (metades.every(x => x.completa)) return "notas completas";
  return metades.map(x => {
    const nome = x.tipo === "execucao" ? "execução" : "reajuste";
    return x.completa ? `${nome} completa` : `${nome}: ${faltamNotas(x.faltam)}`;
  }).join(" · ");
}

/** A metade pronta que espera a outra (so' onde o orgao junta), ou null. */
export function metadeQueEspera(par: ParDaMedicao | null): Metade | null {
  return par?.junta ? par.metades.find(x => x.espera) ?? null : null;
}

// O proximo passo vem do servidor (`medicoes.PROXIMO_PASSO`); aqui so' o rotulo do mapa e a secao da
// pagina da medicao onde ele se resolve.
const PASSOS: Record<string, { rotulo: string; secao: string }> = {
  "enviar a planilha/carta": { rotulo: "Enviar a planilha/carta", secao: "" },
  "registrar o boletim": { rotulo: "Registrar o boletim", secao: "" },
  "gerar o espelho": { rotulo: "Gerar o espelho", secao: "" },
  "enviar ao faturamento": { rotulo: "Enviar ao faturamento", secao: "etapa-2" },
  "anexar as notas": { rotulo: "Nota fiscal", secao: "etapa-3" },
  "protocolar": { rotulo: "Enviar a nota", secao: "etapa-4" },
  "aguardando pagamento": { rotulo: "Aguardando o órgão", secao: "etapa-5" },
};

export function passoDe(proximo: string | null | undefined): { rotulo: string; secao: string } | null {
  return proximo ? PASSOS[proximo] ?? { rotulo: proximo, secao: "" } : null;
}

/** Antes do protocolo: a medicao tem "O que falta para protocolar". */
export function antesDoProtocolo(estado: string): boolean {
  return ["prevista", "espelho_gerado", "espelho_enviado", "nota_emitida"].includes(estado);
}

/** Depois do protocolo o valor e' o protocolado (congelado no protocolo); antes, o valor da medicao. */
export function rotuloDoValor(estado: string): string {
  return ["protocolada", "nf_emitida", "recebida"].includes(estado) ? "protocolado" : "valor da medição";
}

/** Notas que divergem do espelho e ainda nao foram justificadas: o campo, o do espelho e o da nota. */
export function notasDivergentes(m: MedicaoBase): { nota: NotaDaMedicao; diferencas: Conferencia[] }[] {
  return (m.notas ?? [])
    .filter(n => !n.justificativa)
    .map(n => ({ nota: n, diferencas: (n.conferencia ?? []).filter(d => d.grau === "divergente") }))
    .filter(x => x.diferencas.length > 0);
}

/** A medicao que mora o espelho da competencia: a de execucao dele (NAVEGACAO.md: um lar so').
 *  Medicao para a qual o espelho ja foi superado nao e' lar: la ele nao aparece (#208). */
export function larDoEspelho(e: { medicoes: { id: number; tipo: string; superado?: boolean }[] }): number | null {
  const vivas = e.medicoes.filter(x => !x.superado);
  return (vivas.find(x => x.tipo === "execucao") ?? vivas[0])?.id ?? null;
}

/** Protocolos que tocam a medicao. Com varias medicoes, o protocolo mora na primeira; nas outras, resumo. */
export function protocolosDa<P extends ProtocoloResumo>(protocolos: P[], medicaoId: number): { daqui: P[]; deOutra: P[] } {
  const dela = protocolos.filter(p => p.medicoes.some(x => x.id === medicaoId));
  return { daqui: dela.filter(p => p.medicoes[0]?.id === medicaoId), deOutra: dela.filter(p => p.medicoes[0]?.id !== medicaoId) };
}

export type Evento = { data: string; texto: string };

/** Linha do tempo da medicao, do mais antigo ao mais novo, com quem fez quando a API diz. */
export function eventosDaMedicao(m: MedicaoBase, espelhos: EspelhoResumo[], protocolos: ProtocoloResumo[]): Evento[] {
  const out: Evento[] = [];
  for (const e of espelhos.filter(x => x.medicoes.some(y => y.id === m.id))) {
    const versao = e.versao > 1 ? `, versão ${e.versao}` : "";
    out.push({ data: e.criado_em, texto: `Espelho nº ${e.numero}${versao} gerado${e.criado_por_nome ? ` por ${e.criado_por_nome}` : ""}` });
    if (e.envio) out.push({ data: e.envio.enviado_em, texto: `Espelho enviado ao faturamento por ${e.envio.remetente}` });
  }
  if (m.nota_emitida_em) out.push({ data: m.nota_emitida_em, texto: "Nota emitida" });
  const doSistema = new Set<number>();
  for (const p of protocolos.filter(x => x.medicoes.some(y => y.id === m.id))) {
    const nome = `${p.etapa_rotulo}${p.numero_oficio ? ` · ${p.numero_oficio}` : ""}`;
    out.push({ data: p.criado_em, texto: `Protocolo criado (${nome})` });
    if (p.enviado_em) {
      doSistema.add(p.id);
      out.push({ data: p.enviado_em, texto: `Protocolo enviado (${nome})${p.enviado_por ? ` por ${p.enviado_por}` : ""}` });
    }
  }
  // o registro do protocolo na medicao repete o envio feito pelo sistema; o de fora aparece sozinho
  for (const p of m.protocolos.filter(x => !x.protocolo_id || !doSistema.has(x.protocolo_id))) {
    out.push({ data: p.data, texto: `Protocolada${p.numero_oficio ? ` · ofício ${p.numero_oficio}` : ""}${p.numero_processo ? ` · processo ${p.numero_processo}` : ""}` });
  }
  if (m.atestado_em) out.push({ data: m.atestado_em, texto: "Atestada pelo órgão" });
  if (m.recebida_em) out.push({ data: m.recebida_em, texto: "Recebida" });
  if (m.final === 1 && m.final_em) out.push({ data: m.final_em, texto: "Marcada como medição final" });
  for (const e of m.edicoes_valor ?? []) out.push(e);
  return out.sort((a, b) => a.data.localeCompare(b.data));
}

/** `nivel` diz o selo do item (D2, D10): nota divergente e documento sem validade sao criticos; documento
 *  vencendo e pendencia do protocolo pedem atencao; o passo do ciclo e' neutro. */
export type NivelFalta = "critico" | "atencao" | "neutro";
export type ItemFalta =
  | { tipo: "passo"; nivel: NivelFalta; texto: string; secao: string }
  | { tipo: "nota"; nivel: NivelFalta; texto: string; secao: string }
  | { tipo: "documento"; nivel: NivelFalta; texto: string; entidadeId: number }
  | { tipo: "protocolo"; nivel: NivelFalta; texto: string; secao: string };

export type ItemChecklist = { entidade_id: number; entidade: string | null; tipo: string; chave: string | null;
  situacao: string; dias: number | null; competencia?: string | null; esperada?: string };

/** "O que falta para protocolar", em toda medicao aberta antes do protocolo, so' com o que a API manda: os
 *  passos do ciclo, as notas que divergem ou faltam, os documentos do checklist e as pendencias do
 *  protocolo que nao sao documento nem nota. `protocolo` nulo = ainda nao criado (a tela oferece criar). */
export function itensOQueFalta(m: MedicaoBase, faltamNotas: number | null, checklist: ItemChecklist[] | null,
                               protocolo: ProtocoloResumo | null): ItemFalta[] {
  const itens: ItemFalta[] = [];
  if (m.estado === "espelho_gerado") itens.push({ tipo: "passo", nivel: "neutro", texto: "Enviar o espelho ao faturamento", secao: "etapa-2" });
  const semNotas = ["espelho_gerado", "espelho_enviado"].includes(m.estado);
  if (semNotas || (faltamNotas ?? 0) > 0) {
    const n = faltamNotas ?? 0;
    itens.push({ tipo: "passo", nivel: "neutro", secao: "notas",
      texto: n > 0 ? `Anexar as notas (${n === 1 ? "falta 1" : `faltam ${n}`})` : "Anexar as notas" });
  }
  for (const { nota, diferencas } of notasDivergentes(m)) {
    // tributos em sigla (ISS, IRRF); o liquido conferido desde a PR #97 com o nome por extenso
    const d = diferencas.map(x => `${x.campo === "liquido" ? "Líquido" : x.campo.toUpperCase()} ${valorTexto(x.espelho)} no espelho e ${valorTexto(x.nota)} na nota`).join("; ");
    itens.push({ tipo: "nota", nivel: "critico", secao: "notas", texto: `Nota ${Number(nota.numero) || nota.numero} diverge do espelho: ${d}` });
  }
  for (const i of (checklist ?? []).filter(x => x.situacao === "pendente" || x.situacao === "vencendo")) {
    const quem = i.entidade ?? "Empresa";
    // a competencia da regularidade e' a exigida HOJE pelo servidor (nao a da medicao): o texto diz isso
    const o_que = i.chave === "regularidade" ? `regularidade exigida hoje${i.esperada ? ` (${competencia(i.esperada)})` : ""}` : i.tipo;
    // "sem validade hoje": o mesmo texto das pendencias do protocolo e do registro de protocolo feito fora
    const quando = i.situacao === "vencendo" ? (i.dias === null ? "vence em breve" : i.dias <= 0 ? "vence hoje" : `vence em ${i.dias} dias`) : "sem validade hoje";
    itens.push({ tipo: "documento", nivel: i.situacao === "vencendo" ? "atencao" : "critico", entidadeId: i.entidade_id, texto: `${quem}: ${o_que} · ${quando}` });
  }
  if (protocolo) {
    const jaDitas = new Set(["certidao", "regularidade", ...(itens.some(x => "secao" in x && x.secao === "notas") ? ["sem_nota"] : [])]);
    for (const p of protocolo.pendencias.filter(x => !jaDitas.has(x.codigo))) {
      itens.push({ tipo: "protocolo", nivel: p.codigo === "certidao" ? "critico" : "atencao", secao: "protocolo", texto: p.mensagem });
    }
  }
  return itens;
}

function valorTexto(v: number | string | null): string {
  if (v === null) return "—";
  if (typeof v === "number") return (v / 100).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
  return v;
}

function competencia(aaaamm: string): string {
  const m = aaaamm.match(/^(\d{4})-(\d{2})/);
  return m ? `${m[2]}/${m[1]}` : aaaamm;
}
