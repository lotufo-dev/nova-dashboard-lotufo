import { useCallback, useEffect, useRef, useState } from "react";
import CaixaAviso from "./CaixaAviso";
import { baseDosValores } from "./formato";
import { api, mensagemDeErro } from "./api";
import Espelho, { type Referencia } from "./Espelho";
import { CartaoPlanilha, type DetalhePlanilha, NovaPlanilhaCarta, revisaoPendente, type TipoPlanilha } from "./PlanilhaCarta";
import { EtapaEnvio, useEnvios } from "./EtapaEnvio";
import { diaMes, FaixaPasso, PassoCartao, passoDe as passoDoEstado, passoInicial, Passos, passosDa, situacaoDoPasso } from "./Passos";
import PassoAnalise from "./PassoAnalise";
import PassoPagamento from "./PassoPagamento";
import { FrcConsorcio } from "./Frc";
import { IconeAlerta } from "./icones";
import Janela from "./Janela";
import LiberarEnvio from "./LiberarEnvio";
import type { Usuario } from "./Login";
import MaisAcoes, { type ItemAcao } from "./MaisAcoes";
import { DA_PLANILHA, eventosDaMedicao, EXCECOES, FINAIS, metadeQueEspera, passoDe, PROXIMOS, rotuloDoBloco, tituloMedicao,
         type EspelhoResumo, type MedicaoBase, type ParDaMedicao } from "./medicao";
import { FormBoletim } from "./Boletim";
import { FormAssinatura, FormDesmarcarFinal, FormEstado, FormFinal, FormProtocoloManual, FormRecebimento, FormSemAOutra, FormValor, valorEditavel, type Agir } from "./MedicaoAtos";
import { brl, type Medicao } from "./Medicoes";
import { Notas } from "./Notas";
import { ProtocolosDaMedicao, useProtocolos } from "./Protocolo";
import { LinhaDoTempo, ResumoMedicao } from "./ResumoLateral";
import { ir, type Origem, type Rota, useRota } from "./rota";
import { Link } from "./Link";
import Selo from "./Selo";
import { fmtDataHora, fmtDataPura, fmtMesExtenso } from "./tempo";
import { Migalhas, VoltarOrigem } from "./Topo";
import "./etapas.css";
import "./passos.css";

// Pagina da obra em medicao (issue #508, aprovada em 06/11/2026): "Nª Medição + Reajuste" numa pagina so', com o
// cabecalho (obra, medicao, mes e o valor grande), a BARRA DE PASSOS -- Planilha e carta, Analise do orgao,
// Espelhos, Notas, Envio da nota e Pagamento; a MT-PAR comeca em Espelhos -- e so' o passo da vez aberto (os feitos
// abrem no lugar dele, com a faixa para voltar). Resumo e Linha do tempo ficam abaixo. Cada acao se faz num lugar
// so', no passo onde acontece; as listas de Medicoes, o Inicio e a obra so' levam ate' aqui (#passo-N abre o passo;
// as ancoras antigas #etapa-N continuam valendo).

type Cabecalho = { obra: string; orgao: string; instrumento: string; percentual_lotufo_bp: number };
type LinhaAndamento = { id: number; proximo_passo: string; desde: string };
type Painel = "fora" | "protocolado" | "atestado" | "recebimento" | "cancelada" | "desistida" | "final" | "desfinal" | "assinatura" | "boletim" | "sozinha" | "liberar" | null;

// Ancoras antigas (#notas, #espelho, #protocolo e as #etapa-N do trilho de cinco setas, que o Inicio, as listas e o
// SIGA ainda usam) abrem o passo onde a coisa mora hoje.
const SECAO_PASSO: Record<string, number> = { espelho: 3, notas: 4, protocolo: 5, "planilha-carta": 1,
  "etapa-1": 3, "etapa-2": 3, "etapa-3": 4, "etapa-4": 5, "etapa-5": 6 };

