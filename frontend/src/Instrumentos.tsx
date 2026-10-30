import { useEffect, useState } from "react";
import { api, mensagemDeErro } from "./api";
import { IconeAlerta, IconeCadeado } from "./icones";
import { brl } from "./Medicoes";
import { instrumentosDaObra, type AditivoApi, type InstrumentoCadastro, type InstrumentoPrazo } from "./obra";
import { Link } from "./Link";
import { fmtCompetencia as mesBR, fmtDataPura } from "./tempo";
import { fmtPercentual } from "./formato";
import Rolagem from "./Rolagem";
import Selo from "./Selo";

// Contrato › Instrumentos (NAVEGACAO.md › Obra): aditivos (termos e apostilamentos de prazo, valor, escopo e
// mistos), apostilamentos de reajuste, paralisacoes, reinicios e endossos numa lista so', do mais novo ao mais
// antigo, so' leitura (bloco 9). Instrumento entra pelo cadastro versionado (`cadastro/*.yaml` + `python -m
// app.cli cadastro aplicar`); instrumento aplicado nao se altera.

const ROTULO_TIPO: Record<string, string> = { prazo: "de prazo", valor: "de valor", escopo: "de escopo", misto: "misto" };
const TIPO_CADASTRO: Record<string, string> = { paralisacao: "Paralisação", reinicio: "Reinício",
  endosso_garantia: "Endosso do seguro-garantia", apostilamento_reajuste: "Apostilamento de reajuste" };

function data(iso: string | null | undefined): string {
  return iso ? fmtDataPura(iso.slice(0, 10)) : "—";
}

function deltaBR(centavos: number): string {
  return (centavos > 0 ? "+" : centavos < 0 ? "−" : "") + brl(Math.abs(centavos));
}

function Situacao({ a }: { a: AditivoApi }) {
  if (a.cancelado_em) return <Selo>Cancelado</Selo>;
  if (a.status === "assinado") return (
    <Selo classe="selo--ok"
      sufixo={<IconeCadeado className="icone icone--p" titulo="Congelado" />}>
      Assinado
    </Selo>
  );
  return <Selo classe="selo--atencao">Em andamento</Selo>;
}

/** O efeito do apostilamento de reajuste; a data-base leva ao ciclo dela na aba Reajuste. */
function EfeitoDoCadastro({ i, contratoId }: { i: InstrumentoCadastro; contratoId: number }) {
  if (i.tipo !== "apostilamento_reajuste") return <>—</>;
  const pct = i.dados.percentual, eficacia = i.dados.eficacia, base = i.dados.data_base;
  const partes = [pct !== undefined && pct !== null ? fmtPercentual(Number(pct) / 100) : "",
                  typeof eficacia === "string" ? `eficácia ${data(eficacia)}` : ""].filter(Boolean);
  if (typeof base !== "string") return <>{partes.join(" · ") || "—"}</>;
  const mes = base.slice(0, 7);
  return <>{partes.join(" · ")}{partes.length ? " · " : ""}
    <Link para={{ tela: "obra", id: contratoId, aba: "reajuste" }} secao={`db-${mes}`}>data-base {mesBR(mes)}</Link></>;
}

