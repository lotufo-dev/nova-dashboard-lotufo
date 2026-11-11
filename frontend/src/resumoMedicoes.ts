// Regras de APRESENTACAO da pagina Medicoes com abas (09/10/2026, prototipo aprovado pelo Leo): funcoes puras sobre
// GET /api/medicoes/resumo. Situacao, marco, dias parados e a linha unica de medicao + reajuste sao do servidor
// (`medicoes.resumo`); aqui so' os rotulos, os limiares de cor do "Parada há" e o agrupamento por contratante.

export type Situacao = "planilha-gerada" | "planilha-enviada" | "boletim-recebido" | "faturamento" | "aguardando-nota" | "enviar-nota" | "aguardando-pagamento";
export type SituacaoOuSem = "sem-medicao" | Situacao;

export type LinhaResumo = {
  situacao: Situacao; contrato_id: number; obra: string; contratante: string; orgao_sub: string | null;
  medicao_id: number; medicao_ids: number[]; numero: number; competencia: string; titulo: string; proximo_passo: string;
  valor_centavos: number | null; marco: string | null; dias: number | null;
  // #507: o passo da barra de passos (1 Planilha e carta ... 6 Pagamento) e com quem a medicao esta
  passo: { numero: number; nome: string }; com_quem: "Lotufo" | "Órgão";
};
/** #151: o que a janela "Iniciar processo" sabe de uma serie de medicao da obra (execucao ou Projeto). */
export type SerieObra = {
  aberta_id: number | null; aberta_numero: number | null; aberta_passo: string | null;
  prevista_id: number | null; prevista_numero: number | null; prevista_competencia: string | null;
  ultima: { numero: number; competencia: string } | null;   // competencia AAAA-MM
};
export type ObraResumo = {
  contrato_id: number; obra: string; contratante: string; orgao_sub: string | null; aberta: boolean;
  prevista_id: number | null;   // a prevista mais antiga de qualquer serie (a da aba Sem medicao aberta, #154)
  // #151: cada serie no seu bloco; o `prevista_id` e a `ultima` de fora sao os da aba Sem medicao aberta
  execucao: SerieObra;
  projeto: SerieObra | null;   // so' a obra que tem (ou teve) medicao de Projeto

  encerramento: boolean;   // A-21 (10/10/2026): em encerramento segue na lista, mas nao conta como "obra ativa"
  // #154 (aba Sem medicao aberta): ultima medicao, dias desde o fim da competencia dela, a prevista do cronograma
  // e o numero da proxima. Tudo do servidor.
  // Execucao e projeto tem numeracao propria; `proxima_tipo` diz a serie do `proxima`.
  ultima: MedicaoCurta | null; ha_dias: number | null; prevista: MedicaoCurta | null;
  proxima: number; proxima_tipo: "execucao" | "projeto";
  // #507: sem medicao NA competencia pedida (`mes` do resumo), e a ultima medicao com estado e valor
  sem_no_mes: boolean; ultima_medicao: (MedicaoCurta & { estado: string; valor_centavos: number | null }) | null;
};
export type MedicaoCurta = { numero: number; tipo: string; competencia: string };
/** #643, quadro do mês: o passo de uma obra na competência. `data` (AAAA-MM-DD) só no passo feito; `medicao_id` só no da vez. */
/** #664: o processo vivo do SIGA da medição que está no passo: setor atual, entrada nele, dias úteis e quantas
 *  movimentações teve hoje (os da tela SIGA). */
