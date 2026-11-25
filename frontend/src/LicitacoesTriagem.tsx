import Contador from "./Contador";
import { contar } from "./formato";
import { fmtKm, useLicitacoes, type LinhaLicitacao, type Recomendada, type RespostaTriagem } from "./licitacoes";
import { Etapa, LeituraDoRadarLinha, Licitacao, Mudanca, Prazo, SemLeitura, Traco, Valor } from "./LicitacoesPecas";
import { Link } from "./Link";
import Rolagem from "./Rolagem";
import { Glifo } from "./Selo";
import type { Situacao } from "./situacao";
import { fmtDiaNoAno } from "./tempo";

// TRIAGEM (#908, docs/adr/0018): a pagina padrao da area Licitacoes ("/licitacoes"). Responde "o que pede decisao
// agora": as favoritas com prazo chegando ou mudanca recente e as recomendadas que ainda nao tem decisao. So' leitura
// nesta fatia: ninguem decide nada pela tela (favoritar, descartar e etapa chegam na fatia 2).
//
// Tudo vem pronto de GET /api/licitacoes/triagem: as contagens do alto, as duas listas ja' na ordem, os dias uteis ate'
// cada prazo e a situacao dele. A tela nao conta, nao ordena e nao compara data com limite.
//
// Os numeros do alto e os titulos dos blocos tem o mesmo rotulo quando sao a mesma conta ("Recomendadas a decidir"). O
// bloco das favoritas tem outro titulo que o numero "Favoritas": o numero conta todas as favoritas (e e' a porta para a
// pagina delas); o bloco lista so' as que pedem atencao.
//
// O motivo da recomendacao vai sob o objeto, e nao numa coluna: com ele em coluna as sete nao cabiam em 792 px (1024 com
// o menu aberto), e ele e' uma frase, nao um valor que se compara entre linhas.

/** Um numero da faixa: o rotulo (com o simbolo da situacao, so' quando ha' o que contar), o numero em tinta e o apoio. */
function Numero({ rotulo, situacao, apoio, children }: {
  rotulo: string; situacao?: Situacao; apoio?: React.ReactNode; children: React.ReactNode;
}) {
  return (
    <div className="lic-numero">
      <dt>{situacao && <Glifo situacao={situacao} />}{rotulo}</dt>
      <dd className="lic-numero__valor">{children}</dd>
      {apoio && <dd className="lic-numero__apoio">{apoio}</dd>}
    </div>
  );
}

/** O local da obra da recomendada: a cidade e a distancia que o radar mandou com a recomendacao (o municipio do orgao
 *  ou, na obra do Estado e da Uniao, o que o objeto cita). E' por ele que o servidor ordena, e nao pela cidade e pela
 *  distancia da licitacao. Sem cidade e sem distancia, o traco. */
function Local({ rec }: { rec: Recomendada }) {
  const km = fmtKm(rec.km);
  if (!rec.cidade && !km) return <Traco />;
  return <>{rec.cidade && <span className="lic-cidade">{rec.cidade}</span>}{km && <span className="num lic-km">{km}</span>}</>;
}

