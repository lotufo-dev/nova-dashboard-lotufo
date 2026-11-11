import { useEffect, useState } from "react";
import Alertas, { avisosDaObra, type Aviso } from "./Alertas";
import { api, mensagemDeErro } from "./api";
import ExecucaoContrato from "./ExecucaoContrato";
import FichaObra, { RitmoEPrazo, type Ficha } from "./FichaObra";
import { IconeAlerta, IconeVoltar } from "./icones";
import LegendaCor from "./LegendaCor";
import type { Usuario } from "./Login";
import IniciarProxima from "./IniciarProxima";
import Medicoes from "./Medicoes";
import { ContratoObra, DocumentosObra } from "./ObraAbas";
import Prazos from "./Prazos";
import Reajuste from "./Reajuste";
import { NovoProtocolo } from "./Protocolo";
import { ir, medicaoDaBusca, type AbaObra as Aba, type Busca, type Origem } from "./rota";
import { Link } from "./Link";
import { Abas, destinoDeHref, Migalhas, VoltarOrigem } from "./Topo";
import { baseDosValores } from "./formato";
import Selo from "./Selo";

// Bloco 6 (spec §10.3): cabecalho da obra, montado no servidor (`contratos.cabecalho`).
type Cabecalho = {
  id: number; obra: string; orgao: string; instrumento: string;
  percentual_lotufo_bp: number;
  // os inicios alimentam as linhas do tempo (#160); nulos quando o cadastro nao os tem
  execucao_inicio?: string | null; vigencia_inicio?: string | null;
  execucao_fim: string | null; dias_execucao: number | null; vigencia_fim: string | null; dias_vigencia: number | null;
  execucao_sem_prazo?: boolean;      // #662: execucao registrada vencida e aditivo posterior so' de vigencia
  status: StatusObra;
  sem_fluxo_medicao?: boolean;       // #660: `passos_medicao: []` no cadastro: a obra não inicia medição
};

export type StatusObra = "ativo" | "suspenso" | "em_encerramento" | "encerrado" | "rescindido";

export const STATUS: Record<StatusObra, { rotulo: string; classe: string }> = {
  // Ativo e' o normal da carteira: neutro. Verde e' "concluido/recebido" (DESIGN.md › Colors) e 19
  // selos verdes abafavam os poucos que pedem atencao.
  ativo: { rotulo: "Ativo", classe: "" }, suspenso: { rotulo: "Suspenso", classe: "selo--atencao" },
  em_encerramento: { rotulo: "Em encerramento", classe: "selo--atencao" },
  encerrado: { rotulo: "Encerrado", classe: "" }, rescindido: { rotulo: "Rescindido", classe: "" },
};

// A ORDEM da faixa mora aqui, e nao no JSX: e' a do NAVEGACAO.md (Medicoes · Prazos · Reajuste ·
// Documentos · Contrato). As notas moram na pagina de cada medicao e na coluna Notas.
const ABAS: { id: Aba; rotulo: string }[] = [
  { id: "medicoes", rotulo: "Medições" },
  { id: "prazos", rotulo: "Prazos" },
  { id: "reajuste", rotulo: "Reajuste" },
  { id: "documentos", rotulo: "Documentos" },
  { id: "contrato", rotulo: "Contrato" },
];

/** A base dos numeros do resumo, uma vez no cabecalho e so' em consorcio: "Consórcio, cota Lotufo 40%". */
function cotaDaObra(c: Cabecalho): string | null {
  const cota = baseDosValores(c.percentual_lotufo_bp);
  return cota ? `Consórcio, ${cota.replace("cota ", "cota Lotufo ")}` : null;
}

/** Avisos desta obra (NAVEGACAO.md › Obra): os tres mais graves, do mais atrasado ao menos, e "ver todos" leva a
 *  tela de Avisos filtrada pela obra. O servidor ja' filtra pelo perfil: na diretoria, sao os motivos do farol. */
function AvisosDaObra({ contratoId, itens }: { contratoId: number; itens: Aviso[] | null | undefined }) {
  const n = itens?.length ?? 0;
  return <Alertas itens={itens} ir={ir} titulo="Avisos desta obra" limite={3} lateral id="titulo-avisos-obra"
    vazio="Nenhum aviso."
    verTodos={{ para: { tela: "avisos" }, busca: { obra: String(contratoId) }, rotulo: `Ver todos os ${n} avisos da obra` }} />;
}

/* ------------------------------------------------------------------- pagina */

