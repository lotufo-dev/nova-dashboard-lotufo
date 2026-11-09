import { useState, type DragEvent } from "react";
import { apiForm, baixarArquivoForm, mensagemDeErro } from "./api";
import { IconeAlerta, IconeBaixar } from "./icones";
import "./ancorasDocusign.css";

// Ferramenta "Âncoras para o DocuSign" (#626): a pessoa solta os PDFs do pacote, informa o nome de quem assina e baixa um
// PDF juntado com um texto invisível por signatário em cada ponto de assinatura. No DocuSign, um campo de assinatura por
// signatário com a inserção automática pelo texto da âncora cai sozinho em todas as páginas. Nada é gravado: cada pedido
// leva os PDFs de novo e devolve o resultado.

const PAPEIS = [
  { chave: "fiscal", rotulo: "Fiscal do órgão" },
  { chave: "supervisor", rotulo: "Supervisor (supervisora)" },
  { chave: "executora", rotulo: "Responsável técnico da executora" },
  { chave: "superior", rotulo: "Superior imediato do fiscal" },
] as const;
type Papel = (typeof PAPEIS)[number]["chave"];
const ROTULO_PAPEL: Record<Papel, string> = { fiscal: "Fiscal", supervisor: "Supervisor", executora: "Executora", superior: "Superior" };
const RODAPE: Papel[] = ["fiscal", "supervisor", "executora"];

type Motivo = "nome" | "diario" | "rodape";
export type PaginaAncora = { pagina: number; motivo: Motivo | null; papeis: Papel[] };
const ROTULO_MOTIVO: Record<Motivo, string> = { nome: "Nome impresso", diario: "Diário de Obra (rodapé)", rodape: "Rodapé (marcada por você)" };

const URL_BASE = "/api/ancoras-docusign";

function formulario(arquivos: File[], nomes: Record<Papel, string>, marcar: number[], desmarcar: number[], mostrar?: boolean): FormData {
  const f = new FormData();
  for (const a of arquivos) f.append("arquivos", a);
  const preenchidos = Object.fromEntries(Object.entries(nomes).filter(([, n]) => n.trim() !== ""));
  f.append("papeis", JSON.stringify(preenchidos));
  f.append("marcar", JSON.stringify(marcar));
  f.append("desmarcar", JSON.stringify(desmarcar));
  if (mostrar !== undefined) f.append("mostrar", mostrar ? "true" : "false");
  return f;
}

