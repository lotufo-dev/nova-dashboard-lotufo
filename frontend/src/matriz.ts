// Regras de APRESENTACAO da matriz de Documentos (NAVEGACAO.md › Documentos): funcoes puras sobre /api/documentos.
// A situacao de cada certidao (em dia, vencendo, vencida, faltando) e' do servidor; aqui so' se conta, filtra e ordena.

export type CertidaoDoc = { id: number; emissao: string; validade: string; natureza: string | null;
  leitura?: string | null };    // "manual" = digitada (A-19, 10/10/2026)
export type LinhaCertidao = {
  tipo_id: number; chave: string; tipo: string; link_emissao: string | null; exigida: boolean;
  situacao: "ok" | "vencendo" | "vencida" | "faltando" | "nao_se_aplica"; dias: number | null;
  certidao: CertidaoDoc | null;
  // #658: do servidor. `renovar` = vencida, sem registro ou vence ate' o proximo protocolo previsto de uma obra que a
  // exige; `proximo_protocolo` = a data do primeiro protocolo que ela trava.
  renovar?: boolean; proximo_protocolo?: string | null;
};
/** Uma linha do bloco "Renovar agora" (#658): a lista e' do servidor (`documentos.renovar_agora`). */
export type RenovarDoc = {
  entidade_id: number; entidade: string; tipo_id: number; chave: string; tipo: string; link_emissao: string | null;
  situacao: LinhaCertidao["situacao"]; dias: number | null; validade: string | null; certidao_id: number | null;
  proximo_protocolo: string | null;
};
export type RegularidadeDoc = { situacao: "ok" | "atrasada" | "faltando"; competencia: string | null; esperada: string };
export type Garantia = { apolice: string | null; vigencia_fim: string; dias: number; origem: "contrato" | "endosso";
  situacao: "ok" | "vencendo" | "vencida" | "baixada" };
export type ObraDoc = { contrato_id: number; obra: string; entidade_id?: number; garantia: Garantia | null;
  orgao?: string; tipo_contratante?: string;      // #651: "PRIVADO" vai para o grupo "Privados"
  cobre_execucao?: { cobre: boolean | null; ate: string | null }; art?: string | null; cno?: string | null };
export type EmpresaDoc = {
  entidade_id: number; entidade: string; cnpj: string; papel: string; certidoes: LinhaCertidao[];
  regularidade_exigida: boolean; regularidade: RegularidadeDoc | null;
  obras?: { contrato_id: number; obra: string }[];      // A7: as obras ativas que exigem a empresa
  consorciadas?: number[]; consorcios?: number[];       // #161: quem compoe o consorcio / de quais consorcios participa
  regularidades_anexadas?: { id: number; competencia: string; anexada_em: string }[];   // #161: a mais recente primeiro
  primeira_regularidade?: string | null;                // #651: a competencia mais antiga ja' anexada
};

// Decisao 5 do mapa: "antes do proximo protocolo" vira "vence em ate' 30 dias".
export const JANELA_DIAS = 30;

/** Pendencia de uma certidao: exigida e vencida, faltando ou vencendo em ate' 30 dias (os dias sao do servidor). */
export function certidaoPendente(l: LinhaCertidao): boolean {
  if (!l.exigida) return false;
  if (l.situacao === "vencida" || l.situacao === "faltando") return true;
  return (l.situacao === "ok" || l.situacao === "vencendo") && l.dias !== null && l.dias <= JANELA_DIAS;
}

/** O que a garantia das obras contratadas pela empresa pede dela (#161): a garantia vencida ou na janela de
 *  atencao. `garantiasVencidas` sao as que ja' travam. */
export function pendenciasDeObras(e: EmpresaDoc, obras: ObraDoc[]) {
  const minhas = obras.filter(k => k.entidade_id === e.entidade_id);
  const gs = minhas.filter(k => { const n = situacaoGarantia(k.garantia, "").nivel; return n === "acao" || n === "atencao"; });
  return {
    garantiasVencidas: gs.filter(k => k.garantia?.situacao === "vencida").length,
    garantiasVencendo: gs.filter(k => k.garantia?.situacao !== "vencida").map(k => k.garantia!.dias),
    total: gs.length,
  };
}

