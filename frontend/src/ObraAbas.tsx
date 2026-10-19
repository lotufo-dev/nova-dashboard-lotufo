import { useEffect, useState } from "react";
import CaixaAviso from "./CaixaAviso";
import { api, mensagemDeErro } from "./api";
import Cronograma from "./Cronograma";
import { IconeAlerta } from "./icones";
import Instrumentos from "./Instrumentos";
import type { InstrumentoCadastro } from "./obra";
import { Link } from "./Link";
// Validade e' DATA PURA do papel que o orgao emitiu, nao carimbo de instante: fmtData a leria como UTC e a
// traduziria para Cuiaba (UTC-4), deslocando um dia, exatamente na tela que diz se da' para protocolar hoje.
import { fmtCompetencia as mesBR, fmtDataPura } from "./tempo";
import Rolagem from "./Rolagem";
import Selo from "./Selo";

// Abas da pagina da obra (bloco 6; spec §10.3; NAVEGACAO.md › Obra): Documentos exigidos e Contrato, so' leitura
// (o cadastro e' versionado em `cadastro/*.yaml`). As notas moram na pagina de cada medicao. Reajuste e Prazos,
// com o fluxo do oficio, moram em Reajuste.tsx e Prazos.tsx.

function useDados<T>(url: string): { dados: T | null; erro: string } {
  const [dados, setDados] = useState<T | null>(null);
  const [erro, setErro] = useState("");
  useEffect(() => {
    let vivo = true;
    setDados(null); setErro("");
    api<T>(url)
      .then(d => { if (vivo) setDados(d); })
      .catch(e => { if (vivo) setErro(mensagemDeErro(e)); });
    return () => { vivo = false; };
  }, [url]);
  return { dados, erro };
}

function Estado({ erro }: { erro: string }) {
  return erro
    ? <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erro}</p>
    : <section className="cartao"><div className="vazio"><p>Carregando…</p></div></section>;
}

function data(iso: string | null | undefined): string {
  return iso ? fmtDataPura(iso.slice(0, 10)) : "—";
}

function Cartao({ id, titulo, dica, children }: { id: string; titulo: string; dica?: string; children: React.ReactNode }) {
  return (
    <section className="cartao" aria-labelledby={id}>
      <div className="cartao__cabeca">
        <h2 className="cartao__titulo" id={id}>{titulo}</h2>
        {dica && <span className="cartao__dica">{dica}</span>}
      </div>
      {children}
    </section>
  );
}

/* ---------------------------------------------------------------- documentos */

// 'vencendo' NAO trava o protocolo (certidao valida hoje e' certidao valida hoje) e 'nao_se_aplica' nao pesa
// no veredito. Quem decide isso e' o servidor, em `app/checklist.py`: esta tela desenha o que ele respondeu,
// sem recalcular a regra (duas verdades divergiriam no primeiro ajuste).
type Situacao = "ok" | "vencendo" | "pendente" | "nao_se_aplica";

// Bloco 4: um item por EMPRESA x documento exigido (obra de consorcio cobra o consorcio e cada consorciada)
// e, onde o orgao pede, a regularidade mensal do DP (`chave: "regularidade"`).
type ItemChecklist = {
  entidade_id: number; entidade: string | null; tipo_id: number | null; tipo: string; chave: string | null;
  jurisdicao: string | null; situacao: Situacao; validade: string | null; dias: number | null;
  certidao_id: number | null; link_emissao: string | null; competencia?: string | null; esperada?: string;
};
type Checklist = { contrato_id: number; entidade_id: number; entidade: string | null; itens: ItemChecklist[]; pronto: boolean };

const JURISDICOES: Record<string, string> = {
  federal: "Federal", estadual: "Estadual", municipal: "Municipal", trabalhista: "Trabalhista",
};

// Situacao -> modificador do chip. 'nao_se_aplica' cai no `.selo` nu (neutro).
const NIVEL: Record<Situacao, string> = { ok: "selo--ok", vencendo: "selo--atencao", pendente: "selo--acao", nao_se_aplica: "" };

