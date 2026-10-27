import { useState } from "react";
import { IconeAlerta, IconeSeta, IconeSino } from "./icones";
import Selo from "./Selo";
import { semRSOrfao } from "./avisos";
import { brl } from "./Medicoes";
import { type AbaObra, type Busca, type Ir, type Rota } from "./rota";
import { Link } from "./Link";

// Cartao de avisos (spec §11). Bloco 6: o servidor manda o aviso PRONTO (`app/avisos.py`): nivel,
// mensagem de uma linha, obra, dias, valor e destino do clique. Esta tela so' desenha — nao ha mais
// mapa local de tipo para rotulo, e aviso de tipo novo aparece sem mudar nada aqui.

export type Nivel = "critico" | "acao" | "atencao";

// O destino e' o do servidor, no vocabulario dele ("contrato" + aba); `destinoDoAviso` o traduz para a
// rota da tela nova, sem mudar o contrato da API.
export type Destino = { tela: "contrato"; id: number; aba: string } | { tela: "documentos" };

export type Aviso = {
  tipo: string; nivel: Nivel; publico: string[]; contrato_id: number | null; obra: string | null;
  dias: number | null; valor_centavos: number | null; mensagem: string; destino: Destino | null;
  entidade_id?: number;
  entidade?: string | null;     // A11: o nome da empresa, no aviso de documentos
  medicao_id?: number | null;   // A2: a medicao do aviso de nota
  data_base_mes?: string | null; // A10: a data-base do aviso de reajuste
  // A8: a data do fato; "prazo" = o dia em que vence (ou venceu), "desde" = o dia em que o fato comecou
  data?: string | null; sentido?: "prazo" | "desde" | null;
};

const ABAS_OBRA: readonly string[] = ["medicoes", "prazos", "reajuste", "documentos", "contrato"] satisfies AbaObra[];

/** Para onde o aviso leva: as notas da medicao (aviso de nota, A2), o ciclo da data-base (aviso de reajuste,
 *  A10), a aba da obra, ou a pagina da empresa em Documentos. */
export function destinoDoAviso(a: Aviso): { para: Rota; secao?: string; busca?: Busca } | null {
  const d = a.destino;
  if (!d) return null;
  // a empresa em Documentos: a pagina dela (#161); o aviso da regularidade do mes leva direto a aba dela
  if (d.tela === "documentos") return a.entidade_id
    ? { para: { tela: "documentos-empresa", id: a.entidade_id, aba: a.tipo === "regularidade_mes" ? "regularidade" : (a.tipo === "garantia_vencendo" || a.tipo === "garantia_aquem_execucao") ? "garantia" : undefined } }
    : { para: { tela: "documentos" } };
  if (d.aba === "notas" && a.medicao_id) return { para: { tela: "medicao", obra: d.id, id: a.medicao_id }, secao: "notas" };
  if (d.aba === "reajuste" && a.data_base_mes) return { para: { tela: "obra", id: d.id, aba: "reajuste" }, secao: `db-${a.data_base_mes}` };
  const aba = (ABAS_OBRA.includes(d.aba) ? d.aba : "medicoes") as AbaObra;
  // na aba Medicoes, as medicoes em andamento, nao o resumo do topo
  return { para: { tela: "obra", id: d.id, aba }, secao: aba === "medicoes" ? "em-andamento" : undefined };
}

const ORDEM_NIVEL: Record<string, number> = { critico: 0, acao: 1, atencao: 2 };

/** Do mais grave ao mais atrasado (mapa de 2026-09-28, A8): no mesmo nivel, a data do fato mais antiga
 *  primeiro, seja o prazo que venceu antes, seja o fato parado ha' mais tempo; sem data, depois, na ordem
 *  do servidor. Nivel desconhecido conta como atencao, como no selo. */
export function porAtraso(avisos: Aviso[]): Aviso[] {
  const nivel = (a: Aviso) => ORDEM_NIVEL[a.nivel] ?? 2;
  return [...avisos].sort((x, y) => nivel(x) - nivel(y)
    || (x.data && y.data ? x.data.localeCompare(y.data) : x.data ? -1 : y.data ? 1 : 0));
}

/** A mensagem sem o "Obra: " do comeco, onde a tela ja' diz a obra (a pagina dela, o grupo dela): o mesmo
 *  corte que o servidor faz nos motivos do farol (A5), pelo campo `obra`, nunca adivinhando pelo texto. */
export function semObra(a: Aviso): Aviso {
  const prefixo = a.obra ? `${a.obra}: ` : "";
  return prefixo && a.mensagem.startsWith(prefixo) ? { ...a, mensagem: a.mensagem.slice(prefixo.length) } : a;
}

/** A mensagem sem o "Empresa: " do comeco, no grupo da empresa (A11), pelo campo `entidade`. */
export function semEmpresa(a: Aviso): Aviso {
  const prefixo = a.entidade ? `${a.entidade}: ` : "";
  return prefixo && a.mensagem.startsWith(prefixo) ? { ...a, mensagem: a.mensagem.slice(prefixo.length) } : a;
}