/** Quantas pendencias a empresa tem: as certidoes, a regularidade do mes que nao esta' em dia e (com `obras`) a garantia
 *  das obras dela. */
export function pendenciasDa(e: EmpresaDoc, obras: ObraDoc[] = []): number {
  const reg = e.regularidade && e.regularidade.situacao !== "ok" ? 1 : 0;
  return e.certidoes.filter(certidaoPendente).length + reg + pendenciasDeObras(e, obras).total;
}

/** 0 = o que ja' trava (certidao exigida vencida ou faltando, regularidade fora do dia, garantia vencida); 1 = o que
 *  vence em ate' 30 dias; 2 = nada pendente. */
export function gravidade(e: EmpresaDoc, obras: ObraDoc[] = []): number {
  const trava = e.certidoes.some(l => l.exigida && (l.situacao === "vencida" || l.situacao === "faltando"))
    || (e.regularidade !== null && e.regularidade.situacao !== "ok") || pendenciasDeObras(e, obras).garantiasVencidas > 0;
  return trava ? 0 : pendenciasDa(e, obras) > 0 ? 1 : 2;
}

/** Os dias da certidao exigida que vence primeiro (dentro da janela), para desempatar pela mais urgente. */
function menorDias(e: EmpresaDoc): number {
  return Math.min(999, ...e.certidoes.filter(l => l.exigida && l.dias !== null && certidaoPendente(l)).map(l => l.dias!));
}

/** Pela gravidade (o que ja' trava, o que vence, o resto), depois pela que vence primeiro, depois a ordem do
 *  servidor; `soPendentes` e' o filtro da URL. */
export function matriz(empresas: EmpresaDoc[], soPendentes: boolean, obras: ObraDoc[] = []): EmpresaDoc[] {
  const ordem = new Map(empresas.map((e, i) => [e.entidade_id, i]));
  return empresas.filter(e => !soPendentes || pendenciasDa(e, obras) > 0)
    .sort((a, b) => gravidade(a, obras) - gravidade(b, obras) || menorDias(a) - menorDias(b)
      || ordem.get(a.entidade_id)! - ordem.get(b.entidade_id)!);
}

/** As colunas da matriz: os tipos de certidao que alguma empresa tem, na ordem dada. */
export function colunas(empresas: EmpresaDoc[], ordem: string[]): string[] {
  const tem = new Set(empresas.flatMap(e => e.certidoes.map(l => l.chave)));
  return [...ordem.filter(c => tem.has(c)), ...[...tem].filter(c => !ordem.includes(c))];
}

/* ---------------------------------------------------------------- redesenho de Documentos (#161) */

export type Nivel = "ok" | "atencao" | "acao" | "neutro";

/** A ordem das certidoes nos cartoes e na tabela da empresa (a do desenho aprovado); tipo novo vai para o fim. */
export const ORDEM_CERTIDOES = ["federal", "estadual", "municipal", "fgts", "trabalhista", "falencia"];
export const NOME_CURTO: Record<string, string> = {
  federal: "Federal", estadual: "Estadual", municipal: "Municipal", fgts: "FGTS", trabalhista: "Trabalhista", falencia: "Falência",
};

/** As certidoes da empresa na ordem do desenho. */
export function certidoesOrdenadas(e: EmpresaDoc): LinhaCertidao[] {
  const pos = (c: string) => { const i = ORDEM_CERTIDOES.indexOf(c); return i < 0 ? 99 : i; };
  return [...e.certidoes].sort((a, b) => pos(a.chave) - pos(b.chave));
}

function venceEm(d: number): string {
  return d <= 0 ? "vence hoje" : d === 1 ? "vence amanhã" : `vence em ${d} dias`;
}

/** A situacao de UMA certidao como a tela a diz: o texto do selo, a nota embaixo (a data) e o nivel. O selo segue a
 *  janela da pendencia (decisao 5): certidao exigida que vence em ate' 30 dias diz "vence em N dias", mesmo que o
 *  servidor ainda a chame de em dia. A que nao e' exigida fica neutra. `validade` ja' vem em dd/mm/aaaa. */
