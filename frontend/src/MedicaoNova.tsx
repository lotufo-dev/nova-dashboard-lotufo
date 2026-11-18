import { useEffect, useState } from "react";
import { api } from "./api";
import type { Usuario } from "./Login";
import { ir, medicaoDaBusca, temOrigem, type Busca, type Origem, type Rota } from "./rota";
import { Link } from "./Link";
import { FaixaPasso, PassoCartao, Passos, passosDa } from "./Passos";
import { NovaPlanilhaCarta } from "./PlanilhaCarta";
import { baseDosValores } from "./formato";
import { useNomesDoCaminho } from "./nomesDoCaminho";
import { VoltarOrigem } from "./Topo";
import "./etapas.css";

// Medicao que ainda nao existe (#153): a antiga tela "Nova medição" virou o primeiro passo da pagina da medicao. Desde a
// issue #289 o formulario dele e' a "Nova planilha/carta" (antes, o do espelho): registra-la cria a medicao e a
// pagina dela abre com o cartao da planilha/carta. #653: a barra e' a mesma da pagina da medicao (os seis passos de
// Passos.tsx; a obra sem planilha/carta comeca em Espelhos). Os outros passos aparecem na barra, mas so' liberam depois.

type Cabecalho = { obra: string; orgao: string; instrumento: string; percentual_lotufo_bp: number;
  // #805: a sigla do contratante e a chave da pagina dele, para o caminho do topo
  contratante?: string | null; contratante_chave?: string | null;
  /** #660: os passos da medição que a obra inicia, decididos no servidor (família do órgão e cadastro da obra) */
  passos_medicao?: number[] };
// as telas que estao no caminho da medicao (Obras › contratante › obra › ...): o trecho delas ja' volta sozinho
const FORA_DO_CAMINHO: Rota["tela"][] = ["obras", "contratante"];

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
  // o passo aberto no lugar do primeiro (clique na barra); null = o primeiro
  const [vendo, setVendo] = useState<number | null>(null);
  // issue #289: a planilha/carta e' o 1o passo so' na obra que gera a medicao pelo espelho; a outra lanca a mao
  const [regraAtiva, setRegraAtiva] = useState<boolean | null>(null);
  useEffect(() => {
    api<Cabecalho>(`/api/contratos/${contratoId}/cabecalho`).then(setCab).catch(() => setCab(null));
    api<{ regra: { situacao: string } | null }>(`/api/contratos/${contratoId}/espelho`)
      .then(r => setRegraAtiva(r.regra?.situacao === "ativa")).catch(() => setRegraAtiva(false));
  }, [contratoId]);
  const obra = cab?.obra ?? "Obra";
  useEffect(() => { document.title = `${obra} · ${nome} · grupolotufo`; }, [obra, nome]);
  // o caminho do topo (#814): Obras › contratante › obra › Medições › Nova medição
  useNomesDoCaminho({ obra: cab?.obra, medicao: nome,
    contratante: cab ? { nome: cab.contratante ?? cab.orgao, chave: cab.contratante_chave } : null });
  const passos = cab?.passos_medicao?.length ? cab.passos_medicao : passosDa(regraAtiva !== false);
  const atual = passos[0];
  const aberto = vendo !== null && passos.includes(vendo) ? vendo : atual;

  return (
    <>
      {/* o caminho e' da barra do topo (#814); aqui, so' o "← origem" de quem chegou de fora dele */}
      {temOrigem(origem, FORA_DO_CAMINHO) && (
        <header className="topbar topbar--detalhe med-trilha">
          <div className="topbar__trilha">
            <VoltarOrigem origem={origem} alemDe={FORA_DO_CAMINHO} />
          </div>
        </header>
      )}
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
        <div className="med-grade">
          <div className="med-principal">
            <Passos passos={passos} atual={atual} vendo={aberto} datas={{}} aoIr={n => setVendo(n === atual ? null : n)} />
            {/* #722: o painel do passo aberto, ligado a' aba dele, como na pagina da medicao */}
            <div className="med-quadro">
            <FaixaPasso vendo={aberto} atual={atual} passos={passos} aoVoltar={() => setVendo(null)} />
            <PassoCartao key={aberto} n={aberto} atual={atual} passos={passos}>
              {/* os outros passos so' tem o selo "Libera depois do passo N" */}
              {aberto === atual && (
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
            </PassoCartao>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
