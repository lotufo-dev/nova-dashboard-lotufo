/* Politica de fuso do projeto (divida da fase 2, decidida na fase 3) — par do
 * backend/app/tempo.py:
 *
 *  - ARMAZENAR: o banco grava UTC sempre (datetime('now') do SQLite). Nada migra.
 *  - EXIBIR/DECIDIR: America/Cuiaba. Fronteira de mes/dia do negocio = a local.
 *
 * PROIBIDO fora deste arquivo: `new Date().toLocaleString()` (e irmaos) direto, e
 * montar mes/dia a partir de `new Date()` cru — os dois usam o fuso do NAVEGADOR,
 * que nao e' nem o do banco nem o do escritorio. Quem precisa exibir um carimbo do
 * banco usa fmtDataHora/fmtData; quem precisa do mes corrente usa mesAtualLocal.
 *
 * Duas armadilhas que estas funcoes resolvem:
 *  1. "2026-09-01 01:30:00" do banco e' UTC. Fatiar a string ("01/09") exibe uma
 *     data que nunca existiu para quem publicou — la eram 21:30 de 31/08.
 *  2. `new Date("2026-09-01 01:30:00")` (sem o "Z") e' lido como hora LOCAL do
 *     navegador. Por isso `paraDate` normaliza para ISO com "Z" antes de parsear.
 *
 * Atencao: isto vale para CARIMBO DE INSTANTE (criado_em e afins). Campo que ja e'
 * uma data pura do cadastro ("2026-10-15", vigencia/protocolo) nao passa por aqui:
 * converter fuso nele deslocaria um dia que nao tem hora nenhuma.
 */

const TZ = "America/Cuiaba";

// "AAAA-MM-DD HH:MM:SS" (formato do SQLite, UTC e sem fuso declarado) -> Date.
// Sem o "Z" o parse cairia no fuso do navegador — o bug que este modulo existe
// para impedir. Carimbo que ja venha com fuso explicito ("Z" ou "+00:00") passa
// como esta: quem declarou o fuso ja disse tudo.
function paraDate(iso: string): Date | null {
  const t = iso.trim().replace(" ", "T");
  const comFuso = /(?:Z|[+-]\d{2}:?\d{2})$/.test(t) ? t : `${t}Z`;
  const d = new Date(comFuso);
  return Number.isNaN(d.getTime()) ? null : d;
}

function partes(d: Date): Record<string, string> {
  const fmt = new Intl.DateTimeFormat("pt-BR", {
    timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  });
  const out: Record<string, string> = {};
  for (const p of fmt.formatToParts(d)) out[p.type] = p.value;
  return out;
}

/** Carimbo UTC do banco -> "DD/MM/AAAA às HH:MM" em Cuiaba. */
export function fmtDataHora(iso: string): string {
  const d = paraDate(iso);
  if (d === null) return iso;   // dado ilegivel aparece cru, nunca como data inventada
  const p = partes(d);
  return `${p.day}/${p.month}/${p.year} às ${p.hour}:${p.minute}`;
}

/** Quanto durou, entre dois carimbos: "38 s" ou "1 min 05 s" ("—" se algum for ilegivel ou o fim vier antes do inicio). */
export function fmtDuracao(inicio: string, fim: string): string {
  const a = paraDate(inicio), b = paraDate(fim);
  if (a === null || b === null || b < a) return "—";
  const s = Math.round((b.getTime() - a.getTime()) / 1000);
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60), r = s % 60;
  return m < 60 ? `${m} min ${String(r).padStart(2, "0")} s` : `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")} min`;
}

/** Instante -> "HH:MM" em Cuiaba (A-05, 10/10/2026: "bloqueado até 14:35" na lista de usuarios). */
export function fmtHora(iso: string): string {
  const d = paraDate(iso);
  if (d === null) return iso;
  const p = partes(d);
  return `${p.hour}:${p.minute}`;
}