export function situacaoCertidao(l: LinhaCertidao, validade: string): { texto: string; data?: string; nivel: Nivel } {
  if (l.situacao === "nao_se_aplica") return { texto: "não se aplica", data: "declarado", nivel: "neutro" };
  if (!l.exigida) {
    return { texto: "não exigida", nivel: "neutro",
             data: !l.certidao ? undefined : l.situacao === "vencida" ? `vencida em ${validade}` : `até ${validade}` };
  }
  switch (l.situacao) {
    case "ok":
      return l.dias !== null && l.dias <= JANELA_DIAS ? { texto: venceEm(l.dias), data: `até ${validade}`, nivel: "atencao" }
        : { texto: "em dia", data: `até ${validade}`, nivel: "ok" };
    case "vencendo": return { texto: venceEm(l.dias ?? 0), data: `até ${validade}`, nivel: "atencao" };
    case "vencida": return { texto: "vencida", data: `em ${validade}`, nivel: "acao" };
    default: return { texto: "falta", nivel: "acao" };
  }
}

/** A situacao geral da empresa (a pilula do cartao e do cabecalho): o que ja' trava, o que vence e a regularidade
 *  fora do dia, em uma frase; "Em dia" quando nada pende. */
export function resumoEmpresa(e: EmpresaDoc, obras: ObraDoc[] = []): { texto: string; nivel: Nivel; pendencias: number } {
  const exigidas = e.certidoes.filter(l => l.exigida);
  const vencidas = exigidas.filter(l => l.situacao === "vencida").length;
  const faltas = exigidas.filter(l => l.situacao === "faltando").length;
  const vencendo = exigidas.filter(l => (l.situacao === "ok" || l.situacao === "vencendo") && certidaoPendente(l));
  const regFora = e.regularidade !== null && e.regularidade.situacao !== "ok";
  const partes: string[] = [];
  if (vencidas) partes.push(vencidas === 1 ? "1 vencida" : `${vencidas} vencidas`);
  if (faltas) partes.push(faltas === 1 ? "1 falta" : `${faltas} faltam`);
  if (vencendo.length === 1) partes.push(`1 ${venceEm(vencendo[0].dias ?? 0)}`);
  else if (vencendo.length > 1) partes.push(`${vencendo.length} vencem em até ${Math.max(...vencendo.map(l => l.dias ?? 0))} dias`);
  if (regFora) partes.push(`regularidade ${e.regularidade!.situacao === "faltando" ? "não anexada" : "atrasada"}`);
  const o = pendenciasDeObras(e, obras);
  if (o.garantiasVencidas) partes.push(o.garantiasVencidas === 1 ? "garantia vencida" : `${o.garantiasVencidas} garantias vencidas`);
  if (o.garantiasVencendo.length === 1) partes.push(`garantia ${venceEm(o.garantiasVencendo[0])}`);
  else if (o.garantiasVencendo.length > 1) partes.push(`${o.garantiasVencendo.length} garantias vencendo`);
  const texto = partes.length ? partes.join(" · ") : "em dia";
  return { texto: texto.charAt(0).toUpperCase() + texto.slice(1),
    nivel: vencidas || faltas || o.garantiasVencidas ? "acao" : partes.length ? "atencao" : "ok", pendencias: pendenciasDa(e, obras) };
}

/** A pendencia mais urgente da tabela da empresa: a unica que leva o botao principal ("Emitir"). Sem dias (vencida
 *  ou faltando) vem antes de quem ainda vigora. */
export function pendenciaMaisUrgente(e: EmpresaDoc): LinhaCertidao | null {
  return certidoesOrdenadas(e).filter(certidaoPendente).sort((a, b) => (a.dias ?? -999) - (b.dias ?? -999))[0] ?? null;
}