function rotuloSituacao(i: ItemChecklist): string {
  switch (i.situacao) {
    case "ok": return "Em dia";
    case "vencendo":
      // `dias` so' e' null quando nao ha certidao, e ai a situacao nunca e' 'vencendo'; o ramo existe para a
      // tela nao escrever "Vence em null dias" se isso mudar.
      if (i.dias === null) return "A vencer";
      if (i.dias <= 0) return "Vence hoje";
      if (i.dias === 1) return "Vence amanhã";
      return `Vence em ${i.dias} dias`;
    case "pendente": return "Pendente";
    default: return "Não se aplica";
  }
}

function explicacao(i: ItemChecklist): string {
  if (i.chave === "regularidade") {
    return i.situacao === "ok" ? `Regularidade do DP de ${mesBR(i.competencia)} anexada`
      : `Regularidade do DP de ${mesBR(i.esperada)} ainda não anexada — anexe em Documentos`;
  }
  // 'ok'/'vencendo' sempre tem validade (sao derivadas de uma certidao vigente); o ramo sem data existe para
  // a frase nunca terminar em "válida até " se isso mudar.
  const ate = i.validade === null ? "válida hoje" : `válida até ${fmtDataPura(i.validade)}`;
  switch (i.situacao) {
    case "ok": return `Certidão ${ate}`;
    case "vencendo": return `Certidão ${ate} — vale hoje e o órgão aceita, mas renove antes do próximo protocolo`;
    case "pendente":
      return "Nenhuma certidão válida hoje — vencida, revogada ou nunca cadastrada. Enquanto estiver assim, o protocolo fica travado.";
    default:
      return "Alguém declarou que esta entidade não está sujeita a este tipo de certidão — por isso não pesa no veredito.";
  }
}

// o ato de cada natureza: a medicao se protocola; o reajuste se pede no pleito
const NATUREZA = {
  execucao: { titulo: "Medição", onde: "no protocolo da medição", antes: "antes de levar a pasta ao protocolo",
              pronto: "Pronto para protocolar" },
  reajuste: { titulo: "Reajuste", onde: "no pleito de reajuste", antes: "antes de enviar o pleito",
              pronto: "Pronto para enviar o pleito" },
};

/** Um quadro por natureza: o veredito de hoje e os documentos de cada empresa (a empresa e' a linha-titulo do
 *  grupo, com o caminho para ela em Documentos, onde a certidao e' anexada), com "Emitir" onde vence ou falta. */
