import { useRascunho } from "./rascunho";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import CaixaAviso from "./CaixaAviso";
import { api, mensagemDeErro } from "./api";
import { IconeAlerta, IconeCadeado, IconeMais } from "./icones";
import { brl } from "./Medicoes";
// O cadeado do passado congelado e a data de publicacao da versao sao decisoes de
// CALENDARIO: valem no fuso do escritorio (America/Cuiaba), nao no do navegador nem
// no UTC em que o carimbo esta gravado. Ver tempo.ts.
// competencia vem "AAAA-MM" (formato do CHECK da tabela); na tabela le-se "MM/AAAA",
// no eixo do grafico "jul/26" — o eixo tem 11px e nao cabe o ano inteiro legivel.
import { fmtCompetencia as competenciaBR, fmtData, fmtDataPura, fmtMesCurto as mesCurto, mesAtualLocal } from "./tempo";
import Rolagem from "./Rolagem";

type ItemVersao = { competencia: string; valor_previsto_centavos: number };
type Versao = { numero: number; criado_em: string; origem: string; itens: ItemVersao[] };

// Linha da lista de versoes (issue #256): a que veio do cadastro traz o documento (origem, data,
// instrumento); a publicada na tela, ou a da carga inicial, vem com esses campos nulos.
type VersaoLista = {
  numero: number; criado_em: string; chave: string | null; origem_documento: string | null;
  data_documento: string | null; instrumento: string | null; competencias: number;
  total_centavos: number; vigente: boolean;
};

const ORIGEM_DOCUMENTO: Record<string, string> = {
  contratual: "Contrato", aditivo: "Termo aditivo", carta: "Carta de repactuação", smo: "Curva do SMO",
};

function documentoDaVersao(v: VersaoLista): string {
  // publicada na tela ou vinda da carga inicial: o sistema nao sabe de que documento saiu
  if (!v.origem_documento) return "Sem documento no cadastro";
  const origem = ORIGEM_DOCUMENTO[v.origem_documento] ?? v.origem_documento;
  return v.instrumento ? `${origem} · ${v.instrumento}` : origem;
}

// `pendente_por_tipo` e `medido_projeto_centavos` sao aditivos ao contrato do plano
// (o servidor ja os manda). `atestado_pendente` qualifica SO a execucao — a serie que
// alimenta o saldo; as outras pendencias vem no dicionario por tipo (spec §6).
type Ponto = {
  competencia: string;
  previsto_centavos: number;
  medido_execucao_centavos: number;
  medido_reajuste_centavos: number;
  medido_projeto_centavos: number;
  atestado_pendente: boolean;
  pendente_por_tipo?: Record<string, boolean>;
};
type Saldo = {
  vigente_centavos: number; atestado_execucao_centavos: number;
  saldo_centavos: number; formula: string;
};
type Curva = { curva: Ponto[]; saldo: Saldo };


