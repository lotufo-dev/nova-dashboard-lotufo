import { useCallback, useEffect, useRef, useState } from "react";
import { baseDosValores } from "./formato";
import { api, mensagemDeErro } from "./api";
import Espelho from "./Espelho";
import { EtapaEnvio, useEnvios } from "./EtapaEnvio";
import { EtapaCartao, etapaDe, etapaInicial, FaixaVendo, Setas, situacaoDa } from "./Etapas";
import { FrcConsorcio } from "./Frc";
import { IconeAlerta } from "./icones";
import Janela from "./Janela";
import LiberarEnvio from "./LiberarEnvio";
import type { Usuario } from "./Login";
import MaisAcoes, { type ItemAcao } from "./MaisAcoes";
import { eventosDaMedicao, EXCECOES, FINAIS, metadeQueEspera, passoDe, PROXIMOS, rotuloDoBloco, tituloMedicao,
         type EspelhoResumo, type MedicaoBase, type ParDaMedicao } from "./medicao";
import { FormAssinatura, FormDesmarcarFinal, FormEstado, FormFinal, FormProtocoloManual, FormRecebimento, FormSemAOutra, FormValor, valorEditavel, type Agir } from "./MedicaoAtos";
import { brl, type Medicao } from "./Medicoes";
import { Notas } from "./Notas";
import { ProtocolosDaMedicao, useProtocolos } from "./Protocolo";
import { LinhaDoTempo, ResumoMedicao } from "./ResumoLateral";
import { type AbaMedicoes, type Origem, type Rota, useRota } from "./rota";
import { Link } from "./Link";
import Selo from "./Selo";
import { fmtCompetencia, fmtDataHora, fmtDataPura } from "./tempo";
import { Migalhas, VoltarOrigem } from "./Topo";
import "./etapas.css";

// Pagina da medicao (opcao B, aprovada em 16/10/2026): "Nª Medição + Reajuste" numa pagina so', com o trilho de
// cinco setas -- Espelho, Faturamento, Nota fiscal, Envio ao orgao e Pagamento --, so' a etapa da vez aberta (as
// feitas abrem no lugar dela, com a faixa para voltar) e, a direita, o Resumo e a Linha do tempo. Cada acao se faz
// num lugar so', na etapa onde acontece; as abas de Medicoes, o Inicio e a obra so' listam e levam ate' aqui
// (#etapa-N abre a etapa).

type Cabecalho = { obra: string; orgao: string; instrumento: string; percentual_lotufo_bp: number };
type LinhaAndamento = { id: number; proximo_passo: string; desde: string };
type Painel = "fora" | "protocolado" | "atestado" | "recebimento" | "cancelada" | "desistida" | "final" | "desfinal" | "assinatura" | "sozinha" | "liberar" | null;

// Ancoras antigas (#notas, #espelho, #protocolo) abrem a etapa onde a coisa mora hoje.
const SECAO_ETAPA: Record<string, number> = { espelho: 1, notas: 3, protocolo: 4 };

/** A aba de Medicoes onde esta medicao aparece (o "Medicoes" do caminho do topo volta para la'). */
export function abaDa(estado: string): Exclude<AbaMedicoes, "resumo" | "sem-medicao"> | undefined {
  switch (estado) {
    case "planilha_gerada": return "planilha-gerada";
    case "planilha_enviada": return "planilha-enviada";
    case "boletim_recebido": return "boletim-recebido";
    case "espelho_gerado": return "faturamento";
    case "espelho_enviado": return "aguardando-nota";
    case "nota_emitida": return "enviar-nota";
    case "protocolada": case "nf_emitida": return "aguardando-pagamento";
    default: return undefined;
  }
}

