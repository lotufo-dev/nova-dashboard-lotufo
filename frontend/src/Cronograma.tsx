import { useRascunho } from "./rascunho";
import { useEffect, useRef, useState } from "react";
import CaixaAviso from "./CaixaAviso";
import { api, mensagemDeErro } from "./api";
import { IconeAlerta, IconeMais } from "./icones";
import { brl } from "./Medicoes";
// A data de publicacao da versao e' decisao de CALENDARIO: vale no fuso do escritorio (America/Cuiaba),
// nao no do navegador nem no UTC em que o carimbo esta gravado. Ver tempo.ts.
// competencia vem "AAAA-MM" (formato do CHECK da tabela); na tabela le-se "MM/AAAA".
import { fmtCompetencia as competenciaBR, fmtData, fmtDataPura } from "./tempo";
import Rolagem from "./Rolagem";
import Selo from "./Selo";

type ItemVersao = { competencia: string; valor_previsto_centavos: number };
type Versao = { numero: number; criado_em: string; origem: string; itens: ItemVersao[] };

// Linha da lista de versoes (issue #256): a que veio do cadastro traz o documento (origem, data,
// instrumento); a publicada na tela, ou a da carga inicial, vem com esses campos nulos.
type VersaoLista = {
  numero: number; criado_em: string; chave: string | null; origem_documento: string | null;
  data_documento: string | null; instrumento: string | null; competencias: number;
  total_centavos: number; vigente: boolean;
  // issue #395: superada pelo cadastro (carimbo UTC); fica na lista, mas nao vale mais
  superada_em?: string | null;
};

const ORIGEM_DOCUMENTO: Record<string, string> = {
  contratual: "Contrato", aditivo: "Termo aditivo", carta: "Carta de repactuação", smo: "Curva do SMO",
};

function documentoDaVersao(v: VersaoLista): string {
  // publicada na tela ou vinda da carga inicial: o sistema nao sabe de que documento saiu
  if (!v.origem_documento) return "—";
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
  // issue #647: o pedido (protocolado) e o aprovado (atestado) da execucao, em separado; null = nao ha'
  pedido_execucao_centavos?: number | null;
  aprovado_execucao_centavos?: number | null;
  atestado_pendente: boolean;
  pendente_por_tipo?: Record<string, boolean>;
};
// #262: o saldo e' a precos iniciais (vigente de execucao); o aditivo de reajuste vem a parte.
type Saldo = {
  vigente_centavos: number; vigente_execucao_centavos?: number; reajuste_contratado_centavos?: number;
  atestado_execucao_centavos: number; saldo_centavos: number; formula: string;
};
type Curva = { curva: Ponto[]; saldo: Saldo };