/** A garantia de uma obra como a tela a diz (texto do selo, nota embaixo e nivel). `ate` ja' vem em dd/mm/aaaa. */
export function situacaoGarantia(g: Garantia | null, ate: string): { texto: string; nota: string; nivel: Nivel; forte?: boolean } {
  if (!g) return { texto: "sem vigência no cadastro", nota: "", nivel: "neutro" };
  const nota = `${g.dias < 0 ? `venceu em ${ate}` : `até ${ate}`}${g.origem === "endosso" ? " (endosso)" : ""}${g.apolice ? ` · apólice ${g.apolice}` : ""}`;
  if (g.situacao === "baixada") return { texto: "baixada", nota, nivel: "neutro" };
  if (g.situacao === "vencida") return { texto: "vencida", nota, nivel: "acao", forte: true };
  if (g.situacao === "vencendo") return { texto: venceEm(g.dias), nota, nivel: g.dias <= 15 ? "acao" : "atencao" };
  return { texto: "em dia", nota, nivel: "ok" };
}

/* ---------------------------------------------------------------- Documentos em tres abas (#513) */

/** A cor do chip (as classes `info--*` do tokens.css): feito = em dia/anexada, andamento = aguardando, breve = vence
 *  antes do proximo protocolo (#658) ou falta, critico = vencida, sem registro ou vence hoje. */
export type CorChip = "feito" | "andamento" | "breve" | "critico" | "neutro";
export const LIMITE_BREVE_DIAS = 7;

/** O chip de uma certidao na aba Certidoes: dias que faltam ("9 d", "hoje") e a data completa. Certidao nao exigida
 *  fica neutra ("—"); `contaNoAviso` diz se entra no contador "N a renovar" (amarelo ou vermelho, so' as exigidas).
 *  Ambar (#658): a que o servidor marca `renovar` (vence ate' o proximo protocolo previsto); resposta sem a marca cai
 *  no limite fixo de 7 dias. */
export function chipCertidao(l: LinhaCertidao | undefined, validade: string):
    { cor: CorChip; valor: string; data: string; contaNoAviso: boolean } {
  if (!l || l.situacao === "nao_se_aplica" || !l.exigida) return { cor: "neutro", valor: "—", data: "", contaNoAviso: false };
  if (l.situacao === "faltando") return { cor: "critico", valor: "sem registro", data: "", contaNoAviso: true };
  if (l.situacao === "vencida" || l.dias === null || l.dias < 0) {
    return { cor: "critico", valor: "vencida", data: validade, contaNoAviso: true };
  }
  if (l.dias === 0) return { cor: "critico", valor: "hoje", data: validade, contaNoAviso: true };
  const breve = l.renovar ?? l.dias <= LIMITE_BREVE_DIAS;
  return { cor: breve ? "breve" : "feito", valor: `${l.dias} d`, data: validade, contaNoAviso: breve };
}

/** As empresas da aba Certidoes (#651): so' quem tem ao menos uma certidao exigida por obra ativa. */
export function empresasComCertidaoExigida(empresas: EmpresaDoc[]): EmpresaDoc[] {
  return empresas.filter(e => e.certidoes.some(l => l.exigida));
}

export function certidoesVencendo(empresas: EmpresaDoc[]): number {
  return empresas.reduce((n, e) => n + e.certidoes.filter(l => chipCertidao(l, "").contaNoAviso).length, 0);
}

function mesMais(c: string, n: number): string {
  const t = Number(c.slice(0, 4)) * 12 + (Number(c.slice(5, 7)) - 1) + n;
  return `${String(Math.floor(t / 12)).padStart(4, "0")}-${String((t % 12) + 1).padStart(2, "0")}`;
}

/** Os seis meses da regularidade, do mais antigo ao mais novo; o ultimo e' o mes anterior ao de `hoje`. A competencia C
 *  e' esperada a partir do dia 10 do mes seguinte: antes disso, "aguardando" o DP. */
export function competenciasRegularidade(hoje: string): { competencia: string; aguardando: boolean }[] {
  const atual = hoje.slice(0, 7);
  return [5, 4, 3, 2, 1, 0].map(i => {
    const competencia = mesMais(atual, -1 - i);
    return { competencia, aguardando: hoje < `${mesMais(competencia, 1)}-10` };
  });
}

/** "sem" = nao cobrada (#651, #699): anterior ao primeiro PDF da empresa, ou mes que nao e' o que o proximo protocolo pede. */
export type EstadoCompetencia = { competencia: string; estado: "anexada" | "faltando" | "aguardando" | "sem"; id?: number };

