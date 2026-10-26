// Regras de APRESENTACAO da tela de Avisos (NAVEGACAO.md › Avisos): funcoes puras sobre o aviso que o servidor
// manda pronto (`app/avisos.py`). Nada aqui decide nivel, prazo ou atraso: so' agrupa, filtra e ordena.
import { porAtraso, type Aviso, type Nivel } from "./Alertas";

export type Familia = "prazo" | "reajuste" | "nota" | "documentos" | "outros";

// A ordem dos grupos e' a do mapa; "Outros" guarda o aviso de lar desconhecido, para nada sumir. A familia
// Dinheiro saiu com o aviso de pagamento atrasado (issue #255), que era o unico dela.
export const FAMILIAS: { id: Familia; rotulo: string }[] = [
  { id: "prazo", rotulo: "Prazo" }, { id: "reajuste", rotulo: "Reajuste" }, { id: "nota", rotulo: "Nota" },
  { id: "documentos", rotulo: "Documentos" }, { id: "outros", rotulo: "Outros" },
];

/** A familia e' o lar do aviso: o `destino` que o servidor manda (a aba da obra, ou Documentos). */
export function familiaDoAviso(a: Aviso): Familia {
  const d = a.destino;
  if (d?.tela === "documentos") return "documentos";
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
