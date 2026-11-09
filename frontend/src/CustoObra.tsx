import { useEffect, useState } from "react";
import { api, mensagemDeErro } from "./api";
import CaixaAviso from "./CaixaAviso";
import { brl, fmtQuantidade } from "./formato";
import { IconeAlerta } from "./icones";
import Rolagem from "./Rolagem";
import { fmtCompetencia, fmtData, fmtHora } from "./tempo";

// Aba Custo da Carteira (issue #491, piloto MT-388): por competencia, o medido por grupo da planilha ao lado do custo
// lancado no RM (apontado nas tarefas do grupo + rateado do centro), com o acumulado da obra. Decisao do Leo de
// 06/11/2026: "custo lançado no RM", nunca margem nem lucro. As regras moram em `app/custo_obra.py`.

type ObraCusto = { contrato_id: number; obra: string };
type LinhaGrupo = {
  nome: string; tipo: "grupo" | "fora" | "sem_grupo" | "ajuste" | "nao_lido"; medido_centavos: number | null;
  apontado_centavos: number; rateado_centavos: number; custo_centavos: number;
  /** null: medido do grupo desconhecido (mes sem leitura da planilha) ou linha so' de custo */
  diferenca_centavos: number | null;
};
type Totais = { medido_centavos: number; apontado_centavos: number; rateado_centavos: number; custo_centavos: number;
  diferenca_centavos: number };
type Linha = Totais & {
  competencia: string; medicoes: { id: number; numero: number; nome: string }[]; previsto_centavos: number | null;
  grupos: LinhaGrupo[];
};
/** #492: custo por unidade medida do item-chave do grupo; quantidade em texto decimal ("1234.5"), sem float. */
type ItemChave = {
  grupo: string; item: string; descricao: string | null; unidade: string; quantidade_acumulada: string | null;
  medicao: string | null; custo_centavos: number; custo_unitario_centavos: number | null;
  preco_unitario_centavos: number | null; diferenca_centavos: number | null;
  situacao: "ok" | "sem_medicao" | "sem_custo" | "ambiguo";
};
type Custo = {
  contrato_id: number; obra: string; grupos: string[]; linhas: Linha[];
  acumulado: Totais & { previsto_centavos: number };
  itens_chave?: ItemChave[];
  rm: { sincronizado_em: string | null; desatualizado: boolean };
};

const SITUACAO_CHAVE = {
  sem_medicao: "sem medição", sem_custo: "sem custo lançado", ambiguo: "item-chave ambíguo",
} as const;