export default function MedicaoPagina({ contratoId, medicaoId, usuario, origem }:
    { contratoId: number; medicaoId: number; usuario: Usuario; origem: Origem | null }) {
  const podeEditar = usuario.perfil === "engenharia" || usuario.perfil === "admin";
  const { secao } = useRota();
  const [cab, setCab] = useState<Cabecalho | null>(null);
  const [medicoes, setMedicoes] = useState<Medicao[] | null>(null);
  const [andamento, setAndamento] = useState<LinhaAndamento[]>([]);
  const [espelhos, setEspelhos] = useState<EspelhoResumo[]>([]);
  // issue #188: a execucao e o reajuste da mesma competencia (as notas dos dois, a espera e a liberacao)
  const [par, setPar] = useState<ParDaMedicao | null>(null);
  const [erro, setErro] = useState("");
  const [feito, setFeito] = useState("");
  const [salvando, setSalvando] = useState(false);
  const [painel, setPainel] = useState<Painel>(null);
  const [alvoRecebimento, setAlvoRecebimento] = useState<Medicao | null>(null);
  // a etapa aberta no lugar da atual (clique na seta ou ancora); null = a da vez
  const [vendo, setVendo] = useState<number | null>(null);
  const protocolos = useProtocolos(contratoId);
  const geracao = useRef(0);
  // Notas e FRC leem o mesmo anexo: o que um anexa, o outro recarrega
  const [versaoNotas, setVersaoNotas] = useState(0);
  const [versaoFrc, setVersaoFrc] = useState(0);

  const m = medicoes?.find(x => x.id === medicaoId) ?? null;
  // a execucao e o reajuste do mesmo numero formam a pagina "Nª Medição + Reajuste"
  const execucao = !m || m.tipo === "projeto" ? null : m.tipo === "execucao" ? m : medicoes?.find(x => x.numero === m.numero && x.tipo === "execucao") ?? null;
  const reajuste = !m || m.tipo === "projeto" ? null : m.tipo === "reajuste" ? m : medicoes?.find(x => x.numero === m.numero && x.tipo === "reajuste") ?? null;
  const doPar = !!execucao && !!reajuste;
  const grupo = doPar ? [execucao, reajuste] : m ? [m] : [];
  const envios = useEnvios(grupo.map(x => x.id));

  // Tudo o que a pagina le alem dos cartoes que se leem sozinhos (espelho, notas, protocolos).
  const carregar = useCallback(async () => {
    const g = geracao.current;
    const [lista, abertas, esp, duas] = await Promise.all([
      api<Medicao[]>(`/api/contratos/${contratoId}/medicoes`),
      api<LinhaAndamento[]>(`/api/medicoes/andamento?contrato_id=${contratoId}`).catch(() => []),
      api<{ espelhos: EspelhoResumo[] }>(`/api/contratos/${contratoId}/espelho`).catch(() => ({ espelhos: [] })),
      // sem o par a pagina fica como antes (um bloco so'): a falha aqui nao derruba a medicao
      api<ParDaMedicao>(`/api/medicoes/${medicaoId}/par`).catch(() => null),
    ]);
    if (g !== geracao.current) return;
    setMedicoes(lista); setAndamento(abertas); setEspelhos(esp.espelhos ?? []);
    setPar(duas && Array.isArray(duas.metades) ? duas : null);
  }, [contratoId, medicaoId]);

  useEffect(() => {
    geracao.current += 1;
    const g = geracao.current;
    setCab(null); setMedicoes(null); setPar(null); setErro(""); setFeito(""); setPainel(null); setVendo(null);
    api<Cabecalho>(`/api/contratos/${contratoId}/cabecalho`).then(c => { if (g === geracao.current) setCab(c); }).catch(() => {});
    carregar().catch(e => { if (g === geracao.current) setErro(mensagemDeErro(e)); });
    return () => { geracao.current += 1; };
  }, [contratoId, medicaoId, carregar]);

  // A ancora (#etapa-4, ou as antigas #notas...) abre a etapa na pagina.
  useEffect(() => {
    const n = /^etapa-([1-5])$/.exec(secao);
    const alvo = n ? Number(n[1]) : SECAO_ETAPA[secao];
    if (alvo) setVendo(alvo);
  }, [secao]);

  // Titulo da aba do navegador: a obra e a medicao.
  
  useEffect(() => {
    document.title = `${cab?.obra ?? "Obra"} · ${m ? (doPar ? `${m.numero}ª Medição + Reajuste` : tituloMedicao(m)) : "Medição"} · grupolotufo`;
  }, [cab, m, doPar]);

  // Toda acao recarrega a pagina inteira (a medicao, a fila, os protocolos e os envios): o estado de uma etapa muda o
  // que falta nas outras. Devolve se a GRAVACAO foi aceita, como na tabela da obra.
  const recarregar = () => { void carregar().catch(() => {}); void protocolos.carregar(); void envios.carregar(); };
  const agir: Agir = async (fn, mensagemFeito) => {
    setErro(""); setFeito(""); setSalvando(true);
    let gravou = false;
    try {
      await fn();
      gravou = true;
      if (mensagemFeito) setFeito(mensagemFeito);
      await carregar();
      await protocolos.carregar();
      await envios.carregar();
    } catch (e) {
      setErro(gravou ? "Gravado, mas a página não recarregou — recarregue para ver o resultado."
        : mensagemDeErro(e));
    } finally { setSalvando(false); }
    return gravou;
  };

  const obra = cab?.obra ?? "Obra";
  const titulo = m ? (doPar ? `${m.numero}ª Medição + Reajuste` : tituloMedicao(m)) : "Medição";
  const linha = andamento.find(x => x.id === medicaoId);
  // issue #188: a metade pronta que espera a outra (orgao que junta); o passo da vez e' a espera
  const pronta = metadeQueEspera(par);
  const esperaAqui = pronta?.medicao_id === medicaoId ? pronta.espera : null;
  const passo = esperaAqui ? { rotulo: esperaAqui.texto.charAt(0).toUpperCase() + esperaAqui.texto.slice(1), secao: "etapa-4" }
    : passoDe(linha?.proximo_passo);
  const aqui: Rota = { tela: "medicao", obra: contratoId, id: medicaoId };

  // quando a etapa da vez muda (enviou, a nota chegou), a pagina acompanha: o clique numa seta so' vale ate' la'
  const atual = m ? etapaDe(m.estado) : 0;
  const atualAnterior = useRef<number | null>(null);
  useEffect(() => {
    if (!m) return;
    if (atualAnterior.current !== null && atualAnterior.current !== atual) setVendo(null);
    atualAnterior.current = atual;
  }, [m, atual]);

  const cabeca = (
    <header className="topbar topbar--detalhe">
      <div className="topbar__trilha">
        <VoltarOrigem origem={origem} alemDe={["obras", "medicoes"]} />
        <Migalhas origem={origem} itens={[{ rotulo: "Medições", para: { tela: "medicoes", aba: m ? abaDa(m.estado) : undefined } },
          { rotulo: obra, para: { tela: "obra", id: contratoId, aba: "medicoes" } }, { rotulo: titulo }]} />
      </div>
    </header>
  );

  if (erro && !medicoes) {
    return (
      <>{cabeca}<div className="pagina">
        <div className="form-inline">
          <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />Não foi possível abrir a medição: {erro}</p>
          <button type="button" className="btn" onClick={() => { setErro(""); void carregar().catch(e => setErro(mensagemDeErro(e))); }}>Tentar de novo</button>
        </div>
      </div></>
    );
  }
  if (!medicoes) {
    return <>{cabeca}<div className="pagina"><section className="cartao"><div className="vazio"><p>Carregando a medição…</p></div></section></div></>;
  }
  if (!m) {
    return (
      <>{cabeca}<div className="pagina">
        <section className="cartao"><div className="vazio">
          <p className="vazio__titulo">Esta medição não é desta obra</p>
          <p><Link className="link" para={{ tela: "obra", id: contratoId, aba: "medicoes" }}>Ver as medições de {obra}</Link></p>
        </div></section>
      </div></>
    );
  }

  const sit = (n: number) => situacaoDa(n, atual);
  const aberta = vendo ?? etapaInicial(atual, !!m.nota_emitida_em);
  const metades = par?.metades.length === 2 ? par.metades : [];
  const medicaoDa = (id: number) => medicoes.find(x => x.id === id);
  // #208: o misto que ficou vigente para outra medicao (superado para esta) nao e' o espelho desta
  const espVigente = espelhos.find(e => e.situacao === "vigente" && e.medicoes.some(x => x.id === m.id && !x.superado));
  const abrir = (p: Painel) => { setErro(""); setFeito(""); setPainel(p); };
  const fechar = () => { setPainel(null); setAlvoRecebimento(null); };
  const outras = medicoes.filter(x => x.numero === m.numero && x.id !== m.id && !(doPar && (x.id === execucao.id || x.id === reajuste.id)));
  const lib = par?.metades.find(x => x.medicao_id === m.id)?.liberacao;
  // a liberacao vem da auditoria, como as edicoes de valor (mesmo formato de data): entra na linha do tempo junto delas
  const base: MedicaoBase = m;
  const comLiberacao: MedicaoBase = lib ? { ...base, edicoes_valor: [...(base.edicoes_valor ?? []), { data: lib.em,
    texto: `Envio liberado sem ${m.tipo === "execucao" ? "o reajuste" : "a medição"}${lib.por ? ` por ${lib.por}` : ""}. `
      + `Justificativa: “${lib.justificativa ?? ""}”` }] } : m;
  const eventos = eventosDaMedicao(comLiberacao, espelhos, protocolos.dados?.protocolos ?? []);
  const registrados = m.protocolos.filter(p => !p.protocolo_id);

  // Mais acoes: so' o que nao e' de uma etapa
  const preso = (envios.envios ?? []).filter(e => e.protocolo_id !== null && !!e.envio_reservado_em);
  const acoes: ItemAcao[] = !podeEditar ? [] : [
    ...(valorEditavel(m, "atestado", podeEditar) ? [{ id: "atestado", rotulo: m.valor_atestado_centavos === null ? "Definir o atestado" : "Editar o atestado" }] : []),
    ...(!EXCECOES.includes(m.estado) ? [{ id: "assinatura", rotulo: "Registrar assinatura" }] : []),
    ...(m.final !== 1 && !EXCECOES.includes(m.estado) ? [{ id: "final", rotulo: "Marcar como medição final" }] : []),
    ...(m.final === 1 ? [{ id: "desfinal", rotulo: "Desmarcar a medição final" }] : []),
    ...(PROXIMOS[m.estado] ?? []).filter(e => e !== "recebida").map((e, i) =>
      ({ id: e, rotulo: e === "cancelada" ? "Cancelar a medição" : "Registrar desistência", perigo: true, separador: i === 0 })),
    ...(preso.length > 0 ? [{ id: "liberar", rotulo: "Liberar envio preso", separador: true }] : []),
  ];

  // ---------------------------------------------------------------- etapas
  const corpoEtapa1 = (
    <div className="med-etapa__corpo">
      <Espelho contratoId={contratoId} podeEditar={podeEditar} aoMudar={recarregar} medicao={{ id: m.id, tipo: m.tipo }} parte="espelho"
        abrirForm={m.estado === "prevista" && !espVigente} inicial={{ numero: m.numero, competencia: m.competencia }} />
    </div>
  );
  const corpoEtapa2 = (
    <div className="med-etapa__corpo">
      <Espelho contratoId={contratoId} podeEditar={podeEditar} aoMudar={recarregar} medicao={{ id: m.id, tipo: m.tipo }} parte="faturamento" />
    </div>
  );
  const corpoEtapa3 = (
    <div className="med-etapa__corpo">
      <div id="notas">
        {/* issue #188: a execucao e o reajuste da mesma competencia, um bloco para cada; a nota anexada num bloco vai
            para a medicao daquele bloco, e a FRC e' da medicao do bloco */}
        {metades.length > 0 ? (
          <div className="notas-blocos">
            {metades.map(x => {
              const mx = medicaoDa(x.medicao_id);
              return mx ? (
                <section key={`${x.medicao_id}-${versaoNotas}`} className="notas-bloco" aria-label={rotuloDoBloco(mx)}>
                  <Notas medicao={mx} rotulo={rotuloDoBloco(mx)} podeEditar={podeEditar && !FINAIS.includes(mx.estado)}
                    podeDesfazer={usuario.perfil === "admin" && !FINAIS.includes(mx.estado)}
                    aoMudar={() => { recarregar(); setVersaoFrc(v => v + 1); }} />
                  <FrcConsorcio medicaoId={mx.id} podeEditar={podeEditar && !FINAIS.includes(mx.estado)} versao={versaoFrc}
                    aoMudar={() => { recarregar(); setVersaoNotas(v => v + 1); }} />
                </section>
              ) : null;
            })}
          </div>
        ) : (
          <>
            <Notas key={versaoNotas} medicao={m} podeEditar={podeEditar && !FINAIS.includes(m.estado)}
              podeDesfazer={usuario.perfil === "admin" && !FINAIS.includes(m.estado)}
              aoMudar={() => { recarregar(); setVersaoFrc(v => v + 1); }} />
            <FrcConsorcio medicaoId={m.id} podeEditar={podeEditar && !FINAIS.includes(m.estado)} versao={versaoFrc}
              aoMudar={() => { recarregar(); setVersaoNotas(v => v + 1); }} />
          </>
        )}
      </div>
    </div>
  );
  const corpoEtapa4 = sit(4) === "feita" ? (
    <div className="med-etapa__corpo">
      {/* o historico dos envios so' depois de enviada: o nº do protocolo no orgao se registra aqui, com o comprovante */}
      <ProtocolosDaMedicao semCartao contratoId={contratoId} medicaoId={m.id} dados={protocolos.dados} erro={protocolos.erro}
        carregar={protocolos.carregar} podeEditar={podeEditar} aoMudar={() => void carregar().catch(() => {})}
        vazio={registrados.length > 0 ? "" : "Nenhum envio desta medição."}>
        {registrados.map(p => (
          <p key={`reg-${p.id}`}>
            Enviada em <span className="num">{fmtDataPura(p.data)}</span>
            {p.numero_oficio ? ` · ofício ${p.numero_oficio}` : ""}{p.numero_processo ? ` · processo ${p.numero_processo}` : ""}
            {" "}<Selo>Fora do sistema</Selo>
          </p>
        ))}
        {registrados.length > 0 && <NumeroDoOrgaoFora ms={grupo.filter(x => x.protocolos.some(p => !p.protocolo_id) && !FINAIS.includes(x.estado))} junta={!!par?.junta} podeEditar={podeEditar && !FINAIS.includes(m.estado)}
          aoMudar={() => { setFeito("Número gravado."); recarregar(); }} />}
        {/* outro protocolo feito fora (reprotocolo) numa medicao ja protocolada: confere as certidoes e pede a justificativa */}
        {podeEditar && !FINAIS.includes(m.estado) && (
          <div><button type="button" id="ato-fora" className="btn btn--pequeno" disabled={salvando} onClick={() => abrir("fora")}>Registrar protocolo feito fora</button></div>
        )}
      </ProtocolosDaMedicao>
    </div>
  ) : (
    <div className="med-etapa__corpo">
      <EtapaEnvio medicaoId={m.id} envios={envios.envios} erro={envios.erro} recarregarEnvios={envios.carregar} podeEditar={podeEditar}
        versaoDocs={versaoNotas + versaoFrc} aoAnexarItem={() => setVersaoFrc(v => v + 1)}
        aoMudar={aviso => { setErro(""); setFeito(aviso ?? ""); recarregar(); }}
        pronta={pronta} aoSemAOutra={() => abrir("sozinha")} />
    </div>
  );
  const corpoEtapa5 = (
    <div className="med-etapa__corpo">
      <EtapaPagamento grupo={grupo} junta={!!par?.junta} usuario={usuario}
        protocolos={protocolos.dados?.protocolos ?? []} aqui={aqui}
        aoReceber={x => { setAlvoRecebimento(x); abrir("recebimento"); }} />
    </div>
  );

  const selo = (nivel: string, texto: string) => (
    <span className={`selo selo--${nivel}`}><span className="selo__ponto" aria-hidden="true" /><span className="selo__texto">{texto}</span></span>
  );
  // o selo da etapa feita leva a data; a futura so' tem o selo "Libera depois da etapa N" (o corpo fica vazio)
  const seloEtapa: Record<number, React.ReactNode> = {
    1: espVigente ? selo("ok", `Gerado em ${fmtDataHora(espVigente.criado_em)}`)
      : m.espelho_em ? selo("ok", `Gerado em ${fmtDataHora(m.espelho_em)}`) : undefined,
    2: espVigente?.envio ? selo("ok", `Enviado ao faturamento em ${fmtDataHora(espVigente.envio.enviado_em)}`) : undefined,
  };
  const corpo = (n: number) => {
    if (n === 4 && sit(4) === "futura" && pronta) return corpoEtapa4;   // a saida de emergencia mora na linha do envio
    if (sit(n) === "futura") return null;
    return [corpoEtapa1, corpoEtapa2, corpoEtapa3, corpoEtapa4, corpoEtapa5][n - 1];
  };

  return (
    <>
      {cabeca}
      <div className="pagina med">
        <div className="med-cabeca">
          <div>
            <h1 title={`${obra} · ${titulo}`}>{titulo}</h1>
            <p className="med-meta">
              <span>{obra}</span>
              {cab && <span>{cab.orgao}</span>}
              <span className="num">{fmtCompetencia(m.competencia)}</span>
              {cab && <span>{cab.instrumento}</span>}
              {/* a cota, so' em consorcio, como a obra (principio 7) */}
              {cab && baseDosValores(cab.percentual_lotufo_bp) && <span>{baseDosValores(cab.percentual_lotufo_bp)}</span>}
            </p>
          </div>
          <MaisAcoes itens={acoes} desabilitado={salvando} aoEscolher={id => abrir(id as Painel)} />
        </div>

        {/* com uma janela aberta, o erro aparece dentro dela, perto de onde se agiu */}
        {erro && painel === null && <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erro}</p>}
        {/* regiao viva sempre montada: o leitor de tela so' anuncia o texto que CHEGA numa regiao ja' existente */}
        <p className={feito ? "notas__ok" : "sr-only"} role="status">{feito}</p>

        <div className="med-grade">
          <div className="med-principal">
            <Setas atual={atual} vendo={aberta} espera={!!esperaAqui} aoIr={n => setVendo(n === atual && atual !== 0 ? null : n)} />
            <FaixaVendo vendo={aberta} atual={atual} aoVoltar={() => setVendo(null)} />
            <EtapaCartao key={aberta} n={aberta} atual={atual} selo={seloEtapa[aberta]}>
              {corpo(aberta)}
            </EtapaCartao>
          </div>

          <aside className="med-lateral" aria-label="Resumo e linha do tempo">
            <ResumoMedicao m={m} execucao={execucao} reajuste={reajuste} outras={outras} passo={passo} aqui={aqui}
              contratoId={contratoId} podeEditar={podeEditar} salvando={salvando} aoEditarValor={() => abrir("protocolado")} />
            <LinhaDoTempo eventos={eventos} />
          </aside>
        </div>
      </div>

      {(painel === "protocolado" || painel === "atestado") && (
        <Janela titulo={painel === "protocolado" ? "Editar o valor" : "Editar o atestado"} aoFechar={fechar}>
          <FormValor m={m} campo={painel} salvando={salvando} agir={agir} aoFechar={fechar} erro={erro} />
        </Janela>
      )}
      {(painel === "cancelada" || painel === "desistida") && (
        <Janela titulo={painel === "cancelada" ? "Cancelar a medição" : "Registrar desistência"} aoFechar={fechar}>
          <FormEstado m={m} estado={painel} salvando={salvando} agir={agir} aoFechar={fechar} erro={erro} />
        </Janela>
      )}
      {/* F-92: medicao final (e desfazer) por formulario, no lugar de confirm/prompt do navegador */}
      {painel === "fora" && (
        <Janela titulo="Registrar protocolo feito fora do sistema" aoFechar={fechar}>
          <FormProtocoloManual contratoId={contratoId} m={m} salvando={salvando} agir={agir} aoFechar={fechar} erro={erro} />
        </Janela>
      )}
      {painel === "final" && (
        <Janela titulo="Marcar como medição final" aoFechar={fechar}>
          <FormFinal m={m} salvando={salvando} agir={agir} aoFechar={fechar} erro={erro} />
        </Janela>
      )}
      {painel === "assinatura" && (
        <Janela titulo="Registrar assinatura" aoFechar={fechar}>
          <FormAssinatura m={m} salvando={salvando} agir={agir} aoFechar={fechar} erro={erro} />
        </Janela>
      )}
      {painel === "desfinal" && (
        <Janela titulo="Desmarcar a medição final" aoFechar={fechar}>
          <FormDesmarcarFinal m={m} salvando={salvando} agir={agir} aoFechar={fechar} erro={erro} />
        </Janela>
      )}
      {painel === "recebimento" && alvoRecebimento && (
        <Janela titulo="Registrar recebimento" aoFechar={fechar}>
          <FormRecebimento m={alvoRecebimento} salvando={salvando} agir={agir} aoFechar={fechar} erro={erro} />
        </Janela>
      )}
      {painel === "sozinha" && pronta && (
        <Janela titulo={pronta.tipo === "execucao" ? "Enviar a medição sem o reajuste" : "Enviar o reajuste sem a medição"} aoFechar={fechar}>
          <FormSemAOutra pronta={pronta} salvando={salvando} agir={agir} aoFechar={fechar} erro={erro} />
        </Janela>
      )}
      {painel === "liberar" && (
        <Janela titulo="Liberar envio preso" aoFechar={fechar}>
          {preso.map(e => (
            <div key={e.chave} className="pilha">
              {preso.length > 1 && <p className="med-sub">{e.descricao}</p>}
              <LiberarEnvio tabela="protocolos" id={e.protocolo_id!} aoLiberar={recarregar} />
            </div>
          ))}
        </Janela>
      )}
    </>
  );
}