function QuadroExigidos({ contratoId, natureza }: { contratoId: number; natureza: keyof typeof NATUREZA }) {
  const n = NATUREZA[natureza];
  const { dados, erro } = useDados<Checklist>(
    `/api/contratos/${contratoId}/checklist-protocolo${natureza === "execucao" ? "" : `?natureza=${natureza}`}`);
  const id = `titulo-exigidos-${natureza}`;
  const itens = dados?.itens ?? [];
  const pendentes = itens.filter(i => i.situacao === "pendente").length;
  const aVencer = itens.filter(i => i.situacao === "vencendo").length;
  // Quantos itens sao sustentados por uma certidao de verdade. Zero aqui com veredito "Pronto" quer dizer que
  // TODOS os tipos foram declarados "nao se aplica": dizer "todas estao valendo" seria falso.
  const cobertos = itens.filter(i => i.situacao === "ok" || i.situacao === "vencendo").length;
  // Lista VAZIA nao e' "Pronto": o servidor devolve `pronto: true`, mas o motivo real e' cadastro faltando.
  const temVeredito = dados !== null && itens.length > 0;
  const emitir = (i: ItemChecklist) => (i.situacao === "pendente" || i.situacao === "vencendo") && !!i.link_emissao;
  const comEmitir = itens.some(emitir);
  // habilitacao e' por CNPJ: a obra de consorcio se habilita com as certidoes dele e de cada consorciada
  const quem = new Set(itens.map(i => i.entidade_id)).size > 1 ? `${dados?.entidade ?? "Consórcio"} e consorciadas`
    : dados?.entidade ?? "esta entidade";
  // as empresas na ordem em que o servidor as manda (o consorcio, depois cada consorciada)
  const empresas = [...new Map(itens.map(i => [i.entidade_id, i.entidade] as const)).entries()];
  const colunas = comEmitir ? 4 : 3;

  return (
    <section className="cartao" aria-labelledby={id}>
      <div className="cartao__cabeca">
        <h2 className="cartao__titulo" id={id}>{n.titulo}</h2>
        {/* veredito nunca e' so' cor: o chip carrega a palavra */}
        {temVeredito && (
          <Selo classe={dados.pronto ? "selo--ok" : "selo--acao"}>
            {dados.pronto ? n.pronto : pendentes === 1 ? "1 pendência" : `${pendentes} pendências`}
          </Selo>
        )}
      </div>

      {erro && <div className="cartao__corpo"><p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erro}</p></div>}
      {!dados && !erro && <div className="vazio"><p>Verificando os documentos das empresas…</p></div>}
      {dados && itens.length === 0 && (
        <div className="vazio">
          <p className="vazio__titulo">Nenhum documento exigido</p>
          <p>O cadastro do órgão não exige documentos {n.onde}, então não há o que verificar — isto não quer dizer
            que a habilitação esteja em dia.</p>
        </div>
      )}

      {temVeredito && (
        <>
          <div className="cartao__corpo">
            {dados.pronto && cobertos === 0 ? (
              <p className="campo__nota">Nenhuma certidão exigida de {quem} — todos os tipos aplicáveis foram declarados
                “não se aplica”. Nada trava, mas quem declarou responde pela declaração.</p>
            ) : dados.pronto ? (
              <p className="campo__nota">Todas as certidões exigidas de {quem} estão valendo hoje.
                {aVencer > 0 && ` ${aVencer === 1 ? "Uma delas vence em breve — renove" : `${aVencer} delas vencem em breve — renove`} antes do próximo protocolo.`}</p>
            ) : (
              <CaixaAviso nivel="critico">{quem}: {pendentes === 1 ? "1 documento sem validade hoje" : `${pendentes} documentos sem validade hoje`} —
                  emita no órgão e anexe em Documentos {n.antes}.</CaixaAviso>
            )}
          </div>

          <Rolagem rotulo={`Documentos exigidos: ${n.titulo}`}>
            <table className="tabela tabela--grade">
              {/* mesma grade nas tabelas de cada nucleo (F-47) */}
              <colgroup>
                <col /><col className="c-situacao" /><col className="c-data" />{comEmitir && <col className="c-acao" />}
              </colgroup>
              <caption className="sr-only">Situação hoje de cada documento exigido das empresas deste contrato {n.onde}</caption>
              <thead>
                <tr>
                  <th scope="col">Documento</th><th scope="col">Situação</th><th scope="col">Validade</th>
                  {comEmitir && <th scope="col"><span className="sr-only">Emitir</span></th>}
                </tr>
              </thead>
              {empresas.map(([eid, nome]) => (
              <tbody key={eid}>
                <tr className="grupo">
                  <th scope="rowgroup" colSpan={colunas}>
                    {nome ? <Link para={{ tela: "documentos-empresa", id: eid }}>{nome}</Link> : "Empresa sem nome no cadastro"}
                  </th>
                </tr>
                {itens.filter(i => i.entidade_id === eid).map((i, k) => (
                  <tr key={`${i.entidade_id}-${i.chave ?? i.tipo_id}`} className={`linha${k % 2 === 1 ? " par" : ""}`}>
                    <td className="forte">{i.tipo}{i.entidade === null && i.jurisdicao ? ` (${JURISDICOES[i.jurisdicao] ?? i.jurisdicao})` : ""}</td>
                    {/* a explicacao entra como texto sr-only DENTRO do chip (tooltip nao existe para teclado nem
                        para leitor de tela); o `title` fica na celula, so' como conveniencia de mouse */}
                    <td title={explicacao(i)}>
                      {/* D15 (F-102): "Em dia" e' ponto e palavra, sem fundo; o selo fica para Atencao e Critico */}
                      {i.situacao === "ok" ? (
                        <span className="estado estado--ok">
                          <span className="estado__ponto" aria-hidden="true" />{rotuloSituacao(i)}
                          <span className="sr-only"> — {explicacao(i)}</span>
                        </span>
                      ) : (
                        <Selo classe={NIVEL[i.situacao]} sufixo={<span className="sr-only"> — {explicacao(i)}</span>}>
                          {rotuloSituacao(i)}
                        </Selo>
                      )}
                    </td>
                    <td className="num">{i.chave === "regularidade" ? `competência ${mesBR(i.competencia)}` : data(i.validade)}</td>
                    {comEmitir && <td>{emitir(i) && (
                      <a href={i.link_emissao!} target="_blank" rel="noreferrer">Emitir<span className="sr-only"> {i.tipo} (abre o site do órgão)</span></a>
                    )}</td>}
                  </tr>
                ))}
              </tbody>
              ))}
            </table>
          </Rolagem>
        </>
      )}
    </section>
  );
}

