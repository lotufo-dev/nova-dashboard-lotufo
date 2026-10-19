import { useEffect, useState } from "react";
import Alertas, { avisosDaObra, type Aviso } from "./Alertas";
import { api, mensagemDeErro } from "./api";
import CurvaS from "./CurvaS";
import ExecucaoContrato from "./ExecucaoContrato";
import { IconeAlerta } from "./icones";
import type { Usuario } from "./Login";
import IniciarProxima from "./IniciarProxima";
import Medicoes, { brl } from "./Medicoes";
import { ContratoObra, DocumentosObra } from "./ObraAbas";
import type { PontoDaCurva } from "./obra";
import Prazos from "./Prazos";
import Reajuste from "./Reajuste";
import { NovoProtocolo } from "./Protocolo";
import { ir, type AbaObra as Aba, type Busca, type Origem } from "./rota";
import { Link } from "./Link";
import { Abas, Migalhas, VoltarOrigem } from "./Topo";
import { fmtPercentual, baseDosValores } from "./formato";
import Selo from "./Selo";

// Bloco 6 (spec §10.3): cabecalho da obra, montado no servidor (`contratos.cabecalho`).
type Cabecalho = {
  id: number; obra: string; orgao: string; instrumento: string;
  valor_vigente_centavos: number; cota_vigente_centavos: number | null; percentual_lotufo_bp: number;
  // os inicios alimentam as linhas do tempo (#160); nulos quando o cadastro nao os tem
  execucao_inicio?: string | null; vigencia_inicio?: string | null;
  execucao_fim: string | null; dias_execucao: number | null; vigencia_fim: string | null; dias_vigencia: number | null;
  status: StatusObra;
  // A3: em valor cheio; o a receber e' nulo enquanto o total nao esta' liberado (a conciliar)
  faturado_centavos?: number; a_receber_centavos?: number | null;
};
// O saldo da obra e' o do cronograma (NAVEGACAO.md, principio 7): vigente − medido de execucao atestado.
type Saldo = { vigente_centavos: number; atestado_execucao_centavos: number; saldo_centavos: number; formula: string };

export type StatusObra = "ativo" | "suspenso" | "em_encerramento" | "encerrado" | "rescindido";

export const STATUS: Record<StatusObra, { rotulo: string; classe: string }> = {
  // Ativo e' o normal da carteira: neutro. Verde e' "concluido/recebido" (DESIGN.md › Colors) e 19
  // selos verdes abafavam os poucos que pedem atencao.
  ativo: { rotulo: "Ativo", classe: "" }, suspenso: { rotulo: "Suspenso", classe: "selo--atencao" },
  em_encerramento: { rotulo: "Em encerramento", classe: "selo--atencao" },
  encerrado: { rotulo: "Encerrado", classe: "" }, rescindido: { rotulo: "Rescindido", classe: "" },
};

function percentual(bp: number): string {
  return fmtPercentual(bp / 10000);
}

// A ORDEM da faixa mora aqui, e nao no JSX: e' a do NAVEGACAO.md (Medicoes · Prazos · Reajuste ·
// Documentos · Contrato). As notas moram na pagina de cada medicao e na coluna Notas.
const ABAS: { id: Aba; rotulo: string }[] = [
  { id: "medicoes", rotulo: "Medições" },
  { id: "prazos", rotulo: "Prazos" },
  { id: "reajuste", rotulo: "Reajuste" },
  { id: "documentos", rotulo: "Documentos" },
  { id: "contrato", rotulo: "Contrato" },
];

/** Os cinco numeros da obra (desenho de 16/10/2026), sempre no alto, qualquer que seja a aba: quanto vale, quanto
 *  ja' se mediu, quanto se faturou, quanto os orgaos devem e o saldo do cronograma. Valores cheios, com a cota ao
 *  lado quando a Lotufo nao tem 100%. O que vem da curva (medido e saldo) mostra "indisponivel" quando a leitura
 *  falha: a falha nao e' o mesmo que valor nulo. */
