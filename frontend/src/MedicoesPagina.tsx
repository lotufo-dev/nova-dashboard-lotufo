import { useEffect, useState } from "react";
import AbaAguardandoNota from "./AbaAguardandoNota";
import { api, mensagemDeErro } from "./api";
import AbaFaturamento from "./AbaFaturamento";
import AguardandoPagamento from "./AguardandoPagamento";
import { brl } from "./formato";
import { IconeAlerta, IconeMais, IconeSeta } from "./icones";
import IniciarMedicao from "./IniciarMedicao";
import type { Usuario } from "./Login";
import { passoDe } from "./medicao";
import NotasAEnviar from "./NotasAEnviar";
import Rolagem from "./Rolagem";
import { type AbaMedicoes, type Busca } from "./rota";
import { Link } from "./Link";
import { ABAS_MEDICOES, nivelParada, porContratante, rotuloSituacao, SITUACOES, textoParada, type LinhaResumo,
  type ObraResumo, type ResumoMedicoes, type Situacao, type SituacaoOuSem } from "./resumoMedicoes";
import "./medicoes.css";

// Pagina Medicoes com abas (09/10/2026, prototipo aprovado pelo Leo; substitui a fila em grupos pelo proximo passo).
// Resumo: o botao de iniciar, um cartao por situacao (leva a' aba) e "Todas as obras": as medicoes em andamento na
// ordem do ciclo e, embaixo, as obras sem medicao aberta, por contratante, fechadas. Tudo vem de GET
// /api/medicoes/resumo (`medicoes.resumo`); a tela so' desenha.
//
// As abas "Enviar nota" e "Aguardando pagamento" sao as telas de Notas que ja' existiam. "Sem medição aberta",
// "Enviar ao faturamento" sao PROVISORIAS (a tabela do Resumo filtrada) ate' o desenho proprio.

/** A pilula da situacao (cores do prototipo, medicoes.css). */
function Pilula({ s }: { s: SituacaoOuSem }) {
  return <span className={`sit-pilula sit-pilula--${s}`}>{rotuloSituacao(s)}</span>;
}

function Contratante({ nome, sub }: { nome: string; sub: string | null }) {
  return <>{nome}{sub && <span className="medicoes__sub">{sub}</span>}</>;
}

function Parada({ l }: { l: LinhaResumo }) {
  const nivel = nivelParada(l.dias, l.situacao);
  return <span className={nivel ? `medicoes__parada medicoes__parada--${nivel}` : "medicoes__parada"}>{textoParada(l.dias)}</span>;
}

// Mesma grade em todas as tabelas da pagina (a de cima e a de cada grupo): as colunas caem no mesmo x.
function Colunas() {
  return (
    <colgroup>
      <col className="medicoes__c-obra" /><col className="medicoes__c-contratante" /><col className="medicoes__c-medicao" />
      <col className="medicoes__c-situacao" /><col className="medicoes__c-valor" /><col className="medicoes__c-parada" />
    </colgroup>
  );
}

function LinhasAndamento({ linhas }: { linhas: LinhaResumo[] }) {
  return (
    <>
      {linhas.map((l, i) => {
        // segunda medicao aberta da mesma obra, logo abaixo: ligada a' de cima, sem repetir o nome em destaque
        const repete = i > 0 && linhas[i - 1].contrato_id === l.contrato_id;
        const passo = passoDe(l.proximo_passo);
        return (
          <tr key={`${l.situacao}-${l.medicao_id}`}>
            <td>{repete
              ? <span className="medicoes__obra-repete"><span aria-hidden="true">↳ </span>{l.obra}<span className="sr-only">, outra medição aberta</span></span>
              : <Link className="medicoes__obra" para={{ tela: "obra", id: l.contrato_id, aba: "medicoes" }}>{l.obra}</Link>}</td>
            <td><Contratante nome={l.contratante} sub={l.orgao_sub} /></td>
            {/* a medicao abre na etapa pendente (#etapa-N, a mesma de passoDe na pagina da medicao) */}
            <td><Link className="medicoes__medicao" para={{ tela: "medicao", obra: l.contrato_id, id: l.medicao_id }}
              secao={passo?.secao || undefined}>{l.titulo}</Link></td>
            <td><Pilula s={l.situacao} /></td>
            <td className="col-num dinheiro">{brl(l.valor_centavos)}</td>
            <td><Parada l={l} /></td>
          </tr>
        );
      })}
    </>
  );
}