/** Empresas com folha: as que a regularidade e' exigida ou ja' tem PDF anexado. */
export function empresasComFolha(empresas: EmpresaDoc[]): EmpresaDoc[] {
  return empresas.filter(e => e.regularidade !== null || (e.regularidades_anexadas ?? []).length > 0);
}

/** A competencia mais antiga ja' anexada: a do servidor; sem o campo, a mais antiga da lista. */
function primeiraAnexada(e: EmpresaDoc): string | null {
  if (e.primeira_regularidade !== undefined) return e.primeira_regularidade;
  return (e.regularidades_anexadas ?? []).map(x => x.competencia).sort()[0] ?? null;
}

/** O estado de UMA competencia sem PDF (#651, #699). So' falta a competencia que o proximo protocolo pede (`esperada`,
 *  do servidor), a mesma que o contador da aba conta; antes do primeiro PDF da empresa nada e' cobrado, nem ela. */
function estadoSemPdf(e: EmpresaDoc, competencia: string, aguardando: boolean): EstadoCompetencia["estado"] {
  if (aguardando) return "aguardando";
  const primeira = primeiraAnexada(e);
  if (primeira !== null && competencia < primeira) return "sem";
  return competencia === e.regularidade?.esperada ? "faltando" : "sem";
}

export function estadosRegularidade(e: EmpresaDoc, hoje: string): EstadoCompetencia[] {
  const anexadas = e.regularidades_anexadas ?? [];
  return competenciasRegularidade(hoje).map(({ competencia, aguardando }) => {
    const a = anexadas.find(x => x.competencia === competencia);
    return a ? { competencia, estado: "anexada" as const, id: a.id }
      : { competencia, estado: estadoSemPdf(e, competencia, aguardando) };
  });
}

/** O contador da aba (#651): as empresas com folha que devem a competencia que o proximo protocolo pede. */
export function regularidadesFaltando(empresas: EmpresaDoc[]): number {
  return empresasComFolha(empresas).filter(e => {
    const esperada = e.regularidade?.esperada;
    if (!esperada || (e.regularidades_anexadas ?? []).some(x => x.competencia === esperada)) return false;
    return estadoSemPdf(e, esperada, false) === "faltando";
  }).length;
}

/** As garantias cujo ultimo documento venceu (#651): a tela nao afirma "vencida", pede para conferir. */
export function garantiasAConferir(obras: ObraDoc[]): number {
  return obras.filter(o => o.garantia?.situacao === "vencida").length;
}

/** O chip "Válida até" da aba Garantias (#651). Do ultimo documento vencido so' se sabe a data dele: "Último registro",
 *  sem vermelho. `ate` ja' vem em dd/mm/aaaa. */
export function chipValidadeGarantia(g: Garantia | null, ate: string): { cor: CorChip; valor: string } {
  if (!g) return { cor: "critico", valor: "sem registro" };
  if (g.situacao === "vencida") return { cor: "neutro", valor: `Último registro: ${ate}` };
  const nivel = situacaoGarantia(g, ate).nivel;
  return { cor: nivel === "acao" ? "critico" : nivel === "atencao" ? "breve" : nivel === "ok" ? "feito" : "neutro", valor: ate };
}

/** As obras por orgao, o maior grupo primeiro (empate: ordem alfabetica do orgao). Contratante privado (#651) tem
 *  grupo proprio, "Privados". */
export function obrasPorOrgao(obras: ObraDoc[]): { orgao: string; obras: ObraDoc[] }[] {
  const m = new Map<string, ObraDoc[]>();
  for (const o of obras) {
    const grupo = o.tipo_contratante === "PRIVADO" ? "Privados" : o.orgao ?? "Sem órgão";
    m.set(grupo, [...(m.get(grupo) ?? []), o]);
  }
  return [...m].map(([orgao, lista]) => ({ orgao, obras: lista }))
    .sort((a, b) => b.obras.length - a.obras.length || a.orgao.localeCompare(b.orgao, "pt-BR"));
}
