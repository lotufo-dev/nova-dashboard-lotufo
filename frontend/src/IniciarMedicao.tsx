import { useEffect, useMemo, useState } from "react";
import { api, apiForm, mensagemDeErro } from "./api";
import CampoValor from "./CampoValor";
import ErroCampo from "./ErroCampo";
import { brl, fmtTamanho } from "./formato";
import { IconeAlerta, IconeEnviarNuvem } from "./icones";
import { centavosDoTexto, mesCivil, type Registrada } from "./PlanilhaCarta";
import { filtrarObras, porContratante, type ObraResumo } from "./resumoMedicoes";
import { ir } from "./rota";
import { fmtCompetencia } from "./tempo";
import "./iniciarMedicao.css";

// "Iniciar medição" (redesenho 2026-11, #507; tela aprovada em 06/11/2026, três painéis com busca): o painel do meio
// lista as obras ativas SEM medição no mês escolhido, com busca e chips por contratante; o da direita é o formulário da
// obra escolhida. Criar a medição é a rota de sempre: planilha/carta (POST /api/contratos/{id}/planilhas, com a carta
// assinada e a planilha) na obra que gera a medição por ela, e a medição lançada à mão (POST .../medicoes) na que não
// tem planilha e carta (MTPAR). Criada, abre a página da medição.

const MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];

/** "2026-10" -> "outubro de 2026". */
function mesPorExtenso(aaaaMm: string): string {
  const m = /^(\d{4})-(\d{2})$/.exec(aaaaMm);
  const nome = m ? MESES[Number(m[2]) - 1] : undefined;
  return m && nome ? `${nome} de ${m[1]}` : fmtCompetencia(aaaaMm);
}

/** "2026-12" + 1 -> "2027-01"; -1 volta o mês. */
function somarMes(aaaaMm: string, n: number): string {
  const m = /^(\d{4})-(\d{2})$/.exec(aaaaMm);
  if (!m) return aaaaMm;
  const total = Number(m[1]) * 12 + (Number(m[2]) - 1) + n;
  return `${Math.floor(total / 12)}-${String((total % 12) + 1).padStart(2, "0")}`;
}

// A letra sem acento, uma por uma: o texto normalizado tem o mesmo tamanho do original (o trecho achado vale nos dois).
const base = (c: string) => c.normalize("NFD").charAt(0).toLocaleLowerCase("pt-BR");
const semAcento = (t: string) => Array.from(t).map(base).join("");

/** O nome da obra com o trecho buscado em destaque (sem acento nem caixa). */
function Destacado({ texto, termo }: { texto: string; termo: string }) {
  const t = semAcento(termo.trim());
  const i = t ? semAcento(texto).indexOf(t) : -1;
  if (i < 0) return <>{texto}</>;
  return <>{texto.slice(0, i)}<mark className="iniciar-med__achado">{texto.slice(i, i + t.length)}</mark>{texto.slice(i + t.length)}</>;
}