function Indicadores({ c, contratoId, saldo, falhou }: { c: Cabecalho; contratoId: number; saldo: Saldo | null; falhou: boolean }) {
  const cota = c.percentual_lotufo_bp !== 10000;
  const indisponivel = falhou && !saldo;
  const medido = saldo ? brl(saldo.atestado_execucao_centavos) : indisponivel ? "indisponível" : "—";
  const pct = saldo && c.valor_vigente_centavos > 0
    ? fmtPercentual(saldo.atestado_execucao_centavos / c.valor_vigente_centavos, 1) : null;
  return (
    <ul className="indicadores" id="indicadores" aria-label="Números da obra">
      <li className="cartao indicador"><span className="indicador__rotulo">Valor vigente</span>
        <span className="indicador__valor">{brl(c.valor_vigente_centavos)}</span>
        {cota && <span className="campo__nota">cota da Lotufo ({percentual(c.percentual_lotufo_bp)}): <span className="dinheiro num">{brl(c.cota_vigente_centavos)}</span></span>}</li>
      <li className="cartao indicador"><span className="indicador__rotulo">Medido (execução)</span>
        <span className={`indicador__valor${indisponivel ? " indicador__valor--indisponivel" : ""}`}>{medido}</span>
        {pct && <span className="campo__nota">{pct} do valor vigente</span>}</li>
      <li className="cartao indicador"><span className="indicador__rotulo">Faturado</span>
        <span className="indicador__valor">{c.faturado_centavos === undefined ? "—" : brl(c.faturado_centavos)}</span></li>
      <li className="cartao indicador"><span className="indicador__rotulo">A receber</span>
        <span className="indicador__valor">{c.a_receber_centavos === undefined || c.a_receber_centavos === null ? "—" : brl(c.a_receber_centavos)}</span>
        {c.a_receber_centavos === null && <span className="campo__nota">a conciliar</span>}</li>
      {/* os mesmos rotulos do cronograma, o lar deles: la' mora a formula do saldo */}
      <li className="cartao indicador">
        <Link className="indicador__rotulo" para={{ tela: "obra", id: contratoId, aba: "contrato" }} secao="cronograma">Saldo do cronograma</Link>
        <span className={`indicador__valor${indisponivel ? " indicador__valor--indisponivel" : saldo && saldo.saldo_centavos < 0 ? " negativo" : ""}`}>
          {saldo ? brl(saldo.saldo_centavos) : indisponivel ? "indisponível" : "—"}</span>
        {indisponivel ? <span className="campo__nota" role="alert">não foi possível ler o cronograma agora</span>
          : <span className="campo__nota">valor vigente − medido</span>}</li>
    </ul>
  );
}

/** Avisos desta obra (NAVEGACAO.md › Obra): os tres mais graves, do mais atrasado ao menos, e "ver todos" leva a
 *  tela de Avisos filtrada pela obra. O servidor ja' filtra pelo perfil: na diretoria, sao os motivos do farol. */
function AvisosDaObra({ contratoId, itens }: { contratoId: number; itens: Aviso[] | null | undefined }) {
  const n = itens?.length ?? 0;
  return <Alertas itens={itens} ir={ir} titulo="Avisos desta obra" limite={3} lateral id="titulo-avisos-obra"
    vazio="Nenhum aviso nesta obra."
    verTodos={{ para: { tela: "avisos" }, busca: { obra: String(contratoId) }, rotulo: `Ver todos os ${n} avisos da obra` }} />;
}

/* ------------------------------------------------------------------- pagina */