export function DocumentosObra({ contratoId }: { contratoId: number }) {
  return (
    <div className="pilha">
      <QuadroExigidos contratoId={contratoId} natureza="execucao" />
      <QuadroExigidos contratoId={contratoId} natureza="reajuste" />
    </div>
  );
}

/* ------------------------------------------------------------------ contrato */

function texto(v: unknown): string {
  return v === undefined || v === null || v === "" ? "—" : String(v);
}

type Detalhe = { objeto: string; numero_instrumento: string; orgao: string; lei?: string | null;
                 municipio?: string | null; numero_processo?: string | null; centro_custo_rm?: string | null;
                 execucao_inicio?: string | null; vigencia_inicio?: string | null };
type Fiscal = { nome: string; email: string | null; desde: string; cargo: string | null; portaria: string | null };
type Cadastro = { datas_base?: { mes: string; indice: string | null }[]; fiscais: Fiscal[]; instrumentos: InstrumentoCadastro[] };

/** Contrato: o cadastro (com as datas-base e os fiscais), os instrumentos numa lista so' e o cronograma. */
export function ContratoObra({ contratoId }: { contratoId: number }) {
  const { dados, erro } = useDados<Detalhe>(`/api/contratos/${contratoId}`);
  const cad = useDados<Cadastro>(`/api/contratos/${contratoId}/cadastro`);
  if (!dados) return <Estado erro={erro} />;
  const bases = cad.dados?.datas_base ?? [];
  const campos: [string, string][] = [
    ["Instrumento", dados.numero_instrumento], ["Órgão", dados.orgao], ["Objeto", dados.objeto],
    ["Município", texto(dados.municipio)], ["Lei", texto(dados.lei)], ["Processo", texto(dados.numero_processo)],
    ["Centro de custo (RM)", texto(dados.centro_custo_rm)], ["Início da execução", data(dados.execucao_inicio)],
    ["Início da vigência", data(dados.vigencia_inicio)],
    ["Datas-base", !cad.dados ? (cad.erro ? "—" : "carregando…")
      : bases.length === 0 ? "nenhuma no cadastro" : bases.map(b => `${mesBR(b.mes)}${b.indice ? ` (${b.indice})` : ""}`).join(", ")],
  ];
  const fiscais = cad.dados?.fiscais ?? [];
  return (
    <div className="pilha">
      <Cartao id="titulo-cadastro-obra" titulo="Cadastro">
        {/* rotulo e valor lado a lado: o cadastro em poucas linhas, e os instrumentos logo abaixo */}
        <dl className="cartao__corpo pares">
          {campos.map(([k, v]) => <div key={k}><dt className="campo__rotulo">{k}</dt><dd>{v}</dd></div>)}
          <div>
            <dt className="campo__rotulo">Fiscais</dt>
            <dd>{!cad.dados ? (cad.erro ? "—" : "carregando…") : fiscais.length === 0 ? "nenhum no cadastro" : (
              <ul className="lista-simples">
                {fiscais.map(f => (
                  <li key={`${f.email}-${f.desde}`}>{f.nome || f.email || "sem nome no cadastro"}
                    {f.cargo ? `, ${f.cargo}` : ""}{f.portaria ? `, ${f.portaria}` : ""} (desde <span className="num">{data(f.desde)}</span>)</li>
                ))}
              </ul>
            )}</dd>
          </div>
        </dl>
        {cad.erro && <div className="cartao__corpo"><p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{cad.erro}</p></div>}
      </Cartao>
      <Instrumentos contratoId={contratoId} cadastro={cad.dados?.instrumentos ?? null} erroCadastro={cad.erro} />
      <Cronograma contratoId={contratoId} podeEditar={false} />
    </div>
  );
}
