import { useState } from "react";
import Contador from "./Contador";
import { contar } from "./formato";
import type { ItemLegenda } from "./LegendaCor";
import { chipValidadeGarantia, garantiasAConferir, obrasPorOrgao, type ObraDoc } from "./matriz";
import { fmtDataPura } from "./tempo";
import { Chip, MolduraDocumentos } from "./documentosComum";
import { usePainel } from "./documentosDados";

/* Garantias (#65, #651, #658; pagina propria na #820): "a garantia de cada obra ativa cobre a execucao?". Um painel
 * por orgao, uma linha por obra com apolice, validade, se cobre a execucao e o CNO. Sem acao de escrita, como
 * na aba de antes. Endereco: "/documentos/garantias". */

const OBRAS_POR_GRUPO = 8;

const LEGENDA: ItemLegenda[] = [
  { situacao: "feito", texto: "em dia" }, { situacao: "breve", texto: "não cobre" }, { situacao: "critico", texto: "sem registro" },
];

function GrupoGarantias({ orgao, obras }: { orgao: string; obras: ObraDoc[] }) {
  const [tudo, setTudo] = useState(false);
  const vistas = tudo ? obras : obras.slice(0, OBRAS_POR_GRUPO);
  return (
    <section className="cartao doc-bloco doc-grupo" aria-label={`Garantias de ${orgao}`}>
      <div className="doc-linha doc-linha--cabeca">
        <h2 className="doc-grupo__cabeca">{orgao} <Contador>{obras.length === 1 ? "1 obra" : `${obras.length} obras`}</Contador></h2>
        <div className="doc-chips doc-chips--4" aria-hidden="true">
          {["Apólice", "Válida até", "Cobre a execução", "CNO"].map(r => <span key={r}>{r}</span>)}
        </div>
      </div>
      <ul className="doc-linhas">
        {vistas.map(o => {
          const g = o.garantia;
          const valida = chipValidadeGarantia(g, g ? fmtDataPura(g.vigencia_fim) : "");
          const cob = o.cobre_execucao;
          return (
            <li key={o.contrato_id} className="doc-linha doc-linha--obra">
              <div className="doc-linha__nome"><span className="doc-linha__obra">{o.obra}</span></div>
              <div className="doc-chips doc-chips--4">
                <Chip semRotulo cor={g?.apolice ? "feito" : "critico"} rotulo="Apólice" valor={g?.apolice || "sem registro"} />
                <Chip semRotulo cor={valida.cor} rotulo="Válida até" valor={valida.valor} />
                <Chip semRotulo cor={!g ? "critico" : cob?.cobre === true ? "feito" : cob?.cobre === false && cob.ate ? "breve" : "neutro"}
                  rotulo="Cobre a execução"
                  valor={!g ? "sem registro" : cob?.cobre === true ? "sim" : cob?.cobre === false && cob.ate ? `não, até ${fmtDataPura(cob.ate)}` : "—"} />
                <Chip semRotulo cor={o.cno ? "feito" : "critico"} rotulo="CNO" valor={o.cno ? "registrado" : "sem registro"} />
              </div>
            </li>
          );
        })}
      </ul>
      {obras.length > OBRAS_POR_GRUPO && (
        <button type="button" className="doc-grupo__mais" onClick={() => setTudo(t => !t)}>
          {tudo ? "mostrar menos" : `+${contar(obras.length - OBRAS_POR_GRUPO, "obra", "obras")}`}
        </button>
      )}
    </section>
  );
}

export default function DocumentosGarantias() {
  const { painel, erro } = usePainel();
  const obras = painel?.contratos ?? [];
  // #651: do ultimo documento vencido so' se sabe a data; o contador pede conferencia, sem vermelho
  const n = garantiasAConferir(obras);

  return (
    <MolduraDocumentos classe="doc-garantias" erro={erro} carregado={!!painel} legenda={LEGENDA}
      contador={n > 0 ? <Contador situacao="breve">{`${n} a conferir`}</Contador> : null}>
      {obras.length === 0 ? <div className="vazio"><p className="vazio__titulo">Nenhuma obra ativa.</p></div>
        : obrasPorOrgao(obras).map(g => <GrupoGarantias key={g.orgao} orgao={g.orgao} obras={g.obras} />)}
    </MolduraDocumentos>
  );
}
