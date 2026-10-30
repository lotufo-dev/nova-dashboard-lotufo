import { useEffect, useState } from "react";
import { api, mensagemDeErro } from "./api";
import { IconeAlerta } from "./icones";
import { Link } from "./Link";
import { substituir } from "./rota";

// O endereco antigo da pagina avulsa "Enviar a nota" (/notas/envio/:id, de e-mails e favoritos): a pagina saiu (16/10/2026)
// e o envio mora na etapa 4 da pagina da medicao. Descobre a medicao do protocolo e troca o endereco, sem empilhar historico.

export default function AbrirEnvio({ protocoloId }: { protocoloId: number }) {
  const [erro, setErro] = useState("");
  useEffect(() => {
    let vivo = true;
    api<{ envio: { contrato_id: number; medicao_ids: number[] } }>(`/api/notas/envio/${protocoloId}`)
      .then(d => { if (vivo) substituir({ tela: "medicao", obra: d.envio.contrato_id, id: d.envio.medicao_ids[0] }, { secao: "etapa-4", semBusca: true }); })
      .catch(e => { if (vivo) setErro(mensagemDeErro(e)); });
    return () => { vivo = false; };
  }, [protocoloId]);
  return (
    <div className="pagina">
      {erro ? (
        <div className="pilha">
          <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />Não foi possível abrir o envio: {erro}</p>
          <p><Link className="link" para={{ tela: "medicoes", aba: "enviar-nota" }}>Ver as notas a enviar</Link></p>
        </div>
      ) : <p className="campo__nota" role="status">Abrindo a etapa 4 da medição…</p>}
    </div>
  );
}
