import { useEffect, useState } from "react";
import { api, mensagemDeErro } from "./api";
import { brl } from "./formato";
import Contador from "./Contador";
import IniciarMedicao from "./IniciarMedicao";
import Janela from "./Janela";
import LegendaCor from "./LegendaCor";
import Selo, { Glifo } from "./Selo";
import { Link } from "./Link";
import type { Usuario } from "./Login";
import { diaMes, PASSOS } from "./Passos";
import { mesPorExtenso, somarMes, type LinhaAnterior, type LinhaQuadro, type ObraResumo, type PassoQuadro, type ResumoMedicoes, type SigaNoQuadro } from "./resumoMedicoes";
import { nivelDias, tempoNoSetor } from "./siga";
import type { Situacao } from "./situacao";
import { fmtCompetencia, hojeLocal } from "./tempo";
import "./medicoes.css";
import Falha from "./Falha";

// Medições (#643, decisão do dono na revisão página a página de 10/11/2026): o QUADRO DO MÊS no lugar de "Iniciar medição"
// e "Em andamento". Uma linha por obra e uma coluna por passo do fluxo, na competência em trabalho (o mês anterior ao de
// hoje; o seletor mostra outra). O passo feito mostra a data, o da vez é o link para o passo na página da medição e a obra sem
// medição na competência tem o "Iniciar", que abre o formulário de sempre (a Nova planilha/carta, #653) já nessa competência. Abaixo, "Meses anteriores": as
// medições abertas de outras competências. Tudo vem de GET /api/medicoes/resumo (`medicoes.resumo`); a tela só desenha.

const traco = <span className="medicoes__traco">—</span>;

// O tempo do processo no setor, na situação da fundação que o mostra (cor e forma): movimentou hoje = feito; parado além
// do primeiro limiar de `nivelDias` = vence em breve; além do segundo = crítico. Dentro do prazo não tem situação.
const SITUACAO_DO_TEMPO: Record<"hoje" | "atencao" | "acao", Situacao> = { hoje: "feito", atencao: "breve", acao: "critico" };

/** #664: onde está o processo do SIGA da medição que está neste passo: sigla do setor e tempo no setor, com o texto da
 *  tela SIGA (o `NoSetor` de SigaPagina: "hoje" quando houve movimentação hoje; senão `tempoNoSetor`) e a situação do
 *  atraso de `nivelDias`. Sem data de entrada no setor, só a sigla. */
function PosicaoSiga({ siga }: { siga: SigaNoQuadro | null }) {
  if (!siga) return null;
  const nivel = siga.hoje > 0 ? "hoje" : nivelDias(siga.dias_uteis);
  const situacao = nivel ? SITUACAO_DO_TEMPO[nivel] : undefined;
  const tempo = siga.hoje > 0 ? "hoje" : siga.desde === null || siga.dias_uteis === null ? "—" : tempoNoSetor(siga, new Date());
  return (
    <span className="quadro__siga">
      <span className="sr-only">No SIGA: </span>
      <span className="quadro__siga-setor">{siga.setor}</span>
      {tempo !== "—" && <> <span className={`quadro__siga-tempo num${situacao ? ` quadro__siga-tempo--${situacao}` : ""}`}>{situacao && <Glifo situacao={situacao} />}{tempo}</span></>}
    </span>
  );
}

function CelulaPasso({ n, passo, linha }: { n: number; passo: PassoQuadro | undefined; linha: LinhaQuadro }) {
  const nome = PASSOS[n - 1];
  // o passo que a obra não tem fica vazio
  if (!passo) return <td className="quadro__passo quadro__passo--sem" data-rotulo={nome} />;
  if (passo.situacao === "feito") {
    const data = diaMes(passo.data);
    return (
      <td className="quadro__passo quadro__passo--feito" data-rotulo={nome}>
        <span className="quadro__feito">
          <Glifo situacao="feito" />
          {data ? <><span className="sr-only">Feito em </span><span className="num">{data}</span></> : "Feito"}
        </span>
      </td>
    );
  }
  if (passo.situacao === "atual" && passo.medicao_id !== null) {
    const medicao = linha.medicoes.find(m => m.id === passo.medicao_id);
    return (
      <td className="quadro__passo" data-rotulo={nome} aria-current="step">
        <Link className="link-selo quadro__atual" para={{ tela: "medicao", obra: linha.contrato_id, id: passo.medicao_id }}
          secao={`passo-${n}`}
          aria-label={`Abrir ${medicao?.titulo ?? "a medição"} de ${linha.obra}: ${nome}`}><Selo situacao="andamento">Atual</Selo></Link>
        <PosicaoSiga siga={passo.siga} />
      </td>
    );
  }
  return <td className="quadro__passo quadro__passo--futuro" data-rotulo={nome}>A fazer<PosicaoSiga siga={passo.siga} /></td>;
}