/** Um contratante com as obras sem medicao aberta: fechado no Resumo (abre ao clicar), aberto na aba propria. */
function GrupoSem({ contratante, obras, aberto }: { contratante: string; obras: ObraResumo[]; aberto: boolean }) {
  return (
    <details className="medicoes__grupo" open={aberto || undefined}>
      <summary>
        <IconeSeta className="icone icone--p medicoes__seta" />
        <span className="medicoes__grupo-nome">{contratante}</span>
      </summary>
      <table className="medicoes__tabela">
        <caption className="sr-only">{`${contratante}: obras sem medição aberta`}</caption>
        <Colunas />
        <tbody>
          {obras.map(o => (
            <tr key={o.contrato_id}>
              <td><Link className="medicoes__obra" para={{ tela: "obra", id: o.contrato_id, aba: "medicoes" }}>{o.obra}</Link></td>
              <td><Contratante nome={o.contratante} sub={o.orgao_sub} /></td>
              <td className="medicoes__traco">—</td>
              <td><Pilula s="sem-medicao" /></td>
              <td className="col-num medicoes__traco">—</td>
              <td className="medicoes__traco">—</td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}

const CABECA = (
  <thead>
    <tr>
      <th scope="col">Obra</th><th scope="col">Contratante</th><th scope="col">Medição atual</th>
      <th scope="col">Situação</th><th scope="col" className="col-num">Valor</th><th scope="col">Parada há</th>
    </tr>
  </thead>
);

/** O cartao com a tabela: as linhas em andamento (com cabecalho) e, se houver, a faixa "Sem medição aberta" com os
 *  grupos por contratante. */
function Quadro({ id, titulo, linhas, sem, gruposAbertos, vazio }:
    { id: string; titulo: string; linhas: LinhaResumo[]; sem: ObraResumo[] | null;
      gruposAbertos: boolean; vazio: string }) {
  const grupos = sem ? porContratante(sem) : [];
  const nada = linhas.length === 0 && grupos.length === 0;
  return (
    <section className="medicoes__quadro" aria-labelledby={id}>
      <div className="medicoes__quadro-cabeca">
        <h2 id={id}>{titulo}</h2>
      </div>
      {nada ? <div className="vazio"><p className="vazio__titulo">{vazio}</p></div> : (
        <Rolagem rotulo={titulo}>
          {linhas.length > 0 && (
            <table className="medicoes__tabela">
              <Colunas />
              {CABECA}
              <tbody><LinhasAndamento linhas={linhas} /></tbody>
            </table>
          )}
          {grupos.length > 0 && (
            <>
              {/* na aba propria nao ha' linhas em andamento acima: a faixa so' repetiria o titulo do quadro */}
              {linhas.length > 0 && <div className="medicoes__faixa">Sem medição aberta</div>}
              {grupos.map(g => <GrupoSem key={g.contratante} contratante={g.contratante} obras={g.obras} aberto={gruposAbertos} />)}
            </>
          )}
        </Rolagem>
      )}
    </section>
  );
}

const VAZIO: Record<Exclude<Situacao, "aguardando-nota">, string> = {
  "planilha-gerada": "Nenhuma planilha/carta gerada à espera de envio.",
  "planilha-enviada": "Nenhuma planilha/carta enviada à espera do boletim.",
  "boletim-recebido": "Nenhum boletim recebido à espera do espelho.",
  faturamento: "Nenhuma medição para enviar ao faturamento.",
  "enviar-nota": "Nenhuma nota a enviar.",
  "aguardando-pagamento": "Nenhuma medição aguardando pagamento.",
};

function Resumo({ dados, podeIniciar, aoIniciar }: { dados: ResumoMedicoes; podeIniciar: boolean; aoIniciar: () => void }) {
  const sem = dados.obras.filter(o => !o.aberta);
  return (
    <>
      {podeIniciar && (
        <div className="medicoes__acoes">
          <button type="button" className="btn btn--primario medicoes__iniciar" onClick={aoIniciar}>
            <IconeMais className="icone" />Iniciar processo de medição
          </button>
        </div>
      )}
      <nav className="medicoes__cartoes" aria-label="Medições por situação">
        {SITUACOES.map(s => {
          const n = dados.contagens[s.id] ?? 0;
          return (
            <Link key={s.id} className="medicoes__cartao" para={{ tela: "medicoes", aba: s.id }}>
              <span className="medicoes__cartao-rotulo"><i className={`sit-ponto sit-ponto--${s.id}`} aria-hidden="true" />{s.rotulo}</span>
              <span className={`medicoes__cartao-n${n === 0 ? " medicoes__cartao-n--zero" : ""}`}>{n}</span>
            </Link>
          );
        })}
      </nav>
      <Quadro id="medicoes-todas" titulo="Todas as obras" gruposAbertos={false} linhas={dados.linhas} sem={sem}
        vazio="Nenhuma obra ativa." />
    </>
  );
}

export default function MedicoesPagina({ aba, busca, usuario }: { aba: AbaMedicoes; busca: Busca; usuario: Usuario }) {
  const [dados, setDados] = useState<ResumoMedicoes | null>(null);
  const [erro, setErro] = useState("");
  const [iniciando, setIniciando] = useState(false);
  const podeIniciar = usuario.perfil !== "diretoria";
  const podeEditar = usuario.perfil === "engenharia" || usuario.perfil === "admin";   // B-09 (10/10/2026)

  // relido a cada troca de aba: o envio de uma nota (aba Enviar nota) muda as contagens das outras
  useEffect(() => {
    let vivo = true;
    api<ResumoMedicoes>("/api/medicoes/resumo")
      .then(d => { if (vivo) { setDados(d); setErro(""); } })
      .catch(e => { if (vivo) setErro(mensagemDeErro(e)); });
    return () => { vivo = false; };
  }, [aba]);

  let conteudo: React.ReactNode;
  if (aba === "enviar-nota") {
    conteudo = <NotasAEnviar busca={busca} podeEditar={podeEditar} />;
  } else if (aba === "aguardando-pagamento") {
    conteudo = <AguardandoPagamento podeEditar={podeEditar} />;
  } else if (!dados) {
    conteudo = erro
      ? <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />Não foi possível ler as medições: {erro} Recarregue a página para tentar de novo.</p>
      : <section className="cartao"><div className="vazio"><p>Carregando as medições…</p></div></section>;
  } else if (aba === "resumo") {
    conteudo = <Resumo dados={dados} podeIniciar={podeIniciar} aoIniciar={() => setIniciando(true)} />;
  } else if (aba === "sem-medicao") {
    const sem = dados.obras.filter(o => !o.aberta);
    conteudo = <Quadro id="medicoes-aba" titulo="Sem medição aberta" linhas={[]}
      sem={sem} gruposAbertos vazio="Nenhuma obra sem medição aberta." />;
  } else if (aba === "faturamento") {
    conteudo = <AbaFaturamento linhas={dados.linhas.filter(l => l.situacao === "faturamento")} podeIniciar={podeIniciar}
      aoIniciar={() => setIniciando(true)} />;
  } else if (aba === "aguardando-nota") {
    conteudo = <AbaAguardandoNota linhas={dados.linhas.filter(l => l.situacao === aba)} podeIniciar={podeIniciar}
      aoIniciar={() => setIniciando(true)} />;
  } else {
    const linhas = dados.linhas.filter(l => l.situacao === aba);
    conteudo = <Quadro id="medicoes-aba" titulo={rotuloSituacao(aba)}
      linhas={linhas} sem={null} gruposAbertos={false} vazio={VAZIO[aba]} />;
  }

  return (
    <>
      {/* Faixa de abas logo abaixo da barra superior: links (cada aba tem endereco), contagem em pilula. No celular
          rola na horizontal dentro dela, sem rolar a pagina. */}
      <nav className="abas-secao" aria-label="Seções de Medições">
        {ABAS_MEDICOES.map(a => (
          <Link key={a.id} className="abas-secao__aba" para={{ tela: "medicoes", aba: a.id }}
            aria-current={a.id === aba ? "page" : undefined}>
            {a.rotulo}
            {a.id !== "resumo" && dados && <span className="abas-secao__n">{dados.contagens[a.id as SituacaoOuSem] ?? 0}</span>}
          </Link>
        ))}
      </nav>
      <div className="pagina medicoes">{conteudo}</div>
      {iniciando && dados && <IniciarMedicao obras={dados.obras} aoFechar={() => setIniciando(false)} />}
    </>
  );
}