export default function AncorasDocusign() {
  const [arquivos, setArquivos] = useState<File[]>([]);
  const [nomes, setNomes] = useState<Record<Papel, string>>({ fiscal: "", supervisor: "", executora: "", superior: "" });
  const [mostrar, setMostrar] = useState(false);
  const [paginas, setPaginas] = useState<PaginaAncora[] | null>(null);
  const [marcar, setMarcar] = useState<Set<number>>(new Set());
  const [desmarcar, setDesmarcar] = useState<Set<number>>(new Set());
  const [ocupado, setOcupado] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [arrastando, setArrastando] = useState(false);

  // Mudou arquivo ou nome: a leitura das páginas e as marcações perdem o sentido.
  function invalidar() { setPaginas(null); setMarcar(new Set()); setDesmarcar(new Set()); setErro(null); }
  function adicionar(novos: FileList | File[] | null) {
    const pdfs = Array.from(novos ?? []).filter(a => a.type === "application/pdf" || a.name.toLowerCase().endsWith(".pdf"));
    if (pdfs.length === 0) return;
    setArquivos(atual => [...atual, ...pdfs]);
    invalidar();
  }
  function soltar(ev: DragEvent<HTMLElement>) { ev.preventDefault(); setArrastando(false); adicionar(ev.dataTransfer.files); }
  function tirar(i: number) { setArquivos(atual => atual.filter((_, k) => k !== i)); invalidar(); }

  async function analisar() {
    setOcupado(true); setErro(null);
    try {
      const r = await apiForm<{ paginas: PaginaAncora[] }>(`${URL_BASE}/paginas`, formulario(arquivos, nomes, [], []));
      setPaginas(r.paginas); setMarcar(new Set()); setDesmarcar(new Set());
    } catch (e) { setErro(mensagemDeErro(e)); } finally { setOcupado(false); }
  }
  async function baixar() {
    setOcupado(true); setErro(null);
    try {
      await baixarArquivoForm(`${URL_BASE}/pdf`, formulario(arquivos, nomes, [...marcar], [...desmarcar], mostrar), "pacote-com-ancoras.pdf");
    } catch (e) { setErro(mensagemDeErro(e)); } finally { setOcupado(false); }
  }

  function alternar(conj: Set<number>, set: (s: Set<number>) => void, n: number) {
    const novo = new Set(conj);
    if (!novo.delete(n)) novo.add(n);
    set(novo);
  }

  // O que cada página tem agora: a leitura automática com as marcações da pessoa por cima.
  const atuais = (paginas ?? []).map(p => {
    if (desmarcar.has(p.pagina)) return { ...p, motivo: null, papeis: [] as Papel[] };
    if (marcar.has(p.pagina) && p.motivo === null) return { ...p, motivo: "rodape" as Motivo, papeis: RODAPE };
    return p;
  });
  const com = atuais.filter(p => p.motivo !== null);
  const sem = atuais.filter(p => p.motivo === null);

  return (
    <section className="ancoras" aria-labelledby="ancoras-titulo">
      <h1 id="ancoras-titulo" className="ancoras__titulo">Âncoras para o DocuSign</h1>
      {erro && <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erro}</p>}

      <div className={`ancoras__soltar${arrastando ? " ancoras__soltar--sobre" : ""}`}
        onDragOver={ev => { ev.preventDefault(); setArrastando(true); }} onDragLeave={() => setArrastando(false)} onDrop={soltar}>
        <label className="btn" htmlFor="ancoras-arquivos">Escolher PDFs</label>
        <input id="ancoras-arquivos" type="file" multiple accept=".pdf,application/pdf" className="sr-only"
          onChange={ev => { adicionar(ev.currentTarget.files); ev.currentTarget.value = ""; }} />
        <span className="ancoras__dica">ou solte aqui os PDFs, na ordem do pacote</span>
      </div>
      {arquivos.length > 0 && (
        <ol className="ancoras__arquivos" aria-label="PDFs do pacote">
          {arquivos.map((a, i) => (
            <li key={`${a.name}-${i}`}>{a.name}
              <button type="button" className="btn btn--pequeno" aria-label={`Tirar ${a.name}`} onClick={() => tirar(i)}>Tirar</button>
            </li>
          ))}
        </ol>
      )}

      <fieldset className="ancoras__nomes">
        <legend>Nome de quem assina, como está impresso nos documentos (todos opcionais)</legend>
        {PAPEIS.map(p => (
          <div className="campo" key={p.chave}>
            <label className="campo__rotulo" htmlFor={`ancoras-${p.chave}`}>{p.rotulo}</label>
            <input id={`ancoras-${p.chave}`} type="text" maxLength={200} value={nomes[p.chave]}
              onChange={ev => { setNomes({ ...nomes, [p.chave]: ev.target.value }); invalidar(); }} />
          </div>
        ))}
      </fieldset>

      <label className="campo--linha ancoras__mostrar">
        <input type="checkbox" checked={mostrar} onChange={ev => setMostrar(ev.target.checked)} />
        Mostrar âncoras (versão de conferência, em vermelho)
      </label>

      <div className="ancoras__acoes">
        <button type="button" className="btn btn--primario" disabled={ocupado || arquivos.length === 0} onClick={analisar}>
          {ocupado && paginas === null ? "Lendo o pacote…" : "Ver as páginas com âncora"}
        </button>
        <button type="button" className="btn" disabled={ocupado || arquivos.length === 0} onClick={baixar}>
          <IconeBaixar className="icone" />{ocupado && paginas !== null ? "Montando o PDF…" : "Baixar PDF com âncoras"}
        </button>
      </div>

      {paginas !== null && (
        <div className="ancoras__paginas">
          <h2>Páginas com âncora ({com.length})</h2>
          {com.length === 0 ? <p>—</p> : (
            <div className="tabela-wrap"><table className="tabela">
              <thead><tr><th>Página</th><th>Motivo</th><th>Para quem</th><th>Manter</th></tr></thead>
              <tbody>
                {com.map(p => (
                  <tr key={p.pagina}>
                    <td>{p.pagina}</td>
                    <td>{p.motivo ? ROTULO_MOTIVO[p.motivo] : ""}</td>
                    <td>{p.papeis.map(x => ROTULO_PAPEL[x]).join(", ")}</td>
                    <td><label className="campo--linha">
                      <input type="checkbox" checked aria-label={`Manter a âncora da página ${p.pagina}`}
                        onChange={() => p.motivo === "rodape" ? alternar(marcar, setMarcar, p.pagina) : alternar(desmarcar, setDesmarcar, p.pagina)} />
                    </label></td>
                  </tr>
                ))}
              </tbody>
            </table></div>
          )}

          <h2>Páginas sem âncora ({sem.length})</h2>
          {sem.length === 0 ? <p>—</p> : (
            <>
              <div className="tabela-wrap"><table className="tabela">
                <thead><tr><th>Página</th><th>Pôr âncoras no rodapé</th></tr></thead>
                <tbody>
                  {sem.map(p => (
                    <tr key={p.pagina}>
                      <td>{p.pagina}</td>
                      <td><label className="campo--linha">
                        <input type="checkbox" checked={false} aria-label={`Pôr âncoras no rodapé da página ${p.pagina}`}
                          onChange={() => p.pagina && (desmarcar.has(p.pagina) ? alternar(desmarcar, setDesmarcar, p.pagina) : alternar(marcar, setMarcar, p.pagina))} />
                      </label></td>
                    </tr>
                  ))}
                </tbody>
              </table></div>
            </>
          )}
        </div>
      )}
    </section>
  );
}