/** Carimbo UTC do banco -> "DD/MM/AAAA" em Cuiaba (o DIA local do instante). */
export function fmtData(iso: string): string {
  const d = paraDate(iso);
  if (d === null) return iso;
  const p = partes(d);
  return `${p.day}/${p.month}/${p.year}`;
}

/** Carimbo UTC do banco -> "AAAA-MM-DD", o DIA local (Cuiaba) do instante; null se ilegivel. */
export function diaLocal(iso: string): string | null {
  const d = paraDate(iso);
  if (d === null) return null;
  const p = partes(d);
  return `${p.year}-${p.month}-${p.day}`;
}

/** Mes corrente em Cuiaba, "AAAA-MM" — a mesma fronteira que o servidor usa. */
export function mesAtualLocal(): string {
  const p = partes(new Date());
  return `${p.year}-${p.month}`;
}

/** Hoje em Cuiaba, "AAAA-MM-DD" — a mesma fronteira de dia que o servidor usa. */
export function hojeLocal(): string {
  const p = partes(new Date());
  return `${p.year}-${p.month}-${p.day}`;
}

/** Data PURA do cadastro ("AAAA-MM-DD") -> "DD/MM/AAAA". Sem fuso, sem `Date`.
 *
 * Emissao e validade de certidao nao sao instantes: sao dias escritos no papel que o
 * orgao emitiu, e o banco os guarda exatamente como estao (a politica do topo deste
 * arquivo ja avisa disso). Passar um deles por fmtData/fmtDataHora o leria como
 * carimbo UTC e o traduziria para Cuiaba (UTC-4), deslocando UM DIA para tras: uma
 * certidao valida ate 01/10 apareceria vencendo em 30/09, e o semaforo viraria ambar
 * (ou vermelho) um dia antes da hora, na tela cuja unica funcao e' dizer se da' para
 * protocolar hoje.
 *
 * Por isso aqui nao existe `new Date()`: a unica forma segura de nao ter fuso e' nunca
 * construir um. E' recorte de string, e string malformada aparece crua — como no resto
 * do modulo, dado ilegivel nunca vira data inventada.
 */
export function fmtDataPura(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec((iso ?? "").trim());
  return m === null ? iso : `${m[3]}/${m[2]}/${m[1]}`;
}

/** Competencia "AAAA-MM" -> "MM/AAAA" (DESIGN.md › Numeros e datas). E' mes de calendario, sem
 *  fuso; vazio vira "—" e o que nao for competencia aparece cru. */
export function fmtCompetencia(c: string | null | undefined): string {
  const m = /^(\d{4})-(\d{2})/.exec((c ?? "").trim());
  return m === null ? (c || "—") : `${m[2]}/${m[1]}`;
}

const MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];

/** Competencia "AAAA-MM" -> "set/26". SO' no eixo de grafico (11px), a excecao declarada no
 *  DESIGN.md; em texto e tabela a competencia e' `fmtCompetencia`. */
export function fmtMesCurto(c: string): string {
  const m = /^(\d{4})-(\d{2})/.exec((c ?? "").trim());
  const nome = m ? MESES[Number(m[2]) - 1] : undefined;
  return m && nome ? `${nome}/${m[1].slice(2)}` : c;
}

/** Competencia "AAAA-MM" -> nome do mes por extenso ("setembro"), pelo Intl pt-BR (nada de lista a mao). `antes`
 *  recua meses (1 = o mes anterior, virando o ano se preciso). Mes de calendario, em UTC puro, sem fuso do
 *  navegador; o que nao for competencia volta cru. */
export function fmtMesExtenso(c: string, antes = 0): string {
  const m = /^(\d{4})-(\d{2})/.exec((c ?? "").trim());
  if (m === null || Number(m[2]) < 1 || Number(m[2]) > 12) return c;
  const d = new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1 - antes, 1));
  return new Intl.DateTimeFormat("pt-BR", { month: "long", timeZone: "UTC" }).format(d);
}
