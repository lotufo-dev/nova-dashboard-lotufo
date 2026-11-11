import { useEffect, useState } from "react";
import { api, apiForm, mensagemDeErro } from "./api";
import CampoValor from "./CampoValor";
import ErroCampo from "./ErroCampo";
import { fmtTamanho } from "./formato";
import { IconeAlerta, IconeEnviarNuvem } from "./icones";
import { centavosDoTexto, mesCivil, type Registrada } from "./PlanilhaCarta";
import type { ObraResumo } from "./resumoMedicoes";
import { ir } from "./rota";
import "./iniciarMedicao.css";

// O formulário de iniciar a medição de uma obra numa competência (#507). Desde a #643 ele abre pelo botão "Iniciar" do
// quadro do mês (MedicoesPagina.tsx), já na competência do quadro. Criar a medição é a rota de sempre: planilha/carta
// (POST /api/contratos/{id}/planilhas, com a carta assinada e a planilha) na obra que gera a medição por ela, e a medição
// lançada à mão (POST .../medicoes) na que não tem planilha e carta (MTPAR). Criada, abre a página da medição.

/** Área de soltar o arquivo: arrastar ou clicar. */
function Soltar({ id, titulo, aceita, arquivo, aoEscolher, erro }: {
  id: string; titulo: string; aceita: string; arquivo: File | null; aoEscolher: (f: File | null) => void; erro?: string;
}) {
  const [sobre, setSobre] = useState(false);
  return (
    <div className="iniciar-med__soltar-caixa">
      <label className={`iniciar-med__soltar${sobre ? " iniciar-med__soltar--sobre" : ""}${arquivo ? " iniciar-med__soltar--cheia" : ""}`}
        htmlFor={id}
        onDragOver={ev => { ev.preventDefault(); if (!sobre) setSobre(true); }} onDragLeave={() => setSobre(false)}
        onDrop={ev => { ev.preventDefault(); setSobre(false); aoEscolher(ev.dataTransfer.files?.[0] ?? null); }}>
        <IconeEnviarNuvem className="icone iniciar-med__soltar-icone" />
        <strong>{titulo}</strong>
        <span className="iniciar-med__soltar-sub" title={arquivo?.name}>
          {arquivo ? `${arquivo.name} · ${fmtTamanho(arquivo.size)}` : "Arraste o arquivo ou clique"}
        </span>
        <input id={id} type="file" accept={aceita} className="iniciar-med__arquivo" aria-invalid={erro ? true : undefined}
          aria-describedby={erro ? `${id}-erro` : undefined}
          onChange={ev => { aoEscolher(ev.currentTarget.files?.[0] ?? null); ev.currentTarget.value = ""; }} />
      </label>
      <ErroCampo id={`${id}-erro`} erro={erro} />
    </div>
  );
}

type Sugestao = { numero: number; numero_orgao: number | null; competencia: string; periodo_inicio: string; periodo_fim: string };

