import { useEffect, useState } from "react";
import { api, mensagemDeErro } from "./api";
import Contador from "./Contador";
import { contar } from "./formato";
import { porComQuem, type Anteriores, type FilaMedicoes, type Limites } from "./filaMedicoes";
import IniciarMedicao from "./IniciarMedicao";
import Janela from "./Janela";
import LegendaCor from "./LegendaCor";
import { Link } from "./Link";
import type { Usuario } from "./Login";
import MedicoesFila, { GruposDaFila, SemMedicaoNoMes } from "./MedicoesFila";
import MedicoesQuadro from "./MedicoesQuadro";
import { mesPorExtenso, somarMes, type ObraResumo } from "./resumoMedicoes";
import { trocarBusca, type AbaMedicoes, type Busca } from "./rota";
import { hojeLocal } from "./tempo";
import "./medicoes.css";
import Falha from "./Falha";

// Medições (#805, etapa 3a; decisão do dono de 18/11/2026): a tela de quem opera, em três vistas com endereço próprio.
// A FILA DE TRABALHO (a padrão, "/medicoes") responde "o que eu preciso fazer agora?"; o QUADRO DO MÊS (#643,
// "/medicoes/quadro") é a matriz obra × passo; os MESES ANTERIORES ("/medicoes/anteriores") ficam só com o que ainda
// pede ação de quem opera. A competência é a em trabalho (o mês anterior ao de hoje) ou a escolhida nas setas, e fica
// na URL (?mes=). Pedido e aprovado são o valor cheio da medição. Tudo vem de GET /api/medicoes/fila; a tela só desenha.

const MES = /^\d{4}-(0[1-9]|1[0-2])$/;
const VISTAS: { id: AbaMedicoes; rotulo: string }[] = [
  { id: "fila", rotulo: "Fila de trabalho" }, { id: "quadro", rotulo: "Quadro do mês" }, { id: "anteriores", rotulo: "Meses anteriores" },
];

/** Meses anteriores: os mesmos painéis da fila, com a competência em cada linha, e o que só espera o pagamento (ou é
 *  de antes do primeiro ano que as telas contam) numa linha de resumo que leva à página Em aberto (#816), onde o em
 *  aberto está nota a nota. */
function MesesAnteriores({ a, limites, opera }: { a: Anteriores; limites: Limites; opera: boolean }) {
  const resto = [
    a.esperam_pagamento > 0 ? (a.esperam_pagamento === 1 ? "1 medição espera pagamento" : `${a.esperam_pagamento.toLocaleString("pt-BR")} medições esperam pagamento`) : null,
    a.antes_do_ano_inicial > 0 ? `${contar(a.antes_do_ano_inicial, "medição aberta", "medições abertas")} de antes de ${a.ano_inicial}` : null,
  ].filter(Boolean);
  return (
    <>
      {a.linhas.length === 0
        ? <p className="medicoes__vazio medicoes__vazio--pagina">Nenhuma medição de meses anteriores pede ação.</p>
        : <GruposDaFila grupos={porComQuem(a.linhas)} limites={limites} opera={opera} comCompetencia />}
      {resto.length > 0 && (
        <p className="fila-resumo">
          <span className="num">{resto.join(" · ")}</span>
          <Link para={{ tela: "a-receber" }}>Ver na página Em aberto</Link>
        </p>
      )}
    </>
  );
}