/** O nº do protocolo no orgao de um envio registrado fora do sistema: so' se digita aqui, na etapa 4. Onde o orgao
 *  junta medicao e reajuste (SINFRA, Pref. VG) o registro cobriu as duas e o numero e' um so'; onde separa (MTPAR,
 *  SES) cada medicao tem o SIGA dela, um campo por envio registrado por fora. */
function NumeroDoOrgaoFora({ ms, junta, podeEditar, aoMudar }: { ms: Medicao[]; junta: boolean; podeEditar: boolean; aoMudar: () => void }) {
  const unidades = junta ? [ms] : ms.map(x => [x]);
  return (
    <div className="pilha">
      {unidades.map(u => <CampoNumeroOrgao key={u.map(x => x.id).join("-")} ms={u} rotulo={unidades.length > 1 ? ` · ${tituloMedicao(u[0])}` : ""}
        podeEditar={podeEditar} aoMudar={aoMudar} />)}
    </div>
  );
}

function CampoNumeroOrgao({ ms, rotulo, podeEditar, aoMudar }: { ms: Medicao[]; rotulo: string; podeEditar: boolean; aoMudar: () => void }) {
  const atual = ms[0].protocolos.filter(p => !p.protocolo_id).at(-1)?.numero_processo ?? "";
  const [numero, setNumero] = useState(atual);
  const [erro, setErro] = useState("");
  const [ocupado, setOcupado] = useState(false);
  const id = `numero-orgao-fora-${ms[0].id}`;
  async function salvar(ev: React.FormEvent) {
    ev.preventDefault();
    setOcupado(true); setErro("");
    const gravadas: string[] = [];
    try {
      for (const x of ms) {
        await api(`/api/notas/${x.id}/numero-orgao`, { method: "POST", body: JSON.stringify({ numero: numero.trim() }) });
        gravadas.push(tituloMedicao(x));
      }
      aoMudar();
    } catch (e) {
      setErro(gravadas.length > 0 ? `${mensagemDeErro(e)} O número já ficou na ${gravadas.join(" e na ")}; salve de novo para a outra.` : mensagemDeErro(e));
      if (gravadas.length > 0) aoMudar();   // a pagina le de novo e mostra o que ja' foi gravado
    } finally { setOcupado(false); }
  }
  return (
    <form className="form-inline" onSubmit={salvar}>
      <div className="campo">
        <label className="campo__rotulo" htmlFor={id}>Nº do protocolo no órgão{rotulo}</label>
        <input id={id} name="numero_orgao" autoComplete="off" spellCheck={false} className="entrada--media" maxLength={100}
          value={numero} disabled={!podeEditar} onChange={ev => setNumero(ev.target.value)} />
      </div>
      {podeEditar && <button type="submit" className="btn btn--pequeno" disabled={ocupado || !numero.trim()}>{ocupado ? "Salvando…" : "Salvar"}</button>}
      {erro && <span className="notas__diverge">{erro}</span>}
    </form>
  );
}

