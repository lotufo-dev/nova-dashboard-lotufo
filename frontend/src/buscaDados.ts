import type { Busca as Filtros, Rota } from "./rota";
import { fmtCompetencia } from "./tempo";

// O dado da busca unica do topo (#819): o contrato de GET /api/busca?q= e a resposta em secoes de opcoes, para a
// peca (Busca.tsx) so' desenhar. O recorte do perfil e' do servidor: sem SIGA, `processos` nao vem.

export type ObraAchada = { id: number; nome: string; instrumento: string | null; contratante: string; orgao_sub: string | null };
export type MedicaoAchada = { id: number; contrato_id: number; titulo: string; competencia: string; obra: string; contratante: string };
export type ProcessoAchado = { id: number; numero: string | null; assunto: string };
type Grupo<T> = { itens: T[]; total: number };
export type RespostaBusca = { obras: Grupo<ObraAchada>; medicoes: Grupo<MedicaoAchada>; processos?: Grupo<ProcessoAchado> };

/** Espera a pessoa parar de digitar antes de perguntar ao servidor. */
export const ESPERA_MS = 250;
/** O mesmo teto do servidor (`busca.MAX_PERGUNTA`). */
export const MAX_PERGUNTA = 100;

export type Opcao = { chave: string; principal: string; detalhe: string; para: Rota; busca?: Filtros };
export type Secao = { id: "obras" | "medicoes" | "processos"; rotulo: string; um: string; varios: string; total: number; opcoes: Opcao[] };

/** Mac (e iPad com teclado): o atalho da busca e' Cmd+K; nos outros sistemas, Ctrl+K. O Ctrl+K do Mac fica com o
 *  campo de texto, onde ele apaga ate' o fim da linha. */
export function ehMac(): boolean {
  const n = typeof navigator === "undefined" ? undefined : navigator;
  const plataforma = (n as (Navigator & { userAgentData?: { platform?: string } }) | undefined)?.userAgentData?.platform
    || n?.platform || n?.userAgent || "";
  return /mac|iphone|ipad/i.test(plataforma);
}

function juntar(...partes: (string | null | undefined)[]): string {
  return partes.filter(Boolean).join(" · ");
}

/** A resposta do servidor em secoes de opcoes, na ordem da tela; secao sem item nao aparece. */
export function secoesDe(r: RespostaBusca): Secao[] {
  const secoes: Secao[] = [
    { id: "obras", rotulo: "Obras", um: "obra", varios: "obras", total: r.obras.total,
      opcoes: r.obras.itens.map(o => ({ chave: `o${o.id}`, principal: o.nome, detalhe: juntar(o.contratante, o.orgao_sub),
        para: { tela: "obra", id: o.id, aba: "ficha" } })) },
    { id: "medicoes", rotulo: "Medições", um: "medição", varios: "medições", total: r.medicoes.total,
      opcoes: r.medicoes.itens.map(m => ({ chave: `m${m.id}`, principal: juntar(m.titulo, m.obra),
        detalhe: juntar(m.contratante, fmtCompetencia(m.competencia)), para: { tela: "medicao", obra: m.contrato_id, id: m.id } })) },
  ];
  if (r.processos) {
    secoes.push({ id: "processos", rotulo: "Processos", um: "processo", varios: "processos", total: r.processos.total,
      opcoes: r.processos.itens.map(p => ({ chave: `p${p.id}`, principal: p.assunto, detalhe: p.numero ?? "",
        para: { tela: "siga" }, busca: { processo: String(p.id) } })) });
  }
  return secoes.filter(s => s.opcoes.length > 0);
}