/** O formulário da obra escolhida. `key` na obra e no mês: trocar de um ou de outro recomeça o formulário. */
export default function IniciarMedicao({ obra, mes, aoCancelar }: { obra: ObraResumo; mes: string; aoCancelar: () => void }) {
  const tipo = obra.proxima_tipo;
  const [regraAtiva, setRegraAtiva] = useState<boolean | null>(null);
  const [erroRegra, setErroRegra] = useState("");
  const [numero, setNumero] = useState(String(obra.proxima));
  const [numeroCarta, setNumeroCarta] = useState("");
  const [inicio, setInicio] = useState(mesCivil(mes)[0]);
  const [fim, setFim] = useState(mesCivil(mes)[1]);
  const [valor, setValor] = useState("");
  const [carta, setCarta] = useState<File | null>(null);
  const [planilha, setPlanilha] = useState<File | null>(null);
  const [tentou, setTentou] = useState(false);
  const [ocupado, setOcupado] = useState(false);
  const [erro, setErro] = useState("");

  useEffect(() => {
    let vivo = true;
    api<{ regra: { situacao: string } | null }>(`/api/contratos/${obra.contrato_id}/espelho`)
      .then(r => { if (vivo) setRegraAtiva(r.regra?.situacao === "ativa"); })
      // sem saber a regra da obra nao se cria nada: assumir "sem planilha e carta" lancaria a medicao a mao numa obra que a exige
      .catch(e => { if (vivo) setErroRegra(mensagemDeErro(e)); });
    api<Sugestao>(`/api/contratos/${obra.contrato_id}/planilhas/sugestao?tipo=${tipo}`)
      .then(s => { if (vivo && s.numero === obra.proxima && s.numero_orgao !== null) setNumeroCarta(String(s.numero_orgao)); })
      .catch(() => {});
    return () => { vivo = false; };
  }, [obra.contrato_id, obra.proxima, tipo]);

  const de = tipo === "projeto" ? " de Projeto" : "";
  const numeroOk = /^[1-9][0-9]{0,2}$/.test(numero);

  async function iniciar(ev: React.FormEvent) {
    ev.preventDefault();
    setTentou(true); setErro("");
    if (!numeroOk) return;
    // a prevista do cronograma ja' e' a medicao: abre-la (na obra sem planilha/carta nao ha' o que criar)
    if (regraAtiva === false && obra.prevista_id !== null) { ir({ tela: "medicao", obra: obra.contrato_id, id: obra.prevista_id }, { forcar: true }); return; }
    if (regraAtiva === false) {
      setOcupado(true);
      try {
        const r = await api<{ id: number }>(`/api/contratos/${obra.contrato_id}/medicoes`, {
          method: "POST", body: JSON.stringify({ numero: Number(numero), tipo, competencia: mes }) });
        ir({ tela: "medicao", obra: obra.contrato_id, id: r.id }, { forcar: true });
      } catch (e) { setErro(mensagemDeErro(e)); } finally { setOcupado(false); }
      return;
    }
    if (!carta || !planilha || centavosDoTexto(valor) === null || !inicio || !fim) return;
    setOcupado(true);
    const fd = new FormData();
    fd.append("numero", numero); fd.append("tipo", tipo); fd.append("competencia", mes);
    fd.append("periodo_inicio", inicio); fd.append("periodo_fim", fim); fd.append("valor", valor);
    if (numeroCarta.trim()) fd.append("numero_orgao", numeroCarta.trim());
    fd.append("oficio", carta); fd.append("planilha", planilha);
    try {
      const r = await apiForm<Registrada>(`/api/contratos/${obra.contrato_id}/planilhas`, fd);
      ir({ tela: "medicao", obra: obra.contrato_id, id: r.medicao_id }, { forcar: true });
    } catch (e) { setErro(mensagemDeErro(e)); } finally { setOcupado(false); }
  }

  if (erroRegra) return <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />Não foi possível ler a regra da obra: {erroRegra} Escolha a obra de novo para tentar outra vez.</p>;
  if (regraAtiva === null) return <p role="status" className="iniciar-med__carregando">Carregando…</p>;

  return (
    <form className="cartao iniciar-med__cartao" onSubmit={iniciar} aria-label={`Iniciar a ${obra.proxima}ª medição${de} de ${obra.obra}`}>
      <h2 className="iniciar-med__cartao-titulo">{regraAtiva ? "Planilha e carta" : "Espelho"}</h2>
      {erro && <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erro}</p>}
      <div className={regraAtiva ? "iniciar-med__corpo" : "iniciar-med__corpo iniciar-med__corpo--so-campos"}>
        <div className="iniciar-med__campos">
          <div className="campo">
            <label className="campo__rotulo" htmlFor="im-numero">Número</label>
            <input id="im-numero" name="numero" className="entrada--num num" inputMode="numeric" autoComplete="off" spellCheck={false} value={numero}
              aria-invalid={tentou && !numeroOk ? true : undefined} aria-describedby={tentou && !numeroOk ? "im-numero-erro" : undefined} onChange={e => setNumero(e.target.value.replace(/\D/g, "").slice(0, 3))} />
            <ErroCampo id="im-numero-erro" erro={tentou && !numeroOk ? "Informe o número da medição." : undefined} />
          </div>
          {regraAtiva && (
            <>
              <fieldset className="campo iniciar-med__periodo">
                <legend className="campo__rotulo">Período</legend>
                <div className="iniciar-med__periodo-datas">
                  <input type="date" aria-label="Período: de" required value={inicio} onChange={e => setInicio(e.target.value)} />
                  <span aria-hidden="true">a</span>
                  <input type="date" aria-label="Período: até" required value={fim} onChange={e => setFim(e.target.value)} />
                </div>
              </fieldset>
              <div className="campo">
                <label className="campo__rotulo" htmlFor="im-carta">Nº da carta</label>
                <input id="im-carta" name="numero_orgao" className="entrada--num num" inputMode="numeric" autoComplete="off" spellCheck={false}
                  value={numeroCarta} onChange={e => setNumeroCarta(e.target.value.replace(/\D/g, "").slice(0, 4))} />
              </div>
              <div className="campo">
                <label className="campo__rotulo" htmlFor="im-valor">Valor pedido</label>
                <CampoValor id="im-valor" name="valor" value={valor} onChange={setValor} className="entrada--num num" />
                <ErroCampo id="im-valor-erro" erro={tentou && centavosDoTexto(valor) === null ? "Informe o valor pedido." : undefined} />
              </div>
            </>
          )}
        </div>
        {regraAtiva && (
          <div className="iniciar-med__arquivos">
            <Soltar id="im-carta-pdf" titulo="Carta assinada (PDF)" aceita="application/pdf,.pdf" arquivo={carta} aoEscolher={setCarta}
              erro={tentou && !carta ? "Anexe a carta assinada." : undefined} />
            <Soltar id="im-planilha" titulo="Planilha de medição" aceita=".xlsx,.pdf,application/pdf" arquivo={planilha} aoEscolher={setPlanilha}
              erro={tentou && !planilha ? "Anexe a planilha de medição." : undefined} />
          </div>
        )}
      </div>
      <div className="iniciar-med__botoes">
        <button type="button" className="btn" onClick={aoCancelar}>Cancelar</button>
        <button type="submit" className="btn btn--primario" disabled={ocupado}>{ocupado ? "Iniciando…" : "Iniciar medição"}</button>
      </div>
    </form>
  );
}