export default function MedicaoPagina({ contratoId, medicaoId, usuario, origem }:
    { contratoId: number; medicaoId: number; usuario: Usuario; origem: Origem | null }) {
  const podeEditar = usuario.perfil === "engenharia" || usuario.perfil === "admin";
  const { secao } = useRota();
  const [cab, setCab] = useState<Cabecalho | null>(null);
  const [medicoes, setMedicoes] = useState<Medicao[] | null>(null);
  const [andamento, setAndamento] = useState<LinhaAndamento[]>([]);
  const [espelhos, setEspelhos] = useState<EspelhoResumo[]>([]);
  // issue #289: a planilha/carta e' o 1o passo so' na obra que gera a medicao pelo espelho (regra ativa)
  const [regraAtiva, setRegraAtiva] = useState(false);
  // revisao da planilha/carta registrada e nao enviada: o espelho espera o envio dela (PR #382, rodada extra)
  // so' libera o espelho depois de o cartao confirmar que nao ha' revisao pendente (issue #384)
  // a conferencia vale so' para a medicao e o estado em que o cartao a fez: trocar um dos dois a reinicia
  const [tentativa, setTentativa] = useState(0);
  const [revisaoDe, setRevisaoDe] = useState<{ chave: string; valor: "pendente" | "livre" | "falhou" } | null>(null);
  // #460 (gate Sol, PR #528): a planilha/carta so' gerada com o envio saindo pelo sistema (ou preso) nao mostra o espelho
  const [reservaDe, setReservaDe] = useState<{ chave: string; reservado: boolean } | null>(null);
  // issue #188: a execucao e o reajuste da mesma competencia (as notas dos dois, a espera e a liberacao)
  const [par, setPar] = useState<ParDaMedicao | null>(null);
  const [erro, setErro] = useState("");
  const [feito, setFeito] = useState("");
  const [salvando, setSalvando] = useState(false);
  const [painel, setPainel] = useState<Painel>(null);
  const [alvoRecebimento, setAlvoRecebimento] = useState<Medicao | null>(null);
  // a etapa aberta no lugar da atual (clique na seta ou ancora); null = a da vez
  const [vendo, setVendo] = useState<number | null>(null);
  // #508: no passo 2, "Gerar o espelho sem o boletim" abre o formulario do espelho embaixo da resposta do orgao
  const [semBoletim, setSemBoletim] = useState(false);
  const protocolos = useProtocolos(contratoId);
  const geracao = useRef(0);
  // Notas e FRC leem o mesmo anexo: o que um anexa, o outro recarrega
  const [versaoNotas, setVersaoNotas] = useState(0);
  const [versaoFrc, setVersaoFrc] = useState(0);
  // #508: cada leitura da lista da obra relê tambem a planilha/carta da medicao (a conferencia da revisao)
  const [leituraLista, setLeituraLista] = useState(0);

  const m = medicoes?.find(x => x.id === medicaoId) ?? null;
  // a execucao e o reajuste do mesmo numero formam a pagina "Nª Medição + Reajuste"
  // #557: so' a metade valida forma o par (como notas_envio.par()): a cancelada ou desistida fica de fora do grupo
  // (total, pagamento, envio) e aparece em "Da mesma competência"
  const valida = (x: Medicao) => !["cancelada", "desistida"].includes(x.estado);
  const execucao = !m || m.tipo === "projeto" ? null : m.tipo === "execucao" ? m : medicoes?.find(x => x.numero === m.numero && x.tipo === "execucao" && valida(x)) ?? null;
  const reajuste = !m || m.tipo === "projeto" ? null : m.tipo === "reajuste" ? m : medicoes?.find(x => x.numero === m.numero && x.tipo === "reajuste" && valida(x)) ?? null;
  const doPar = !!execucao && !!reajuste && valida(execucao) && valida(reajuste);
  const grupo = doPar ? [execucao, reajuste] : m ? [m] : [];
  const envios = useEnvios(grupo.map(x => x.id));

  // Tudo o que a pagina le alem dos cartoes que se leem sozinhos (espelho, notas, protocolos).
  const carregar = useCallback(async () => {
    const g = geracao.current;
    const [lista, abertas, esp, duas] = await Promise.all([
      api<Medicao[]>(`/api/contratos/${contratoId}/medicoes`),
      api<LinhaAndamento[]>(`/api/medicoes/andamento?contrato_id=${contratoId}`).catch(() => []),
      api<{ espelhos: EspelhoResumo[]; regra?: { situacao: string } | null }>(`/api/contratos/${contratoId}/espelho`)
        .catch(() => ({ espelhos: [], regra: null })),
      // sem o par a pagina fica como antes (um bloco so'): a falha aqui nao derruba a medicao
      api<ParDaMedicao>(`/api/medicoes/${medicaoId}/par`).catch(() => null),
    ]);
    if (g !== geracao.current) return;
    setMedicoes(lista); setLeituraLista(n => n + 1); setAndamento(abertas); setEspelhos(esp.espelhos ?? []); setRegraAtiva(esp.regra?.situacao === "ativa");
    setPar(duas && Array.isArray(duas.metades) ? duas : null);
  }, [contratoId, medicaoId]);

  useEffect(() => {
    geracao.current += 1;
    const g = geracao.current;
    setCab(null); setMedicoes(null); setPar(null); setErro(""); setFeito(""); setPainel(null); setVendo(null); setSemBoletim(false);
    api<Cabecalho>(`/api/contratos/${contratoId}/cabecalho`).then(c => { if (g === geracao.current) setCab(c); }).catch(() => {});
    carregar().catch(e => { if (g === geracao.current) setErro(mensagemDeErro(e)); });
    return () => { geracao.current += 1; };
  }, [contratoId, medicaoId, carregar]);

  // A ancora (#passo-5, ou as antigas #etapa-4, #notas...) abre o passo na pagina.
  useEffect(() => {
    const n = /^passo-([1-6])$/.exec(secao);
    const alvo = n ? Number(n[1]) : SECAO_PASSO[secao];
    if (alvo) setVendo(alvo);
  }, [secao]);

  // #508: a pagina le a planilha/carta (o mesmo detalhe que o cartao le) enquanto a medicao esta' nos passos dela: o
  // passo 2 mostra o envio e o SIGA, a revisao registrada e nao enviada devolve a vez ao passo 1, e o espelho espera a
  // conferencia (#384) mesmo com o cartao fora da tela. O cartao, quando aberto, avisa tambem; a ultima leitura vale.
  const comPlanilha = !!m && (m.tipo === "execucao" || m.tipo === "projeto");
  const enviada = m?.estado === "planilha_enviada" || m?.estado === "boletim_recebido";
  const gerada = m?.estado === "planilha_gerada";
  const chaveRevisao = m ? `${m.id}:${m.estado}` : "";
  const [planilhaDe, setPlanilhaDe] = useState<{ chave: string; d: DetalhePlanilha } | null>(null);
  const lerPlanilha = comPlanilha && (enviada || gerada);
  // relida a cada leitura da lista da obra (toda acao recarrega a pagina)
  useEffect(() => {
    if (!lerPlanilha) return;
    let vivo = true;
    const chave = chaveRevisao;
    api<DetalhePlanilha>(`/api/medicoes/${medicaoId}`).then(d => {
      // detalhe sem as versoes nao confere nada: a conferencia fica com o cartao
      if (!vivo || !Array.isArray(d?.planilhas) || !d.envio_planilha) return;
      setPlanilhaDe({ chave, d });
      setRevisaoDe({ chave, valor: revisaoPendente(d) ? "pendente" : "livre" });
      setReservaDe({ chave, reservado: !!d.envio_planilha?.reserva });
    }).catch(() => { if (vivo) setRevisaoDe({ chave, valor: "falhou" }); });
    return () => { vivo = false; };
  }, [lerPlanilha, chaveRevisao, medicaoId, leituraLista, tentativa]);
  const planilha = planilhaDe?.chave === chaveRevisao ? planilhaDe.d : null;
  const revisao = revisaoDe?.chave === chaveRevisao ? revisaoDe.valor : "conferindo";

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
  // #359: o aprovado mudou depois do espelho (o servidor compara com o espelho vigente): uma linha por medicao da
  // pagina, com o titulo dela no par, para a acao de uma nao esconder a da outra (rodada 2 da PR #474)
  const desatualizadas = grupo.filter(x => x.espelho_desatualizado);

  // #508: a obra tem os passos "Planilha e carta" e "Análise do órgão" quando a planilha/carta e' o 1o passo da
  // medicao (execucao e projeto, regra de espelho ativa ou medicao que ja' nasceu dela) e vai ao orgao (nunca na MT-PAR)
  const temPassosPlanilha = !!m && comPlanilha && m.com_envio_planilha !== false
    && (regraAtiva || DA_PLANILHA.includes(m.estado) || !!m.planilha_enviada_em);
  const passos = passosDa(temPassosPlanilha);
  // quando o passo da vez muda (enviou, a nota chegou), a pagina acompanha: o clique num passo so' vale ate' la'.
  // A revisao registrada e nao enviada devolve a vez ao passo 1 (e' la' que ela sai).
  const atual = !m ? 0 : temPassosPlanilha && m.estado === "planilha_enviada" && revisao === "pendente" ? 1
    : passoDoEstado(m.estado, temPassosPlanilha);
  // enquanto a conferencia da revisao nao volta, o passo da vez ainda nao esta' firme: a chegada dela nao descarta o
  // passo aberto pela ancora (#passo-2, #etapa-N do Inicio e do SIGA)
  const atualFirme = !(temPassosPlanilha && m?.estado === "planilha_enviada" && revisao === "conferindo");
  const atualAnterior = useRef<number | null>(null);
  useEffect(() => {
    if (!m || !atualFirme) return;
    if (atualAnterior.current !== null && atualAnterior.current !== atual) setVendo(null);
    atualAnterior.current = atual;
  }, [m, atual, atualFirme]);

  const cabeca = (
    <header className="topbar topbar--detalhe">
      <div className="topbar__trilha">
        <VoltarOrigem origem={origem} alemDe={["obras", "medicoes"]} />
        <Migalhas origem={origem} itens={[{ rotulo: "Medições", para: { tela: "medicoes", aba: "em-andamento" } },
          { rotulo: obra, para: { tela: "obra", id: contratoId, aba: "ficha" } }, { rotulo: titulo }]} />
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

  const sit = (n: number) => situacaoDoPasso(n, atual);
  // passo fora da barra desta obra (ancora antiga, MT-PAR) abre o primeiro dela
  const aberta = vendo !== null && passos.includes(vendo) ? vendo : passoInicial(atual, !!m.nota_emitida_em, passos);
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
  // #290: o boletim do orgao (spec §2.1 passo 3) vem depois do envio da planilha/carta; na planilha enviada ele mora
  // no passo 2 ("Aprovou a medição", #508), nos outros estados (prevista do fluxo antigo, glosa depois do espelho, a
  // MT-PAR sem o passo 2) em Mais acoes. Com revisao registrada e nao enviada a vez volta ao passo 1 e o passo 2 nao
  // abre: o boletim (o orgao pode aprovar a versao que recebeu) volta a Mais acoes (revisor, PR #553). A assinatura
  // do DocuSign e' a do boletim: so' aparece depois dele.
  const comBoletim = (m.boletins ?? []).some(b => b.tem_arquivo);
  const boletimNaEtapa = podeEditar && m.estado === "planilha_enviada" && temPassosPlanilha && atual === 2;
  const podeBoletim = podeEditar && !EXCECOES.includes(m.estado) && m.estado !== "planilha_gerada";
  const acoes: ItemAcao[] = !podeEditar ? [] : [
    ...(valorEditavel(m, "atestado", podeEditar) ? [{ id: "atestado", rotulo: m.valor_atestado_centavos === null ? "Definir o atestado" : "Editar o atestado" }] : []),
    ...(podeBoletim && !boletimNaEtapa ? [{ id: "boletim", rotulo: comBoletim ? "Registrar boletim novo" : "Registrar boletim" }] : []),
    ...(!EXCECOES.includes(m.estado) && comBoletim ? [{ id: "assinatura", rotulo: "Registrar assinatura" }] : []),
    ...(m.final !== 1 && !EXCECOES.includes(m.estado) ? [{ id: "final", rotulo: "Marcar como medição final" }] : []),
    ...(m.final === 1 ? [{ id: "desfinal", rotulo: "Desmarcar a medição final" }] : []),
    ...(PROXIMOS[m.estado] ?? []).filter(e => e !== "recebida").map((e, i) =>
      ({ id: e, rotulo: e === "cancelada" ? "Cancelar a medição" : "Registrar desistência", perigo: true, separador: i === 0 })),
    ...(preso.length > 0 ? [{ id: "liberar", rotulo: "Liberar envio preso", separador: true }] : []),
  ];

  // ---------------------------------------------------------------- passos
  // issue #289: a planilha/carta vem antes do espelho (execucao e projeto, na obra com regra de espelho ativa; o
  // reajuste continua pelo espelho). A prevista abre o formulario dela; registrada, o cartao dela (#508: pacote do
  // envio e e-mail ao orgao) e' o passo 1 -- na MT-PAR, sem os passos 1 e 2, fica no alto do passo 3. O espelho segue
  // a planilha enviada (com ou sem o boletim da #284) ou so' gerada, sem o envio registrado (#460, decisao do Leo de
  // 07/11/2026: a operacao ainda envia ao orgao por fora; segue sem boletim, com justificativa).
  // quem so' consulta continua vendo o espelho da prevista, so' para ler (sem formulario)
  const novaPlanilha = podeEditar && regraAtiva && comPlanilha && m.estado === "prevista" && !espVigente;
  // a so' gerada espera o cartao dizer que nao ha' envio saindo; a revisao dela nao conta (nunca foi enviada)
  const geradaLivre = reservaDe?.chave === chaveRevisao && !reservaDe.reservado && revisao !== "falhou";
  // so' as medicoes com cartao esperam a conferencia dele; as outras (reajuste) seguem direto pelo espelho
  const espelhoEspera = comPlanilha && ((enviada && revisao !== "livre") || (gerada && !geradaLivre));
  // #514: o total do espelho se confere com o aprovado (o boletim) de cada medicao dele; sem aprovado, com o pedido
  const referencias: Record<number, Referencia | null> = Object.fromEntries(medicoes.map(x => [x.id,
    x.valor_atestado_centavos !== null ? { valor: x.valor_atestado_centavos, fonte: "aprovado" as const }
      : x.valor_protocolado_centavos !== null ? { valor: x.valor_protocolado_centavos, fonte: "pedido" as const } : null]));
  const formEspelho = (
    <Espelho contratoId={contratoId} podeEditar={podeEditar} aoMudar={recarregar} medicao={{ id: m.id, tipo: m.tipo }} parte="espelho" referencias={referencias}
      abrirForm={podeEditar && ["prevista", "planilha_gerada", "planilha_enviada", "boletim_recebido"].includes(m.estado) && !espVigente} inicial={{ numero: m.numero, competencia: m.competencia }} />
  );
  const blocoPlanilha = (
    <>
      {novaPlanilha && (
        <NovaPlanilhaCarta contratoId={contratoId} tipo={m.tipo as TipoPlanilha} inicial={{ numero: m.numero, competencia: m.competencia }}
          aoRegistrar={() => { setFeito("Planilha/carta registrada."); recarregar(); }} />
      )}
      {comPlanilha && m.estado !== "prevista" && <CartaoPlanilha key={tentativa} medicaoId={m.id} estado={m.estado} podeEditar={podeEditar} aoMudar={recarregar}
        aoRevisaoPendente={p => setRevisaoDe({ chave: chaveRevisao, valor: p === null ? "falhou" : p ? "pendente" : "livre" })}
        aoEnvioReservado={r => setReservaDe({ chave: chaveRevisao, reservado: r })} />}
      {comPlanilha && (enviada || gerada) && revisao === "falhou" && (
        <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />Não foi possível conferir a planilha/carta.
          <button type="button" className="btn btn--pequeno" onClick={() => { setRevisaoDe(null); setTentativa(t => t + 1); }}>Tentar de novo</button></p>
      )}
      {gerada && !espelhoEspera && <CaixaAviso nivel="atencao">Envio da planilha/carta não registrado.</CaixaAviso>}
    </>
  );
  // passo 1: a planilha/carta; a so' gerada sem o envio registrado segue para o espelho daqui mesmo (#460)
  const corpoPasso1 = (
    <section className="med-passo" id="passo-1" aria-labelledby="passo-1-titulo">
      <h2 className="sr-only" id="passo-1-titulo">Planilha e carta</h2>
      {blocoPlanilha}
      {(gerada || (m.estado === "prevista" && !novaPlanilha)) && !espelhoEspera && formEspelho}
    </section>
  );
  // passo 2: a analise do orgao; o espelho sem o boletim (#284) continua possivel, a pedido
  const corpoPasso2 = (
    <section className="med-passo" id="passo-2" aria-labelledby="passo-2-titulo">
      <h2 className="sr-only" id="passo-2-titulo">Análise do órgão</h2>
      <PassoAnalise m={m} planilha={planilha} podeEditar={podeEditar} salvando={salvando} agir={agir}
        aoMudarSiga={() => { setFeito("Número gravado."); recarregar(); }}
        aoRevisar={() => { setRevisaoDe(null); setPlanilhaDe(null); }} />
      {comPlanilha && enviada && revisao === "falhou" && (
        <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />Não foi possível conferir a planilha/carta.
          <button type="button" className="btn btn--pequeno" onClick={() => { setRevisaoDe(null); setTentativa(t => t + 1); }}>Tentar de novo</button></p>
      )}
      {podeEditar && m.estado === "planilha_enviada" && !espelhoEspera && !espVigente && (
        semBoletim ? formEspelho
          : <div><button type="button" className="botao-link" onClick={() => setSemBoletim(true)}>Gerar o espelho sem o boletim</button></div>
      )}
    </section>
  );
  // passo 3: o espelho e o envio dele ao faturamento (as etapas 1 e 2 do trilho antigo, numa so')
  const antesDoEspelho = ["prevista", ...DA_PLANILHA].includes(m.estado);
  // #514: a tabela dos espelhos com o total conferido a' esquerda; "Enviar ao faturamento" a' direita
  const corpoPasso3 = (
    <section className="med-passo" id="passo-3" aria-labelledby="passo-3-titulo">
      <h2 className="sr-only" id="passo-3-titulo">Espelhos</h2>
      {!temPassosPlanilha && blocoPlanilha}
      {/* depois do boletim o cartao mora no passo 1: a falha da conferencia avisa aqui, onde o espelho esperaria */}
      {temPassosPlanilha && comPlanilha && enviada && revisao === "falhou" && (
        <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />Não foi possível conferir a planilha/carta.
          <button type="button" className="btn btn--pequeno" onClick={() => { setRevisaoDe(null); setTentativa(t => t + 1); }}>Tentar de novo</button></p>
      )}
      {!novaPlanilha && !espelhoEspera && (
        <div className={antesDoEspelho ? undefined : "med-duas"}>
          <section className="cartao med-painel" aria-labelledby="espelhos-titulo">
            <h3 className="med-painel__titulo" id="espelhos-titulo">Espelhos
              {/* a data do espelho vigente (a versao mais nova desta medicao) */}
              {(espVigente || m.espelho_em) && <Selo classe="selo--ok">Gerado em {fmtDataHora(espVigente?.criado_em ?? m.espelho_em!)}</Selo>}</h3>
            {formEspelho}
          </section>
          {!antesDoEspelho && (
            <section className="cartao med-painel" aria-labelledby="faturamento-titulo">
              <h3 className="med-painel__titulo" id="faturamento-titulo">Enviar ao faturamento</h3>
              <Espelho contratoId={contratoId} podeEditar={podeEditar} aoMudar={recarregar} medicao={{ id: m.id, tipo: m.tipo }} parte="faturamento" />
            </section>
          )}
        </div>
      )}
    </section>
  );
  // #514: a nota de cada espelho a' esquerda (soltar os PDFs) e, em consorcio, a "Fatura do consórcio" a' direita
  const notasDe = (mx: Medicao, rotulo?: string) => (
    <div className="med-duas">
      <section className="cartao med-painel" aria-label={rotulo ? `Notas fiscais: ${rotulo}` : "Notas fiscais"}>
        <h3 className="med-painel__titulo">Notas fiscais</h3>
        <Notas medicao={mx} rotulo={rotulo} podeEditar={podeEditar && !FINAIS.includes(mx.estado)}
          podeDesfazer={usuario.perfil === "admin" && !FINAIS.includes(mx.estado)}
          aoMudar={() => { recarregar(); setVersaoFrc(v => v + 1); }} />
      </section>
      <FrcConsorcio medicaoId={mx.id} podeEditar={podeEditar && !FINAIS.includes(mx.estado)} versao={versaoFrc}
        aoMudar={() => { recarregar(); setVersaoNotas(v => v + 1); }} />
    </div>
  );
  const corpoPasso4 = (
    <section className="med-passo" id="passo-4" aria-labelledby="passo-4-titulo">
      <h2 className="sr-only" id="passo-4-titulo">Notas</h2>
      <div id="notas">
        {/* issue #188: a execucao e o reajuste da mesma competencia, um bloco para cada; a nota anexada num bloco vai
            para a medicao daquele bloco, e a FRC e' da medicao do bloco */}
        {metades.length > 0 ? (
          <div className="notas-blocos">
            {metades.map(x => {
              const mx = medicaoDa(x.medicao_id);
              return mx ? (
                <section key={`${x.medicao_id}-${versaoNotas}`} className="notas-bloco" aria-label={rotuloDoBloco(mx)}>
                  {notasDe(mx, rotuloDoBloco(mx))}
                </section>
              ) : null;
            })}
          </div>
        ) : (
          <div key={versaoNotas}>{notasDe(m)}</div>
        )}
      </div>
    </section>
  );
  const corpoPasso5 = sit(5) === "feito" ? (
    <section className="med-passo" id="passo-5" aria-labelledby="passo-5-titulo">
      <h2 className="sr-only" id="passo-5-titulo">Envio da nota</h2>
      <div className="cartao med-painel">
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
    </section>
  ) : (
    <section className="med-passo" id="passo-5" aria-labelledby="passo-5-titulo">
      <h2 className="sr-only" id="passo-5-titulo">Envio da nota</h2>
      <EtapaEnvio medicaoId={m.id} envios={envios.envios} erro={envios.erro} recarregarEnvios={envios.carregar} podeEditar={podeEditar}
        versaoDocs={versaoNotas + versaoFrc} aoAnexarItem={() => setVersaoFrc(v => v + 1)}
        aoMudar={aviso => { setErro(""); setFeito(aviso ?? ""); recarregar(); }}
        pronta={pronta} aoSemAOutra={() => abrir("sozinha")} />
    </section>
  );
  // o valor grande do cabecalho: o da pagina (medicao + reajuste somados no par), cheio; o passo 6 mostra o mesmo
  const valores = grupo.map(x => x.valor_protocolado_centavos).filter((v): v is number => v !== null);
  const valor = valores.length > 0 ? valores.reduce((a, b) => a + b, 0) : null;
  const corpoPasso6 = (
    <PassoPagamento grupo={grupo} junta={!!par?.junta} usuario={usuario}
      protocolos={protocolos.dados?.protocolos ?? []} aqui={aqui} percentualBp={cab?.percentual_lotufo_bp ?? null} total={valor}
      aoReceber={x => { setAlvoRecebimento(x); abrir("recebimento"); }} />
  );

  const corpo = (n: number) => {
    if (n === 5 && sit(5) === "futuro" && pronta) return corpoPasso5;   // a saida de emergencia mora na linha do envio
    if (sit(n) === "futuro") return null;
    return [corpoPasso1, corpoPasso2, corpoPasso3, corpoPasso4, corpoPasso5, corpoPasso6][n - 1];
  };
  // a data de cada passo feito, na barra
  const ultimoBoletim = (m.boletins ?? []).filter(b => b.atestado_em).at(-1);
  const datas: Record<number, string | null> = {
    1: diaMes(m.planilha_ultimo_envio_em ?? m.planilha_enviada_em), 2: diaMes(ultimoBoletim?.atestado_em ?? m.atestado_em),
    3: diaMes(espVigente?.envio?.enviado_em), 4: diaMes(m.nota_emitida_em),
    5: diaMes(m.protocolos.map(p => p.data).sort().at(-1)), 6: diaMes(m.recebida_em),
  };
  // #514: todo passo aberto tem estrutura propria; so' o futuro (sem corpo) fica no cartao "Libera depois do passo N"
  const proprio = sit(aberta) !== "futuro" || (aberta === 5 && !!pronta);

  return (
    <>
      {cabeca}
      <div className="pagina med">
        <div className="med-topo">
          <div className="med-topo__id">
            <h1 title={`${obra} · ${titulo}`}>{obra}</h1>
            <p className="med-meta">
              <span>{titulo}</span>
              <span>{fmtMesExtenso(m.competencia)} de {m.competencia.slice(0, 4)}</span>
              {cab && <span>{cab.orgao}</span>}
              {/* a cota, so' em consorcio, como a obra (principio 7) */}
              {cab && baseDosValores(cab.percentual_lotufo_bp) && <span>{baseDosValores(cab.percentual_lotufo_bp)}</span>}
            </p>
          </div>
          <div className="med-topo__dir">
            <p className="med-valor" aria-label={`Valor: ${brl(valor)}`}>{brl(valor)}</p>
            <MaisAcoes itens={acoes} desabilitado={salvando} aoEscolher={id => abrir(id as Painel)} />
          </div>
        </div>

        {/* com uma janela aberta, o erro aparece dentro dela, perto de onde se agiu */}
        {erro && painel === null && <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erro}</p>}
        {/* regiao viva sempre montada: o leitor de tela so' anuncia o texto que CHEGA numa regiao ja' existente */}
        <p className={feito ? "notas__ok" : "sr-only"} role="status">{feito}</p>
        {desatualizadas.map(x => {
          const nota = x.espelho_desatualizado === "nota_emitida";
          const frase = x.espelho_desatualizado === "nao_conferido" ? "não foi possível conferir o valor do espelho antigo"
            : nota ? "o aprovado mudou depois do espelho e a nota já foi emitida" : "o aprovado mudou depois do espelho";
          const comeco = grupo.length > 1 ? `${tituloMedicao(x)}: ${frase}, ` : `${frase.charAt(0).toUpperCase()}${frase.slice(1)}: `;
          return (
            <CaixaAviso key={x.id} nivel="atencao">
              {/* abre o passo tambem quando a ancora ja' e' a dele (o efeito da secao so' roda quando ela muda) */}
              {comeco}<Link className="link" para={aqui} secao={nota ? "notas" : "espelho"}
                ir={(p, o) => { setVendo(nota ? 4 : 3); ir(p, o); }}>{nota ? "ver as notas" : "gere o espelho de novo"}</Link>
            </CaixaAviso>
          );
        })}

        <Passos passos={passos} atual={atual} vendo={aberta} datas={datas} espera={!!esperaAqui}
          aoIr={n => setVendo(n === atual && atual !== 0 ? null : n)} />
        <FaixaPasso vendo={aberta} atual={atual} passos={passos} aoVoltar={() => setVendo(null)} />
        {proprio ? <div key={aberta}>{corpo(aberta)}</div> : (
          <PassoCartao key={aberta} n={aberta} atual={atual} passos={passos}>
            {corpo(aberta)}
          </PassoCartao>
        )}

        <aside className="med-lateral med-lateral--baixo" aria-label="Resumo e linha do tempo">
          <ResumoMedicao m={m} execucao={execucao} reajuste={reajuste} outras={outras} passo={passo} aqui={aqui}
            contratoId={contratoId} podeEditar={podeEditar} salvando={salvando} aoEditarValor={() => abrir("protocolado")} />
          <LinhaDoTempo eventos={eventos} />
        </aside>
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
      {painel === "boletim" && (
        <Janela titulo="Registrar boletim" aoFechar={fechar}>
          <FormBoletim m={m} salvando={salvando} agir={agir} aoFechar={fechar} erro={erro} />
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