// Pagina unica da obra (#646): o resumo da ficha no alto, o cartao "Ritmo e prazo" (#655) e as abas. A aba vem da URL (rota.tsx): cada
// aba tem endereco proprio ("/obras/7/prazos") e e' um link de verdade, entao F5, o link do e-mail e o "abrir em
// nova aba" abrem a secao certa. "/obras/7" (aba "ficha" na rota) abre a mesma pagina com a primeira aba, Medicoes.
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
  // o resumo do alto (contrato, execucao, prazo, medicoes, vencimentos); a falha (null) vira "indisponível" nos cartoes
  const [ficha, setFicha] = useState<Ficha | null | undefined>(undefined);
  const abaAtiva: Exclude<Aba, "ficha"> = aba === "ficha" ? "medicoes" : aba;

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

  // O resumo e' lido de novo quando uma medicao nasce ou anda na aba Medicoes (`versaoMedicoes`), sem voltar ao
  // "Carregando": os numeros de antes ficam ate' os novos chegarem.
  useEffect(() => {
    let vivo = true;
    api<Ficha>(`/api/contratos/${contratoId}/ficha`)
      .then(d => { if (vivo) setFicha(d); })
      .catch(() => { if (vivo) setFicha(null); });
    return () => { vivo = false; };
  }, [contratoId, versaoMedicoes]);

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
    const rotulo = ABAS.find(a => a.id === aba)?.rotulo;
    document.title = `${c ? c.obra : "Obra"}${rotulo ? ` · ${rotulo}` : ""} · grupolotufo`;
  }, [c, aba]);

  // "Todas as obras" volta a lista; se foi dela que se chegou, com os filtros que ela tinha.
  const lista = origem?.tela === "obras" ? destinoDeHref(origem.href) : { para: { tela: "obras" as const }, busca: undefined };

  return (
    <>
      <header className="topbar topbar--detalhe">
        <div className="topbar__linha topbar__linha--quebra">
          <div className="topbar__trilha">
            <Link className="btn--voltar" para={lista.para} busca={lista.busca}>
              <IconeVoltar className="icone icone--p" /> Todas as obras
            </Link>
            <VoltarOrigem origem={origem} alemDe={["obras"]} />
            {/* Obras › contratante › obra. O contratante e' o orgao do contrato; o link dele abre a lista de Obras
                daquele orgao (a lista ja' filtra por ?orgao=) e nao a origem de onde se chegou. */}
            <Migalhas origem={origem} itens={[{ rotulo: "Obras", para: { tela: "obras" } },
              ...(c ? [{ rotulo: c.orgao, para: { tela: "obras" as const }, busca: { orgao: c.orgao }, fixa: true }] : []),
              { rotulo: c?.obra ?? "Obra" }]} />
          </div>
          <LegendaCor />
        </div>
        <div className="topbar__linha topbar__linha--quebra">
          <h1 className="topbar__titulo topbar__titulo--grande" title={c?.obra}>{c ? c.obra : "Obra"}</h1>
          {c && c.status !== "ativo" && <Selo classe={STATUS[c.status]?.classe ?? ""}>{STATUS[c.status]?.rotulo ?? c.status}</Selo>}
          {/* a base dos numeros do resumo entra uma vez, aqui: a cota da Lotufo, so' onde ela nao tem 100% */}
          {c && <p className="topbar__meta topbar__meta--obra">{[c.orgao, `Contrato ${c.instrumento}`, cotaDaObra(c)].filter(Boolean).join(" · ")}</p>}
        </div>
      </header>

      <div className="pagina ficha">
        {erro && <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erro}</p>}

        {!c && !erro && (
          <section className="cartao">
            <div className="vazio"><p>Carregando a obra…</p></div>
          </section>
        )}

        {/* So depois que o contrato existe: se o GET falhou (404/403), abrir as abas
            faria as filhas repetirem o mesmo erro em cascata. */}
        {c && (
          <>
          <FichaObra contratoId={contratoId} prazos={c} ficha={ficha} />
          <div className="obra-grade">
            <div className="obra-grade__principal">
              <div id="ritmo"><RitmoEPrazo ficha={ficha} /></div>

              <section className="cartao" id="secoes" aria-label="Seções da obra">
                <Abas rotulo="Seções da obra" atual={abaAtiva} classe="abas--obra"
                  itens={ABAS.map(a => ({ id: a.id, rotulo: a.rotulo, para: { tela: "obra" as const, id: contratoId, aba: a.id } }))} />

                <div className="painel-aba">
                  {abaAtiva === "medicoes" && (
                    <div className="pilha">
                      {/* a medicao nasce do espelho, na etapa 1 da pagina dela (ou, no fluxo antigo, a mao): aqui so' o atalho */}
                      {podeEditar && !c.sem_fluxo_medicao && <IniciarProxima contratoId={contratoId} versao={versaoMedicoes} inicial={medicaoDaBusca(busca)} aoCriar={() => setVersaoMedicoes(v => v + 1)} />}
                      <Medicoes contratoId={contratoId} busca={busca} versao={versaoMedicoes} />
                      {podeEditar && <NovoProtocolo contratoId={contratoId} versao={versaoMedicoes} aoMudar={() => setVersaoMedicoes(v => v + 1)} />}
                    </div>
                  )}
                  {/* um quadro por natureza (medicao, reajuste): o veredito de hoje e empresa x documento */}
                  {abaAtiva === "documentos" && <DocumentosObra contratoId={contratoId} />}
                  {abaAtiva === "reajuste" && <Reajuste contratoId={contratoId} podeEditar={podeEditar} />}
                  {abaAtiva === "prazos" && <Prazos contratoId={contratoId} podeEditar={podeEditar} />}
                  {abaAtiva === "contrato" && <ContratoObra contratoId={contratoId} />}
                </div>
              </section>
            </div>

            <aside className="obra-grade__lateral" aria-label="Avisos e prazos da obra">
              <div id="avisos-obra"><AvisosDaObra contratoId={contratoId} itens={avisos} /></div>
              <div id="execucao">
                <ExecucaoContrato execucaoInicio={c.execucao_inicio ?? null} execucaoFim={c.execucao_fim}
                  vigenciaInicio={c.vigencia_inicio ?? null} vigenciaFim={c.vigencia_fim} status={c.status}
                  execucaoSemPrazo={c.execucao_sem_prazo} />
              </div>
            </aside>
          </div>
          </>
        )}
      </div>
    </>
  );
}
