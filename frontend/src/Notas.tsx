import { useEffect, useRef, useState } from "react";
import { brl } from "./formato";
import { api, apiForm, mensagemDeErro } from "./api";
import CampoValor from "./CampoValor";
import { IconeAlerta } from "./icones";
import { tituloMedicao } from "./medicao";
import type { Medicao } from "./Medicoes";
import { fmtDataPura } from "./tempo";
import Rolagem from "./Rolagem";
import Selo from "./Selo";

// Notas da medicao (bloco 3, spec §3 passo 3 e §7.1): a pessoa arrasta os PDFs que o faturamento
// devolveu; o sistema le a nota da Lotufo, confere contra a saida do espelho e fecha "nota emitida"
// quando o conjunto esperado esta' completo. O RM confirma depois. Painel que abre SOB a linha da
// medicao, no mesmo lugar dos outros paineis de Medicoes.tsx.

type Esperada = {
  chave: string; natureza: string; rotulo?: string | null; emissor: string; municipio: string; valor: number;
  iss: number | null; inss: number | null; irrf: number | null; ibs: number | null; cbs: number | null;
  liquido: number; nota_id: number | null;
};
type Diferenca = { campo: string; espelho: number | string | null; nota: number | string | null; grau: string };
type NotaVinculada = {
  alocacao_id: number; nota_id: number; coligada: number; numero: string; serie: string | null; emissao: string | null;
  valor_centavos: number; valor_pdf_centavos: number | null; origem_nota: string; confirmacao: string;
  documento_id: number | null; conferencia: Diferenca[]; justificativa: string | null; leitura: string | null;
  municipio: string | null; regra: string | null; recebido_centavos: number;
};
type Dados = { esperadas: Esperada[]; notas: NotaVinculada[]; faltam: number;
  documentos_sem_nota?: { documento_id: number; nome: string }[]; pode_declarar: boolean };
type Leitura = { ok: boolean; motivo: string | null; leiaute: string | null; numero?: number; avisos?: string[] };
type Anexado = { documento_id: number; repetido: boolean; leitura: Leitura; nota_id: number | null;
  conferencia: Diferenca[]; faltam: number; estado: string };

const SITUACAO: Record<string, string> = {
  aguardando_rm: "aguardando o RM", confirmada: "confirmada pelo RM", divergente: "divergente do RM (valor)",
  so_rm: "só no RM (PDF não anexado)",
};
const CAMPO: Record<string, string> = {
  valor: "valor", iss: "ISS", inss: "INSS", irrf: "IRRF", ibs: "IBS", cbs: "CBS", liquido: "líquido", municipio: "município", tomador: "tomador",
};

function dataBR(iso: string | null): string {
  return iso ? fmtDataPura(iso) : "sem data";
}
function mensagem(e: unknown): string {
  return mensagemDeErro(e);
}
function motivoLeitura(motivo: string | null): string {
  if (motivo === "sem-texto") return "o PDF não tem texto (digitalizado)";
  if (motivo === "leiaute-desconhecido") return "leiaute da nota ainda não reconhecido";
  if (motivo === "sem-numero") return "a nota está sem número (rascunho?)";
  if (motivo?.startsWith("campos-ausentes")) return "faltaram campos na leitura";
  return motivo ?? "não foi possível ler";
}
const emissorNome = (e: string) => e.charAt(0).toUpperCase() + e.slice(1);
// mesmo rotulo da coluna "Saida" do espelho (Espelho.tsx usa `s.rotulo` que vem do servidor, com
// reserva Medição/Reajuste/Projeto em espelho.py); as esperadas nao trazem o rotulo, entao o mapa
// natureza -> rotulo e' replicado aqui, com acento, incluindo o tipo "execucao" da medicao.
const NATUREZA: Record<string, string> = {
  medicao: "Medição", execucao: "Execução", reajuste: "Reajuste", projeto: "Projeto",
};
const naturezaNome = (n: string, rotulo?: string | null) => rotulo || NATUREZA[n] || emissorNome(n);