// Valor sem "R$" para o textarea, no formato que o parse_brl do servidor aceita.
// Mesmo padrao de Contratos.tsx/Medicoes.tsx (local: aquele nao e' exportado).
function brlCampo(centavos: number): string {
  return (centavos / 100).toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// Zero em centavos aqui quer dizer AUSENCIA (competencia sem previsao, serie sem
// lancamento) — o servidor completa com 0 o que nao existe. Exibir "R$ 0,00" seria
// afirmar um lancamento de zero que ninguem fez.
function valorOuTraco(centavos: number): string {
  return centavos === 0 ? "—" : brl(centavos);
}

/* ------------------------------------------------------------------ entrada */

// Espelha `parse_brl` do servidor (backend/app/dinheiro.py) SO para a previa: quem
// valida de verdade e' o POST. BigInt porque a coluna aceita ate int64 e a soma de
// varias competencias passa do inteiro exato do JS.
function parseBrlCentavos(texto: string): bigint | null {
  // Agrupamento pt-BR conferido antes de limpar: "12.34" e' invalido, nao R$ 1.234,00.
  const limpo = texto.replaceAll("R$", "").trim();
  const m = /^(\d{1,3}(?:\.\d{3})*|\d+)(?:,(\d{1,2}))?$/.exec(limpo);
  if (!m) return null;
  return BigInt(m[1].replaceAll(".", "")) * 100n + BigInt((m[2] ?? "").padEnd(2, "0") || "0");
}

const COMPETENCIA = /^[0-9]{4}-(0[1-9]|1[0-2])$/;
const MAX_ITENS = 600;  // mesmo teto do servidor (api_cronograma.MAX_ITENS)

type Linha = { competencia: string; valor: string; centavos: bigint };
type Analise = { itens: Linha[]; total: bigint; erro: string };

// Erros do servidor sao 422 em pt-BR e continuam valendo; esta analise so antecipa
// o que da' para apontar POR LINHA, que a resposta HTTP nao consegue localizar.
function analisar(texto: string): Analise {
  const itens: Linha[] = [];
  const vistas = new Map<string, number>();
  let total = 0n;
  const linhas = texto.split(/\r?\n/);
  const cheias = linhas.filter(l => l.trim() !== "").length;
  if (cheias > MAX_ITENS) {
    return { itens, total, erro: `Máximo de ${MAX_ITENS} competências por versão (há ${cheias}).` };
  }
  for (let i = 0; i < linhas.length; i++) {
    const bruta = linhas[i].trim();
    if (bruta === "") continue;
    const n = i + 1;
    const corte = bruta.indexOf(";");
    if (corte < 0) {
      return { itens, total, erro: `Linha ${n}: falta o ponto e vírgula — use AAAA-MM;valor (ex.: 2026-07;100.000,00).` };
    }
    const competencia = bruta.slice(0, corte).trim();
    const valor = bruta.slice(corte + 1).trim();
    if (!COMPETENCIA.test(competencia)) {
      return { itens, total, erro: `Linha ${n}: “${competencia}” não é uma competência AAAA-MM (ex.: 2026-07).` };
    }
    const anterior = vistas.get(competencia);
    if (anterior !== undefined) {
      return { itens, total, erro: `Linha ${n}: competência ${competenciaBR(competencia)} repetida (já está na linha ${anterior}).` };
    }
    const centavos = parseBrlCentavos(valor);
    if (centavos === null) {
      return { itens, total, erro: `Linha ${n}: “${valor}” não é um valor em reais (ex.: 100.000,00).` };
    }
    vistas.set(competencia, n);
    itens.push({ competencia, valor, centavos });
    total += centavos;
  }
  if (itens.length === 0) return { itens, total, erro: "Informe ao menos uma competência." };
  return { itens, total, erro: "" };
}

/* ------------------------------------------------------------------ grafico */

// Escala "redonda" para a grade: 4 a 5 linhas em passos de 1/2/2,5/5 x potencia de 10.
function escala(maxCentavos: number): { topo: number; passo: number } {
  const max = Math.max(1, maxCentavos);
  const alvo = max / 4;
  const mag = Math.pow(10, Math.floor(Math.log10(alvo)));
  const passo = Math.max(1, [1, 2, 2.5, 5, 10].map(m => m * mag).find(p => p >= alvo) ?? mag * 10);
  return { topo: Math.ceil(max / passo) * passo, passo };
}

// O eixo nao repete "R$ 1.200.000,00" cinco vezes: a unidade sai uma vez no topo do
// eixo e os rotulos ficam com 1 a 5 caracteres.
function unidade(topoCentavos: number): { divisor: number; rotulo: string } {
  const reais = topoCentavos / 100;
  if (reais >= 1_000_000) return { divisor: 100_000_000, rotulo: "R$ mi" };
  if (reais >= 10_000) return { divisor: 100_000, rotulo: "R$ mil" };
  return { divisor: 100, rotulo: "R$" };
}

function numeroEixo(centavos: number, divisor: number): string {
  return (centavos / divisor).toLocaleString("pt-BR", { maximumFractionDigits: 1 });
}

function outrasSeries(p: Ponto): number {
  return p.medido_reajuste_centavos + p.medido_projeto_centavos;
}

function medidoTotal(p: Ponto): number {
  return p.medido_execucao_centavos + outrasSeries(p);
}

function pendenteOutras(p: Ponto): boolean {
  return Boolean(p.pendente_por_tipo?.reajuste) || Boolean(p.pendente_por_tipo?.projeto);
}

function resumoPonto(p: Ponto): string {
  const partes = [`previsto ${valorOuTraco(p.previsto_centavos)}`,
                  `execução ${valorOuTraco(p.medido_execucao_centavos)}${p.atestado_pendente ? " (provisório)" : ""}`];
  if (p.medido_reajuste_centavos > 0) {
    partes.push(`reajuste ${brl(p.medido_reajuste_centavos)}${p.pendente_por_tipo?.reajuste ? " (provisório)" : ""}`);
  }
  if (p.medido_projeto_centavos > 0) {
    partes.push(`projeto ${brl(p.medido_projeto_centavos)}${p.pendente_por_tipo?.projeto ? " (provisório)" : ""}`);
  }
  return `${mesCurto(p.competencia)} — ${partes.join(" · ")}`;
}

function Grafico({ pontos, mes }: { pontos: Ponto[]; mes: string }) {
  // Passo maior quando ha poucos meses: o SVG e' desenhado no tamanho natural (nao
  // escalado por width:100%), senao os 11px do eixo esticariam junto com as barras.
  // Passando da largura do cartao, quem rola e' o .grafico.
  const PASSO = pontos.length <= 8 ? 104 : pontos.length <= 16 ? 76 : 56;
  const LARG = Math.max(12, Math.round(PASSO * 0.26));
  const VAO = 4;
  // N07-03: o eixo Y mora num SVG proprio, FORA da caixa de rolagem (EIXO_W de largura, mesmas
  // coordenadas y), para nao sumir quando o grafico abre rolado ate' a competencia corrente. O SVG
  // que rola comeca na grade (MARGEM_E = 0); o vao de 8px entre rotulo e grade vem do EIXO_W.
  const EIXO_W = 66, MARGEM_E = 0, MARGEM_D = 14, TOPO = 24, ALTURA = 200;
  const BASE = TOPO + ALTURA;
  const comRotulo = PASSO >= 76;                 // valor medido sob o eixo: so quando cabe
  const H = BASE + (comRotulo ? 46 : 28);
  const W = MARGEM_E + pontos.length * PASSO + MARGEM_D;

  const { topo, passo } = escala(Math.max(...pontos.map(p => Math.max(p.previsto_centavos, medidoTotal(p)))));
  const { divisor, rotulo } = unidade(topo);
  const y = (v: number) => BASE - (v / topo) * ALTURA;
  // Valor lancado nunca vira barra invisivel: piso de 2px preserva "existe, e' pouco".
  const altura = (v: number) => (v <= 0 ? 0 : Math.max(2, (v / topo) * ALTURA));

  const linhas: number[] = [];
  for (let v = 0; v <= topo + passo / 2; v += passo) linhas.push(v);

  // F-73: a caixa de rolagem (.grafico, dona do overflow) abre rolada ate' a competencia
  // corrente, que fica perto da borda direita (com uma competencia futura depois dela), em
  // vez de abrir no mes mais antigo. So' acontece na montagem: republicar uma versao nao
  // pode tirar a pessoa de onde ela esta. Se o grafico cabe sem rolar (F-83), nada e' forcado.
  // `data-esq` marca "ha mais a esquerda" (scrollLeft > 0) para o CSS esmaecer a borda; o
  // atributo e' escrito aqui, e nao na className, porque a className da caixa e' do Rolagem.
  const svg = useRef<SVGSVGElement>(null);
  useLayoutEffect(() => {
    const caixa = svg.current?.closest<HTMLElement>(".grafico");
    if (!caixa) return;
    const marcar = () => {
      if (caixa.scrollLeft > 1) caixa.setAttribute("data-esq", "1");
      else caixa.removeAttribute("data-esq");
    };
    if (caixa.clientWidth > 0 && caixa.scrollWidth > caixa.clientWidth + 1) {
      let atual = pontos.findIndex(p => p.competencia >= mes);
      if (atual < 0) atual = pontos.length - 1;
      const borda = MARGEM_E + (atual + 1) * PASSO;           // borda direita da coluna corrente
      const alvo = borda + PASSO - caixa.clientWidth;          // a caixa rolavel nao tem padding esquerdo
      caixa.scrollLeft = Math.max(0, alvo);
    }
    marcar();
    caixa.addEventListener("scroll", marcar, { passive: true });
    return () => { caixa.removeEventListener("scroll", marcar); caixa.removeAttribute("data-esq"); };
    // so' na montagem (ver o comentario acima)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="grafico__quadro">
    <svg className="grafico__eixo-y" width={EIXO_W} height={H} viewBox={`0 0 ${EIXO_W} ${H}`} aria-hidden="true" focusable="false">
      <text className="g-eixo num" x={EIXO_W - 8} y={TOPO - 9} textAnchor="end">{rotulo}</text>
      {linhas.map(v => (
        <text key={v} className="g-eixo num" x={EIXO_W - 8} y={y(v) + 4} textAnchor="end">
          {numeroEixo(v, divisor)}
        </text>
      ))}
    </svg>
    <Rolagem rotulo="Gráfico de previsto e medido por competência" className="grafico">
    <svg ref={svg} className="grafico__svg" width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img"
      aria-label={`Previsto e medido por competência, de ${mesCurto(pontos[0].competencia)} a `
        + `${mesCurto(pontos[pontos.length - 1].competencia)}, em ${rotulo}. `
        + "Os mesmos números estão na “Tabela por competência”, recolhida logo abaixo."}>
      <defs>
        {/* Hachura clara POR CIMA da barra: o medido provisorio continua sendo lido como
            a serie dele (a cor nao e' substituida), com a marca ambar por cima. */}
        <pattern id="cronograma-hachura" width="6" height="6"
          patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <line className="g-hachura" x1="0" y1="0" x2="0" y2="6" />
        </pattern>
      </defs>

      {linhas.map(v => (
        <line key={v} className={v === 0 ? "g-base" : "g-grade"}
          x1={MARGEM_E} y1={y(v)} x2={W - MARGEM_D} y2={y(v)} />
      ))}

      {pontos.map((p, i) => {
        const cx = MARGEM_E + i * PASSO + PASSO / 2;
        const xPrev = cx - VAO / 2 - LARG;
        const xMed = cx + VAO / 2;
        const cxMed = xMed + LARG / 2;
        const exec = p.medido_execucao_centavos;
        const outras = outrasSeries(p);
        const hPrev = altura(p.previsto_centavos);
        const hExec = altura(exec);
        const hOutras = altura(outras);
        const hMed = hExec + hOutras;
        const pendOutras = pendenteOutras(p);
        const pendente = (p.atestado_pendente && hExec > 0) || (pendOutras && hOutras > 0);
        const ySelo = Math.max(11, BASE - Math.max(hMed, hPrev) - 12);
        return (
          <g key={p.competencia}>
            <title>{resumoPonto(p)}</title>

            {hPrev > 0
              ? <rect className="g-previsto" x={xPrev} y={BASE - hPrev} width={LARG} height={hPrev} rx={2.5} />
              /* sem previsao no cronograma: talo no zero, nunca barra de altura zero
                 (que se confundiria com "previsto igual a zero") */
              : <rect className="g-talo" x={xPrev} y={BASE - 4} width={LARG} height={4} rx={2} />}

            {hMed > 0 ? (
              <>
                {hExec > 0 && (
                  <rect className="g-execucao" x={xMed} y={BASE - hExec} width={LARG} height={hExec} rx={2.5} />
                )}
                {hOutras > 0 && (
                  <rect className="g-outras" x={xMed} y={BASE - hMed} width={LARG} height={hOutras} rx={2.5} />
                )}
                {p.atestado_pendente && hExec > 0 && (
                  <rect className="g-provisorio" fill="url(#cronograma-hachura)"
                    x={xMed} y={BASE - hExec} width={LARG} height={hExec} rx={2.5} />
                )}
                {pendOutras && hOutras > 0 && (
                  <rect className="g-provisorio" fill="url(#cronograma-hachura)"
                    x={xMed} y={BASE - hMed} width={LARG} height={hOutras} rx={2.5} />
                )}
              </>
            ) : (
              <rect className="g-talo" x={xMed} y={BASE - 4} width={LARG} height={4} rx={2} />
            )}

            {pendente && (
              <>
                <circle className="g-selo" cx={cxMed} cy={ySelo} r={6.5} />
                <path className="g-selo__marca"
                  d={`M${cxMed} ${ySelo - 3.4}v3.6M${cxMed} ${ySelo + 3.1}h.01`} />
              </>
            )}

            <text className={`g-eixo-x${pendente ? " g-eixo-x--pendente" : ""}`}
              x={cx} y={BASE + 18} textAnchor="middle">{mesCurto(p.competencia)}</text>
            {comRotulo && (
              <text className={`g-eixo num${pendente ? " g-eixo--pendente" : ""}`}
                x={cx} y={BASE + 36} textAnchor="middle">
                {medidoTotal(p) === 0 ? "em aberto" : numeroEixo(medidoTotal(p), divisor)}
              </text>
            )}
          </g>
        );
      })}
    </svg>
    </Rolagem>
    </div>
  );
}

/* ---------------------------------------------------------------- componente */

export default function Cronograma({ contratoId, podeEditar }:
    { contratoId: number; podeEditar: boolean }) {
  const [versao, setVersao] = useState<Versao | null>(null);
  const [versoes, setVersoes] = useState<VersaoLista[]>([]);
  const [dados, setDados] = useState<Curva | null>(null);
  const [texto, setTexto] = useState("");
  const [carregando, setCarregando] = useState(true);
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState("");
  const [sucesso, setSucesso] = useState("");
  const copiado = useRef("");   // texto vindo de "Copiar versao vigente": ainda nao e' rascunho
  useRascunho(texto.trim() !== "" && texto !== copiado.current);   // cronograma digitado e ainda nao publicado
  const area = useRef<HTMLTextAreaElement>(null);

  // GERACAO da leitura — mesma guarda de Medicoes.tsx. Cada troca de `contratoId` (e o
  // desmonte da tela) invalida a anterior, e a resposta em voo dela para de escrever.
  // App.tsx remonta esta tela por `key`, entao o caso vivo e' a resposta que chega
  // depois do desmonte; a guarda tambem cobre a tela ser reaproveitada um dia.
  //
  // Os dois `setState` sairam de dentro dos `then` de proposito: assim a curva e a
  // versao nunca sao aplicadas pela metade — ou as duas leituras valem, ou nenhuma.
  const geracao = useRef(0);

  const carregar = async () => {
    const g = geracao.current;
    const [v, c, vs] = await Promise.all([
      api<Versao | null>(`/api/contratos/${contratoId}/cronograma`),
      api<Curva>(`/api/contratos/${contratoId}/curva`),
      api<VersaoLista[]>(`/api/contratos/${contratoId}/cronograma/versoes`),
    ]);
    if (g !== geracao.current) return;
    setVersao(v); setDados(c); setVersoes(vs);
  };

  useEffect(() => {
    geracao.current += 1;
    const g = geracao.current;
    // O rascunho do textarea e' o estado transitorio mais perigoso desta tela: um
    // cronograma digitado para o contrato A, sobrevivendo a troca, seria publicado
    // no contrato B com um clique. Ele sai junto com o resto.
    setVersao(null); setVersoes([]); setDados(null); setTexto("");
    setErro(""); setSucesso(""); setSalvando(false);
    setCarregando(true);
    carregar()
      .catch(e => { if (g === geracao.current) setErro(mensagemDeErro(e)); })
      .finally(() => { if (g === geracao.current) setCarregando(false); });
    return () => { geracao.current += 1; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [contratoId]);

  // Devolve se a MUTACAO foi aceita — nao se a tela conseguiu se atualizar.
  //
  //  - mutacao recusada: nada foi gravado, o texto FICA no campo para correcao.
  //  - mutacao aceita e recarga falhando (rede caiu entre as duas chamadas): a
  //    versao JA existe. Se o texto continuasse no campo, o caminho natural seria
  //    publicar de novo — e uma segunda versao identica nao tem como ser apagada
  //    (nao existe rota de excluir versao, de proposito: revisar e' sempre criar a
  //    proxima). Entao limpa do mesmo jeito e avisa que o que falhou foi a leitura.
  //
  // A guarda de geracao vale aqui tambem: o desfecho de uma publicacao do contrato A
  // nao pode virar mensagem na tela do contrato B. O efeito de troca ja zera
  // `salvando`, entao a guarda no `finally` nao deixa a tela nova travada.
  const agir = async (fn: () => Promise<unknown>): Promise<boolean> => {
    const g = geracao.current;
    setErro(""); setSalvando(true);
    let gravou = false;
    try {
      await fn();
      gravou = true;
      await carregar();
    } catch (e) {
      if (g === geracao.current) {
        setErro(gravou
          ? "Versão publicada, mas o cronograma não recarregou — recarregue a página para ver o resultado."
          : mensagemDeErro(e));
      }
    } finally { if (g === geracao.current) setSalvando(false); }
    return gravou;
  };

  const analise = analisar(texto);
  const vazio = texto.trim() === "";
  const pontos = dados?.curva ?? [];
  const saldo = dados?.saldo ?? null;
  // Mesmo mes que o servidor usa para congelar o passado (backend tempo.mes_local):
  // com o mes do navegador, o cadeado da tela discordaria do previsto do servidor
  // durante as 4 horas de defasagem na virada.
  const mes = mesAtualLocal();

  async function publicar(ev: React.FormEvent) {
    ev.preventDefault();
    setSucesso("");
    if (analise.erro) { setErro(analise.erro); return; }
    const itens = analise.itens.map(i => ({ competencia: i.competencia, valor: i.valor }));
    // O que foi ENVIADO, congelado antes da ida ao servidor: limpar o campo no sucesso
    // so pode apagar exatamente isto. O textarea segue editavel durante a publicacao
    // (de proposito — ver o comentario dele), entao quem ja comecou a proxima versao
    // enquanto a anterior subia teria o texto novo apagado por baixo dos dedos.
    const enviado = texto;
    let numero = 0;
    const ok = await agir(async () => {
      const r = await api<{ versao: number }>(`/api/contratos/${contratoId}/cronograma`, {
        method: "POST", body: JSON.stringify({ itens }),
      });
      numero = r.versao;
    });
    if (!ok) return;
    setTexto(atual => (atual === enviado ? "" : atual));
    setSucesso(`Versão ${numero} publicada: o previsto acima já é o dela.`);
    // O botao de publicar fica desabilitado com o campo vazio; sem devolver o foco
    // ele morreria no elemento desabilitado e o teclado recomecaria a pagina.
    area.current?.focus();
  }

  function copiarVigente() {
    if (!versao) return;
    setSucesso("");
    const copia = versao.itens.map(i => `${i.competencia};${brlCampo(i.valor_previsto_centavos)}`).join("\n");
    copiado.current = copia;
    setTexto(copia);
    area.current?.focus();
  }

  const dica = versao
    ? `versão ${versao.numero} · ${versao.itens.length} ${versao.itens.length === 1 ? "competência" : "competências"}`
      + ` · publicada em ${fmtData(versao.criado_em)}`
    : "sem versão publicada";

  const totais = pontos.reduce((a, p) => ({
    previsto: a.previsto + p.previsto_centavos,
    execucao: a.execucao + p.medido_execucao_centavos,
    reajuste: a.reajuste + p.medido_reajuste_centavos,
    projeto: a.projeto + p.medido_projeto_centavos,
  }), { previsto: 0, execucao: 0, reajuste: 0, projeto: 0 });

  return (
    <section className="cartao" aria-labelledby="titulo-cronograma" id="cronograma">
      <div className="cartao__cabeca">
        <h2 className="cartao__titulo" id="titulo-cronograma">Cronograma</h2>
        <span className="cartao__dica num"
          title={versao ? `Origem do cadastro: ${versao.origem}` : undefined}>
          {carregando ? "carregando…" : dica}
        </span>
      </div>

      {erro && <div className="cartao__corpo"><p className="erro" role="alert">
        <IconeAlerta className="icone icone--p" />{erro}
      </p></div>}

      {carregando && <div className="vazio"><p>Carregando cronograma…</p></div>}

      {!carregando && saldo && (
        <div className={`saldo${saldo.saldo_centavos < 0 ? " saldo--negativo" : ""}`}>
          <div className="saldo__parcela">
            <span className="resumo__rotulo">Vigente</span>
            <span className="saldo__valor num">{brl(saldo.vigente_centavos)}</span>
          </div>
          <span className="saldo__op" aria-hidden="true">−</span>
          <div className="saldo__parcela">
            <span className="resumo__rotulo">Medido (execução)</span>
            <span className="saldo__valor num">{brl(saldo.atestado_execucao_centavos)}</span>
          </div>
          <span className="saldo__op" aria-hidden="true">=</span>
          <div className="saldo__parcela saldo__parcela--total">
            <span className="resumo__rotulo">Saldo</span>
            <span className="saldo__valor num">{brl(saldo.saldo_centavos)}</span>
          </div>
          {saldo.saldo_centavos < 0 && (
            <CaixaAviso nivel="critico">Medido acima do valor vigente do contrato.</CaixaAviso>
          )}
          {/* a formula e' a do servidor, palavra por palavra: a tela nao reescreve a
              regra do saldo, so mostra os numeros que entram nela */}
          <p className="saldo__nota">{saldo.formula}</p>
        </div>
      )}

      {!carregando && pontos.length === 0 && (
        <div className="vazio">
          <p className="vazio__titulo">Nenhuma competência prevista ou medida</p>
          <p>{podeEditar
            ? "Publique a primeira versão do cronograma no formulário abaixo — uma linha por competência."
            : "Quando a engenharia publicar o cronograma, o previsto e o medido aparecem aqui."}</p>
        </div>
      )}

      {!carregando && pontos.length > 0 && <>
        <Grafico pontos={pontos} mes={mes} />

        <div className="legenda">
          <span className="legenda__item">
            <span className="legenda__chave legenda__chave--previsto" aria-hidden="true" />
            Previsto (cronograma vigente; passado congelado)
          </span>
          <span className="legenda__item">
            <span className="legenda__chave legenda__chave--execucao" aria-hidden="true" />
            Medido — execução
          </span>
          <span className="legenda__item">
            <span className="legenda__chave legenda__chave--outras" aria-hidden="true" />
            Medido — reajuste e projeto
          </span>
          <span className="legenda__item">
            <span className="legenda__chave legenda__chave--provisorio" aria-hidden="true" />
            Provisório: protocolado, ainda sem atestado
          </span>
        </div>

        {/* a tabela e' a consulta fina do grafico: recolhida (NAVEGACAO.md › Obra › Contrato) */}
        <details className="detalhes cartao__corpo">
        <summary>Tabela por competência ({pontos.length})</summary>
        <Rolagem rotulo="Previsto e medido por competência">
          <table className="tabela">
            <caption className="sr-only">Previsto e medido por competência</caption>
            <thead>
              <tr>
                <th scope="col">Competência</th>
                <th scope="col" className="col-num">Previsto</th>
                <th scope="col" className="col-num">Execução</th>
                <th scope="col" className="col-num">Reajuste</th>
                <th scope="col" className="col-num">Projeto</th>
                <th scope="col">Situação</th>
              </tr>
            </thead>
            <tbody>
              {pontos.map((p, i) => {
                // Uma versao nova so alcanca competencias a partir do mes em que nasce:
                // mes ja decorrido COM previsto e' passado congelado (spec §5).
                const congelado = p.competencia < mes && p.previsto_centavos > 0;
                const total = medidoTotal(p);
                const pend = (p.atestado_pendente && p.medido_execucao_centavos > 0) || pendenteOutras(p);
                return (
                  <tr key={p.competencia} className={`linha${i % 2 === 1 ? " par" : ""}`}>
                    <td className="forte num">
                      {competenciaBR(p.competencia)}
                      {congelado && <span className="cadeado">
                        <IconeCadeado className="icone icone--p"
                          titulo="Competência já decorrida: uma nova versão do cronograma não altera este previsto" />
                      </span>}
                    </td>
                    <td className="col-num dinheiro num">{valorOuTraco(p.previsto_centavos)}</td>
                    <td className="col-num dinheiro num">{valorOuTraco(p.medido_execucao_centavos)}</td>
                    <td className="col-num dinheiro num">{valorOuTraco(p.medido_reajuste_centavos)}</td>
                    <td className="col-num dinheiro num">{valorOuTraco(p.medido_projeto_centavos)}</td>
                    <td>
                      {total === 0 ? (
                        <span className="estado estado--aberto">
                          <span className="estado__ponto" aria-hidden="true" />em aberto
                        </span>
                      ) : pend ? (
                        <span className="estado estado--provisorio" title={resumoPonto(p)}>
                          <span className="estado__ponto" aria-hidden="true" />provisório
                        </span>
                      ) : (
                        <span className="estado estado--atestado">
                          <span className="estado__ponto" aria-hidden="true" />atestado
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
            <tfoot>
              <tr>
                <td>Total</td>
                <td className="col-num num">{valorOuTraco(totais.previsto)}</td>
                <td className="col-num num">{valorOuTraco(totais.execucao)}</td>
                <td className="col-num num">{valorOuTraco(totais.reajuste)}</td>
                <td className="col-num num">{valorOuTraco(totais.projeto)}</td>
                <td />
              </tr>
            </tfoot>
          </table>
        </Rolagem>
        </details>
      </>}

      {/* issue #256: uma linha por versao, na ordem em que passaram a valer (data do documento) */}
      {!carregando && versoes.length > 0 && (
        <details className="detalhes cartao__corpo">
        <summary>Versões do cronograma ({versoes.length})</summary>
        <Rolagem rotulo="Versões do cronograma">
          <table className="tabela">
            <caption className="sr-only">Versões do cronograma, da mais antiga à vigente</caption>
            <thead>
              <tr>
                <th scope="col">Versão</th>
                <th scope="col">Data</th>
                <th scope="col">Documento</th>
                <th scope="col" className="col-num">Competências</th>
                <th scope="col" className="col-num">Total previsto</th>
              </tr>
            </thead>
            <tbody>
              {versoes.map((v, i) => (
                <tr key={v.numero} className={`linha${i % 2 === 1 ? " par" : ""}`}>
                  <td className="forte num">{v.numero}{v.vigente && " · vigente"}</td>
                  <td className="num">{v.data_documento ? fmtDataPura(v.data_documento) : fmtData(v.criado_em)}</td>
                  <td>{documentoDaVersao(v)}</td>
                  <td className="col-num num">{v.competencias}</td>
                  <td className="col-num dinheiro num">{brl(v.total_centavos)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Rolagem>
        </details>
      )}

      {podeEditar && (
        <form className="cartao__rodape editor" onSubmit={publicar}>
          <div className="campo">
            <label className="campo__rotulo" htmlFor="cronograma-itens">Nova versão do cronograma</label>
            {/* sem `disabled` durante a gravacao (so os botoes travam): desabilitar o
                campo faria o foco devolvido depois do sucesso cair num elemento ainda
                desabilitado — o React so o reabilita no render seguinte. */}
            <textarea id="cronograma-itens" ref={area} className="entrada--area num" rows={7}
              spellCheck={false} value={texto}
              placeholder={"2026-09;1.200.000,00\n2026-10;900.000,00…"}
              aria-describedby={analise.erro && !vazio ? "cronograma-erro cronograma-ajuda" : "cronograma-ajuda"}
              onChange={e => { setTexto(e.target.value); setSucesso(""); }} />
          </div>

          <p className="campo__nota" id="cronograma-ajuda">
            Uma linha por competência, no formato <code>AAAA-MM;valor</code> — por exemplo{" "}
            <code>2026-09;1.200.000,00</code>.
          </p>

          {!vazio && analise.erro && <p className="campo__erro" id="cronograma-erro">{analise.erro}</p>}
          {!vazio && !analise.erro && (
            <p className="campo__nota num">
              {analise.itens.length} {analise.itens.length === 1 ? "competência" : "competências"}
              {" · total previsto "}
              {analise.total <= BigInt(Number.MAX_SAFE_INTEGER) ? brl(Number(analise.total)) : "acima do exibível"}
            </p>
          )}
          <p className={sucesso ? "campo__nota" : "sr-only"} role="status">{sucesso}</p>

          <CaixaAviso nivel="atencao">
            A nova versão substitui o cronograma futuro por inteiro: competências de {competenciaBR(mes)} em
            diante que não estiverem na lista deixam de estar previstas. Meses já decorridos permanecem como estão.
          </CaixaAviso>

          <div className="editor__acoes">
            <button type="submit" className="btn btn--primario" disabled={salvando || vazio || analise.erro !== ""}>
              <IconeMais className="icone icone--p" />
              {salvando ? "Publicando…" : "Publicar nova versão"}
            </button>
            {versao && (
              <button type="button" className="btn" onClick={copiarVigente} disabled={salvando}
                title="Preenche o campo com as linhas da versão vigente, para você ajustar e publicar a próxima">
                Copiar versão vigente
              </button>
            )}
          </div>
        </form>
      )}
    </section>
  );
}
