import { useEffect, useState } from "react";
import "./medicoes.css";
import { api, mensagemDeErro } from "./api";
import { IconeMais } from "./icones";
import { Link } from "./Link";
import { NovaMedicaoManual, type Medicao } from "./Medicoes";

// Na aba Medicoes da obra, o antigo cartao "Gerar espelho" virou o atalho "Iniciar a Nª medição" (16/10/2026): a
// medicao se inicia na pagina dela, na etapa 1 (Espelho). Com medicao prevista no cronograma, o atalho abre a pagina
// dessa medicao; sem ela, a pagina da medicao nova. Obra do fluxo antigo (sem regra de espelho) continua com a
// medicao a mao.

export default function IniciarProxima({ contratoId, versao, aoCriar }: { contratoId: number; versao: number; aoCriar: () => void }) {
  const [ativa, setAtiva] = useState<boolean | null>(null);
  const [medicoes, setMedicoes] = useState<Medicao[] | null>(null);
  const [erro, setErro] = useState("");
  useEffect(() => {
    let vivo = true;
    api<{ regra: { situacao: string } | null }>(`/api/contratos/${contratoId}/espelho`)
      .then(r => { if (vivo) setAtiva(r.regra?.situacao === "ativa"); })
      .catch(e => { if (vivo) { setAtiva(null); setErro(mensagemDeErro(e)); } });
    api<Medicao[]>(`/api/contratos/${contratoId}/medicoes`).then(l => { if (vivo) setMedicoes(l); }).catch(() => {});
    return () => { vivo = false; };
  }, [contratoId, versao]);

  if (ativa === null) return erro ? <p className="erro" role="alert">Não foi possível ver como iniciar a medição: {erro}</p> : null;
  if (!ativa) {
    return (
      <section className="cartao" aria-labelledby="titulo-nova-medicao" id="nova-medicao">
        <div className="cartao__cabeca"><h2 className="cartao__titulo" id="titulo-nova-medicao">Nova medição</h2></div>
        <NovaMedicaoManual contratoId={contratoId} aoCriar={aoCriar} />
      </section>
    );
  }
  const prevista = medicoes?.find(x => x.estado === "prevista");
  // sem a lista (a leitura falhou), o rotulo nao inventa um numero
  const numero = prevista ? prevista.numero : medicoes ? medicoes.reduce((mx, x) => Math.max(mx, x.numero), 0) + 1 : null;
  return (
    <div className="medicoes__acoes" id="nova-medicao">
      <Link className="btn btn--primario medicoes__iniciar"
        para={prevista ? { tela: "medicao", obra: contratoId, id: prevista.id } : { tela: "nova-medicao", obra: contratoId }}>
        <IconeMais className="icone" />{numero === null ? "Iniciar a próxima medição" : `Iniciar a ${numero}ª medição`}
      </Link>
    </div>
  );
}