/** Etapa 5: uma linha por pagamento -- uma so' onde o orgao junta medicao e reajuste, duas onde separa --, com as notas,
 *  o valor, quando foi ao orgao (e o nº do protocolo, que se registra na etapa 4) e o que ja' foi pago. */
function EtapaPagamento({ grupo, junta, usuario, protocolos, aqui, aoReceber }: {
  grupo: Medicao[]; junta: boolean; usuario: Usuario;
  protocolos: { numero_orgao: string | null; situacao: string; medicoes: { id: number }[] }[]; aqui: Rota; aoReceber: (m: Medicao) => void;
}) {
  const linhas = junta && grupo.length > 1 ? [grupo] : grupo.map(x => [x]);
  return (
    <div className="pilha">
      <div className="med-caixa">
        <table className="tabela envios">
          <thead>
            <tr><th>Envio</th><th>Nota fiscal</th><th className="col-num">Valor</th><th>Enviado ao órgão</th><th>Pagamento</th></tr>
          </thead>
          <tbody>
            {linhas.map(g => {
              const rotulo = g.length > 1 ? "Medição + Reajuste" : g[0].tipo === "reajuste" ? "Reajuste" : g[0].tipo === "projeto" ? "Medição de projeto" : "Medição";
              const notas = g.flatMap(x => x.notas ?? []);
              const nfsDocs = g.flatMap(x => (x.documentos ?? []).filter(d => d.tipo_doc === "nfs" && d.numero_nf));
              const valor = g.reduce((s, x) => s + (x.valor_protocolado_centavos ?? 0), 0);
              const enviada = g.flatMap(x => x.protocolos.map(p => p.data)).sort().at(-1);
              const numero = g.flatMap(x => [
                ...protocolos.filter(p => p.situacao === "enviado" && p.medicoes.some(y => y.id === x.id)).map(p => p.numero_orgao),
                ...x.protocolos.map(p => p.numero_processo)]).find(Boolean) ?? null;
              const protocolada = g.some(x => ["protocolada", "nf_emitida"].includes(x.estado));
              const recebida = g.every(x => x.estado === "recebida");
              const encerrada = g.every(x => ["cancelada", "desistida"].includes(x.estado));
              const recebidoParcial = notas.some(n => n.recebido_centavos > 0);
              return (
                <tr key={g.map(x => x.id).join("-")}>
                  <td data-rotulo="Envio"><strong>{rotulo}</strong></td>
                  <td data-rotulo="Nota fiscal">
                    <div className="envios__nfs">
                      {notas.length === 0 && nfsDocs.length > 0 && nfsDocs.map(d => <span key={d.id}>NF {d.numero_nf}</span>)}
                      {notas.length === 0 && nfsDocs.length === 0 ? <span>—</span> : notas.map(n => (
                        <span key={n.nota_id}>NF {Number(n.numero) || n.numero}</span>
                      ))}
                    </div>
                  </td>
                  <td data-rotulo="Valor" className="col-num">{brl(valor)}</td>
                  <td data-rotulo="Enviado ao órgão">
                    {enviada ? (
                      <>
                        <span className="num">{fmtDataPura(enviada)}</span>
                        <span className="res-nota">
                          {numero ? `protocolo ${numero}` : <Link className="link" para={aqui} secao="etapa-4">Registrar o protocolo</Link>}
                        </span>
                      </>
                    ) : <span>—</span>}
                  </td>
                  <td data-rotulo="Pagamento">
                    {recebida ? <><Selo classe="selo--ok">Recebido</Selo>{g[0].recebida_em && <span className="res-nota">em {fmtDataPura(g[0].recebida_em)}</span>}</>
                      : protocolada && !encerrada
                        ? <Selo classe={recebidoParcial ? "selo--ok" : "selo--atencao"}>{recebidoParcial ? "Recebido em parte" : "Aguardando o órgão"}</Selo>
                        : <span>—</span>}
                    {/* issue #53: o recebimento a mao e' so' do admin (o servidor recusa outro perfil) */}
                    {usuario.perfil === "admin" && g.filter(x => (PROXIMOS[x.estado] ?? []).includes("recebida")).map(x => (
                      <div key={x.id} className="envios__receber">
                        <button type="button" className="btn btn--pequeno" title={tituloMedicao(x)} onClick={() => aoReceber(x)}>Registrar recebimento</button>
                      </div>
                    ))}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

