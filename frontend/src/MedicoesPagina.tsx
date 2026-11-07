import { useEffect, useState } from "react";
import { api, mensagemDeErro } from "./api";
import EmAndamento from "./EmAndamento";
import { IconeAlerta } from "./icones";
import IniciarMedicao from "./IniciarMedicao";
import type { Usuario } from "./Login";
import { type AbaMedicoes } from "./rota";
import type { ResumoMedicoes } from "./resumoMedicoes";
import { hojeLocal } from "./tempo";
import "./medicoes.css";

// Medições (redesenho 2026-11, #507; telas aprovadas em 06/11/2026): só dois itens no menu. "Iniciar medição" é a tela
// de dois painéis com busca de obra; "Em andamento", a lista única das medições iniciadas, que abre a página da medição.
// As oito abas e os oito cartões de antes saíram: a etapa de cada medição está na lista e na página dela. Tudo vem de
// GET /api/medicoes/resumo (`medicoes.resumo`); a tela só desenha.

export default function MedicoesPagina({ aba, usuario }: { aba: AbaMedicoes; usuario: Usuario }) {
  const [dados, setDados] = useState<ResumoMedicoes | null>(null);
  const [erro, setErro] = useState("");
  const [mes, setMes] = useState(() => hojeLocal().slice(0, 7));
  const podeIniciar = usuario.perfil !== "diretoria";

  // relido a cada troca de aba e de mês: iniciar ou enviar algo em outra tela muda as listas
  useEffect(() => {
    let vivo = true;
    api<ResumoMedicoes>(`/api/medicoes/resumo?mes=${mes}`)
      .then(d => { if (vivo) { setDados(d); setErro(""); } })
      .catch(e => { if (vivo) setErro(mensagemDeErro(e)); });
    return () => { vivo = false; };
  }, [aba, mes]);

  if (!dados) {
    return erro
      ? <div className="pagina"><p className="erro" role="alert"><IconeAlerta className="icone icone--p" />Não foi possível ler as medições: {erro} Recarregue a página para tentar de novo.</p></div>
      : <div className="pagina"><section className="cartao"><div className="vazio"><p>Carregando as medições…</p></div></section></div>;
  }
  if (aba === "em-andamento") return <EmAndamento linhas={dados.linhas} />;
  return <IniciarMedicao obras={dados.obras} mes={mes} aoTrocarMes={setMes} podeIniciar={podeIniciar} carregando={dados.mes !== mes} />;
}