function Linha({ linha, podeIniciar, aoIniciar }: { linha: LinhaQuadro; podeIniciar: boolean; aoIniciar: () => void }) {
  return (
    <tr>
      <th scope="row" className="quadro__obra">
        <Link className="medicoes__obra" para={{ tela: "obra", id: linha.contrato_id, aba: "medicoes" }}>{linha.obra}</Link>
        {linha.medicoes.map(m => (
          <Link key={m.id} className="quadro__medicao" para={{ tela: "medicao", obra: linha.contrato_id, id: m.id }}>{m.titulo}</Link>
        ))}
      </th>
      {linha.medicoes.length === 0 ? (
        <td colSpan={PASSOS.length} className="quadro__iniciar" data-rotulo="Medição">
          {linha.iniciar && podeIniciar
            ? <button type="button" className="btn btn--pequeno" aria-label={`Iniciar a medição de ${linha.obra}`} onClick={aoIniciar}>Iniciar</button>
            : traco}
        </td>
      ) : PASSOS.map((_, i) => <CelulaPasso key={i} n={i + 1} passo={linha.passos.find(p => p.numero === i + 1)} linha={linha} />)}
      <td className="col-num dinheiro" data-rotulo="Pedido">{linha.pedido_centavos === null ? traco : brl(linha.pedido_centavos)}</td>
      <td className="col-num dinheiro" data-rotulo="Aprovado">{linha.aprovado_centavos === null ? traco : brl(linha.aprovado_centavos)}</td>
    </tr>
  );
}

