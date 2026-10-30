import { useEffect, useState } from "react";
import { api } from "./api";
import Espelho from "./Espelho";
import { EtapaCartao, FaixaVendo, Setas } from "./Etapas";
import type { Usuario } from "./Login";
import { ir, type Origem } from "./rota";
import { Link } from "./Link";
import { baseDosValores } from "./formato";
import { Migalhas, VoltarOrigem } from "./Topo";
import "./etapas.css";

// Medicao que ainda nao existe (#153): a antiga tela "Nova medição" virou a etapa 1 (Espelho) da pagina da medicao.
// A pagina abre nesta etapa ja' com o formulario; gerar o espelho cria a medicao e a pagina dela abre na etapa 2.
// As outras etapas aparecem no trilho, mas so' liberam depois.

type Cabecalho = { obra: string; orgao: string; instrumento: string; percentual_lotufo_bp: number };

export default function MedicaoNova({ contratoId, usuario, origem }: { contratoId: number; usuario: Usuario; origem: Origem | null }) {
  const podeEditar = usuario.perfil === "engenharia" || usuario.perfil === "admin";
  const [cab, setCab] = useState<Cabecalho | null>(null);
  const [vendo, setVendo] = useState(1);
  useEffect(() => {
    api<Cabecalho>(`/api/contratos/${contratoId}/cabecalho`).then(setCab).catch(() => setCab(null));
  }, [contratoId]);
  const obra = cab?.obra ?? "Obra";
  useEffect(() => { document.title = `${obra} · Nova medição · grupolotufo`; }, [obra]);

  return (
    <>
      <header className="topbar topbar--detalhe">
        <div className="topbar__trilha">
          <VoltarOrigem origem={origem} alemDe={["obras", "medicoes"]} />
          <Migalhas origem={origem} itens={[{ rotulo: "Medições", para: { tela: "medicoes" } },
            { rotulo: obra, para: { tela: "obra", id: contratoId, aba: "medicoes" } }, { rotulo: "Nova medição" }]} />
        </div>
      </header>
      <div className="pagina med">
        <div className="med-cabeca">
          <div>
            <h1 title={`${obra} · Nova medição`}>Nova medição</h1>
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
                  <Espelho contratoId={contratoId} podeEditar={podeEditar} aoMudar={() => {}} abrirForm parte="espelho"
                    aoGerar={id => ir({ tela: "medicao", obra: contratoId, id }, { forcar: true })}
                    semRegra={<p><Link className="link" para={{ tela: "obra", id: contratoId, aba: "medicoes" }}>Lançar a medição à mão</Link></p>} />
                </div>
              )}
            </EtapaCartao>
          </div>
        </div>
      </div>
    </>
  );
}