// Valor sem "R$" para o textarea, no formato que o parse_brl do servidor aceita.
// Mesmo padrao de Contratos.tsx/Medicoes.tsx (local: aquele nao e' exportado).
function brlCampo(centavos: number): string {
  return (centavos / 100).toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// Zero em centavos aqui quer dizer AUSENCIA (serie sem lancamento) — o servidor completa com 0 o
// que nao existe. Exibir "R$ 0,00" seria afirmar um lancamento de zero que ninguem fez.
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
type Analise = { itens: Linha[]; erro: string };

// Erros do servidor sao 422 em pt-BR e continuam valendo; esta analise so antecipa
// o que da' para apontar POR LINHA, que a resposta HTTP nao consegue localizar.
function analisar(texto: string): Analise {
  const itens: Linha[] = [];
  const vistas = new Map<string, number>();
  const linhas = texto.split(/\r?\n/);
  const cheias = linhas.filter(l => l.trim() !== "").length;
  if (cheias > MAX_ITENS) {
    return { itens, erro: `Máximo de ${MAX_ITENS} competências por versão (há ${cheias}).` };
  }
  for (let i = 0; i < linhas.length; i++) {
    const bruta = linhas[i].trim();
    if (bruta === "") continue;
    const n = i + 1;
    const corte = bruta.indexOf(";");
    if (corte < 0) {
      return { itens, erro: `Linha ${n}: falta o ponto e vírgula — use AAAA-MM;valor (ex.: 2026-07;100.000,00).` };
    }
    const competencia = bruta.slice(0, corte).trim();
    const valor = bruta.slice(corte + 1).trim();
    if (!COMPETENCIA.test(competencia)) {
      return { itens, erro: `Linha ${n}: “${competencia}” não é uma competência AAAA-MM (ex.: 2026-07).` };
    }
    const anterior = vistas.get(competencia);
    if (anterior !== undefined) {
      return { itens, erro: `Linha ${n}: competência ${competenciaBR(competencia)} repetida (já está na linha ${anterior}).` };
    }
    const centavos = parseBrlCentavos(valor);
    if (centavos === null) {
      return { itens, erro: `Linha ${n}: “${valor}” não é um valor em reais (ex.: 100.000,00).` };
    }
    vistas.set(competencia, n);
    itens.push({ competencia, valor, centavos });
  }
  if (itens.length === 0) return { itens, erro: "Informe ao menos uma competência." };
  return { itens, erro: "" };
}

function pendenteOutras(p: Ponto): boolean {
  return Boolean(p.pendente_por_tipo?.reajuste) || Boolean(p.pendente_por_tipo?.projeto);
}

// issue #647: a evolucao mensal so' tem os meses em que a obra mediu; mes so' com previsto nao entra
function temMedicao(p: Ponto): boolean {
  return p.pedido_execucao_centavos != null || p.aprovado_execucao_centavos != null
    || p.medido_execucao_centavos !== 0 || p.medido_reajuste_centavos !== 0 || p.medido_projeto_centavos !== 0;
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
  const pontos = (dados?.curva ?? []).filter(temMedicao);
  const saldo = dados?.saldo ?? null;
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
    setSucesso(`Versão ${numero} publicada.`);
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


  const totais = pontos.reduce((a, p) => ({
    pedido: a.pedido + (p.pedido_execucao_centavos ?? 0),
    aprovado: a.aprovado + (p.aprovado_execucao_centavos ?? 0),
    reajuste: a.reajuste + p.medido_reajuste_centavos,
    projeto: a.projeto + p.medido_projeto_centavos,
  }), { pedido: 0, aprovado: 0, reajuste: 0, projeto: 0 });

  return (
    <>
    {/* issue #647: o que a obra pediu e o que o orgao aprovou, mes a mes; aberta, sem o previsto */}
    <section className="cartao" aria-labelledby="titulo-evolucao-mensal" id="evolucao-mensal">
      <div className="cartao__cabeca">
        <h2 className="cartao__titulo" id="titulo-evolucao-mensal">Evolução mensal</h2>
      </div>

      {erro && <div className="cartao__corpo"><p className="erro" role="alert">
        <IconeAlerta className="icone icone--p" />{erro}
      </p></div>}

      {carregando && <div className="vazio"><p>Carregando…</p></div>}

      {!carregando && saldo && (
        <div className={`saldo${saldo.saldo_centavos < 0 ? " saldo--negativo" : ""}`}>
          <div className="saldo__parcela">
            <span className="resumo__rotulo">Vigente de execução</span>
            <span className="saldo__valor num">{brl(saldo.vigente_execucao_centavos ?? saldo.vigente_centavos)}</span>
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
          {(saldo.reajuste_contratado_centavos ?? 0) !== 0 && (
            <div className="saldo__parcela saldo__parcela--aparte">
              <span className="resumo__rotulo">Reajuste contratado (fora do saldo)</span>
              <span className="saldo__valor num">{brl(saldo.reajuste_contratado_centavos ?? 0)}</span>
            </div>
          )}
          {saldo.saldo_centavos < 0 && (
            <CaixaAviso nivel="critico">Medido acima do vigente de execução do contrato.</CaixaAviso>
          )}
        </div>
      )}

      {!carregando && pontos.length === 0 && (
        <div className="vazio">
          <p className="vazio__titulo">Nenhuma medição.</p>
        </div>
      )}

      {!carregando && pontos.length > 0 && (
        <Rolagem rotulo="Evolução mensal">
          <table className="tabela">
            <caption className="sr-only">Evolução mensal</caption>
            <thead>
              <tr>
                <th scope="col">Competência</th>
                <th scope="col" className="col-num">Pedido</th>
                <th scope="col" className="col-num">Aprovado</th>
                <th scope="col" className="col-num">Reajuste</th>
                <th scope="col" className="col-num">Projeto</th>
                <th scope="col">Situação</th>
              </tr>
            </thead>
            <tbody>
              {pontos.map((p, i) => {
                const semValor = (p.pedido_execucao_centavos ?? 0) === 0 && (p.aprovado_execucao_centavos ?? 0) === 0
                  && p.medido_reajuste_centavos === 0 && p.medido_projeto_centavos === 0;
                const pend = (p.atestado_pendente && p.medido_execucao_centavos > 0) || pendenteOutras(p);
                return (
                  <tr key={p.competencia} className={`linha${i % 2 === 1 ? " par" : ""}`}>
                    <td className="forte num">{competenciaBR(p.competencia)}</td>
                    <td className="col-num dinheiro num">{brl(p.pedido_execucao_centavos ?? null)}</td>
                    <td className="col-num dinheiro num">{brl(p.aprovado_execucao_centavos ?? null)}</td>
                    <td className="col-num dinheiro num">{valorOuTraco(p.medido_reajuste_centavos)}</td>
                    <td className="col-num dinheiro num">{valorOuTraco(p.medido_projeto_centavos)}</td>
                    <td>
                      {semValor ? (
                        <span className="estado estado--aberto">
                          <span className="estado__ponto" aria-hidden="true" />em aberto
                        </span>
                      ) : pend ? (
                        <span className="estado estado--provisorio">
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
                <td className="col-num num">{valorOuTraco(totais.pedido)}</td>
                <td className="col-num num">{valorOuTraco(totais.aprovado)}</td>
                <td className="col-num num">{valorOuTraco(totais.reajuste)}</td>
                <td className="col-num num">{valorOuTraco(totais.projeto)}</td>
                <td />
              </tr>
            </tfoot>
          </table>
        </Rolagem>
      )}
    </section>

    <section className="cartao" aria-labelledby="titulo-cronograma" id="cronograma">
      <div className="cartao__cabeca">
        <h2 className="cartao__titulo" id="titulo-cronograma">Cronograma</h2>
        {/* a versao que /cronograma devolveu (o numero dela, nao a marca `vigente` da lista: gate Sol, PR #311);
            documento, data e competencias estao na tabela de versoes */}
        {!carregando && versao && <span className="cartao__dica num">versão {versao.numero}</span>}
      </div>

      {!carregando && versoes.length === 0 && !podeEditar && (
        <div className="vazio vazio--curto"><p>Nenhuma versão.</p></div>
      )}

      {/* issue #256: uma linha por versao, na ordem em que passaram a valer (data do documento) */}
      {!carregando && versoes.length > 0 && (
        <details className="detalhes cartao__corpo">
        <summary>Versões do cronograma</summary>
        <Rolagem rotulo="Versões do cronograma">
          <table className="tabela">
            <caption className="sr-only">Versões do cronograma, na ordem em que passaram a valer</caption>
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
                  <td className="forte num">{v.numero}{v.vigente && <>{" "}<Selo classe="selo--ok">Vigente</Selo></>}
                    {v.superada_em && <>{" "}<Selo>Superada em {fmtData(v.superada_em)}</Selo></>}</td>
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
              aria-describedby={analise.erro && !vazio ? "cronograma-erro" : undefined}
              onChange={e => { setTexto(e.target.value); setSucesso(""); }} />
          </div>

          {!vazio && analise.erro && <p className="campo__erro" id="cronograma-erro">{analise.erro}</p>}
          <p className={sucesso ? "campo__nota" : "sr-only"} role="status">{sucesso}</p>

          <div className="editor__acoes">
            <button type="submit" className="btn btn--primario" disabled={salvando || vazio || analise.erro !== ""}>
              <IconeMais className="icone icone--p" />
              {salvando ? "Publicando…" : "Publicar nova versão"}
            </button>
            {versao && (
              <button type="button" className="btn" onClick={copiarVigente} disabled={salvando}>
                Copiar versão vigente
              </button>
            )}
          </div>
        </form>
      )}
    </section>
    </>
  );
}