// A aba vem da URL (rota.tsx): cada aba tem endereco proprio ("/obras/7/prazos") e e' um link de
// verdade, entao F5, o link do e-mail e o "abrir em nova aba" abrem a secao certa.
export default function ContratoPagina({ contratoId, usuario, aba, origem, busca }:
    { contratoId: number; usuario: Usuario; aba: Aba; origem: Origem | null; busca: Busca }) {
  const [c, setC] = useState<Cabecalho | null>(null);
  const [erro, setErro] = useState("");
  const podeEditar = usuario.perfil === "engenharia" || usuario.perfil === "admin";
  // Bloco 2: o espelho cria/avanca medicoes por fora da tela de medicoes. Em vez de um
  // canal entre os cartoes, gerar/criar incrementa esta chave e a lista de medicoes e o
  // cartao de novo protocolo leem de novo.
  const [versaoMedicoes, setVersaoMedicoes] = useState(0);
  // os avisos da obra: o cartao da lateral, em qualquer aba
  const [avisos, setAvisos] = useState<Aviso[] | null | undefined>(undefined);
  // a curva (previsto x medido) e o saldo: os indicadores e a curva S leem a mesma resposta.
  // N04-12: a falha da leitura (null) nao e' o mesmo que obra sem curva.
  const [curva, setCurva] = useState<{ pontos: PontoDaCurva[]; saldo: Saldo } | null | undefined>(undefined);

  useEffect(() => {
    // `vigente` corta o setState de uma resposta que chega depois de a tela ja ter
    // trocado de contrato (ou saido). Sem ele, um A lento respondendo depois de um B
    // rapido montava uma pagina HIBRIDA: cabecalho, objeto e valor do contrato A com
    // as abas de medicoes/cronograma do B — e nada na tela denunciava a mistura.
    let vigente = true;
    setC(null); setErro("");
    api<Cabecalho>(`/api/contratos/${contratoId}/cabecalho`)
      .then(d => { if (vigente) setC(d); })
      .catch(e => { if (vigente) setErro(mensagemDeErro(e)); });
    return () => { vigente = false; };
  }, [contratoId]);

  useEffect(() => {
    let vivo = true;
    setCurva(undefined);
    api<{ curva?: PontoDaCurva[]; saldo: Saldo }>(`/api/contratos/${contratoId}/curva`)
      .then(d => { if (vivo) setCurva({ pontos: d.curva ?? [], saldo: d.saldo }); })
      .catch(() => { if (vivo) setCurva(null); });
    return () => { vivo = false; };
  }, [contratoId]);

  useEffect(() => {
    let vivo = true;
    setAvisos(undefined);
    api<{ avisos: Aviso[] }>("/api/inicio")
      .then(d => { if (vivo) setAvisos(avisosDaObra(d.avisos, contratoId)); })
      .catch(() => { if (vivo) setAvisos(null); });
    return () => { vivo = false; };
  }, [contratoId]);

  // Titulo da aba do navegador: a obra e a aba, como o historico e o favorito precisam para distinguir.
  useEffect(() => {
    const rotulo = ABAS.find(a => a.id === aba)?.rotulo ?? "";
    document.title = `${c ? c.obra : "Obra"} · ${rotulo} · grupolotufo`;
  }, [c, aba]);

  return (
    <>
      <header className="topbar topbar--detalhe">
        <div className="topbar__trilha">
          <VoltarOrigem origem={origem} alemDe={["obras"]} />
          {/* Obras › contratante › obra. O contratante e' o orgao do contrato; o link dele abre a lista de Obras
              daquele orgao (a lista ja' filtra por ?orgao=) e nao a origem de onde se chegou. */}
          <Migalhas origem={origem} itens={[{ rotulo: "Obras", para: { tela: "obras" } },
            ...(c ? [{ rotulo: c.orgao, para: { tela: "obras" as const }, busca: { orgao: c.orgao }, fixa: true }] : []),
            { rotulo: c?.obra ?? "Obra" }]} />
        </div>
        <div className="topbar__linha topbar__linha--quebra">
          <h1 className="topbar__titulo topbar__titulo--grande" title={c?.obra}>{c ? c.obra : "Obra"}</h1>
          {c && <Selo classe={STATUS[c.status]?.classe ?? ""}>{STATUS[c.status]?.rotulo ?? c.status}</Selo>}
        </div>
        {/* principio 7: a pagina da obra e' toda em valor cheio; a cota vai ao lado onde a Lotufo nao tem 100% */}
        {c && <p className="topbar__meta topbar__meta--obra">{c.orgao} · Contrato {c.instrumento} · {baseDosValores(c.percentual_lotufo_bp)}</p>}
      </header>

      <div className="pagina">
        {erro && <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erro}</p>}

        {!c && !erro && (
          <section className="cartao">
            <div className="vazio"><p>Carregando a obra…</p></div>
          </section>
        )}

        {/* So depois que o contrato existe: se o GET falhou (404/403), abrir as abas
            faria as filhas repetirem o mesmo erro em cascata. */}
        {c && (
          <div className="obra-grade">
            <div className="obra-grade__principal">
              <Indicadores c={c} contratoId={contratoId} saldo={curva ? curva.saldo : null} falhou={curva === null} />

              <div id="curva"><CurvaS pontos={curva === undefined ? undefined : curva ? curva.pontos : null} contratoId={contratoId} /></div>

              <section className="cartao" id="secoes" aria-label="Seções da obra">
                <Abas rotulo="Seções da obra" atual={aba} classe="abas--obra"
                  itens={ABAS.map(a => ({ id: a.id, rotulo: a.rotulo, para: { tela: "obra" as const, id: contratoId, aba: a.id } }))} />

                <div className="painel-aba">
                  {aba === "medicoes" && (
                    <div className="pilha">
                      {/* a medicao nasce do espelho, na etapa 1 da pagina dela (ou, no fluxo antigo, a mao): aqui so' o atalho */}
                      {podeEditar && <IniciarProxima contratoId={contratoId} versao={versaoMedicoes} aoCriar={() => setVersaoMedicoes(v => v + 1)} />}
                      <Medicoes contratoId={contratoId} busca={busca} versao={versaoMedicoes} />
                      {podeEditar && <NovoProtocolo contratoId={contratoId} versao={versaoMedicoes} aoMudar={() => setVersaoMedicoes(v => v + 1)} />}
                    </div>
                  )}
                  {/* um quadro por natureza (medicao, reajuste): o veredito de hoje e empresa x documento */}
                  {aba === "documentos" && <DocumentosObra contratoId={contratoId} />}
                  {aba === "reajuste" && <Reajuste contratoId={contratoId} podeEditar={podeEditar} />}
                  {aba === "prazos" && <Prazos contratoId={contratoId} podeEditar={podeEditar} />}
                  {aba === "contrato" && <ContratoObra contratoId={contratoId} />}
                </div>
              </section>
            </div>

            <aside className="obra-grade__lateral" aria-label="Avisos e prazos da obra">
              <div id="avisos-obra"><AvisosDaObra contratoId={contratoId} itens={avisos} /></div>
              <div id="execucao">
                <ExecucaoContrato execucaoInicio={c.execucao_inicio ?? null} execucaoFim={c.execucao_fim}
                  vigenciaInicio={c.vigencia_inicio ?? null} vigenciaFim={c.vigencia_fim} status={c.status} />
              </div>
            </aside>
          </div>
        )}
      </div>
    </>
  );
}
