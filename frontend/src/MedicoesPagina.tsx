import { useEffect, useState } from "react";
import { api, mensagemDeErro } from "./api";
import { brl } from "./formato";
import { IconeAlerta, IconeCheck } from "./icones";
import IniciarMedicao from "./IniciarMedicao";
import Janela from "./Janela";
import LegendaCor from "./LegendaCor";
import { Link } from "./Link";
import type { Usuario } from "./Login";
import { diaMes, PASSOS } from "./Passos";
import { mesPorExtenso, somarMes, type LinhaAnterior, type LinhaQuadro, type ObraResumo, type PassoQuadro, type ResumoMedicoes, type SigaNoQuadro } from "./resumoMedicoes";
import { nivelDias, tempoNoSetor } from "./siga";
import { fmtCompetencia, hojeLocal } from "./tempo";
import "./iniciarMedicao.css";
import "./medicoes.css";

// Medições (#643, decisão do dono na revisão página a página de 10/11/2026): o QUADRO DO MÊS no lugar de "Iniciar medição"
// e "Em andamento". Uma linha por obra e uma coluna por passo do fluxo, na competência em trabalho (o mês anterior ao de
// hoje; o seletor mostra outra). O passo feito mostra a data, o da vez é o link para o passo na página da medição e a obra sem
// medição na competência tem o "Iniciar", que abre o formulário de sempre (a Nova planilha/carta, #653) já nessa competência. Abaixo, "Meses anteriores": as
// medições abertas de outras competências. Tudo vem de GET /api/medicoes/resumo (`medicoes.resumo`); a tela só desenha.

const traco = <span className="medicoes__traco">—</span>;

/** #664: onde está o processo do SIGA da medição que está neste passo: sigla do setor e tempo no setor, com o texto e a
 *  cor da tela SIGA (o `NoSetor` de SigaPagina: "hoje" quando houve movimentação hoje; senão `tempoNoSetor` com a cor de
 *  atraso de `nivelDias`). Sem data de entrada no setor, só a sigla. */
function PosicaoSiga({ siga }: { siga: SigaNoQuadro | null }) {
  if (!siga) return null;
  const nivel = siga.hoje > 0 ? "hoje" : nivelDias(siga.dias_uteis);
  const tempo = siga.hoje > 0 ? "hoje" : siga.desde === null || siga.dias_uteis === null ? "—" : tempoNoSetor(siga, new Date());
  return (
    <span className="quadro__siga">
      <span className="sr-only">No SIGA: </span>
      <span className="quadro__siga-setor">{siga.setor}</span>
      {tempo !== "—" && <> <span className={`quadro__siga-tempo num${nivel ? ` quadro__siga-tempo--${nivel}` : ""}`}>{tempo}</span></>}
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
      <td className="quadro__passo info--feito" data-rotulo={nome}>
        <IconeCheck className="icone quadro__check" />
        {data ? <><span className="sr-only">Feito em </span><span className="num">{data}</span></> : "Feito"}
      </td>
    );
  }
  if (passo.situacao === "atual" && passo.medicao_id !== null) {
    const medicao = linha.medicoes.find(m => m.id === passo.medicao_id);
    return (
      <td className="quadro__passo" data-rotulo={nome} aria-current="step">
        <Link className="pilula-info pilula-info--andamento quadro__atual" para={{ tela: "medicao", obra: linha.contrato_id, id: passo.medicao_id }}
          secao={`passo-${n}`}
          aria-label={`Abrir ${medicao?.titulo ?? "a medição"} de ${linha.obra}: ${nome}`}>Atual</Link>
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
    <section className="medicoes__quadro" aria-labelledby="anteriores-titulo">
      <div className="medicoes__quadro-cabeca"><h2 id="anteriores-titulo">Meses anteriores</h2></div>
      {linhas.length === 0 ? <div className="vazio vazio--curto"><p>Nenhuma medição aberta de meses anteriores.</p></div> : (
        <table className="medicoes__tabela quadro__anteriores" aria-labelledby="anteriores-titulo">
          <thead>
            <tr>
              <th scope="col">Obra</th><th scope="col">Medição</th><th scope="col">Competência</th><th scope="col">Passo atual</th>
              <th scope="col"><span className="sr-only">Ação</span></th>
            </tr>
          </thead>
          <tbody>
            {linhas.map(l => (
              <tr key={l.medicao_id}>
                <td data-rotulo="Obra"><Link className="medicoes__obra" para={{ tela: "obra", id: l.contrato_id, aba: "medicoes" }}>{l.obra}</Link></td>
                <td data-rotulo="Medição">{l.titulo}</td>
                <td data-rotulo="Competência" className="num">{fmtCompetencia(l.competencia)}</td>
                <td data-rotulo="Passo atual"><span className="pilula-info pilula-info--andamento">{l.passo.nome}</span></td>
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
      ? <div className="pagina"><p className="erro" role="alert"><IconeAlerta className="icone icone--p" />Não foi possível ler as medições: {erro} Recarregue a página para tentar de novo.</p></div>
      : <div className="pagina"><section className="cartao"><div className="vazio"><p>Carregando as medições…</p></div></section></div>;
  }
  // enquanto o mês escolhido não chega, o quadro na tela ainda é o do mês anterior: nada de iniciar nele
  const carregando = dados.mes !== mes;
  const trocarMes = (n: number) => { setIniciando(null); setMes(somarMes(mes, n)); };

  return (
    <div className="pagina medicoes">
      <section className="medicoes__quadro" aria-labelledby="quadro-titulo">
        <div className="medicoes__quadro-cabeca quadro__cabeca">
          <h2 id="quadro-titulo">Quadro do mês</h2>
          <div className="iniciar-med__mes">
            <button type="button" className="iniciar-med__mes-seta" aria-label="Mês anterior" onClick={() => trocarMes(-1)}>‹</button>
            <span className="iniciar-med__mes-nome" aria-live="polite">{mesPorExtenso(mes)}</span>
            <button type="button" className="iniciar-med__mes-seta" aria-label="Mês seguinte" onClick={() => trocarMes(1)}>›</button>
          </div>
          <LegendaCor />
        </div>
        {erro && <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />Não foi possível ler as medições: {erro}</p>}
        {dados.quadro.length === 0 ? <div className="vazio vazio--curto"><p>Nenhuma obra ativa.</p></div> : (
          <table className="quadro__tabela" aria-labelledby="quadro-titulo" aria-busy={carregando || undefined}>
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