const ROTULO_ESTADO: Record<string, string> = {
  planilha_gerada: "planilha/carta gerada", planilha_enviada: "planilha/carta enviada", boletim_recebido: "boletim recebido",
  espelho_gerado: "espelho gerado", espelho_enviado: "espelho enviado", nota_emitida: "nota emitida", protocolada: "protocolada",
  nf_emitida: "lançada no RM", recebida: "recebida",
};

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
function Formulario({ obra, mes, aoCancelar }: { obra: ObraResumo; mes: string; aoCancelar: () => void }) {
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
            <input id="im-numero" className="entrada--num num" inputMode="numeric" autoComplete="off" spellCheck={false} value={numero}
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
                <input id="im-carta" className="entrada--num num" inputMode="numeric" autoComplete="off" spellCheck={false}
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

export default function IniciarMedicao({ obras, mes, aoTrocarMes, podeIniciar, carregando }: {
  obras: ObraResumo[]; mes: string; aoTrocarMes: (m: string) => void; podeIniciar: boolean; carregando: boolean;
}) {
  const [termo, setTermo] = useState("");
  const [chip, setChip] = useState("");
  const [escolhida, setEscolhida] = useState<number | null>(null);

  const doMes = useMemo(() => obras.filter(o => o.sem_no_mes), [obras]);
  const contratantes = useMemo(() => porContratante(doMes).map(g => g.contratante), [doMes]);
  // o chip de um contratante que sumiu da lista (outro mes) volta a "Todas"
  const chipVale = chip !== "" && contratantes.includes(chip) ? chip : "";
  const noChip = useMemo(() => doMes.filter(o => chipVale === "" || o.contratante === chipVale), [doMes, chipVale]);
  const achadas = useMemo(() => filtrarObras(noChip, termo), [noChip, termo]);
  const idsAchadas = new Set(achadas.map(o => o.contrato_id));
  const outras = termo.trim() ? noChip.filter(o => !idsAchadas.has(o.contrato_id)) : [];
  const obra = doMes.find(o => o.contrato_id === escolhida) ?? null;
  const ultima = obra?.ultima_medicao ?? null;

  // chamada como funcao (nao como componente): um componente declarado aqui seria outro a cada digito da busca
  function linha(o: ObraResumo, apagada?: boolean) {
    return (
      <li key={o.contrato_id}>
        <button type="button" className={`iniciar-med__obra${apagada ? " iniciar-med__obra--apagada" : ""}`}
          aria-pressed={escolhida === o.contrato_id} onClick={() => setEscolhida(o.contrato_id)}>
          <span className="iniciar-med__obra-texto">
            <span className="iniciar-med__obra-nome">{apagada ? o.obra : <Destacado texto={o.obra} termo={termo} />}</span>
            <span className="iniciar-med__obra-sub">{o.contratante}{o.orgao_sub ? ` · ${o.orgao_sub}` : ""}</span>
          </span>
          <span className="iniciar-med__obra-num num">{o.proxima}ª</span>
        </button>
      </li>
    );
  }

  return (
    <div className="iniciar-med">
      <section className="iniciar-med__lista" aria-labelledby="iniciar-med-titulo">
        <h2 id="iniciar-med-titulo" className="iniciar-med__titulo">Iniciar medição</h2>
        <div className="iniciar-med__mes">
          <button type="button" className="iniciar-med__mes-seta" aria-label="Mês anterior" onClick={() => aoTrocarMes(somarMes(mes, -1))}>‹</button>
          <span className="iniciar-med__mes-nome" aria-live="polite">{mesPorExtenso(mes)}</span>
          <button type="button" className="iniciar-med__mes-seta" aria-label="Mês seguinte" onClick={() => aoTrocarMes(somarMes(mes, 1))}>›</button>
        </div>
        <input type="search" className="iniciar-med__busca" placeholder="Buscar obra…" aria-label="Buscar obra" autoComplete="off"
          value={termo} onChange={ev => setTermo(ev.target.value)} />
        <div className="iniciar-med__chips" role="group" aria-label="Contratante">
          {["", ...contratantes].map(c => (
            <button key={c || "todas"} type="button" className="iniciar-med__chip" aria-pressed={chipVale === c} onClick={() => setChip(c)}>
              {c || "Todas"}
            </button>
          ))}
        </div>
        <p className="iniciar-med__contagem" role="status">{carregando ? "Carregando…" : `${achadas.length} de ${noChip.length} obras`}</p>
        {achadas.length > 0 && <ul className="iniciar-med__itens" aria-label="Obras sem medição no mês">{achadas.map(o => linha(o))}</ul>}
        {outras.length > 0 && (
          <>
            <h3 className="iniciar-med__outras">Outras obras sem medição</h3>
            <ul className="iniciar-med__itens">{outras.map(o => linha(o, true))}</ul>
          </>
        )}
      </section>

      <section className="iniciar-med__painel" aria-label="Obra escolhida">
        {obra ? (
          <>
            <header className="iniciar-med__cabeca">
              <h2>{obra.obra}</h2>
              <p>Iniciar a {obra.proxima}ª medição{obra.proxima_tipo === "projeto" ? " de Projeto" : ""} · {mesPorExtenso(mes)} · {obra.contratante}</p>
            </header>
            {podeIniciar && !carregando && <Formulario key={`${obra.contrato_id}-${mes}`} obra={obra} mes={mes} aoCancelar={() => setEscolhida(null)} />}
            {ultima && (
              <section className="cartao iniciar-med__cartao" aria-label="Última medição">
                <h2 className="iniciar-med__cartao-titulo">Última medição</h2>
                <p className="iniciar-med__ultima">
                  {ultima.numero}ª{ultima.tipo === "projeto" ? " de Projeto" : ""} · {mesPorExtenso(ultima.competencia)}
                  {ultima.valor_centavos !== null && ` · ${brl(ultima.valor_centavos)}`}
                  {ROTULO_ESTADO[ultima.estado] && ` · ${ROTULO_ESTADO[ultima.estado]}`}
                </p>
              </section>
            )}
          </>
        ) : <p className="iniciar-med__vazio">Escolha uma obra.</p>}
      </section>
    </div>
  );
}
