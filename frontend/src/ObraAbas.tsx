import { useEffect, useState } from "react";
import { api, mensagemDeErro } from "./api";
import Cronograma from "./Cronograma";
import { IconeAlerta } from "./icones";
import Instrumentos from "./Instrumentos";
import type { InstrumentoCadastro } from "./obra";
import { Link } from "./Link";
// Validade e' DATA PURA do papel que o orgao emitiu, nao carimbo de instante: fmtData a leria como UTC e a
// traduziria para Cuiaba (UTC-4), deslocando um dia, exatamente na tela que diz se da' para protocolar hoje.
import { fmtCompetencia as mesBR, fmtDataPura } from "./tempo";
import Selo from "./Selo";

// Abas da pagina da obra (bloco 6; spec §10.3; NAVEGACAO.md › Obra): Documentos (o veredito do protocolo) e Contrato, so' leitura
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

function Cartao({ id, titulo, children }: { id: string; titulo: string; children: React.ReactNode }) {
  return (
    <section className="cartao" aria-labelledby={id}>
      <div className="cartao__cabeca">
        <h2 className="cartao__titulo" id={id}>{titulo}</h2>
      </div>
      {children}
    </section>
  );
}

/* ---------------------------------------------------------------- documentos */

// #661: a obra responde "pode protocolar hoje?", para a medicao e para o reajuste, e diz o que falta; a certidao
// de cada empresa, uma a uma (validade, emitir, anexar), mora em Documentos. Quem decide o veredito e' o servidor,
// em `app/checklist.py` ('vencendo' nao trava, 'nao_se_aplica' nao pesa): esta tela desenha o que ele respondeu,
// sem recalcular a regra (duas verdades divergiriam no primeiro ajuste).
type Situacao = "ok" | "vencendo" | "pendente" | "nao_se_aplica";

// Um item por EMPRESA x documento exigido (obra de consorcio cobra o consorcio e cada consorciada) e, onde o
// orgao pede, a regularidade mensal do DP (`chave: "regularidade"`).
type ItemChecklist = {
  entidade_id: number; entidade: string | null; tipo_id: number | null; tipo: string; chave: string | null;
  jurisdicao: string | null; situacao: Situacao; esperada?: string;
};
type Checklist = { contrato_id: number; entidade_id: number; entidade: string | null; itens: ItemChecklist[]; pronto: boolean };

const JURISDICOES: Record<string, string> = {
  federal: "Federal", estadual: "Estadual", municipal: "Municipal", trabalhista: "Trabalhista",
};

function oQueFalta(i: ItemChecklist): string {
  if (i.chave === "regularidade") return i.esperada ? `${i.tipo} de ${mesBR(i.esperada)}` : i.tipo;
  return `${i.tipo}${i.entidade === null && i.jurisdicao ? ` (${JURISDICOES[i.jurisdicao] ?? i.jurisdicao})` : ""}`;
}

const NATUREZA = { execucao: "Medição", reajuste: "Reajuste" };

/** Um quadro por natureza: o veredito de hoje e, quando falta, uma linha por documento com o caminho para a
 *  empresa em Documentos, onde ele e' anexado. */
function QuadroExigidos({ contratoId, natureza }: { contratoId: number; natureza: keyof typeof NATUREZA }) {
  const { dados, erro } = useDados<Checklist>(
    `/api/contratos/${contratoId}/checklist-protocolo${natureza === "execucao" ? "" : `?natureza=${natureza}`}`);
  const id = `titulo-exigidos-${natureza}`;
  const itens = dados?.itens ?? [];
  const faltam = itens.filter(i => i.situacao === "pendente");
  // Lista VAZIA nao e' "Pronto": o servidor devolve `pronto: true`, mas o motivo real e' cadastro faltando.
  const temVeredito = dados !== null && itens.length > 0;

  return (
    <section className="cartao" aria-labelledby={id}>
      <div className="cartao__cabeca">
        <h2 className="cartao__titulo" id={id}>{NATUREZA[natureza]}</h2>
        {/* veredito nunca e' so' cor: o chip carrega a palavra */}
        {temVeredito && (
          <Selo classe={dados.pronto ? "selo--ok" : "selo--acao"}>
            {dados.pronto ? "Pronto para protocolar" : "Falta documento para protocolar"}
          </Selo>
        )}
      </div>

      {erro && <div className="cartao__corpo"><p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erro}</p></div>}
      {!dados && !erro && <div className="vazio"><p>Verificando os documentos das empresas…</p></div>}
      {dados && itens.length === 0 && (
        <div className="vazio">
          <p className="vazio__titulo">Nenhum documento exigido.</p>
        </div>
      )}

      {temVeredito && faltam.length > 0 && (
        <ul className="docs-falta" aria-label={`O que falta: ${NATUREZA[natureza]}`}>
          {faltam.map(i => (
            <li key={`${i.entidade_id}-${i.chave ?? i.tipo_id}`}>
              <span className="docs-falta__item">{oQueFalta(i)}</span>
              <Link className="link"
                para={i.chave === "regularidade" ? { tela: "documentos-empresa", id: i.entidade_id, aba: "regularidade" }
                  : { tela: "documentos-empresa", id: i.entidade_id }}>
                {i.entidade ?? "Abrir em Documentos"}
              </Link>
            </li>
          ))}
        </ul>
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
      : bases.length === 0 ? "—" : bases.map(b => `${mesBR(b.mes)}${b.indice ? ` (${b.indice})` : ""}`).join(", ")],
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
            <dd>{!cad.dados ? (cad.erro ? "—" : "carregando…") : fiscais.length === 0 ? "—" : (
              <ul className="lista-simples">
                {fiscais.map(f => (
                  <li key={`${f.email}-${f.desde}`}>{f.nome || f.email || "—"}
                    {f.cargo ? `, ${f.cargo}` : ""}{f.portaria ? `, ${f.portaria}` : ""}</li>
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
