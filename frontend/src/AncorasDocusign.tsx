import { useState, type DragEvent } from "react";
import { apiForm, baixarArquivoForm, mensagemDeErro } from "./api";
import { contar } from "./formato";
import Selo from "./Selo";
import Falha from "./Falha";
import { IconeBaixar } from "./icones";
import Rolagem from "./Rolagem";
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
  const [acao, setAcao] = useState<"analisar" | "baixar" | null>(null);
  const ocupado = acao !== null;
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
    setAcao("analisar"); setErro(null);
    try {
      const r = await apiForm<{ paginas: PaginaAncora[] }>(`${URL_BASE}/paginas`, formulario(arquivos, nomes, [], []));
      setPaginas(r.paginas); setMarcar(new Set()); setDesmarcar(new Set());
    } catch (e) { setErro(mensagemDeErro(e)); } finally { setAcao(null); }
  }
  async function baixar() {
    setAcao("baixar"); setErro(null);
    try {
      await baixarArquivoForm(`${URL_BASE}/pdf`, formulario(arquivos, nomes, [...marcar], [...desmarcar], mostrar), "pacote-com-ancoras.pdf");
    } catch (e) { setErro(mensagemDeErro(e)); } finally { setAcao(null); }
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
  const com = atuais.filter(p => p.motivo !== null).length;

  // A tela responde "em que paginas do pacote entra ancora, e para quem" (#768): a' esquerda o que a pessoa entrega
  // (os PDFs e os nomes), a' direita a resposta (as paginas em ordem, cada uma com a ancora dela) e o PDF.
  return (
    <section className="anc" aria-label="Âncoras para o DocuSign">
      <div className="anc__grade">
      <div className="anc__entrada">
        <section className="cartao" aria-labelledby="anc-pacote">
          <div className="cartao__cabeca"><h2 className="cartao__titulo" id="anc-pacote">Pacote</h2></div>
          <div className="cartao__corpo anc__corpo">
            <div className={`anc__soltar${arrastando ? " anc__soltar--sobre" : ""}`}
              onDragOver={ev => { ev.preventDefault(); setArrastando(true); }} onDragLeave={() => setArrastando(false)} onDrop={soltar}>
              <label className="btn" htmlFor="ancoras-arquivos">Escolher PDFs</label>
              <input id="ancoras-arquivos" type="file" multiple accept=".pdf,application/pdf" className="sr-only"
                onChange={ev => { adicionar(ev.currentTarget.files); ev.currentTarget.value = ""; }} />
            </div>
            {arquivos.length > 0 && (
              <ol className="anc__arquivos" aria-label="PDFs do pacote, na ordem em que serão juntados">
                {arquivos.map((a, i) => (
                  <li key={`${a.name}-${i}`}>
                    <span className="anc__ordem num" aria-hidden="true">{i + 1}</span>
                    <span className="anc__arquivo">{a.name}</span>
                    <button type="button" className="btn btn--pequeno" aria-label={`Tirar ${a.name}`} onClick={() => tirar(i)}>Tirar</button>
                  </li>
                ))}
              </ol>
            )}
          </div>
        </section>

        <section className="cartao" aria-labelledby="anc-quem">
          <div className="cartao__cabeca"><h2 className="cartao__titulo" id="anc-quem">Quem assina</h2></div>
          <fieldset className="cartao__corpo anc__nomes">
            <legend className="anc__legenda">Nome como está impresso nos documentos (todos opcionais)</legend>
            {PAPEIS.map(p => (
              <div className="campo" key={p.chave}>
                <label className="campo__rotulo" htmlFor={`ancoras-${p.chave}`}>{p.rotulo}</label>
                <input id={`ancoras-${p.chave}`} type="text" maxLength={200} value={nomes[p.chave]}
                  onChange={ev => { setNomes({ ...nomes, [p.chave]: ev.target.value }); invalidar(); }} />
              </div>
            ))}
          </fieldset>
        </section>
      </div>

      <section className="cartao anc__saida" aria-labelledby="anc-paginas">
        <div className="cartao__cabeca">
          <h2 className="cartao__titulo" id="anc-paginas">Páginas</h2>
          {paginas !== null && (
            <>
              <Selo situacao="feito">{contar(com, "com âncora", "com âncora")}</Selo>
              <Selo>{contar(atuais.length - com, "sem âncora", "sem âncora")}</Selo>
            </>
          )}
        </div>
        <div className="cartao__corpo anc__corpo">
          {erro && <Falha>{erro}</Falha>}
          <div className="anc__acoes">
            <button type="button" className="btn btn--primario" disabled={ocupado || arquivos.length === 0} onClick={analisar}>
              {acao === "analisar" ? "Lendo o pacote…" : "Ver as páginas com âncora"}
            </button>
            <button type="button" className="btn" disabled={ocupado || arquivos.length === 0} onClick={baixar}>
              <IconeBaixar className="icone" />{acao === "baixar" ? "Montando o PDF…" : "Baixar PDF com âncoras"}
            </button>
          </div>
          <label className="campo--linha anc__mostrar">
            <input type="checkbox" checked={mostrar} onChange={ev => setMostrar(ev.target.checked)} />
            Mostrar âncoras (versão de conferência, em vermelho)
          </label>
        </div>
        {paginas !== null && (atuais.length === 0 ? <p className="anc__vazio">Nenhuma página.</p> : (
          <Rolagem rotulo="Páginas do pacote">
            <table className="tabela anc__tabela">
              <caption className="sr-only">Páginas do pacote, em ordem, com a âncora de cada uma</caption>
              <thead><tr><th scope="col" className="col-num">Página</th><th scope="col">Âncora</th><th scope="col">Para quem</th><th scope="col">Pôr âncora</th></tr></thead>
              <tbody>
                {atuais.map(p => (
                  <tr key={p.pagina} className={p.motivo === null ? "anc__sem" : undefined}>
                    <td className="col-num num">{p.pagina}</td>
                    <td>{p.motivo ? ROTULO_MOTIVO[p.motivo] : "—"}</td>
                    <td>{p.motivo ? p.papeis.map(x => ROTULO_PAPEL[x]).join(", ") : "—"}</td>
                    <td><label className="campo--linha">
                      {p.motivo !== null ? (
                        <input type="checkbox" checked aria-label={`Manter a âncora da página ${p.pagina}`}
                          onChange={() => p.motivo === "rodape" ? alternar(marcar, setMarcar, p.pagina) : alternar(desmarcar, setDesmarcar, p.pagina)} />
                      ) : (
                        <input type="checkbox" checked={false} aria-label={desmarcar.has(p.pagina) ? `Restaurar a âncora da página ${p.pagina}` : `Pôr âncoras no rodapé da página ${p.pagina}`}
                          onChange={() => desmarcar.has(p.pagina) ? alternar(desmarcar, setDesmarcar, p.pagina) : alternar(marcar, setMarcar, p.pagina)} />
                      )}
                    </label></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Rolagem>
        ))}
      </section>
      </div>
    </section>
  );
}