export default function Instrumentos({ contratoId, cadastro, erroCadastro }:
    { contratoId: number; cadastro: InstrumentoCadastro[] | null; erroCadastro: string }) {
  const [aditivos, setAditivos] = useState<AditivoApi[] | null>(null);
  const [prazo, setPrazo] = useState<InstrumentoPrazo[]>([]);
  const [erro, setErro] = useState("");

  useEffect(() => {
    let vivo = true;
    setAditivos(null); setErro(""); setPrazo([]);
    api<AditivoApi[]>(`/api/contratos/${contratoId}/aditivos`)
      .then(l => { if (vivo) setAditivos(l); })
      .catch(e => { if (vivo) setErro(mensagemDeErro(e)); });
    // o sinal de retroativo e' o da situacao do prazo; se ela falhar, a lista sai sem o sinal
    api<{ situacao: { instrumentos: InstrumentoPrazo[] } }>(`/api/contratos/${contratoId}/prazos`)
      .then(d => { if (vivo) setPrazo(d.situacao.instrumentos); })
      .catch(() => {});
    return () => { vivo = false; };
  }, [contratoId]);

  const carregando = (aditivos === null && !erro) || (cadastro === null && !erroCadastro);
  const linhas = instrumentosDaObra(aditivos ?? [], cadastro ?? [], prazo);

  return (
    <section className="cartao" aria-labelledby="titulo-instrumentos" id="instrumentos">
      <div className="cartao__cabeca">
        <h2 className="cartao__titulo" id="titulo-instrumentos">Instrumentos</h2>
      </div>

      {erro && <div className="cartao__corpo"><p className="erro" role="alert">
        <IconeAlerta className="icone icone--p" />{erro}
      </p></div>}
      {erroCadastro && <div className="cartao__corpo"><p className="campo__nota">
        Não foi possível ler os instrumentos do cadastro.</p></div>}

      {!carregando && !erro && !erroCadastro && linhas.length === 0 && (
        <div className="vazio">
          <p className="vazio__titulo">Nenhum instrumento.</p>
        </div>
      )}

      {!carregando && linhas.length > 0 && (
        <Rolagem rotulo="Instrumentos do contrato">
          <table className="tabela">
            <caption className="sr-only">Instrumentos do contrato, do mais novo ao mais antigo</caption>
            <thead>
              <tr>
                <th scope="col">Data</th><th scope="col">Instrumento</th><th scope="col">Número</th>
                <th scope="col">Efeito</th><th scope="col" className="col-num">Δ valor</th><th scope="col">Situação</th>
              </tr>
            </thead>
            <tbody>
              {linhas.map((l, n) => {
                const par = `linha${n % 2 === 1 ? " par" : ""}`;
                if (l.de === "cadastro") {
                  const i = l.instrumento;
                  return (
                    <tr key={l.chave} className={par}>
                      <td className="num">{data(i.data)}</td>
                      <td>{TIPO_CADASTRO[i.tipo] ?? i.tipo}</td>
                      <td className="forte">{i.numero ?? "s/n"}</td>
                      <td className="num"><EfeitoDoCadastro i={i} contratoId={contratoId} /></td>
                      <td className="col-num num">—</td>
                      <td>—</td>
                    </tr>
                  );
                }
                const a = l.aditivo;
                // F-72: o valor pesa como o estado — cancelado riscado, em andamento em texto secundario, assinado pleno
                const pesoDoValor = a.cancelado_em ? " valor--cancelado" : a.status === "assinado" ? "" : " valor--andamento";
                return (
                  <tr key={l.chave} className={par}>
                    <td className="num">{data(a.data_assinatura)}</td>
                    <td>{a.forma === "apostilamento" ? "Apostilamento" : "Termo aditivo"} {ROTULO_TIPO[a.tipo] ?? a.tipo}</td>
                    <td className="forte">{a.numero ?? "s/n"}</td>
                    {/* o objeto inteiro, que quebra linha: nada so' no passar do mouse */}
                    <td className="efeito">
                      {a.objeto && <div>{a.objeto}</div>}
                      {a.nova_execucao_fim && <div className="num">execução até {data(a.nova_execucao_fim)}</div>}
                      {a.nova_vigencia_fim && <div className="num">vigência até {data(a.nova_vigencia_fim)}</div>}
                      {!a.objeto && !a.nova_execucao_fim && !a.nova_vigencia_fim && "—"}
                    </td>
                    <td className={`col-num dinheiro num${pesoDoValor}`}>{a.delta_valor_centavos ? deltaBR(a.delta_valor_centavos) : "—"}</td>
                    <td>
                      <Situacao a={a} />
                      {l.retroativo && (
                        <Selo classe="selo--atencao" sufixo={<span className="sr-only"> — assinado depois do fim da execução que prorroga</span>}>
                          retroativo
                        </Selo>
                      )}
                      {/* textos longos: quebram linha dentro da celula, em vez de alargar a tabela */}
                      {a.ressalva_reajuste && <div className="campo__nota">Ressalva de reajuste: {a.ressalva_reajuste}</div>}
                      {a.cancelado_motivo && <div className="campo__nota">Motivo do cancelamento: {a.cancelado_motivo}</div>}
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
