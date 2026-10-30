import { useEffect, useRef, useState } from "react";
import { api, mensagemDeErro } from "./api";
import { brl } from "./formato";
import CampoCompetencia from "./CampoCompetencia";
import { IconeAlerta, IconeBaixar, IconeCadeado, IconeMais } from "./icones";
import { EXCECOES, notasDivergentes, passoDe, resumoNotas, separarMedicoes, tituloMedicao } from "./medicao";
import { type Busca } from "./rota";
import { Link } from "./Link";
// competencia vem "AAAA-MM" (formato do CHECK da tabela); na tela le-se "MM/AAAA"
import { fmtCompetencia as competenciaBR, fmtDataPura as dataBR } from "./tempo";
import Rolagem from "./Rolagem";
import Selo from "./Selo";

// As medicoes da obra (NAVEGACAO.md › Obra › aba Medicoes): "Em andamento", com o proximo passo e o link para
// a secao dele na pagina da medicao, e "Anteriores" (recebidas, canceladas e desistidas), as 6 mais recentes
// e "ver todas", com a coluna Notas. Os atos (protocolar, notas, receber, cancelar) moram na pagina da medicao.

type Protocolo = {
  id: number; data: string; numero_oficio: string | null;
  numero_processo: string | null; origem: string; protocolo_id?: number | null;
};
// Nota vinculada a medicao: do RM (fase 5) ou lida do PDF (bloco 3), com o recebido derivado das
// baixas e a situacao da confirmacao PDF x RM.
type Nota = {
  nota_id: number; coligada: number; numero: string; serie: string | null; emissao: string | null;
  valor_centavos: number; recebido_centavos: number; recebido_em: string | null;
  origem: string; regra: string | null;
  origem_nota?: string; confirmacao?: string; documento_id?: number | null; valor_pdf_centavos?: number | null;
  conferencia?: { campo: string; espelho: number | string | null; nota: number | string | null; grau: string }[];
  justificativa?: string | null; leitura?: string | null;
};
type Frescor = { configurado: boolean; ultima_sincronizacao: string | null; ultimo_erro: string | null };
// Documento de faturamento do consorcio (NF/NFS-e/FATURA do SharePoint, migracao 017) e, do bloco 2, os
// documentos LOCAIS (espelho gerado, evidencia do orgao), que baixam pela API.
type Documento = {
  id: number; tipo_doc: string; nome: string; numero_nf: string | null;
  consorciada: string | null; municipio: string | null; weblink: string | null; fonte: string;
  arquivo?: string | null; tamanho?: number | null; espelho_id?: number | null;
};

export type Medicao = {
  id: number; numero: number; tipo: string; competencia: string; estado: string;
  valor_protocolado_centavos: number | null; valor_protocolado_origem: string | null;
  valor_atestado_centavos: number | null; valor_atestado_origem: string | null;
  atestado_em: string | null; nf_emitida_em: string | null; recebida_em: string | null;
  nota_emitida_em?: string | null;
  espelho_em?: string | null; espelho_origem?: string | null;
  congelada: number; protocolos: Protocolo[]; notas?: Nota[];
  documentos?: Documento[];
  final?: number; final_em?: string | null;       // bloco 7: medicao final poe o contrato em encerramento
};

// dinheiro mora em formato.ts (F-86: sinal de menos U+2212); continua exportado daqui para quem ja importa
export { brl };

export const ROTULO_ESTADO: Record<string, string> = {
  prevista: "Prevista", planilha_gerada: "Planilha/carta gerada", planilha_enviada: "Planilha/carta enviada",
  boletim_recebido: "Boletim recebido", espelho_gerado: "Espelho gerado", espelho_enviado: "Espelho enviado",
  nota_emitida: "Nota emitida", protocolada: "Protocolada", nf_emitida: "Lançada no RM",
  recebida: "Recebida", cancelada: "Cancelada", desistida: "Desistida",
};

export function Estado({ m }: { m: Medicao }) {
  const excecao = EXCECOES.includes(m.estado);
  return (
    <span className={`estado estado--${m.estado}${excecao ? " estado--excecao" : ""}`}>
      <span className="estado__ponto" aria-hidden="true" />
      {ROTULO_ESTADO[m.estado] ?? m.estado}
      {m.final === 1 && <Selo classe="selo--atencao">final</Selo>}
      {m.congelada === 1 && (
        <span className="cadeado">
          <IconeCadeado className="icone icone--p" titulo="Congelada" />
        </span>
      )}
    </span>
  );
}

type LinhaAndamento = { id: number; proximo_passo: string; desde: string };

// Quantas anteriores aparecem antes do "ver todas": as recentes respondem quase tudo; o resto e' historico.
const RECENTES = 6;