/** Os avisos de UMA obra (pelo `contrato_id` que o servidor manda), por atraso, sem o nome da obra no comeco. */
export function avisosDaObra(avisos: Aviso[], contratoId: number): Aviso[] {
  return porAtraso(avisos.filter(a => a.contrato_id === contratoId)).map(semObra);
}

// O nivel vira palavra no selo: estado nunca e' so' cor. D2 (DESIGN.md › Colors): vermelho so' no
// Critico, como o farol da Diretoria; Acao e Atencao dividem o ambar e se separam pela FORMA — Acao
// com contorno cheio e o icone de proximo passo, Atencao com o ponto.
export const SELO: Record<Nivel, { rotulo: string; classe: string; forte?: boolean }> = {
  critico: { rotulo: "Crítico", classe: "selo--acao" },
  acao: { rotulo: "Ação", classe: "selo--atencao", forte: true },
  atencao: { rotulo: "Atenção", classe: "selo--atencao" },
};

// Quantos avisos cabem antes de a lista virar "mostrar os outros": a tela inicial e' lida em
// segundos. O resto continua a um clique, nunca escondido de vez.
const LIMITE = 8;

// `itens === null` NAO e' lista vazia: vazio quer dizer "verificamos, nao ha' aviso"; null quer
// dizer "nao conseguimos verificar". Colapsar os dois faria a tela afirmar que nao ha' aviso
// justamente quando ninguem olhou. `undefined` e' "ainda carregando": o cartao ja' ocupa o lugar dele.
// `verTodos`: onde o resto mora (a tela de Avisos, filtrada); sem ele, o resto abre no lugar.
export default function Alertas({ itens, ir, titulo = "Avisos", limite = LIMITE, id = "titulo-alertas",
                                  vazio = "Nenhum aviso.", verTodos, lateral = false }:
    { itens: Aviso[] | null | undefined; ir: Ir; titulo?: string; limite?: number; id?: string; vazio?: string;
      verTodos?: { para: Rota; busca?: Busca; rotulo: string }; lateral?: boolean }) {
  const [todos, setTodos] = useState(false);
  // A ordem e' a de quem chama: a do servidor (nivel, dias, obra; `avisos.listar`) ou `porAtraso`.
  const lista = itens ?? [];
  const visiveis = todos ? lista : lista.slice(0, limite);
  const ocultos = lista.length - visiveis.length;

  return (
    <section className="cartao" aria-labelledby={id}>
      <div className="cartao__cabeca">
        <IconeSino className="icone icone--p" />
        <h2 className="cartao__titulo" id={id}>{titulo}</h2>
      </div>

      {itens === undefined ? null : itens === null ? (
        <div className="cartao__corpo">
          <p className="erro" role="alert">
            <IconeAlerta className="icone icone--p" />
            Não foi possível verificar os avisos. Recarregue a página para tentar de novo.
          </p>
        </div>
      ) : itens.length === 0 ? (
        <div className="vazio vazio--curto">
          <p className="vazio__titulo">{vazio}</p>
        </div>
      ) : (
        <ul className={lateral ? "alertas alertas--lateral" : "alertas"}>
          {visiveis.map((a, i) => {
            const selo = SELO[a.nivel] ?? SELO.atencao;
            const destino = destinoDoAviso(a);
            // F-96: a linha inteira e' o link; o chevron no fim diz isso.
            const conteudo = (
              <>
                <Selo classe={selo.classe} forte={selo.forte}>{selo.rotulo}</Selo>
                <span className="alerta__msg">{semRSOrfao(a.mensagem)}</span>
                {/* valor em coluna propria, alinhado a' direita: da' para varrer os valores da lista */}
                <span className="alerta__valor num">{a.valor_centavos !== null ? brl(a.valor_centavos) : ""}</span>
                {destino && <IconeSeta className="icone icone--p alerta__seta" />}
              </>
            );
            return (
              <li key={`${a.tipo}-${a.contrato_id}-${a.entidade_id ?? ""}-${i}`}>
                {destino
                  ? <Link className="alerta alerta--seta" para={destino.para} busca={destino.busca} secao={destino.secao} ir={ir}>{conteudo}</Link>
                  : <span className="alerta">{conteudo}</span>}
              </li>
            );
          })}
        </ul>
      )}

      {ocultos > 0 && verTodos && (
        <div className="cartao__rodape">
          <Link className="btn btn--pequeno" para={verTodos.para} busca={verTodos.busca} ir={ir}>{verTodos.rotulo}</Link>
        </div>
      )}
      {ocultos > 0 && !verTodos && (
        <div className="cartao__rodape">
          <button type="button" className="btn btn--pequeno" onClick={() => setTodos(true)}>
            Mostrar os outros {ocultos}
          </button>
        </div>
      )}
      {todos && lista.length > limite && (
        <div className="cartao__rodape">
          <button type="button" className="btn btn--pequeno" onClick={() => setTodos(false)}>
            Mostrar só os {limite} primeiros
          </button>
        </div>
      )}
    </section>
  );
}