function FavoritasQuePedemAtencao({ linhas }: { linhas: LinhaLicitacao[] }) {
  return (
    <section className="cartao lic-bloco" aria-labelledby="lic-atencao">
      <header className="cartao__cabeca">
        <h2 className="cartao__titulo" id="lic-atencao">Favoritas que pedem atenção</h2>
        <Contador rotulo={contar(linhas.length, "favorita", "favoritas")}>{linhas.length.toLocaleString("pt-BR")}</Contador>
      </header>
      {linhas.length === 0 ? <div className="vazio vazio--curto"><p>Nenhuma favorita pede atenção.</p></div> : (
        <Rolagem rotulo="Favoritas que pedem atenção">
          <table className="tabela lic-tabela">
            <caption className="sr-only">Favoritas com prazo chegando ou mudança recente, do prazo mais próximo ao mais distante</caption>
            <thead>
              <tr><th scope="col">Licitação</th><th scope="col">Etapa</th><th scope="col">Próximo prazo</th><th scope="col">Mudança</th></tr>
            </thead>
            <tbody>
              {linhas.map(l => {
                const f = l.favorita;
                if (!f) return null;
                return (
                  <tr key={l.chave}>
                    <th scope="row" className="lic-c-licitacao"><Licitacao l={l} /></th>
                    <td data-rotulo="Etapa"><Etapa f={f} /></td>
                    <td data-rotulo="Próximo prazo">{f.proximo_prazo ? <span className="lic-prazo"><Prazo p={f.proximo_prazo} /></span> : <Traco />}</td>
                    <td data-rotulo="Mudança">{f.mudancas.length > 0 ? <Mudanca m={f.mudancas[0]} /> : <Traco />}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Rolagem>
      )}
    </section>
  );
}

function RecomendadasADecidir({ linhas }: { linhas: LinhaLicitacao[] }) {
  return (
    <section className="cartao lic-bloco" aria-labelledby="lic-recomendadas">
      <header className="cartao__cabeca">
        <h2 className="cartao__titulo" id="lic-recomendadas">Recomendadas a decidir</h2>
        <Contador rotulo={contar(linhas.length, "recomendada", "recomendadas")}>{linhas.length.toLocaleString("pt-BR")}</Contador>
      </header>
      {linhas.length === 0 ? <div className="vazio vazio--curto"><p>Nenhuma recomendada a decidir.</p></div> : (
        <Rolagem rotulo="Recomendadas a decidir">
          <table className="tabela lic-tabela lic-tabela--nota">
            <caption className="sr-only">Recomendadas ainda sem decisão, da nota maior para a menor</caption>
            <thead>
              <tr>
                <th scope="col" className="col-num">Nota</th><th scope="col">Licitação</th><th scope="col">Tipo de obra</th>
                <th scope="col">Local</th><th scope="col" className="col-num">Valor</th><th scope="col">Sessão</th>
              </tr>
            </thead>
            <tbody>
              {linhas.map(l => {
                const rec = l.recomendada;
                if (!rec) return null;
                return (
                  <tr key={l.chave}>
                    <td className="col-num lic-c-nota" data-rotulo="Nota">{rec.nota.toLocaleString("pt-BR")}</td>
                    <th scope="row" className="lic-c-licitacao">
                      <Licitacao l={l}>
                        {rec.motivo && <span className="lic-sub"><span className="sr-only">Motivo: </span>{rec.motivo}</span>}
                      </Licitacao>
                    </th>
                    <td data-rotulo="Tipo de obra">{l.tipo_obra || <Traco />}</td>
                    <td data-rotulo="Local"><Local rec={rec} /></td>
                    <td className="col-num lic-c-valor" data-rotulo="Valor"><Valor l={l} /></td>
                    <td data-rotulo="Sessão">
                      {l.data_sessao
                        ? <span className="lic-prazo"><Prazo p={{ data: l.data_sessao, hora: l.hora_sessao, dias_uteis: l.dias_uteis, passado: l.encerrada, hoje: l.sessao_hoje, situacao: l.prazo }} /></span>
                        : <Traco />}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Rolagem>
      )}
    </section>
  );
}

export default function LicitacoesTriagem() {
  const { dados, erro, tentar } = useLicitacoes<RespostaTriagem>("/api/licitacoes/triagem");
  if (!dados) return <SemLeitura erro={erro} tentar={tentar} />;

  const c = dados.contagens;
  const desde = c.novas_desde ? fmtDiaNoAno(c.novas_desde.desde) : null;
  return (
    <div className="pagina lic">
      <dl className="lic-numeros" aria-label="Licitações na triagem">
        <Numero rotulo="Recomendadas a decidir">{c.recomendadas.toLocaleString("pt-BR")}</Numero>
        {/* o numero e' a porta para a pagina das favoritas, e continua com cara de numero */}
        <Numero rotulo="Favoritas">
          <Link className="lic-porta" para={{ tela: "licitacoes-favoritas" }}>{c.favoritas.toLocaleString("pt-BR")}</Link>
        </Numero>
        <Numero rotulo="Novas"
          apoio={c.novas_desde && desde && <span className="num">+{c.novas_desde.quantas.toLocaleString("pt-BR")} desde {desde}</span>}>
          {c.novas.toLocaleString("pt-BR")}
        </Numero>
        {dados.leitura.fontes_com_problema > 0 && (
          <Numero rotulo="Fontes com problema" situacao="breve">{dados.leitura.fontes_com_problema.toLocaleString("pt-BR")}</Numero>
        )}
      </dl>
      {c.por_orgao.length > 0 && (
        <div className="lic-orgaos">
          <span className="lic-orgaos__rotulo" id="lic-por-orgao">Novas por órgão</span>
          <ul aria-labelledby="lic-por-orgao">
            {c.por_orgao.map(o => (
              <li key={o.orgao}>{o.orgao} <Contador rotulo={contar(o.novas, "nova", "novas")}>{o.novas.toLocaleString("pt-BR")}</Contador></li>
            ))}
          </ul>
        </div>
      )}
      <LeituraDoRadarLinha leitura={dados.leitura} />
      <FavoritasQuePedemAtencao linhas={dados.favoritas} />
      <RecomendadasADecidir linhas={dados.recomendadas} />
    </div>
  );
}