export default function Medicoes({ contratoId, busca, versao = 0 }: { contratoId: number; busca: Busca; versao?: number }) {
  const [itens, setItens] = useState<Medicao[]>([]);
  const [andamento, setAndamento] = useState<Map<number, LinhaAndamento>>(new Map());
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState("");
  // Situacao do RM (spec §6): so' a falha da ultima sincronizacao aparece, como selo. `null` = a leitura falhou
  // ou ainda nao chegou.
  const [frescor, setFrescor] = useState<Frescor | null>(null);
  // Geracao da leitura: resposta de outra obra (ou de antes de um recarregamento) nao escreve no estado.
  const geracao = useRef(0);
  // a obra cujas medicoes ja' estao na tela: so' ao trocar de obra a tela volta a "Carregando"; uma releitura
  // pedida por outro cartao (versao) troca a tabela no lugar, sem encolher a pagina sob o cartao que agiu
  const obraLida = useRef<number | null>(null);

  useEffect(() => {
    geracao.current += 1;
    const g = geracao.current;
    setErro("");
    if (obraLida.current !== contratoId) { setCarregando(true); obraLida.current = contratoId; }
    Promise.all([
      api<Medicao[]>(`/api/contratos/${contratoId}/medicoes`),
      api<LinhaAndamento[]>(`/api/medicoes/andamento?contrato_id=${contratoId}`).catch(() => []),
    ]).then(([lista, abertas]) => {
      if (g !== geracao.current) return;
      setItens(lista); setAndamento(new Map(abertas.map(a => [a.id, a])));
    }).catch(e => { if (g === geracao.current) setErro(mensagemDeErro(e)); })
      .finally(() => { if (g === geracao.current) setCarregando(false); });
    api<Frescor>("/api/rm/status").then(f => { if (g === geracao.current) setFrescor(f); }).catch(() => {});
    return () => { geracao.current += 1; };
  }, [contratoId, versao]);

  const { emAndamento, anteriores } = separarMedicoes(itens);
  const todas = busca.anteriores === "todas";
  const visiveis = todas ? anteriores : anteriores.slice(0, RECENTES);
  const rmFalhou = !!(frescor?.configurado && frescor.ultimo_erro);

  if (erro) return <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erro}</p>;
  if (carregando) return <section className="cartao"><div className="vazio"><p>Carregando medições…</p></div></section>;

  return (
    <>
      <section className="cartao" aria-labelledby="titulo-em-andamento" id="em-andamento">
        <div className="cartao__cabeca">
          <h2 className="cartao__titulo" id="titulo-em-andamento">Em andamento</h2>
          {rmFalhou && <Selo classe="selo--atencao">Sincronização com o RM falhou</Selo>}
        </div>
        {emAndamento.length === 0 ? (
          <div className="vazio vazio--curto"><p>Nenhuma medição aberta.</p></div>
        ) : (
          <Rolagem rotulo="Medições em andamento da obra">
            {/* grade comum com "Anteriores", logo abaixo (F-47): o dinheiro das duas tabelas cai na mesma coluna */}
            <table className="tabela tabela--grade">
              <colgroup>
                <col className="c-medicao-obra" /><col className="c-comp" /><col className="c-estado" />
                <col className="c-valor" /><col /><col className="c-marcas" />
              </colgroup>
              <thead>
                <tr>
                  <th scope="col">Medição</th><th scope="col">Competência</th><th scope="col">Estado</th>
                  <th scope="col" className="col-num">Valor</th><th scope="col">Próximo passo</th><th scope="col">Marcas</th>
                </tr>
              </thead>
              <tbody>
                {emAndamento.map((m, i) => {
                  const linha = andamento.get(m.id);
                  const passo = passoDe(linha?.proximo_passo);
                  const destino = { tela: "medicao" as const, obra: contratoId, id: m.id };
                  return (
                    <tr key={m.id} className={`linha${i % 2 === 1 ? " par" : ""}`}>
                      {/* a medicao abre na secao do proximo passo (NAVEGACAO.md: quem chega cai onde age) */}
                      <td className="forte"><Link className="link" para={destino} secao={passo?.secao || undefined}>{tituloMedicao(m)}</Link></td>
                      <td className="num">{competenciaBR(m.competencia)}</td>
                      <td><Estado m={m} /></td>
                      <td className="col-num dinheiro num">{brl(m.valor_protocolado_centavos)}</td>
                      <td>{passo ? passo.rotulo : "—"}</td>
                      <td>{notasDivergentes(m).length > 0
                        ? <Link className="link-selo" para={destino} secao="notas"><Selo classe="selo--acao">nota diverge</Selo></Link> : "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </Rolagem>
        )}
      </section>

      <section className="cartao" aria-labelledby="titulo-anteriores">
        <div className="cartao__cabeca">
          <h2 className="cartao__titulo" id="titulo-anteriores">Anteriores</h2>
          {/* sem medicao nenhuma nao ha' o que exportar (F-95) */}
          {itens.length > 0 && (
            <div className="cartao__acoes">
              <a className="btn btn--pequeno" href={`/api/contratos/${contratoId}/medicoes.csv`}>
                <IconeBaixar className="icone icone--p" /> Exportar CSV
              </a>
            </div>
          )}
        </div>
        {anteriores.length > 0 && (
          <Rolagem rotulo="Medições anteriores da obra" alta>
            <table className="tabela tabela--grade">
              <colgroup>
                <col className="c-medicao-obra" /><col className="c-comp" /><col className="c-estado" />
                <col className="c-valor" /><col /><col className="c-data" />
              </colgroup>
              <thead>
                <tr>
                  <th scope="col">Medição</th><th scope="col">Competência</th><th scope="col">Estado</th>
                  <th scope="col" className="col-num">Protocolado</th><th scope="col">Notas</th><th scope="col">Recebida em</th>
                </tr>
              </thead>
              <tbody>
                {visiveis.map((m, i) => (
                  <tr key={m.id} className={`linha${i % 2 === 1 ? " par" : ""}`}>
                    <td className="forte"><Link className="link" para={{ tela: "medicao", obra: contratoId, id: m.id }}>{tituloMedicao(m)}</Link></td>
                    <td className="num">{competenciaBR(m.competencia)}</td>
                    <td><Estado m={m} /></td>
                    <td className="col-num dinheiro num">{brl(m.valor_protocolado_centavos)}</td>
                    <td>{resumoNotas(m)}</td>
                    <td className="num">{m.recebida_em ? dataBR(m.recebida_em) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Rolagem>
        )}
        {anteriores.length > RECENTES && (
          <div className="cartao__rodape">
            {/* "ver todas" fica na URL: F5, Voltar e o link copiado mantem a lista aberta */}
            <Link className="btn btn--pequeno" para={{ tela: "obra", id: contratoId, aba: "medicoes" }}
              busca={todas ? undefined : { anteriores: "todas" }}>
              {todas ? `Ver só as ${RECENTES} mais recentes` : `Ver todas as ${anteriores.length}`}
            </Link>
          </div>
        )}
      </section>
    </>
  );
}

/** Nova medicao a mao, na obra do fluxo antigo (sem espelho pelo sistema): numero, tipo e competencia. A medicao
 *  nasce `prevista` e a pagina dela recebe as notas e o protocolo. */
export function NovaMedicaoManual({ contratoId, aoCriar }: { contratoId: number; aoCriar: () => void }) {
  const [novo, setNovo] = useState({ numero: "", tipo: "execucao", competencia: "" });
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState("");
  const [feito, setFeito] = useState<{ id: number; numero: number; tipo: string } | null>(null);

  async function criar(ev: React.FormEvent) {
    ev.preventDefault();
    setErro(""); setFeito(null); setSalvando(true);
    try {
      const r = await api<{ id: number }>(`/api/contratos/${contratoId}/medicoes`, {
        method: "POST",
        body: JSON.stringify({ numero: Number(novo.numero), tipo: novo.tipo, competencia: novo.competencia }),
      });
      setFeito({ id: r.id, numero: Number(novo.numero), tipo: novo.tipo });
      setNovo({ numero: "", tipo: "execucao", competencia: "" });
      aoCriar();
    } catch (e) { setErro(mensagemDeErro(e)); } finally { setSalvando(false); }
  }

  return (
    <form className="cartao__corpo pilha" onSubmit={criar} aria-label="Nova medição">
      <div className="form-inline">
        <div className="campo">
          <label className="campo__rotulo" htmlFor="nova-numero">Nº</label>
          <input id="nova-numero" name="numero" autoComplete="off" spellCheck={false} className="entrada--curta entrada--num num" required
            inputMode="numeric" pattern="[0-9]{1,3}" title="Número da medição (1 a 999)"
            value={novo.numero} onChange={e => setNovo({ ...novo, numero: e.target.value })} />
        </div>
        <div className="campo">
          <label className="campo__rotulo" htmlFor="nova-tipo">Tipo</label>
          <select id="nova-tipo" className="entrada--media" value={novo.tipo} onChange={e => setNovo({ ...novo, tipo: e.target.value })}>
            <option value="execucao">Execução</option>
            <option value="projeto">Projeto</option>
            <option value="reajuste">Reajuste</option>
          </select>
        </div>
        <div className="campo">
          <label className="campo__rotulo" htmlFor="nova-competencia">Competência</label>
          {/* digita-se MM/AAAA; o componente entrega "AAAA-MM", o formato que o CHECK da tabela exige */}
          <CampoCompetencia id="nova-competencia" className="entrada--media"
            value={novo.competencia} onChange={v => setNovo({ ...novo, competencia: v })} />
        </div>
        <button type="submit" className="btn btn--primario" disabled={salvando}>
          <IconeMais className="icone icone--p" />{salvando ? "Criando…" : "Nova medição"}
        </button>
      </div>
      {erro && <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erro}</p>}
      <p className={feito ? "notas__ok" : "sr-only"} role="status">
        {feito && <>Medição criada:{" "}
          <Link para={{ tela: "medicao", obra: contratoId, id: feito.id }}>{tituloMedicao(feito)}</Link>.</>}
      </p>
    </form>
  );
}