function ItensChave({ c }: { c: Custo }) {
  const itens = c.itens_chave ?? [];
  if (itens.length === 0) return null;
  return (
    <>
      <h3 className="cartao__titulo">Custo por unidade medida</h3>
      <Rolagem rotulo="Custo por unidade dos itens-chave">
        <table className="tabela">
          <caption className="sr-only">Custo por unidade dos itens-chave, em {c.obra}</caption>
          <thead>
            <tr>
              <th scope="col">Grupo</th>
              <th scope="col">Item</th>
              <th scope="col">Unidade</th>
              <th scope="col" className="col-num">Quantidade medida</th>
              <th scope="col" className="col-num">Custo por unidade</th>
              <th scope="col" className="col-num">Preço do contrato</th>
              <th scope="col" className="col-num">Diferença</th>
            </tr>
          </thead>
          <tbody>
            {itens.map(k => (
              <tr key={k.grupo}>
                <th scope="row">{k.grupo}</th>
                <td>{k.descricao ? `${k.item} ${k.descricao}` : k.item}</td>
                <td>{k.unidade}</td>
                <td className="col-num num">{fmtQuantidade(k.quantidade_acumulada)}</td>
                <td className="col-num dinheiro num">
                  {k.situacao === "ok" ? brl(k.custo_unitario_centavos) : SITUACAO_CHAVE[k.situacao]}
                </td>
                <td className="col-num dinheiro num">{brl(k.preco_unitario_centavos)}</td>
                <td className="col-num dinheiro num">{brl(k.diferenca_centavos)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Rolagem>
    </>
  );
}

/** Linha de grupo sem nada no mes (sem medido e sem custo) nao entra: so' poluiria a competencia. */
function temValor(g: LinhaGrupo): boolean {
  return (g.medido_centavos !== null && g.medido_centavos !== 0) || g.custo_centavos !== 0;
}

function Valores({ v, previsto }: {
  v: Omit<Totais, "medido_centavos" | "diferenca_centavos"> & { medido_centavos: number | null; diferenca_centavos: number | null };
  previsto?: number | null;
}) {
  return (
    <>
      <td className="col-num dinheiro num">{brl(v.medido_centavos)}</td>
      <td className="col-num dinheiro num">{brl(v.apontado_centavos)}</td>
      <td className="col-num dinheiro num">{brl(v.rateado_centavos)}</td>
      <td className="col-num dinheiro num">{brl(v.custo_centavos)}</td>
      <td className="col-num dinheiro num">{brl(v.diferenca_centavos)}</td>
      <td className="col-num dinheiro num">{previsto === undefined ? "" : brl(previsto)}</td>
    </>
  );
}

function Tabela({ c }: { c: Custo }) {
  if (c.linhas.length === 0) return <div className="vazio vazio--curto"><p>Sem medição nem custo nesta obra.</p></div>;
  return (
    <Rolagem rotulo="Custo lançado no RM por competência" alta>
      <table className="tabela">
        <caption className="sr-only">Medido e custo lançado no RM por competência e grupo, em {c.obra}</caption>
        <thead>
          <tr>
            <th scope="col">Competência</th>
            <th scope="col" className="col-num">Medido</th>
            <th scope="col" className="col-num">Apontado</th>
            <th scope="col" className="col-num">Rateado</th>
            <th scope="col" className="col-num">Custo lançado</th>
            <th scope="col" className="col-num">Diferença</th>
            <th scope="col" className="col-num">Previsto</th>
          </tr>
        </thead>
        {c.linhas.map(l => (
          <tbody key={l.competencia}>
            <tr>
              <th scope="rowgroup">
                {fmtCompetencia(l.competencia)}
                {l.medicoes.map(m => <span key={m.id} className="custo__medicao"> {m.nome}</span>)}
              </th>
              <Valores v={l} previsto={l.previsto_centavos} />
            </tr>
            {l.grupos.filter(temValor).map(g => (
              <tr key={g.nome}>
                <th scope="row" className="custo__grupo">{g.nome}</th>
                <Valores v={g} />
              </tr>
            ))}
          </tbody>
        ))}
        <tfoot>
          <tr>
            <th scope="row">Acumulado</th>
            <Valores v={c.acumulado} previsto={c.acumulado.previsto_centavos} />
          </tr>
        </tfoot>
      </table>
    </Rolagem>
  );
}

export default function CustoObra() {
  const [obras, setObras] = useState<ObraCusto[] | null>(null);
  const [obra, setObra] = useState<number | null>(null);
  const [custo, setCusto] = useState<Custo | null>(null);
  const [erro, setErro] = useState("");            // a lista de obras nao veio: sem seletor
  const [erroObra, setErroObra] = useState<{ obra: number; texto: string } | null>(null);

  useEffect(() => {
    let vivo = true;
    api<ObraCusto[]>("/api/diretoria/custo")
      .then(d => { if (vivo) { setObras(d); setObra(d[0]?.contrato_id ?? null); } })
      .catch(e => { if (vivo) setErro(mensagemDeErro(e)); });
    return () => { vivo = false; };
  }, []);

  useEffect(() => {
    if (obra === null) return;
    let vivo = true;
    api<Custo>(`/api/diretoria/custo/${obra}`)
      .then(d => { if (vivo) { setCusto(d); setErroObra(null); } })
      .catch(e => { if (vivo) setErroObra({ obra, texto: mensagemDeErro(e) }); });
    return () => { vivo = false; };
  }, [obra]);

  if (erro) return <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erro}</p>;
  if (obras === null) return <section className="cartao"><div className="vazio"><p>Carregando…</p></div></section>;
  if (obras.length === 0) return <section className="cartao"><div className="vazio vazio--curto"><p>Nenhuma obra com cadastro de custo.</p></div></section>;
  // a obra trocada mostra "Carregando…" ate' a resposta dela chegar (a anterior nao fica na tela)
  const atual = custo !== null && custo.contrato_id === obra ? custo : null;
  const rm = atual?.rm;
  return (
    <section className="cartao" aria-labelledby="custo-titulo">
      <div className="cartao__cabeca">
        <h2 className="cartao__titulo" id="custo-titulo">Custo lançado no RM</h2>
        <div className="cartao__acoes">
          <div className="campo">
            <label className="campo__rotulo" htmlFor="custo-obra">Obra</label>
            <select id="custo-obra" value={obra ?? ""} onChange={e => { setErroObra(null); setObra(Number(e.target.value)); }}>
              {obras.map(o => <option key={o.contrato_id} value={o.contrato_id}>{o.obra}</option>)}
            </select>
          </div>
        </div>
      </div>
      {rm?.desatualizado && (
        <CaixaAviso nivel="atencao" role="status">
          {rm.sincronizado_em
            ? `RM sincronizado pela última vez em ${fmtData(rm.sincronizado_em)} ${fmtHora(rm.sincronizado_em)}`
            : "RM ainda não sincronizado"}
        </CaixaAviso>
      )}
      {erroObra !== null && erroObra.obra === obra
        ? <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erroObra.texto}</p>
        : atual === null ? <div className="vazio"><p>Carregando…</p></div> : <><Tabela c={atual} /><ItensChave c={atual} /></>}
    </section>
  );
}