export default function MedicoesPagina({ usuario, aba = "fila", busca = {} }: { usuario: Usuario; aba?: AbaMedicoes; busca?: Busca }) {
  const [dados, setDados] = useState<FilaMedicoes | null>(null);
  const [erro, setErro] = useState("");
  // a competência em trabalho: o mês anterior ao de hoje
  const [emTrabalho] = useState(() => somarMes(hojeLocal().slice(0, 7), -1));
  const [mes, setMes] = useState(() => (busca.mes && MES.test(busca.mes) ? busca.mes : emTrabalho));
  const [iniciando, setIniciando] = useState<ObraResumo | null>(null);
  const opera = usuario.perfil !== "diretoria";

  useEffect(() => {
    let vivo = true;
    api<FilaMedicoes>(`/api/medicoes/fila?mes=${mes}`)
      .then(d => { if (vivo) { setDados(d); setErro(""); } })
      .catch(e => { if (vivo) setErro(mensagemDeErro(e)); });
    return () => { vivo = false; };
  }, [mes]);

  if (!dados) {
    return erro
      ? <div className="pagina medicoes"><Falha>Não foi possível ler as medições: {erro} Recarregue a página para tentar de novo.</Falha></div>
      : <div className="pagina medicoes"><p className="medicoes__vazio medicoes__vazio--pagina" role="status">Carregando as medições…</p></div>;
  }
  // enquanto o mês escolhido não chega, o que está na tela ainda é do mês anterior: nada de iniciar nele
  const carregando = dados.mes !== mes;
  // a competência fica na URL (F5 e o link copiado abrem o mesmo mês); a em trabalho é a padrão e não entra nela
  const trocarMes = (n: number) => {
    const novo = somarMes(mes, n);
    setIniciando(null); setMes(novo);
    trocarBusca({ mes: novo === emTrabalho ? null : novo });
  };
  const daUrl = mes === emTrabalho ? undefined : { mes };
  const aoIniciar = (contratoId: number) => setIniciando(dados.obras.find(o => o.contrato_id === contratoId) ?? null);
  const podeIniciar = opera && !carregando;

  return (
    <div className="pagina medicoes" aria-busy={carregando || undefined}>
      <div className="medicoes__cab">
        <div>
          <p className="medicoes__cab-rotulo">Competência · valor cheio</p>
          <div className="medicoes__troca">
            <h2 className="medicoes__mes" aria-live="polite">{mesPorExtenso(mes)}</h2>
            <div className="medicoes__botoes" role="group" aria-label="Trocar a competência">
              <button type="button" className="btn btn--pequeno" aria-label="Mês anterior" onClick={() => trocarMes(-1)}>‹</button>
              <button type="button" className="btn btn--pequeno" aria-label="Mês seguinte" onClick={() => trocarMes(1)}>›</button>
            </div>
          </div>
        </div>
        <LegendaCor />
      </div>
      <nav className="abas medicoes__vistas" aria-label="Vistas de Medições">
        {VISTAS.map(v => (
          <Link key={v.id} className="aba" para={{ tela: "medicoes", aba: v.id }} busca={daUrl} aria-current={v.id === aba ? "page" : undefined}>
            {v.rotulo}
            {v.id === "anteriores" && dados.anteriores.linhas.length > 0 && (
              <Contador rotulo={`, ${contar(dados.anteriores.linhas.length, "medição pede ação", "medições pedem ação")}`}>
                {dados.anteriores.linhas.length.toLocaleString("pt-BR")}
              </Contador>
            )}
          </Link>
        ))}
      </nav>
      {erro && <Falha>Não foi possível ler as medições: {erro}</Falha>}

      {aba === "fila" && <MedicoesFila d={dados} opera={opera} podeIniciar={podeIniciar} aoIniciar={aoIniciar} />}
      {aba === "quadro" && (
        <>
          <MedicoesQuadro grupos={dados.quadro} limites={dados.limites} carregando={carregando} />
          {dados.sem_medicao.length > 0 && <SemMedicaoNoMes obras={dados.sem_medicao} mes={dados.mes} podeIniciar={podeIniciar} aoIniciar={aoIniciar} />}
        </>
      )}
      {aba === "anteriores" && <MesesAnteriores a={dados.anteriores} limites={dados.limites} opera={opera} />}

      {iniciando && (
        <Janela titulo={`${iniciando.obra} · ${mesPorExtenso(mes)}`} aoFechar={() => setIniciando(null)}>
          <IniciarMedicao key={`${iniciando.contrato_id}-${mes}`} obra={iniciando} mes={mes} />
        </Janela>
      )}
    </div>
  );
}
