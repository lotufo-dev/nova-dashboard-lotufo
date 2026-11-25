// Licitacoes (#908, docs/adr/0018): o que GET /api/licitacoes/triagem e GET /api/licitacoes/favoritas devolvem, e o
// texto que as duas paginas escrevem com isso. Tudo vem pronto do servidor (`backend/app/licitacoes.py`): os dias uteis
// ate' cada prazo, a situacao do prazo, a etapa com o rotulo, a ordem das linhas e as contagens. Aqui nao ha' limite nem
// conta: so' formato.

import { useEffect, useState } from "react";
import { api, mensagemDeErro } from "./api";
import type { Situacao } from "./situacao";
import { fmtData, fmtDataPura, fmtDiaNoAno, fmtHora, hojeLocal } from "./tempo";

/** A situacao de um prazo, como o servidor a leu: critico, vence em breve ou nenhuma. */
export type SituacaoDoPrazo = Extract<Situacao, "critico" | "breve"> | null;

/** A ultima leitura do radar (o programa de fora que le as fontes). `atrasada`: e' de antes do dia esperado. */
export type LeituraDoRadar = { lido_em: string | null; atrasada: boolean; fontes_com_problema: number };

/** Um prazo da favorita. `passado` e' do servidor, pela data: de sexta para sabado nao ha' dia util, e o prazo que ja'
 *  passou pode vir com `dias_uteis: 0`. A tela nunca le "passou" no sinal dos dias. */
export type PrazoDaFavorita = {
  codigo: string; rotulo: string; data: string; hora: string | null; aviso: string; dias_uteis: number; passado: boolean;
  situacao: SituacaoDoPrazo;
};
export type MudancaDaFavorita = { data: string; texto: string; rotulo: string };

/** A favorita: a licitacao que se decidiu acompanhar. A etapa vem do dossie quando ha' dossie (`etapa_do_dossie`). */
export type Favorita = {
  desde: string; etapa: string; etapa_rotulo: string; etapa_do_dossie: boolean; dossie: string | null;
  /** o que o dossie diz alem da etapa ("Diretoria: interesse", "Suspensa"); pode vir vazia */
  selos: string[];
  prazos: PrazoDaFavorita[]; proximo_prazo: PrazoDaFavorita | null; mudancas: MudancaDaFavorita[];
};

/** A recomendacao: a nota, o motivo e o local da obra pelo radar (`cidade`, que pode vir vazia, e `km`). */
export type Recomendada = {
  nota: number; pontos: { valor: number; distancia: number; acervo: number }; motivo: string;
  km: number | null; cidade: string;
};

/** Uma licitacao, com a mesma forma nas duas rotas. `orgao_de_interesse`: um dos orgaos que o dono acompanha de perto
 *  (as novas deles ja' vem contadas em `contagens.por_orgao`). */
export type LinhaLicitacao = {
  chave: string; orgao: string; sigla_orgao: string; grupo_orgao: string; orgao_de_interesse: boolean; esfera: string | null;
  municipio: string; uf: string;
  cidade: string; km: number | null; edital: string; modalidade: string; objeto: string; tipo_obra: string;
  valor_centavos: number | null; valor_rotulo: string; situacao: string; data_publicacao: string | null;
  data_sessao: string | null; hora_sessao: string | null; primeira_vez: string | null; link: string; portal: string; fontes: string[];
  recomendada: Recomendada | null;
  /** dias uteis ate' a sessao; nulo e' sem data. Sessao passada e' `encerrada`, nunca o sinal dos dias */
  dias_uteis: number | null;
  prazo: SituacaoDoPrazo; encerrada: boolean; favorita: Favorita | null;
};

export type RespostaTriagem = {
  leitura: LeituraDoRadar;
  contagens: {
    recomendadas: number; favoritas: number; novas: number;
    novas_desde: { desde: string; quantas: number } | null;
    por_orgao: { orgao: string; novas: number }[];
  };
  favoritas: LinhaLicitacao[]; recomendadas: LinhaLicitacao[];
};
export type RespostaFavoritas = { leitura: LeituraDoRadar; favoritas: LinhaLicitacao[] };

/** Le uma rota de Licitacoes ao abrir a pagina; `tentar` le de novo depois da falha. */
export function useLicitacoes<T>(caminho: string) {
  const [dados, setDados] = useState<T | null>(null);
  const [erro, setErro] = useState("");
  const [tentativa, setTentativa] = useState(0);
  useEffect(() => {
    let vivo = true;
    api<T>(caminho).then(d => { if (vivo) { setDados(d); setErro(""); } })
      .catch(e => { if (vivo) setErro(mensagemDeErro(e)); });
    return () => { vivo = false; };
  }, [caminho, tentativa]);
  return { dados, erro, tentar: () => setTentativa(n => n + 1) };
}

/** O endereco do edital, so' quando e' http ou https: o servidor ja' valida, e a tela nao confia. */
export function linkExterno(link: string | null | undefined): string | null {
  return /^https?:\/\//i.test(link ?? "") ? (link as string) : null;
}

/** Quando o radar leu: "24/11 às 09:05", na hora de Cuiaba. */
export function quandoLeu(lidoEm: string): string {
  return `${fmtData(lidoEm).slice(0, 5)} às ${fmtHora(lidoEm)}`;
}

/** O aviso da leitura atrasada; sem leitura nenhuma, que o radar ainda nao entregou. */
export function avisoDaLeitura(leitura: LeituraDoRadar): string {
  return leitura.lido_em ? `O radar não lê desde ${quandoLeu(leitura.lido_em)}.` : "O radar ainda não entregou leitura.";
}

/** Os dias uteis que o servidor contou ate' um prazo que ainda nao passou, por extenso: "em 1 dia útil", "em 12 dias
 *  úteis". No dia do prazo, "hoje". Sem dia util ate' la' e noutro dia (o prazo de sabado visto na sexta), "antes do
 *  próximo dia útil": zero dias uteis nao quer dizer hoje. Sem a contagem, nada. Se o prazo passou quem diz e' o
 *  servidor (`passado`, `encerrada`), e ai' esta funcao nem e' chamada. `hoje` ("AAAA-MM-DD") e' para o teste. */
export function emDiasUteis(dias: number | null, data: string, hoje: string = hojeLocal()): string | null {
  if (dias === null) return null;
  if (data === hoje) return "hoje";
  return dias <= 0 ? "antes do próximo dia útil" : dias === 1 ? "em 1 dia útil" : `em ${dias.toLocaleString("pt-BR")} dias úteis`;
}

/** Data pura e hora de um prazo: "27/11" no ano de hoje, "01/03/2027" em outro, com a hora quando ha'. */
export function dataDoPrazo(data: string, hora: string | null, hoje?: string): string {
  return `${fmtDiaNoAno(data, hoje) ?? fmtDataPura(data)}${hora ? ` ${hora}` : ""}`;
}

/** O orgao como a linha o escreve: a sigla, quando o radar a manda; senao o nome. */
export function orgaoDaLinha(l: Pick<LinhaLicitacao, "orgao" | "sigla_orgao">): string {
  return l.sigla_orgao || l.orgao;
}

/** A distancia ate' a obra: "1.250 km", com o espaco que nao separa o numero da unidade; nulo sem distancia. */
export function fmtKm(km: number | null): string | null {
  return km === null ? null : `${km.toLocaleString("pt-BR")}\u00a0km`;
}
