// Regras de APRESENTACAO da tela de Avisos (NAVEGACAO.md › Avisos): funcoes puras sobre o aviso que o servidor
// manda pronto (`app/avisos.py`). Nada aqui decide nivel, prazo ou atraso: so' agrupa, filtra e ordena.
import { porAtraso, type Aviso, type Nivel } from "./Alertas";
import { hojeLocal } from "./tempo";

export type Familia = "prazo" | "reajuste" | "nota" | "siga" | "documentos" | "outros";

// A ordem dos grupos e' a do mapa; "Outros" guarda o aviso de lar desconhecido, para nada sumir. A familia
// Dinheiro saiu com o aviso de pagamento atrasado (issue #255), que era o unico dela.
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

/** O filtro por categoria da rota (?familia=reajustes|prazos|certidoes, do "Ver todos" do Inicio); os ids das
 *  familias (?familia=prazo) continuam valendo. */
export function familiaDaBusca(v: string | undefined): Familia | null {
  const alias: Record<string, Familia> = { reajustes: "reajuste", prazos: "prazo", certidoes: "documentos" };
  const id = alias[v ?? ""] ?? v;
  return FAMILIAS.find(f => f.id === id)?.id ?? null;
}
