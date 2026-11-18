import { useMemo } from "react";
import { contar, fmtDias, brl } from "./formato";
import { Link } from "./Link";
import { contratantesPorContratado, criticosPorObra, mesesDoMedido, participacao, pctPiso, resumoDe, type ObraLista } from "./listaObras";
import MarcaEtapa from "./MarcaEtapa";
import { type Painel } from "./ObrasCarteira";
import { AReceber, EtiquetasDeAtencao, Executado, MedidoNoMes, NumerosDeObras } from "./ObrasPecas";
import { type Ir } from "./rota";

// "Por contratante" (#805), a entrada de Obras: os numeros da carteira e um bloco por contratante, do maior contratado
// para o menor. O bloco inteiro leva a' pagina do contratante (o link e' o nome; a area clicavel e' o bloco). Tudo na
// COTA da Lotufo: os numeros de cada bloco sao a soma das obras em andamento do contratante (`resumoDe`), e o prazo
// de pagamento e' o do servidor (`/api/diretoria`, docs/adr/0007).

export default function ObrasContratantes({ obras, painel, ir }: { obras: ObraLista[]; painel: Painel | null | undefined; ir: Ir }) {
  const criticos = useMemo(() => criticosPorObra(painel?.avisos ?? []), [painel]);
  const carteira = useMemo(() => resumoDe(obras, criticos), [obras, criticos]);
  const grupos = useMemo(() => contratantesPorContratado(obras), [obras]);
  if (obras.length === 0) return <section className="cartao"><div className="vazio vazio--curto"><p className="vazio__titulo">Nenhuma obra.</p></div></section>;
  const mes = carteira.medidoMes ? mesesDoMedido(carteira.medidoMes).curto : null;
  return (
    <>
      <NumerosDeObras r={carteira} rotulo="Números da carteira" />
      <ul className="obras-contratantes" aria-label="Contratantes">
        {grupos.map(g => {
          const r = resumoDe(g.obras, criticos);
          const prazo = painel?.prazo_pagamento?.[g.contratante];
          const parte = participacao(r.totais.contratado, carteira.totais.contratado);
          return (
            <li key={g.contratante} className={`obras-contratante${g.chave ? " obras-contratante--link" : ""}`}>
              <div className="obras-contratante__cabeca">
                <h2 className="obras-contratante__nome">
                  {g.chave ? <Link className="obras-contratante__link" para={{ tela: "contratante", chave: g.chave }} ir={ir}>{g.contratante}</Link> : g.contratante}
                </h2>
                <span className="obras-contratante__n num">{contar(r.obras, "obra", "obras")}</span>
              </div>
              <dl className="obras-contratante__numeros">
                <div>
                  <dt>Contratado</dt>
                  <dd><span className="obras-cel"><span className="num">{brl(r.totais.contratado)}</span>
                    {parte && <span className="obras-contratante__apoio num">{parte} da carteira</span>}</span></dd>
                </div>
                <div><dt>Executado</dt><dd><Executado pct={pctPiso(r.totais.medido, r.totais.contratado)} /></dd></div>
                <div><dt>Medido{mes ? ` em ${mes}` : " no mês"}</dt><dd><MedidoNoMes mm={r.medidoMes} /></dd></div>
                <div>
                  <dt><MarcaEtapa etapa="em_aberto">A receber</MarcaEtapa></dt>
                  <dd><AReceber centavos={r.totais.temReceber ? r.totais.aReceber : null} /></dd>
                </div>
                <div><dt>Prazo de pagamento</dt><dd className="num">{prazo === undefined ? "—" : fmtDias(prazo)}</dd></div>
              </dl>
              <EtiquetasDeAtencao r={r} />
            </li>
          );
        })}
      </ul>
    </>
  );
}
