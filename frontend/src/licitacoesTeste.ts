import type { Favorita, LeituraDoRadar, LinhaLicitacao, MudancaDaFavorita, PrazoDaFavorita, Recomendada } from "./licitacoes";

// Licitacoes inventadas para os testes da Triagem e das Favoritas (#908): orgao, edital, objeto, valor e pasta nao
// existem; o CNPJ da chave e' o ficticio de digito valido. Os testes fixam o dia em 24/11/2026, 11h de Cuiaba.

export const HOJE_DO_TESTE = new Date("2026-11-24T15:00:00Z");

/** A leitura do radar de 24/11/2026 às 09:05 de Cuiaba, em dia e sem fonte com problema. */
export const leitura = (extra: Partial<LeituraDoRadar> = {}): LeituraDoRadar => ({
  lido_em: "2026-11-24T13:05:00+00:00", atrasada: false, fontes_com_problema: 0, ...extra });

export const prazo = (rotulo: string, data: string, dias_uteis: number, situacao: PrazoDaFavorita["situacao"],
    extra: Partial<PrazoDaFavorita> = {}): PrazoDaFavorita => ({
  codigo: rotulo.toLowerCase(), rotulo, data, hora: null, aviso: "", dias_uteis, passado: false, situacao, ...extra });

export const mudanca = (data: string, rotulo: string): MudancaDaFavorita => ({ data, rotulo, texto: "texto que o radar leu" });

export const favorita = (extra: Partial<Favorita> = {}): Favorita => {
  const prazos = extra.prazos ?? [];
  return { desde: "2026-11-13", etapa: "acompanhando", etapa_rotulo: "Acompanhando", etapa_do_dossie: false, dossie: null, selos: [],
    prazos, proximo_prazo: prazos.find(p => !p.passado) ?? null, mudancas: [], ...extra };
};

export const recomendada = (nota: number, extra: Partial<Recomendada> = {}): Recomendada => ({
  nota, pontos: { valor: 3, distancia: 2, acervo: 2 }, motivo: "concorrência · R$ 123,4 mi · Exemplo · 120 km · 2 atestados",
  km: 120, cidade: "Exemplo", ...extra });

export const linha = (n: number, extra: Partial<LinhaLicitacao> = {}): LinhaLicitacao => ({
  chave: `11444777000161-1-${String(n).padStart(6, "0")}/2026`, orgao: "Prefeitura Municipal de Exemplo", sigla_orgao: "PME",
  grupo_orgao: "Outros órgãos", orgao_de_interesse: false, esfera: "Municipal", municipio: "Exemplo", uf: "MT", cidade: "Exemplo", km: 120,
  edital: `CE ${String(n).padStart(3, "0")}/2026`, modalidade: "Concorrência", objeto: `Objeto inventado ${n}`, tipo_obra: "Urbanização",
  valor_centavos: 123456789, valor_rotulo: "", situacao: "Divulgada no PNCP", data_publicacao: "2026-11-10", data_sessao: "2026-12-10",
  hora_sessao: "09:00", primeira_vez: "2026-11-11", link: `https://exemplo.com.br/editais/${n}`, portal: "Site do órgão", fontes: ["PNCP"],
  recomendada: null, dias_uteis: 12, prazo: "breve", encerrada: false, favorita: null, ...extra });
