import { useEffect, useState } from "react";
import { api } from "./api";
import { EtapaCartao, FaixaVendo, Setas } from "./Etapas";
import type { Usuario } from "./Login";
import { ir, medicaoDaBusca, type Busca, type Origem } from "./rota";
import { Link } from "./Link";
import { NovaPlanilhaCarta } from "./PlanilhaCarta";
import { baseDosValores } from "./formato";
import { Migalhas, VoltarOrigem } from "./Topo";
import "./etapas.css";

// Medicao que ainda nao existe (#153): a antiga tela "Nova medição" virou a etapa 1 da pagina da medicao. Desde a
// issue #289 o formulario da etapa 1 e' a "Nova planilha/carta" (antes, o do espelho): registra-la cria a medicao e a
// pagina dela abre com o cartao da planilha/carta.
// As outras etapas aparecem no trilho, mas so' liberam depois.

type Cabecalho = { obra: string; orgao: string; instrumento: string; percentual_lotufo_bp: number };

// A janela "Iniciar processo" (#151) manda o número, a competência e a série pela busca da URL
// (?numero=25&competencia=2026-10&tipo=projeto); valor fora do padrão é ignorado.
export default function MedicaoNova({ contratoId, usuario, origem, busca = {} }: {
  contratoId: number; usuario: Usuario; origem: Origem | null; busca?: Busca;
}) {
  const { numero, competencia, tipo } = medicaoDaBusca(busca);
  const inicial = numero || competencia
    ? { numero: numero ? Number(numero) : undefined, competencia: competencia || undefined } : undefined;
  // a obra sem planilha/carta lanca a mao na aba Medicoes da obra; o link leva o que veio da janela
  const buscaManual: Busca = { ...(numero ? { numero } : {}), ...(competencia ? { competencia } : {}), ...(tipo ? { tipo } : {}) };
  const nome = tipo ? "Nova medição de Projeto" : "Nova medição";
  // issue #567: a janela Iniciar processo escolheu a serie (sem `tipo` na busca, a de execucao); sem nada na busca, a
  // planilha/carta pre-seleciona o tipo da ultima medicao da obra
  const tipoPlanilha = tipo || (inicial ? "execucao" : undefined);
  const podeEditar = usuario.perfil === "engenharia" || usuario.perfil === "admin";
  const [cab, setCab] = useState<Cabecalho | null>(null);
  const [vendo, setVendo] = useState(1);
  // issue #289: a planilha/carta e' o 1o passo so' na obra que gera a medicao pelo espelho; a outra lanca a mao
  const [regraAtiva, setRegraAtiva] = useState<boolean | null>(null);
  useEffect(() => {
    api<Cabecalho>(`/api/contratos/${contratoId}/cabecalho`).then(setCab).catch(() => setCab(null));
    api<{ regra: { situacao: string } | null }>(`/api/contratos/${contratoId}/espelho`)
      .then(r => setRegraAtiva(r.regra?.situacao === "ativa")).catch(() => setRegraAtiva(false));
  }, [contratoId]);
  const obra = cab?.obra ?? "Obra";
  useEffect(() => { document.title = `${obra} · ${nome} · grupolotufo`; }, [obra, nome]);

  return (
    <>
      <header className="topbar topbar--detalhe">
        <div className="topbar__trilha">
          <VoltarOrigem origem={origem} alemDe={["obras", "medicoes"]} />
          <Migalhas origem={origem} itens={[{ rotulo: "Medições", para: { tela: "medicoes" } },
            { rotulo: obra, para: { tela: "obra", id: contratoId, aba: "medicoes" } }, { rotulo: nome }]} />
        </div>
      </header>
      <div className="pagina med">
        <div className="med-cabeca">
          <div>
            <h1 title={`${obra} · ${nome}`}>{nome}</h1>
            <p className="med-meta">
              <span>{obra}</span>
              {cab && <span>{cab.orgao}</span>}
              {cab && <span>{cab.instrumento}</span>}
              {cab && baseDosValores(cab.percentual_lotufo_bp) && <span>{baseDosValores(cab.percentual_lotufo_bp)}</span>}
            </p>
          </div>
        </div>
        <div className="med-grade med-grade--so-principal">
          <div className="med-principal">
            <Setas atual={1} vendo={vendo} aoIr={n => setVendo(n === 1 ? 1 : n)} />
            <FaixaVendo vendo={vendo} atual={1} aoVoltar={() => setVendo(1)} />
            <EtapaCartao key={vendo} n={vendo} atual={1}>
              {/* as outras etapas so' tem o selo "Libera depois da etapa N" */}
              {vendo === 1 && (
                <div className="med-etapa__corpo">
                  {/* issue #289: o primeiro passo da medicao e' a planilha/carta (spec 2026-10-20 §2.1); registrada, a
                      pagina da medicao abre com o cartao dela. Numero, competencia e serie vem da busca da URL (#151) */}
                  {!podeEditar || regraAtiva === null ? null : regraAtiva
                    ? <NovaPlanilhaCarta contratoId={contratoId} tipo={tipoPlanilha} inicial={inicial}
                        aoRegistrar={r => ir({ tela: "medicao", obra: contratoId, id: r.medicao_id }, { forcar: true })} />
                    : <p><Link className="link" para={{ tela: "obra", id: contratoId, aba: "medicoes" }}
                        busca={Object.keys(buscaManual).length ? buscaManual : undefined}>Lançar a medição à mão</Link></p>}
                </div>
              )}
            </EtapaCartao>
          </div>
        </div>
      </div>
    </>
  );
}