export function Notas({ medicao, podeEditar, podeDesfazer = false, aoMudar, aoFechar, rotulo }: {
  medicao: Medicao; podeEditar: boolean; aoMudar: () => void; aoFechar?: () => void;
  podeDesfazer?: boolean;   // issue #71: so' o admin desfaz o vinculo de uma nota com a medicao
  rotulo?: string;   // issue #188: o bloco da execucao ou do reajuste na pagina da medicao
}) {
  const [dados, setDados] = useState<Dados | null>(null);
  const [erro, setErro] = useState("");
  const [ocupado, setOcupado] = useState(false);
  // Qual acao roda: so' o botao dela troca o rotulo; os demais apenas ficam desabilitados.
  const [acao, setAcao] = useState<"manual" | "justificar" | "declarar" | "desfazer" | null>(null);
  const [linhas, setLinhas] = useState<string[]>([]);
  const [frc, setFrc] = useState(false);
  // Upload que voltou sem leitura: a pessoa digita numero, data e valor (spec §7.1).
  const [manual, setManual] = useState<{ documento_id: number; nome: string; numero: string; emissao: string; valor: string } | null>(null);
  const [justificar, setJustificar] = useState<{ nota_id: number; texto: string } | null>(null);
  const [declarar, setDeclarar] = useState("");
  const [desfazer, setDesfazer] = useState<{ alocacao_id: number; numero: string; motivo: string } | null>(null);
  const geracao = useRef(0);

  const carregar = async () => {
    const g = geracao.current;
    const d = await api<Dados>(`/api/medicoes/${medicao.id}/notas`);
    if (g === geracao.current) setDados(d);
  };

  useEffect(() => {
    geracao.current += 1;
    const g = geracao.current;
    setDados(null); setErro(""); setLinhas([]); setManual(null); setJustificar(null); setDeclarar(""); setDesfazer(null);
    carregar().catch(e => { if (g === geracao.current) setErro(mensagem(e)); });
    return () => { geracao.current += 1; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [medicao.id]);

  // Toda acao com sucesso recarrega o painel e avisa a lista (o estado da linha pode ter mudado).
  const agir = async (qual: "manual" | "justificar" | "declarar" | "desfazer", fn: () => Promise<void>) => {
    setErro(""); setOcupado(true); setAcao(qual);
    try {
      await fn();
      await carregar();
      aoMudar();
    } catch (e) { setErro(mensagem(e)); } finally { setOcupado(false); setAcao(null); }
  };

  const descrever = (nome: string, r: Anexado): string => {
    if (r.repetido) return `${nome}: já estava anexado a esta medição.`;
    if (!r.leitura.ok) {
      return r.nota_id === null && r.leitura.motivo !== "fatura"
        ? `${nome}: ${motivoLeitura(r.leitura.motivo)} — informe número, data e valor abaixo.`
        : `${nome}: anexado como fatura do consórcio.`;
    }
    if (r.nota_id === null) return `${nome}: nota ${r.leitura.numero} lida e guardada (emissor não é a Lotufo).`;
    const divergentes = r.conferencia.filter(d => d.grau === "divergente").map(d => CAMPO[d.campo] ?? d.campo);
    const arred = r.conferencia.filter(d => d.grau === "arredondamento").map(d => CAMPO[d.campo] ?? d.campo);
    let texto = `${nome}: nota ${r.leitura.numero} lida e vinculada`;
    if (divergentes.length) texto += ` — DIVERGE do espelho em ${divergentes.join(", ")}`;
    else if (arred.length) texto += ` — confere (arredondamento de 1 centavo em ${arred.join(", ")})`;
    else texto += " — confere com o espelho";
    if (r.estado === "nota_emitida") texto += ". Notas completas: medição em Nota emitida.";
    else texto += r.faltam > 0 ? `. Falta${r.faltam === 1 ? "" : "m"} ${r.faltam} nota${r.faltam === 1 ? "" : "s"}.` : ".";
    return texto;
  };

  const anexar = async (input: HTMLInputElement) => {
    const arquivos = Array.from(input.files ?? []);
    if (arquivos.length === 0) return;
    setErro(""); setOcupado(true);
    const novas: string[] = [];
    try {
      // Um por vez, na ordem: cada resposta vira uma linha de feedback, e o primeiro que nao le
      // abre o formulario de digitacao (o proximo so' entra depois de ele ser tratado).
      for (const arquivo of arquivos) {
        const fd = new FormData();
        fd.append("arquivo", arquivo);
        fd.append("tipo_doc", frc ? "fatura" : "nfs");
        const r = await apiForm<Anexado>(`/api/medicoes/${medicao.id}/notas`, fd);
        novas.push(descrever(arquivo.name, r));
        if (!r.repetido && !r.leitura.ok && r.nota_id === null && !frc && manual === null) {
          setManual({ documento_id: r.documento_id, nome: arquivo.name, numero: "", emissao: "", valor: "" });
        }
      }
      await carregar();
      aoMudar();
    } catch (e) { setErro(mensagem(e)); } finally {
      setLinhas(l => [...l, ...novas]); setOcupado(false); input.value = "";
    }
  };

  const enviarManual = async (ev: React.FormEvent) => {
    ev.preventDefault();
    if (!manual) return;
    const m = manual;
    await agir("manual", async () => {
      const r = await api<{ nota_id: number; conferencia: Diferenca[]; faltam: number; estado: string }>(
        `/api/medicoes/${medicao.id}/notas/manual`,
        { method: "POST", body: JSON.stringify({ documento_id: m.documento_id, numero: Number(m.numero), emissao: m.emissao, valor: m.valor }) });
      setLinhas(l => [...l, `${m.nome}: nota ${m.numero} registrada` + (r.estado === "nota_emitida" ? " — medição em Nota emitida." : ".")]);
      setManual(null);
    });
  };

  const enviarJustificativa = async (ev: React.FormEvent) => {
    ev.preventDefault();
    if (!justificar) return;
    const j = justificar;
    await agir("justificar", async () => {
      await api(`/api/notas/${j.nota_id}/justificar`, { method: "POST", body: JSON.stringify({ justificativa: j.texto }) });
      setJustificar(null);
    });
  };

  const enviarDesfazer = async (ev: React.FormEvent) => {
    ev.preventDefault();
    if (!desfazer) return;
    const d = desfazer;
    await agir("desfazer", async () => {
      await api(`/api/medicoes/${medicao.id}/notas/alocacoes/${d.alocacao_id}/desfazer`,
        { method: "POST", body: JSON.stringify({ motivo: d.motivo }) });
      setLinhas(l => [...l, `Vínculo da nota ${Number(d.numero) || d.numero} desfeito.`]);
      setDesfazer(null);
    });
  };

  // o PDF anexado na medicao seguiria no envio ao orgao: o servidor recusa, entao o botao nem aparece
  const botaoDesfazer = (n: NotaVinculada) => podeDesfazer && n.documento_id === null && desfazer?.alocacao_id !== n.alocacao_id && (
    <>{" "}<button type="button" className="btn btn--pequeno" disabled={ocupado}
      aria-label={`Desfazer vínculo da nota ${Number(n.numero) || n.numero}`}
      onClick={() => setDesfazer({ alocacao_id: n.alocacao_id, numero: n.numero, motivo: "" })}>Desfazer vínculo</button></>
  );

  const enviarDeclaracao = async (ev: React.FormEvent) => {
    ev.preventDefault();
    await agir("declarar", async () => {
      await api(`/api/medicoes/${medicao.id}/notas/completa`, { method: "POST", body: JSON.stringify({ justificativa: declarar }) });
      setLinhas(l => [...l, "Notas declaradas completas: medição em Nota emitida."]);
      setDeclarar("");
    });
  };

  const porId = new Map((dados?.notas ?? []).map(n => [n.nota_id, n]));
  const soltas = (dados?.notas ?? []).filter(n => !(dados?.esperadas ?? []).some(e => e.nota_id === n.nota_id));
  // IBS e CBS so' entram na tabela quando alguma saida os traz (como no espelho)
  const temIbsCbs = (dados?.esperadas ?? []).some(e => e.ibs !== null || e.cbs !== null);

  // a nota se identifica pelo numero e pela data; a situacao no RM e' selo
  const situacaoNota = (n: NotaVinculada) => (
    <><span className="num">nº {Number(n.numero) || n.numero} · {dataBR(n.emissao)}</span>{" "}<Selo>{SITUACAO[n.confirmacao] ?? n.confirmacao}</Selo></>
  );

  // so' a divergencia aparece (o que confere ou arredonda 1 centavo nao pede nada)
  const conferencia = (n: NotaVinculada) => {
    const div = n.conferencia.filter(d => d.grau === "divergente");
    if (div.length === 0) return null;
    return (
      <>{" "}<span className="notas__conferencia">
        <span className="notas__diverge">
          <IconeAlerta className="icone icone--p" />
          diverge do espelho: {div.map(d => `${CAMPO[d.campo] ?? d.campo} (espelho ${typeof d.espelho === "number" ? brl(d.espelho) : d.espelho ?? "—"}, nota ${typeof d.nota === "number" ? brl(d.nota) : d.nota ?? "—"})`).join("; ")}
          {n.justificativa ? ` · justificado: ${n.justificativa}` : ""}
        </span>
        {podeEditar && div.length > 0 && !n.justificativa && justificar?.nota_id !== n.nota_id && (
          <button type="button" className="btn btn--pequeno" disabled={ocupado}
            onClick={() => setJustificar({ nota_id: n.nota_id, texto: "" })}>Justificar</button>
        )}
      </span></>
    );
  };

  return (
    <div className="notas" onKeyDown={ev => ev.key === "Escape" && aoFechar?.()}>
      <p className="painel__titulo">
        {/* o nome inteiro da medicao: "Reajuste da 23ª Medição" nao e' a 23ª de execucao */}
        {rotulo ?? tituloMedicao(medicao)}
        {dados && dados.esperadas.length > 0 && dados.faltam > 0 && (
          <>{" "}<Selo classe="selo--atencao">{dados.faltam === 1 ? "Falta 1 nota" : `Faltam ${dados.faltam} notas`}</Selo></>
        )}
      </p>

      {erro && <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erro}</p>}
      {!dados && !erro && <p className="campo__nota">Carregando…</p>}

      {dados && dados.esperadas.length > 0 && (
        <Rolagem rotulo="Notas esperadas da medição">
          <table className="tabela tabela--densa notas__tabela" aria-label={rotulo ? `Notas esperadas: ${rotulo}` : undefined}>
            <thead>
              <tr>
                <th scope="col">Saída</th><th scope="col" className="col-num num">Valor</th><th scope="col" className="col-num num">INSS</th>
                <th scope="col" className="col-num num">ISS</th><th scope="col" className="col-num num">IRRF</th>
                {temIbsCbs && <><th scope="col" className="col-num num">IBS</th><th scope="col" className="col-num num">CBS</th></>}
                <th scope="col" className="col-num num">Líquido</th><th scope="col">Nota</th>
              </tr>
            </thead>
            <tbody>
              {dados.esperadas.map(e => {
                const n = e.nota_id ? porId.get(e.nota_id) : undefined;
                // G3-11: so' a celula do campo que diverge fica destacada, com o valor lido na nota
                const lidos = new Map((n?.conferencia ?? []).filter(d => d.grau === "divergente").map(d => [d.campo, d.nota]));
                // A conferencia e' gravada quando a nota chega; se o espelho mudou de versao depois e hoje
                // bate com a nota, a celula nao se destaca (nada de "R$ X no espelho; na nota R$ X").
                const diverge = (campo: string, valor: number | string | null) => lidos.has(campo)
                  && String(lidos.get(campo) ?? "").toLowerCase() !== String(valor ?? "").toLowerCase();
                const celula = (campo: string, valor: number | null) => {
                  if (!diverge(campo, valor)) return <td className="col-num dinheiro num">{brl(valor)}</td>;
                  const lido = lidos.get(campo);
                  const naNota = typeof lido === "number" ? brl(lido) : "não lido";
                  return (
                    <td className="col-num dinheiro num notas__celula--diverge" title={`Na nota: ${naNota}`}>
                      {brl(valor)}<span className="sr-only"> no espelho; na nota {naNota}</span>
                    </td>
                  );
                };
                return (
                  <tr key={e.chave}>
                    <td>{naturezaNome(e.natureza, e.rotulo)} · {emissorNome(e.emissor)} · {diverge("municipio", e.municipio)
                      ? <span className="notas__celula--diverge" title={`Na nota: ${lidos.get("municipio") ?? "não lido"}`}>
                          {e.municipio}<span className="sr-only"> no espelho; na nota {lidos.get("municipio") ?? "não lido"}</span>
                        </span>
                      : e.municipio}</td>
                    {celula("valor", e.valor)}{celula("inss", e.inss)}
                    {celula("iss", e.iss)}{celula("irrf", e.irrf)}
                    {temIbsCbs && <>{celula("ibs", e.ibs)}{celula("cbs", e.cbs)}</>}
                    {celula("liquido", e.liquido)}
                    <td>{n ? <>{situacaoNota(n)}{conferencia(n)}{botaoDesfazer(n)}</> : "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Rolagem>
      )}

      {soltas.length > 0 && (
        <ul className="lista-simples">
          {soltas.map(n => (
            <li key={n.nota_id}>
              NF {situacaoNota(n)}{" "}<span className="num">{brl(n.valor_centavos)}</span>{conferencia(n)}{botaoDesfazer(n)}
            </li>
          ))}
        </ul>
      )}

      {justificar && (
        <form className="form-inline" onSubmit={enviarJustificativa}>
          <div className="campo">
            <label className="campo__rotulo" htmlFor={`nota-justificativa-${medicao.id}`}>Justificativa da divergência</label>
            <input id={`nota-justificativa-${medicao.id}`} name="justificativa" autoComplete="off" className="entrada--larga" required maxLength={1000} autoFocus
              value={justificar.texto} onChange={ev => setJustificar({ ...justificar, texto: ev.target.value })} />
          </div>
          <button type="submit" className="btn btn--primario" disabled={ocupado}>{acao === "justificar" ? "Gravando…" : "Gravar justificativa"}</button>
          <button type="button" className="btn" onClick={() => setJustificar(null)}>Voltar</button>
        </form>
      )}

      {desfazer && (
        <form className="form-inline" onSubmit={enviarDesfazer}>
          <div className="campo">
            <label className="campo__rotulo" htmlFor={`nota-desfazer-${medicao.id}`}>
              Motivo para desfazer o vínculo da nota {Number(desfazer.numero) || desfazer.numero}
            </label>
            <input id={`nota-desfazer-${medicao.id}`} name="motivo" autoComplete="off" className="entrada--larga" required maxLength={1000} autoFocus
              value={desfazer.motivo} onChange={ev => setDesfazer({ ...desfazer, motivo: ev.target.value })} />
          </div>
          <button type="submit" className="btn btn--primario" disabled={ocupado}>{acao === "desfazer" ? "Desfazendo…" : "Desfazer o vínculo"}</button>
          <button type="button" className="btn" onClick={() => setDesfazer(null)}>Voltar</button>
        </form>
      )}

      {/* regiao viva sempre montada: o resultado de cada nota anexada e' anunciado quando chega */}
      <div role="status">{linhas.length > 0 && (
        <ul className="lista-simples notas__feito">
          {linhas.map((l, i) => <li key={i}>{l}</li>)}
        </ul>
      )}</div>

      {podeEditar && !manual && (dados?.documentos_sem_nota ?? []).length > 0 && (
        <ul className="lista-simples">
          {(dados?.documentos_sem_nota ?? []).map(d => (
            <li key={d.documento_id}>
              <a className="link" href={`/api/medicoes/${medicao.id}/documentos/${d.documento_id}`}>{d.nome}</a>
              {" "}— PDF sem leitura{" "}
              <button type="button" className="btn btn--pequeno" disabled={ocupado}
                onClick={() => setManual({ documento_id: d.documento_id, nome: d.nome, numero: "", emissao: "", valor: "" })}>
                Informar número, data e valor
              </button>
            </li>
          ))}
        </ul>
      )}

      {podeEditar && manual && (
        <form className="form-inline" onSubmit={enviarManual}>
          <span className="campo__nota">{manual.nome}</span>
          <div className="campo">
            <label className="campo__rotulo" htmlFor={`nota-numero-${medicao.id}`}>Número da nota</label>
            <input id={`nota-numero-${medicao.id}`} name="numero" autoComplete="off" spellCheck={false} className="entrada--curta entrada--num num" required inputMode="numeric" pattern="[0-9]{1,9}"
              value={manual.numero} onChange={ev => setManual({ ...manual, numero: ev.target.value })} />
          </div>
          <div className="campo">
            <label className="campo__rotulo" htmlFor={`nota-emissao-${medicao.id}`}>Emissão</label>
            <input id={`nota-emissao-${medicao.id}`} name="emissao" autoComplete="off" type="date" className="entrada--media" required
              value={manual.emissao} onChange={ev => setManual({ ...manual, emissao: ev.target.value })} />
          </div>
          <div className="campo">
            <label className="campo__rotulo" htmlFor={`nota-valor-${medicao.id}`}>Valor bruto (R$)</label>
            <CampoValor id={`nota-valor-${medicao.id}`} name="valor" required
              value={manual.valor} onChange={v => setManual({ ...manual, valor: v })} />
          </div>
          <button type="submit" className="btn btn--primario" disabled={ocupado}>{acao === "manual" ? "Registrando…" : "Registrar nota"}</button>
          <button type="button" className="btn" onClick={() => setManual(null)}>Deixar só o arquivo</button>
        </form>
      )}

      {podeEditar && (
        <div className="form-inline">
          <label className="btn btn--pequeno espelho__anexar">
            Anexar notas (PDF)
            <input type="file" name="notas" accept="application/pdf" multiple className="espelho__arquivo" disabled={ocupado}
              aria-label={rotulo ? `Anexar notas: ${rotulo}` : `Anexar notas à medição ${medicao.numero}`} onChange={ev => anexar(ev.currentTarget)} />
          </label>
          <label className="marcar">
            <input type="checkbox" name="frc" checked={frc} onChange={ev => setFrc(ev.target.checked)} />
            é a fatura do consórcio (FRC)
          </label>
        </div>
      )}

      {podeEditar && dados && dados.pode_declarar && dados.faltam > 0 && dados.notas.length > 0 && (
        <form className="form-inline" onSubmit={enviarDeclaracao}>
          <div className="campo">
            <label className="campo__rotulo" htmlFor={`nota-declarar-${medicao.id}`}>Declarar as notas completas — justificativa</label>
            <input id={`nota-declarar-${medicao.id}`} name="declaracao" autoComplete="off" className="entrada--larga" required maxLength={1000}
              value={declarar} onChange={ev => setDeclarar(ev.target.value)} />
          </div>
          <button type="submit" className="btn btn--pequeno" disabled={ocupado}>{acao === "declarar" ? "Gravando…" : "Declarar completas"}</button>
        </form>
      )}

      {aoFechar && (
        <div className="painel__rodape form-inline">
          <button type="button" className="btn" onClick={aoFechar}>Fechar</button>
        </div>
      )}
    </div>
  );
}