export type SigaNoQuadro = { processo_id: number; setor: string; dias_uteis: number | null; desde: string | null; hoje: number };
export type PassoQuadro = {
  numero: number; nome: string; situacao: "feito" | "atual" | "futuro"; data: string | null; medicao_id: number | null;
  siga: SigaNoQuadro | null;
};
/** Uma obra no quadro: os passos que ela tem, as medições da competência e o pedido e o aprovado somados. Sem medição, `iniciar`. */
export type LinhaQuadro = {
  contrato_id: number; obra: string; contratante: string; orgao_sub: string | null; medicoes: { id: number; titulo: string }[];
  passos: PassoQuadro[]; iniciar: boolean; pedido_centavos: number | null; aprovado_centavos: number | null;
};
/** Medição aberta de uma competência anterior à do quadro. */
export type LinhaAnterior = {
  contrato_id: number; obra: string; medicao_id: number; titulo: string; numero: number; competencia: string;
  passo: { numero: number; nome: string };
};
export type ResumoMedicoes = {
  hoje: string; mes: string; contagens: Record<SituacaoOuSem | "iniciar" | "em-andamento", number>; linhas: LinhaResumo[]; obras: ObraResumo[];
  quadro: LinhaQuadro[]; anteriores: LinhaAnterior[];
};

const MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];

/** "2026-10" -> "outubro de 2026" (o seletor de mês do quadro). */
export function mesPorExtenso(aaaaMm: string): string {
  const m = /^(\d{4})-(\d{2})$/.exec(aaaaMm);
  const nome = m ? MESES[Number(m[2]) - 1] : undefined;
  return m && nome ? `${nome} de ${m[1]}` : aaaaMm;
}

/** "2026-12" + 1 -> "2027-01"; -1 volta o mês. */
export function somarMes(aaaaMm: string, n: number): string {
  const m = /^(\d{4})-(\d{2})$/.exec(aaaaMm);
  if (!m) return aaaaMm;
  const total = Number(m[1]) * 12 + (Number(m[2]) - 1) + n;
  return `${Math.floor(total / 12)}-${String((total % 12) + 1).padStart(2, "0")}`;
}

/** "hoje", "1 dia", "24 dias"; sem marco (o servidor nunca usa a data de lancamento no lugar dele), "—". */
export function textoParada(dias: number | null): string {
  if (dias === null) return "\u2014";
  if (dias <= 0) return "hoje";
  return dias === 1 ? "1\u00a0dia" : `${dias.toLocaleString("pt-BR")}\u00a0dias`;
}

/** Cor do "Parada há": o orgao leva 30+ dias para pagar, entao "aguardando pagamento" so' acende a partir disso
 *  (ambar a partir de 30, vermelho a partir de 45); as outras situacoes dependem da Lotufo (acima de 7 e de 15). */
export function nivelParada(dias: number | null, situacao: SituacaoOuSem): "atencao" | "acao" | null {
  if (dias === null) return null;
  if (situacao === "aguardando-pagamento") return dias >= 45 ? "acao" : dias >= 30 ? "atencao" : null;
  return dias > 15 ? "acao" : dias > 7 ? "atencao" : null;
}

/** "23ª · 01/2026" (numero e competencia "2026-01"); medicao de projeto: "1ª de Projeto · 09/2026". */
export function textoMedicao(m: MedicaoCurta): string {
  return `${m.numero}ª${m.tipo === "projeto" ? " de Projeto" : ""} · ${m.competencia.slice(5, 7)}/${m.competencia.slice(0, 4)}`;
}

export type GrupoContratante = { contratante: string; obras: ObraResumo[] };

/** Obras por contratante, o grupo com mais obras primeiro (empate: pelo nome). Dentro do grupo, a ordem do servidor
 *  (alfabetica). */
export function porContratante(obras: ObraResumo[]): GrupoContratante[] {
  const m = new Map<string, ObraResumo[]>();
  for (const o of obras) m.set(o.contratante, [...(m.get(o.contratante) ?? []), o]);
  return [...m.entries()].map(([contratante, os]) => ({ contratante, obras: os }))
    .sort((a, b) => b.obras.length - a.obras.length || a.contratante.localeCompare(b.contratante, "pt-BR"));
}

const semAcento = (s: string) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLocaleLowerCase("pt-BR");

/** Busca da janela "Iniciar processo de medição": obra, contratante ou sub-orgao, sem acento nem caixa. */
export function filtrarObras(obras: ObraResumo[], termo: string): ObraResumo[] {
  const t = semAcento(termo.trim());
  if (!t) return obras;
  return obras.filter(o => semAcento([o.obra, o.contratante, o.orgao_sub ?? ""].join(" ")).includes(t));
}