function Anteriores({ linhas }: { linhas: LinhaAnterior[] }) {
  return (
    <section className="cartao medicoes__painel" aria-labelledby="anteriores-titulo">
      <div className="medicoes__painel-cab">
        <h2 id="anteriores-titulo">Meses anteriores</h2>
        {linhas.length > 0 && <Contador rotulo={linhas.length === 1 ? "1 medição" : `${linhas.length} medições`}>{linhas.length.toLocaleString("pt-BR")}</Contador>}
      </div>
      {linhas.length === 0 ? <p className="medicoes__vazio">Nenhuma medição aberta de meses anteriores.</p> : (
        <table className="tabela quadro__anteriores" aria-labelledby="anteriores-titulo">
          <thead>
            <tr>
              <th scope="col">Obra</th><th scope="col">Medição</th><th scope="col">Competência</th><th scope="col">Passo atual</th>
              <th scope="col"><span className="sr-only">Ação</span></th>
            </tr>
          </thead>
          <tbody>
            {linhas.map(l => (
              <tr key={l.medicao_id}>
                <td className="quadro__anterior-obra"><Link className="medicoes__obra" para={{ tela: "obra", id: l.contrato_id, aba: "medicoes" }}>{l.obra}</Link></td>
                <td data-rotulo="Medição">{l.titulo}</td>
                <td data-rotulo="Competência" className="num">{fmtCompetencia(l.competencia)}</td>
                <td data-rotulo="Passo atual"><Selo situacao="andamento">{l.passo.nome}</Selo></td>
                <td className="quadro__acao">
                  <Link className="btn btn--pequeno" para={{ tela: "medicao", obra: l.contrato_id, id: l.medicao_id }} secao={`passo-${l.passo.numero}`}
                    aria-label={`Abrir ${l.titulo} de ${l.obra}`}>Abrir</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

export default function MedicoesPagina({ usuario }: { usuario: Usuario }) {
  const [dados, setDados] = useState<ResumoMedicoes | null>(null);
  const [erro, setErro] = useState("");
  // a competência em trabalho: o mês anterior ao de hoje
  const [mes, setMes] = useState(() => somarMes(hojeLocal().slice(0, 7), -1));
  const [iniciando, setIniciando] = useState<ObraResumo | null>(null);
  const podeIniciar = usuario.perfil !== "diretoria";

  useEffect(() => {
    let vivo = true;
    api<ResumoMedicoes>(`/api/medicoes/resumo?mes=${mes}`)
      .then(d => { if (vivo) { setDados(d); setErro(""); } })
      .catch(e => { if (vivo) setErro(mensagemDeErro(e)); });
    return () => { vivo = false; };
  }, [mes]);

  if (!dados) {
    return erro
      ? <div className="pagina medicoes"><Falha>Não foi possível ler as medições: {erro} Recarregue a página para tentar de novo.</Falha></div>
      : <div className="pagina medicoes"><p className="medicoes__vazio medicoes__vazio--pagina" role="status">Carregando as medições…</p></div>;
  }
  // enquanto o mês escolhido não chega, o quadro na tela ainda é o do mês anterior: nada de iniciar nele
  const carregando = dados.mes !== mes;
  const trocarMes = (n: number) => { setIniciando(null); setMes(somarMes(mes, n)); };

  return (
    <div className="pagina medicoes">
      <div className="medicoes__cab">
        <div>
          <p className="medicoes__cab-rotulo">Competência</p>
          <div className="medicoes__troca">
            <h2 className="medicoes__mes" aria-live="polite">{mesPorExtenso(mes)}</h2>
            <div className="medicoes__botoes" role="group" aria-label="Trocar a competência">
              <button type="button" className="btn btn--pequeno" aria-label="Mês anterior" onClick={() => trocarMes(-1)}>‹</button>
              <button type="button" className="btn btn--pequeno" aria-label="Mês seguinte" onClick={() => trocarMes(1)}>›</button>
            </div>
          </div>
        </div>
        <LegendaCor />
      </div>
      {erro && <Falha>Não foi possível ler as medições: {erro}</Falha>}

      <section className="cartao medicoes__painel" aria-labelledby="quadro-titulo">
        <div className="medicoes__painel-cab">
          <h2 id="quadro-titulo">Quadro do mês</h2>
          {dados.quadro.length > 0 && (
            <Contador rotulo={dados.quadro.length === 1 ? "1 obra" : `${dados.quadro.length} obras`}>{dados.quadro.length.toLocaleString("pt-BR")}</Contador>
          )}
        </div>
        {dados.quadro.length === 0 ? <p className="medicoes__vazio">Nenhuma obra ativa.</p> : (
          <table className="tabela quadro__tabela" aria-labelledby="quadro-titulo" aria-busy={carregando || undefined}>
            <colgroup>
              <col className="quadro__c-obra" />{PASSOS.map(p => <col key={p} className="quadro__c-passo" />)}
              <col className="quadro__c-valor" /><col className="quadro__c-valor" />
            </colgroup>
            <thead>
              <tr>
                <th scope="col">Obra</th>{PASSOS.map(p => <th key={p} scope="col" className="quadro__th-passo">{p}</th>)}
                <th scope="col" className="col-num">Pedido</th><th scope="col" className="col-num">Aprovado</th>
              </tr>
            </thead>
            <tbody>
              {dados.quadro.map(l => (
                <Linha key={l.contrato_id} linha={l} podeIniciar={podeIniciar && !carregando}
                  aoIniciar={() => setIniciando(dados.obras.find(o => o.contrato_id === l.contrato_id) ?? null)} />
              ))}
            </tbody>
          </table>
        )}
      </section>

      <Anteriores linhas={dados.anteriores} />

      {iniciando && (
        <Janela titulo={`${iniciando.obra} · ${mesPorExtenso(mes)}`} aoFechar={() => setIniciando(null)}>
          <IniciarMedicao key={`${iniciando.contrato_id}-${mes}`} obra={iniciando} mes={mes} />
        </Janela>
      )}
    </div>
  );
}
