import { useEffect, useState } from "react";
import { api, mensagemDeErro } from "./api";
import { IconeAlerta } from "./icones";
import { Link } from "./Link";
import { NovaMedicaoManual } from "./Medicoes";
import { NovaPlanilhaCarta } from "./PlanilhaCarta";
import type { ObraResumo } from "./resumoMedicoes";
import { ir } from "./rota";

// Iniciar a medição de uma obra pelo "Iniciar" do quadro do mês (MedicoesPagina.tsx), na competência do quadro. Desde a
// #653 não há formulário próprio daqui: é o mesmo da página da obra e da página da medição, a "Nova planilha/carta"
// (PlanilhaCarta.tsx, que trata o reajuste junto), aberto na competência pedida. A obra sem regra de espelho ativa (a que
// não gera a medição pela planilha e carta) segue com o lançamento à mão (NovaMedicaoManual). Criada, abre a página da medição.

/** O formulário da obra escolhida. `key` na obra e no mês: trocar de um ou de outro recomeça o formulário. */
export default function IniciarMedicao({ obra, mes }: { obra: ObraResumo; mes: string }) {
  const [regraAtiva, setRegraAtiva] = useState<boolean | null>(null);
  const [erroRegra, setErroRegra] = useState("");

  useEffect(() => {
    let vivo = true;
    api<{ regra: { situacao: string } | null }>(`/api/contratos/${obra.contrato_id}/espelho`)
      .then(r => { if (vivo) setRegraAtiva(r.regra?.situacao === "ativa"); })
      // sem saber a regra da obra nao se cria nada: assumir "sem planilha e carta" lancaria a medicao a mao numa obra que a exige
      .catch(e => { if (vivo) setErroRegra(mensagemDeErro(e)); });
    return () => { vivo = false; };
  }, [obra.contrato_id]);

  if (erroRegra) return <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />Não foi possível ler a regra da obra: {erroRegra} Escolha a obra de novo para tentar outra vez.</p>;
  if (regraAtiva === null) return <p role="status" className="iniciar-med__carregando">Carregando…</p>;

  const abrir = (id: number) => ir({ tela: "medicao", obra: obra.contrato_id, id }, { forcar: true });
  if (regraAtiva) {
    // o nº vem da sugestão da obra (a prevista do cronograma, senão o seguinte); a competência é a do quadro
    return <NovaPlanilhaCarta contratoId={obra.contrato_id} tipo={obra.proxima_tipo} inicial={{ competencia: mes }} aoRegistrar={r => abrir(r.medicao_id)} />;
  }
  // a prevista do cronograma ja' e' a medicao: na obra sem planilha/carta nao ha' o que criar, so' abri-la
  if (obra.prevista_id !== null) {
    return (
      <p>
        <Link className="link forte" para={{ tela: "medicao", obra: obra.contrato_id, id: obra.prevista_id }}>
          Abrir a {obra.proxima}ª medição{obra.proxima_tipo === "projeto" ? " de Projeto" : ""}, prevista no cronograma
        </Link>
      </p>
    );
  }
  return (
    <NovaMedicaoManual contratoId={obra.contrato_id} aoCriar={abrir}
      inicial={{ numero: String(obra.proxima), competencia: mes, tipo: obra.proxima_tipo === "projeto" ? "projeto" : "" }} />
  );
}
